"""Speaker diarization using pyannote.audio."""
import os
from datetime import datetime
from ..app import celery_app
from ..db import get_session
from .base import update_job, append_log, update_asset
from ..config import AUDIO_DIR


@celery_app.task(bind=True, name="tasks.diarize.run_diarization", queue="gpu")
def run_diarization(self, media_id: str, job_id: str):
    db = get_session()
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)
        update_asset(db, media_id, processing_stage="diarizing", processing_progress=70.0)

        audio_path = os.path.join(AUDIO_DIR, f"{media_id}.wav")
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio not found: {audio_path}")

        from pyannote.audio import Pipeline
        import torch

        append_log(db, job_id, "Loading diarization pipeline...")
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=os.getenv("HF_TOKEN", ""),
        )
        pipeline = pipeline.to(device)

        append_log(db, job_id, "Running diarization...")
        diarization = pipeline(audio_path)

        speaker_map: dict[str, list[tuple[float, float]]] = {}
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            speaker_map.setdefault(speaker, []).append((turn.start, turn.end))

        from sqlalchemy import text
        for seg_row in db.execute(
            text("SELECT id, start_time, end_time FROM transcript_segments WHERE media_id = :mid ORDER BY start_time"),
            {"mid": media_id},
        ).fetchall():
            seg_id, seg_start, seg_end = seg_row
            best_speaker = None
            best_overlap = 0.0
            for speaker, intervals in speaker_map.items():
                for turn_start, turn_end in intervals:
                    overlap = min(seg_end, turn_end) - max(seg_start, turn_start)
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_speaker = speaker
            if best_speaker:
                db.execute(
                    text("UPDATE transcript_segments SET speaker = :spk WHERE id = :sid"),
                    {"spk": best_speaker, "sid": seg_id},
                )

        db.commit()
        n_speakers = len(speaker_map)
        update_asset(db, media_id, speaker_count=n_speakers, processing_stage="diarized", processing_progress=75.0)
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        append_log(db, job_id, f"Diarization complete: {n_speakers} speakers found")

    except Exception as e:
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
