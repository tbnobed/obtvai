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
                boxes, _probs = mtcnn.detect(img)
                if boxes is None:
                    continue
                faces = mtcnn.extract(img, boxes, None)
                if faces is None:
                    continue
                with torch.no_grad():
                    embs = resnet(faces.to(device))
                for j, emb in enumerate(embs):
                    embeddings.append(emb.cpu().numpy())
                    scene_meta.append({
                        "scene_id": scene_id,
                        "start_time": start_time,
                        "end_time": end_time,
                        "thumb_file": thumb_file,
                        "box": [float(v) for v in boxes[j]],
                    })
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

        cluster_members: dict[int, list[int]] = {}
        for idx, label in enumerate(labels):
            if label >= 0:
                cluster_members.setdefault(label, []).append(idx)

        for label, appearances in clusters.items():
            cluster_id = str(uuid.uuid4())
            deduped = []
            seen = set()
            for a in appearances:
                key = (a["start_time"], a["end_time"])
                if key not in seen:
                    seen.add(key)
                    deduped.append({"start_time": a["start_time"], "end_time": a["end_time"]})

            # Centroid embedding for cross-asset identity matching
            member_idx = cluster_members.get(label, [])
            centroid = None
            if member_idx:
                c = X[member_idx].mean(axis=0)
                norm = np.linalg.norm(c)
                if norm > 0:
                    c = c / norm
                centroid = [float(v) for v in c]

            # Face crop thumbnail from the first appearance
            face_thumb_name = None
            if member_idx:
                meta = scene_meta[member_idx[0]]
                try:
                    src = Image.open(meta["thumb_file"]).convert("RGB")
                    x1, y1, x2, y2 = meta["box"]
                    mx = (x2 - x1) * 0.3
                    my = (y2 - y1) * 0.3
                    crop = src.crop((
                        max(0, int(x1 - mx)), max(0, int(y1 - my)),
                        min(src.width, int(x2 + mx)), min(src.height, int(y2 + my)),
                    ))
                    face_thumb_name = f"face_{cluster_id}.jpg"
                    crop.save(os.path.join(THUMBNAILS_DIR, face_thumb_name), quality=90)
                except Exception:
                    face_thumb_name = None

            db.execute(
                text("""
                    INSERT INTO face_clusters (cluster_id, media_id, appearances, embedding, thumbnail_url)
                    VALUES (:cid, :mid, CAST(:apps AS jsonb), CAST(:emb AS jsonb), :thumb)
                """),
                {
                    "cid": cluster_id,
                    "mid": media_id,
                    "apps": json.dumps(deduped),
                    "emb": json.dumps(centroid) if centroid else None,
                    "thumb": face_thumb_name,
                },
            )

        db.commit()
        n_clusters = len(clusters)
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        update_asset(db, media_id, processing_stage="face_detect_complete", processing_progress=92.0)
        append_log(db, job_id, f"Detected {n_clusters} face clusters")

        # Queue cross-asset person identification (idempotent; also triggered
        # by diarize — whichever finishes last sees the full picture)
        from tasks.base import create_job
        ident_job_id = create_job(db, media_id, "identify")
        from tasks.identify import identify_people
        identify_people.delay(media_id, ident_job_id)

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
