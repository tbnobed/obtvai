"""Transcribe audio with timestamps using faster-whisper (CUDA)."""
import os
import uuid
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log, update_asset, create_job
from config import AUDIO_DIR, WHISPER_MODEL, WHISPER_LANGUAGE


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

            # Language detection: Whisper auto-detects from ONLY the first 30 s.
            # Dailies often start with quiet room tone, so it guesses a random
            # language (e.g. Welsh) and then "transcribes" the whole English
            # interview in it. Sample several windows across the file and take
            # a probability-weighted majority vote instead.
            import subprocess, tempfile
            language = None
            if WHISPER_LANGUAGE:
                language = WHISPER_LANGUAGE
                append_log(db, job_id, f"Language pinned via WHISPER_LANGUAGE: {language}")
            else:
                def _wav_duration(path: str) -> float:
                    out = subprocess.run(
                        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=nw=1:nk=1", path],
                        capture_output=True, text=True, timeout=30,
                    )
                    try:
                        return float(out.stdout.strip())
                    except ValueError:
                        return 0.0

                dur = _wav_duration(audio_path)
                votes: dict[str, float] = {}
                # Keep memory O(window): seek-extract each 30 s probe with
                # ffmpeg instead of decoding the whole file into RAM.
                fracs = (0.1, 0.3, 0.5, 0.7, 0.9) if dur > 60 else (0.0,)
                for frac in fracs:
                    start = dur * frac
                    if dur - start < 5 and frac > 0:
                        continue
                    with tempfile.NamedTemporaryFile(suffix=".wav") as tf:
                        ext = subprocess.run(
                            ["ffmpeg", "-y", "-ss", f"{start:.2f}", "-t", "30",
                             "-i", audio_path, "-ar", "16000", "-ac", "1", tf.name],
                            capture_output=True, text=True, timeout=120,
                        )
                        if ext.returncode != 0:
                            continue
                        try:
                            _, chunk_info = model.transcribe(
                                tf.name, beam_size=1, vad_filter=True,
                                condition_on_previous_text=False,
                                without_timestamps=True,
                            )
                            lang = chunk_info.language
                            prob = float(chunk_info.language_probability or 0)
                            votes[lang] = votes.get(lang, 0.0) + prob
                        except Exception:
                            continue
                if votes:
                    top = max(votes, key=votes.get)
                    # Whisper notoriously misdetects English as Welsh (and a few
                    # other confusables). If English got ANY meaningful vote,
                    # prefer it over a known confusable winner.
                    confusables = {"cy", "nn", "haw", "jw", "br", "la"}
                    if top in confusables and votes.get("en", 0.0) >= 0.3:
                        top = "en"
                    if votes[top] >= 0.5:
                        language = top
                if language:
                    append_log(db, job_id, f"Detected language: {language} "
                               f"(votes: {', '.join(f'{k}={v:.2f}' for k, v in sorted(votes.items(), key=lambda x: -x[1]))})")

            # vad_filter: skip non-speech audio — without it Whisper hallucinates
            # cues ("You" / "Thank you.") at every 30 s window boundary on
            # silent/ambient-only material (e.g. dailies).
            # condition_on_previous_text=False: prevents a hallucination from one
            # window seeding repetition loops in the following windows.
            segments, info = model.transcribe(
                audio_path,
                language=language,
                beam_size=5,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=False,
            )
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
