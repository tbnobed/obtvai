"""Detect and cluster faces across scenes using InsightFace (SCRFD + ArcFace).

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
MIN_DET_SCORE = 0.55          # SCRFD detection confidence floor. SCRFD is far
                              # more precise than MTCNN — it rarely fires on
                              # hands/necks/graphics, so no geometry gates are
                              # needed beyond size/aspect sanity.
MIN_FACE_SIDE = 36            # ignore tiny background faces (pixels)
MIN_ASPECT = 0.5              # face box width/height sanity range
MAX_ASPECT = 1.25
CLUSTER_EPS = 0.45            # cosine DISTANCE for DBSCAN on ArcFace
                              # embeddings. ArcFace same-person similarity runs
                              # lower than FaceNet's (0.5-0.8 vs 0.7+), so the
                              # FaceNet-era 0.30 would shatter one person into
                              # many clusters. 0.45 ≈ sim 0.55.

_face_app = None


def _load_face_app():
    """Cached InsightFace FaceAnalysis (SCRFD detector + ArcFace embedder).
    buffalo_l downloads once to ~/.insightface on first run."""
    global _face_app
    if _face_app is None:
        import torch
        import onnxruntime as ort
        # Load cuDNN/cuBLAS from the pip nvidia-* wheels BEFORE any session is
        # created — they live in site-packages, not on the loader path, and
        # without this the CUDA provider silently fails and detection runs on
        # CPU (10-20x slower).
        if torch.cuda.is_available() and hasattr(ort, "preload_dlls"):
            try:
                ort.preload_dlls()
            except Exception as e:
                print(f"[face] ort.preload_dlls failed: {e}")
        from insightface.app import FaceAnalysis
        providers = (
            ["CUDAExecutionProvider", "CPUExecutionProvider"]
            if torch.cuda.is_available() else ["CPUExecutionProvider"]
        )
        app = FaceAnalysis(name="buffalo_l", providers=providers)
        app.prepare(ctx_id=0 if torch.cuda.is_available() else -1, det_size=(640, 640))
        _face_app = app
    return _face_app


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
        import numpy as np
        from PIL import Image
        from sklearn.cluster import DBSCAN

        append_log(db, job_id, "Loading InsightFace (SCRFD + ArcFace)...")
        face_app = _load_face_app()

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

        rejects = {"low_prob": 0, "too_small": 0, "aspect": 0}

        def _detect(img):
            """Returns list of (box, normed_embedding) passing confidence and
            size/aspect gates. InsightFace handles alignment internally."""
            bgr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
            keep = []
            for face in face_app.get(bgr):
                if float(face.det_score) < MIN_DET_SCORE:
                    rejects["low_prob"] += 1
                    continue
                x1, y1, x2, y2 = [float(v) for v in face.bbox]
                w, h = x2 - x1, y2 - y1
                if w < MIN_FACE_SIDE or h < MIN_FACE_SIDE:
                    rejects["too_small"] += 1
                    continue
                if h <= 0 or not (MIN_ASPECT <= w / h <= MAX_ASPECT):
                    rejects["aspect"] += 1
                    continue
                keep.append(([x1, y1, x2, y2], face.normed_embedding))
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
                    for box, emb in detections:
                        embeddings.append(np.asarray(emb, dtype=float))
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
            append_log(db, job_id, f"No faces found (candidates rejected: {rej_note or 'none detected by SCRFD'})")
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
