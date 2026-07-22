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

        from sqlalchemy import text
        audio_path = os.path.join(AUDIO_DIR, f"{media_id}.wav")

        def _insert_segments(rows):
            # Idempotent re-run: clear any segments left by a previous attempt
            db.execute(text("DELETE FROM transcript_segments WHERE media_id = :mid"), {"mid": media_id})
            db.commit()
            n = 0
            for start, end, txt, conf in rows:
                db.execute(
                    text("""
                        INSERT INTO transcript_segments (id, media_id, start_time, end_time, text, confidence)
                        VALUES (:id, :mid, :start, :end, :txt, :conf)
                    """),
                    {"id": str(uuid.uuid4()), "mid": media_id,
                     "start": start, "end": end, "txt": txt, "conf": conf},
                )
                n += 1
            db.commit()
            return n

        try:
            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"Audio file not found: {audio_path}")

            append_log(db, job_id, f"Loading Whisper model: {WHISPER_MODEL}")

            from faster_whisper import WhisperModel
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            compute = "float16" if device == "cuda" else "int8"

            from tasks.gpu_mem import load_with_oom_retry
            model = load_with_oom_retry(
                WHISPER_MODEL,
                lambda: WhisperModel(WHISPER_MODEL, device=device, compute_type=compute),
            )
            append_log(db, job_id, f"Transcribing with {device}...")

            segments, info = model.transcribe(audio_path, beam_size=5, word_timestamps=True)
            total_duration = float(getattr(info, "duration", 0) or 0)

            db.execute(text("DELETE FROM transcript_segments WHERE media_id = :mid"), {"mid": media_id})
            db.commit()

            inserted = 0
            last_reported = 0.0
            for seg in segments:
                db.execute(
                    text("""
                        INSERT INTO transcript_segments (id, media_id, start_time, end_time, text, confidence)
                        VALUES (:id, :mid, :start, :end, :txt, :conf)
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "mid": media_id,
                        "start": float(seg.start),
                        "end": float(seg.end),
                        "txt": seg.text.strip(),
                        "conf": float(seg.avg_logprob) if getattr(seg, "avg_logprob", None) is not None else None,
                    },
                )
                inserted += 1
                if total_duration > 0:
                    pct = min(99.0, (float(seg.end) / total_duration) * 100.0)
                    if pct - last_reported >= 5.0:
                        last_reported = pct
                        update_job(db, job_id, progress=round(pct, 1))

            db.commit()
            append_log(db, job_id, f"Transcription complete: {inserted} segments")
        except Exception as whisper_err:
            # Fallback: Curator assets ship their own STT subtitles
            # (<id>_subtitle.vtt). Only used when Whisper itself fails.
            db.rollback()
            row = db.execute(text("SELECT original_path FROM media_assets WHERE id = :mid"),
                             {"mid": media_id}).fetchone()
            src = row[0] if row else None
            from tasks.curator import is_curator_video, find_curator_vtt, parse_vtt
            vtt = find_curator_vtt(src) if src and is_curator_video(src) else None
            if not vtt:
                raise
            append_log(db, job_id,
                       f"Whisper failed ({str(whisper_err)[:200]}) — falling back to Curator VTT: {vtt}")
            cues = parse_vtt(vtt)
            if not cues:
                raise RuntimeError(
                    f"Whisper failed and Curator VTT {vtt} had no usable cues; "
                    f"whisper error: {whisper_err}"
                )
            inserted = _insert_segments((s, e, t, None) for s, e, t in cues)
            append_log(db, job_id, f"Transcript loaded from Curator VTT: {inserted} segments")
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
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
