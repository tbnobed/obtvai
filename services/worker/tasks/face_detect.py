"""Detect and cluster faces across scenes using MTCNN + FaceNet."""
import os
import uuid
import json
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log, update_asset
from config import THUMBNAILS_DIR, PROXIES_DIR


@celery_app.task(bind=True, name="tasks.face_detect.detect_faces", queue="gpu")
def detect_faces(self, media_id: str, job_id: str):
    db = get_session()
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)
        update_asset(db, media_id, processing_stage="face_detect", processing_progress=85.0)

        from sqlalchemy import text
        scenes = db.execute(
            text("SELECT id, start_time, end_time, thumbnail_url FROM scenes WHERE media_id = :mid"),
            {"mid": media_id},
        ).fetchall()

        if not scenes:
            update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
            append_log(db, job_id, "No scenes for face detection")
            return

        import torch
        import numpy as np
        from facenet_pytorch import MTCNN, InceptionResnetV1
        from PIL import Image
        from sklearn.cluster import DBSCAN

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        mtcnn = MTCNN(device=device, keep_all=True)
        resnet = InceptionResnetV1(pretrained="vggface2").eval().to(device)

        embeddings = []
        scene_meta = []

        for scene_id, start_time, end_time, thumb_url in scenes:
            if not thumb_url:
                continue
            thumb_file = os.path.join(THUMBNAILS_DIR, os.path.basename(thumb_url))
            if not os.path.exists(thumb_file):
                continue
            try:
                img = Image.open(thumb_file).convert("RGB")
                faces = mtcnn(img)
                if faces is None:
                    continue
                with torch.no_grad():
                    embs = resnet(faces.to(device))
                for emb in embs:
                    embeddings.append(emb.cpu().numpy())
                    scene_meta.append({"scene_id": scene_id, "start_time": start_time, "end_time": end_time})
            except Exception:
                continue

        if not embeddings:
            update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
            append_log(db, job_id, "No faces found")
            return

        X = np.array(embeddings)
        clustering = DBSCAN(eps=0.6, min_samples=1, metric="cosine").fit(X)
        labels = clustering.labels_

        clusters: dict[int, list] = {}
        for label, meta in zip(labels, scene_meta):
            if label < 0:
                continue
            clusters.setdefault(label, []).append(meta)

        for label, appearances in clusters.items():
            cluster_id = str(uuid.uuid4())
            deduped = []
            seen = set()
            for a in appearances:
                key = (a["start_time"], a["end_time"])
                if key not in seen:
                    seen.add(key)
                    deduped.append({"start_time": a["start_time"], "end_time": a["end_time"]})

            db.execute(
                text("""
                    INSERT INTO face_clusters (cluster_id, media_id, appearances)
                    VALUES (:cid, :mid, :apps::jsonb)
                """),
                {"cid": cluster_id, "mid": media_id, "apps": json.dumps(deduped)},
            )

        db.commit()
        n_clusters = len(clusters)
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        update_asset(db, media_id, processing_stage="face_detect_complete", processing_progress=92.0)
        append_log(db, job_id, f"Detected {n_clusters} face clusters")

    except Exception as e:
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
