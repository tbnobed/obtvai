"""Detect and cluster faces across scenes using MTCNN + FaceNet.

Samples MULTIPLE frames per scene from the proxy video (not just the single
scene thumbnail), so every person visible during a scene can be detected —
critical for talk-show / interview footage where several people share a scene
but only one is visible in any given frame.
"""
import os
import uuid
import json
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log, update_asset
from config import THUMBNAILS_DIR

FRAMES_PER_SCENE_MAX = 4      # sample up to this many frames per scene
FRAME_SAMPLE_EVERY = 4.0      # ~one sample per this many seconds of scene
TOTAL_FRAME_CAP = 500         # hard cap of sampled frames per asset
MIN_FACE_PROB = 0.95          # MTCNN detection confidence floor (0.90 let
                              # hands / necks / graphics through as "faces";
                              # 0.98 rejected soft/filtered 720p footage —
                              # geometry gates below catch the false positives)
MIN_FACE_SIDE = 36            # ignore tiny background faces (pixels)
MIN_ASPECT = 0.5              # face box width/height sanity range —
MAX_ASPECT = 1.25             # hands and neck closeups produce odd boxes
CLUSTER_EPS = 0.30            # cosine DISTANCE for DBSCAN — 0.6 merged
                              # different people (sim 0.4!); 0.3 ≈ sim 0.7


def _sample_times(start: float, end: float) -> list[float]:
    dur = max(0.0, float(end) - float(start))
    n = min(FRAMES_PER_SCENE_MAX, max(1, int(dur / FRAME_SAMPLE_EVERY)))
    return [float(start) + dur * (k + 1) / (n + 1) for k in range(n)]


