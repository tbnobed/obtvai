"""Extract audio track as WAV for transcription."""
import os
import subprocess
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log, update_asset
from config import AUDIO_DIR


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

        # Curator WebProxy _video.mp4 files are video-only: the audio lives in
        # sidecar _audioN.mp4 files in the same folder. Extract from those.
        from tasks.curator import is_curator_video, has_audio_stream, find_curator_audio
        inputs = [src]
        if is_curator_video(src) and not has_audio_stream(src):
            sidecars = find_curator_audio(src)
            if not sidecars:
                raise RuntimeError(
                    "Source video has no audio track and no Curator _audioN.mp4 "
                    "sidecar was found next to it"
                )
            inputs = sidecars
            append_log(db, job_id, "Video-only Curator proxy — using sidecar audio: "
                       + ", ".join(os.path.basename(p) for p in inputs))

        cmd = ["ffmpeg", "-y"]
        for p in inputs:
            cmd += ["-i", p]
        if len(inputs) > 1:
            cmd += ["-filter_complex", f"amix=inputs={len(inputs)}:duration=longest:normalize=0"]
        cmd += [
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
        from tasks.base import create_job
        trans_job_id = create_job(db, media_id, "transcribe")
        from tasks.transcribe import transcribe_audio
        transcribe_audio.delay(media_id, trans_job_id)

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
