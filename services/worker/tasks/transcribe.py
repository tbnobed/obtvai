"""Transcribe audio with timestamps using faster-whisper (CUDA)."""
import os
import uuid
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log, update_asset, create_job
from config import AUDIO_DIR, WHISPER_MODEL


@celery_app.task(bind=True, name="tasks.transcribe.transcribe_audio", queue="gpu")
def transcribe_audio(self, media_id: str, job_id: str):
    db = get_session()
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)
        update_asset(db, media_id, processing_stage="transcribing", processing_progress=50.0)

        audio_path = os.path.join(AUDIO_DIR, f"{media_id}.wav")
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        append_log(db, job_id, f"Loading Whisper model: {WHISPER_MODEL}")

        from faster_whisper import WhisperModel
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute = "float16" if device == "cuda" else "int8"

        model = WhisperModel(WHISPER_MODEL, device=device, compute_type=compute)
        append_log(db, job_id, f"Transcribing with {device}...")

        segments, info = model.transcribe(audio_path, beam_size=5, word_timestamps=True)

        from sqlalchemy import text
        inserted = 0
        for seg in segments:
            seg_id = str(uuid.uuid4())
            db.execute(
                text("""
                    INSERT INTO transcript_segments (id, media_id, start_time, end_time, text, confidence)
                    VALUES (:id, :mid, :start, :end, :txt, :conf)
                """),
                {
                    "id": seg_id,
                    "mid": media_id,
                    "start": seg.start,
                    "end": seg.end,
                    "txt": seg.text.strip(),
                    "conf": seg.avg_logprob if hasattr(seg, "avg_logprob") else None,
                },
            )
            inserted += 1

        db.commit()
        append_log(db, job_id, f"Transcription complete: {inserted} segments")
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        update_asset(db, media_id, processing_stage="transcribed", processing_progress=65.0)

        # Queue diarization
        diar_job_id = create_job(db, media_id, "diarize")
        from tasks.diarize import run_diarization
        run_diarization.delay(media_id, diar_job_id)

        # Queue indexing
        index_job_id = create_job(db, media_id, "index")
        from tasks.index import build_index
        build_index.delay(media_id, index_job_id)

    except Exception as e:
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
