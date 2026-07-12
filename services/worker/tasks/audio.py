"""Extract audio track as WAV for transcription."""
import os
import subprocess
from datetime import datetime
from ..app import celery_app
from ..db import get_session
from .base import update_job, append_log, update_asset
from ..config import AUDIO_DIR


@celery_app.task(bind=True, name="tasks.audio.extract_audio", queue="cpu")
def extract_audio(self, media_id: str, job_id: str):
    db = get_session()
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)
        update_asset(db, media_id, processing_stage="audio_extract", processing_progress=30.0)

        from sqlalchemy import text
        row = db.execute(text("SELECT original_path FROM media_assets WHERE id = :mid"), {"mid": media_id}).fetchone()
        src = row[0]

        os.makedirs(AUDIO_DIR, exist_ok=True)
        audio_path = os.path.join(AUDIO_DIR, f"{media_id}.wav")
        append_log(db, job_id, f"Extracting audio to {audio_path}")

        cmd = [
            "ffmpeg", "-y", "-i", src,
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            audio_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg audio extract failed: {result.stderr[-500:]}")

        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        append_log(db, job_id, "Audio extracted successfully")

        # Queue transcription
        from .base import create_job
        trans_job_id = create_job(db, media_id, "transcribe")
        from .transcribe import transcribe_audio
        transcribe_audio.delay(media_id, trans_job_id)

    except Exception as e:
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
