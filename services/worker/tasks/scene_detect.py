"""Detect scenes and extract representative frames."""
import os
import uuid
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log, update_asset, create_job
from config import PROXIES_DIR, THUMBNAILS_DIR


@celery_app.task(bind=True, name="tasks.scene_detect.detect_scenes", queue="cpu")
def detect_scenes(self, media_id: str, job_id: str):
    db = get_session()
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)
        update_asset(db, media_id, processing_stage="scene_detect", processing_progress=45.0)

        from sqlalchemy import text
        row = db.execute(text("SELECT original_path, proxy_path FROM media_assets WHERE id = :mid"), {"mid": media_id}).fetchone()
        video_path = row[1] or row[0]

        if not video_path or not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found for scene detection")

        append_log(db, job_id, f"Detecting scenes in {os.path.basename(video_path)}")

        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector

        video = open_video(video_path)
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=27.0))
        scene_manager.detect_scenes(video, show_progress=False)
        scene_list = scene_manager.get_scene_list()

        os.makedirs(THUMBNAILS_DIR, exist_ok=True)

        # Idempotent retry: drop scenes from any previous run so we never
        # accumulate duplicates.
        db.execute(text("DELETE FROM scenes WHERE media_id = :mid"), {"mid": media_id})

        import subprocess
        inserted = 0
        thumb_failures = 0
        for scene_start, scene_end in scene_list:
            scene_id = str(uuid.uuid4())
            start_sec = scene_start.get_seconds()
            end_sec = scene_end.get_seconds()
            duration = max(0.1, end_sec - start_sec)

            thumb_name = f"scene_{scene_id}.jpg"
            thumb_path = os.path.join(THUMBNAILS_DIR, thumb_name)

            # Pick a *representative* frame, not a blind midpoint grab.
            # Textless masters and fades often have black frames at/around
            # cuts; ffmpeg's `thumbnail` filter scans sampled frames and picks
            # the most representative one (histogram-based), which avoids
            # black/uniform frames. Sample up to ~30s of the scene at 2fps.
            sample_span = min(duration, 30.0)
            batch = max(2, int(sample_span * 2))
            proc = subprocess.run(
                [
                    "ffmpeg", "-y", "-ss", str(start_sec),
                    "-i", video_path, "-t", str(sample_span),
                    "-vf", f"fps=2,thumbnail={batch}",
                    "-frames:v", "1", "-q:v", "3", thumb_path,
                ],
                capture_output=True, timeout=120,
            )
            if proc.returncode != 0 or not os.path.exists(thumb_path):
                thumb_failures += 1
                # Fallback: plain midpoint grab so we at least have something.
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-ss", str(start_sec + duration / 2),
                        "-i", video_path, "-vframes", "1", "-q:v", "3", thumb_path,
                    ],
                    capture_output=True, timeout=30,
                )

            db.execute(
                text("""
                    INSERT INTO scenes (id, media_id, start_time, end_time, thumbnail_url)
                    VALUES (:id, :mid, :start, :end, :thumb)
                """),
                {
                    "id": scene_id,
                    "mid": media_id,
                    "start": start_sec,
                    "end": end_sec,
                    "thumb": thumb_name if os.path.exists(thumb_path) else None,
                },
            )
            inserted += 1

        db.commit()
        update_asset(db, media_id, scene_count=inserted, processing_stage="scenes_detected", processing_progress=60.0)
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        append_log(db, job_id, f"Detected {inserted} scenes")
        if thumb_failures:
            append_log(db, job_id, f"{thumb_failures} scene(s) needed midpoint-frame fallback for thumbnails")

        # Queue visual embedding
        vis_job_id = create_job(db, media_id, "visual_embed")
        from tasks.visual_embed import embed_scenes
        embed_scenes.delay(media_id, vis_job_id)

        # Queue face detection
        face_job_id = create_job(db, media_id, "face_detect")
        from tasks.face_detect import detect_faces
        detect_faces.delay(media_id, face_job_id)

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
