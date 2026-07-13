"""Orchestrates the full ingestion pipeline for a media asset."""
import os
import subprocess
import json
import uuid
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log, create_job, update_asset


@celery_app.task(bind=True, name="tasks.ingest.run_ingest_pipeline", queue="ingest")
def run_ingest_pipeline(self, media_id: str, job_id: str = None):
    db = get_session()
    try:
        if not job_id:
            job_id = create_job(db, media_id, "ingest")

        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)
        update_asset(db, media_id, status="processing", processing_stage="metadata", processing_progress=5.0)

        from sqlalchemy import text
        row = db.execute(text("SELECT original_path, filename FROM media_assets WHERE id = :mid"), {"mid": media_id}).fetchone()
        if not row or not row[0]:
            raise ValueError("No source file path for asset")

        src_path = row[0]
        append_log(db, job_id, f"Starting ingest for: {src_path}")

        # Extract metadata with ffprobe
        append_log(db, job_id, "Extracting metadata with ffprobe...")
        metadata = _ffprobe(src_path)
        update_asset(db, media_id,
            duration_seconds=metadata.get("duration"),
            width=metadata.get("width"),
            height=metadata.get("height"),
            fps=metadata.get("fps"),
            codec=metadata.get("codec"),
            processing_stage="metadata",
            processing_progress=10.0,
        )
        append_log(db, job_id, f"Metadata: {metadata.get('width')}x{metadata.get('height')} {metadata.get('duration'):.1f}s {metadata.get('codec')}")

        # Create proxy
        append_log(db, job_id, "Creating browser-compatible proxy...")
        proxy_job_id = create_job(db, media_id, "proxy")
        from tasks.proxy import create_proxy
        create_proxy.delay(media_id, proxy_job_id)

        # Extract audio
        append_log(db, job_id, "Queuing audio extraction...")
        audio_job_id = create_job(db, media_id, "audio_extract")
        from tasks.audio import extract_audio
        extract_audio.delay(media_id, audio_job_id)

        # Scene detection
        append_log(db, job_id, "Queuing scene detection...")
        scene_job_id = create_job(db, media_id, "scene_detect")
        from tasks.scene_detect import detect_scenes
        detect_scenes.delay(media_id, scene_job_id)

        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        update_asset(db, media_id, processing_stage="queued_for_processing", processing_progress=20.0)
        append_log(db, job_id, "Ingest complete — downstream jobs queued")

    except Exception as e:
        update_job(db, job_id or "unknown", status="error", error_message=str(e), finished_at=datetime.utcnow())
        update_asset(db, media_id, status="error", processing_stage="ingest_failed")
        raise
    finally:
        db.close()


def _ffprobe(path: str) -> dict:
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    data = json.loads(result.stdout)

    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    duration = float(data.get("format", {}).get("duration", 0) or 0)
    width = int(video_stream.get("width", 0)) if video_stream else None
    height = int(video_stream.get("height", 0)) if video_stream else None
    codec = video_stream.get("codec_name") if video_stream else None

    fps = None
    if video_stream:
        r_frame_rate = video_stream.get("r_frame_rate", "0/1")
        try:
            num, den = r_frame_rate.split("/")
            fps = float(num) / float(den) if float(den) > 0 else None
        except Exception:
            fps = None

    return {"duration": duration, "width": width, "height": height, "codec": codec, "fps": fps}