@celery_app.task(bind=True, name="tasks.face_detect.detect_faces", queue="gpu")
def detect_faces(self, media_id: str, job_id: str):
    db = get_session()
    cap = None
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)
        update_asset(db, media_id, processing_stage="face_detect", processing_progress=85.0)

        from sqlalchemy import text
        scenes = db.execute(
            text("SELECT id, start_time, end_time, thumbnail_url FROM scenes WHERE media_id = :mid ORDER BY start_time"),
            {"mid": media_id},
        ).fetchall()

        if not scenes:
            update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
            append_log(db, job_id, "No scenes for face detection")
            return

        row = db.execute(
            text("SELECT original_path, proxy_path FROM media_assets WHERE id = :mid"),
            {"mid": media_id},
        ).fetchone()
        video_path = (row[1] or row[0]) if row else None

        import cv2
        import torch
        import numpy as np
        from facenet_pytorch import MTCNN, InceptionResnetV1
        from PIL import Image
        from sklearn.cluster import DBSCAN

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        mtcnn = MTCNN(device=device, keep_all=True)
        resnet = InceptionResnetV1(pretrained="vggface2").eval().to(device)

        if video_path and os.path.exists(video_path):
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                cap = None
        if cap is None:
            append_log(db, job_id, "Proxy video unavailable — falling back to scene thumbnails only")

        def _grab_frame(ts: float):
            if cap is None:
                return None
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, ts) * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                return None
            return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

        rejects = {"low_prob": 0, "too_small": 0, "aspect": 0, "geometry": 0, "eye_dist": 0}

        def _detect(img):
            """Returns list of (box, face_tensor) passing confidence, size and
            facial-geometry gates (kills hands / necks / graphics that MTCNN
            occasionally reports as faces)."""
            boxes, probs, landmarks = mtcnn.detect(img, landmarks=True)
            if boxes is None:
                return []
            keep, keep_boxes = [], []
            for j, box in enumerate(boxes):
                p = probs[j] if probs is not None else 1.0
                if p is None or p < MIN_FACE_PROB:
                    rejects["low_prob"] += 1
                    continue
                w, h = box[2] - box[0], box[3] - box[1]
                if w < MIN_FACE_SIDE or h < MIN_FACE_SIDE:
                    rejects["too_small"] += 1
                    continue
                if h <= 0 or not (MIN_ASPECT <= w / h <= MAX_ASPECT):
                    rejects["aspect"] += 1
                    continue
                # Geometric sanity: a real frontal/profile face has both eyes
                # above the nose and the nose above the mouth, all inside the box.
                lm = landmarks[j] if landmarks is not None else None
                if lm is None:
                    rejects["geometry"] += 1
                    continue
                le, re_, nose, ml, mr = lm
                if not (le[1] < nose[1] and re_[1] < nose[1] and nose[1] < (ml[1] + mr[1]) / 2):
                    rejects["geometry"] += 1
                    continue
                pad_x, pad_y = 0.15 * w, 0.15 * h
                inside = all(
                    box[0] - pad_x <= px <= box[2] + pad_x and box[1] - pad_y <= py <= box[3] + pad_y
                    for px, py in lm
                )
                if not inside:
                    rejects["geometry"] += 1
                    continue
                # Eye spacing should be a meaningful fraction of box width —
                # extreme chin/neck closeups fail this.
                eye_dist = ((le[0] - re_[0]) ** 2 + (le[1] - re_[1]) ** 2) ** 0.5
                if eye_dist < 0.2 * w:
                    rejects["eye_dist"] += 1
                    continue
                keep_boxes.append(box)
            if not keep_boxes:
                return []
            faces = mtcnn.extract(img, np.array(keep_boxes), None)
            if faces is None:
                return []
            for j in range(len(keep_boxes)):
                keep.append((keep_boxes[j], faces[j]))
            return keep

        embeddings = []
        scene_meta = []
        frames_sampled = 0

        for scene_id, start_time, end_time, thumb_url in scenes:
            sources = []
            if cap is not None and frames_sampled < TOTAL_FRAME_CAP:
                for ts in _sample_times(start_time, end_time):
                    if frames_sampled >= TOTAL_FRAME_CAP:
                        break
                    img = _grab_frame(ts)
                    frames_sampled += 1
                    if img is not None:
                        sources.append((img, ("video", float(ts))))
            if not sources and thumb_url:
                thumb_file = os.path.join(THUMBNAILS_DIR, os.path.basename(thumb_url))
                if os.path.exists(thumb_file):
                    try:
                        sources.append((Image.open(thumb_file).convert("RGB"), ("file", thumb_file)))
                    except Exception:
                        pass

            for img, src in sources:
                try:
                    detections = _detect(img)
                    if not detections:
                        continue
                    face_tensors = torch.stack([f for _, f in detections])
                    with torch.no_grad():
                        embs = resnet(face_tensors.to(device))
                    for (box, _f), emb in zip(detections, embs):
                        embeddings.append(emb.cpu().numpy())
                        scene_meta.append({
                            "scene_id": scene_id,
                            "start_time": start_time,
                            "end_time": end_time,
                            "src": src,
                            "box": [float(v) for v in box],
                        })
                except Exception:
                    continue

        if not embeddings:
            db.execute(text("DELETE FROM face_clusters WHERE media_id = :mid"), {"mid": media_id})
            db.commit()
            update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
            rej_note = ", ".join(f"{k}={v}" for k, v in rejects.items() if v)
            append_log(db, job_id, f"No faces found (candidates rejected: {rej_note or 'none detected by MTCNN'})")
            # Still re-run identify so person appearances reflect the (now
            # empty) cluster set instead of stale face links from prior runs.
            from tasks.base import create_job
            ident_job_id = create_job(db, media_id, "identify")
            from tasks.identify import identify_people
            identify_people.delay(media_id, ident_job_id)
            return

        rej_note = ", ".join(f"{k}={v}" for k, v in rejects.items() if v)
        append_log(db, job_id, f"Detected {len(embeddings)} faces across {frames_sampled or len(scenes)} sampled frames" + (f" (rejected: {rej_note})" if rej_note else ""))

        X = np.array(embeddings)
        clustering = DBSCAN(eps=CLUSTER_EPS, min_samples=1, metric="cosine").fit(X)
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

        # Re-runs must replace, not accumulate: drop this asset's old clusters
        # (identify rebuilds appearances from the fresh set afterwards).
        db.execute(text("DELETE FROM face_clusters WHERE media_id = :mid"), {"mid": media_id})

        def _load_source(src):
            kind, ref = src
            if kind == "file":
                return Image.open(ref).convert("RGB")
            return _grab_frame(ref)

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

            # Face crop thumbnail: prefer the largest detected face in the cluster
            face_thumb_name = None
            if member_idx:
                best = max(
                    member_idx,
                    key=lambda i: (scene_meta[i]["box"][2] - scene_meta[i]["box"][0])
                    * (scene_meta[i]["box"][3] - scene_meta[i]["box"][1]),
                )
                meta = scene_meta[best]
                try:
                    src_img = _load_source(meta["src"])
                    if src_img is not None:
                        x1, y1, x2, y2 = meta["box"]
                        mx = (x2 - x1) * 0.3
                        my = (y2 - y1) * 0.3
                        crop = src_img.crop((
                            max(0, int(x1 - mx)), max(0, int(y1 - my)),
                            min(src_img.width, int(x2 + mx)), min(src_img.height, int(y2 + my)),
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
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        db.close()
