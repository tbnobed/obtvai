"""Speaker diarization using pyannote.audio."""
import os
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log, update_asset
from config import AUDIO_DIR


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

        DIARIZATION_MODEL = os.getenv(
            "DIARIZATION_MODEL", "pyannote/speaker-diarization-community-1"
        )

        # PyTorch >=2.6 defaults torch.load to weights_only=True, which rejects
        # pyannote's checkpoint format. The model comes from pyannote's official
        # HF repo (trusted), so temporarily restore the legacy behavior.
        _orig_torch_load = torch.load

        def _legacy_load(*args, **kwargs):
            kwargs["weights_only"] = False
            return _orig_torch_load(*args, **kwargs)

        from tasks.gpu_mem import load_with_oom_retry

        def _load():
            try:
                # pyannote.audio >= 4.0
                return Pipeline.from_pretrained(
                    DIARIZATION_MODEL, token=os.getenv("HF_TOKEN", "") or None,
                )
            except TypeError:
                # pyannote.audio 3.x
                return Pipeline.from_pretrained(
                    DIARIZATION_MODEL, use_auth_token=os.getenv("HF_TOKEN", ""),
                )

        torch.load = _legacy_load
        try:
            pipeline = load_with_oom_retry(DIARIZATION_MODEL, _load)
        finally:
            torch.load = _orig_torch_load
        if pipeline is None:
            raise RuntimeError(
                f"Failed to load {DIARIZATION_MODEL} — check that HF_TOKEN "
                "is set and the model's gated-access terms are accepted on Hugging Face"
            )
        pipeline = pipeline.to(device)

        append_log(db, job_id, f"Running diarization ({DIARIZATION_MODEL})...")
        try:
            result = pipeline(audio_path, return_embeddings=True)
        except TypeError:
            # pyannote 4.x pipelines don't take return_embeddings; embeddings
            # (if available) come back on the output object instead.
            result = pipeline(audio_path)
        # pyannote 3.x returns (Annotation, embeddings); 4.x returns an output
        # object with .speaker_diarization / .speaker_embeddings attributes.
        if isinstance(result, tuple):
            diarization, speaker_embeddings = result
        else:
            diarization = getattr(result, "speaker_diarization", result)
            speaker_embeddings = getattr(result, "speaker_embeddings", None)

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

        # Persist per-speaker voice embeddings for cross-asset person identification.
        try:
            import json
            emb_map = {}
            labels = list(diarization.labels())
            if speaker_embeddings is not None:
                if hasattr(speaker_embeddings, "get") and hasattr(speaker_embeddings, "keys"):
                    # dict-like: keyed by speaker label (pyannote 4.x variants)
                    for label in labels:
                        vec = speaker_embeddings.get(label)
                        if vec is not None:
                            emb_map[label] = [float(x) for x in vec]
                else:
                    # array-like: row order matches diarization.labels()
                    for i, label in enumerate(labels):
                        if i < len(speaker_embeddings):
                            vec = speaker_embeddings[i]
                            if vec is not None:
                                emb_map[label] = [float(x) for x in vec]
            if emb_map:
                db.execute(
                    text("UPDATE media_assets SET speaker_embeddings = CAST(:emb AS jsonb) WHERE id = :mid"),
                    {"emb": json.dumps(emb_map), "mid": media_id},
                )
                db.commit()
                append_log(db, job_id, f"Stored voice embeddings for {len(emb_map)} speakers")
        except Exception as emb_err:
            db.rollback()
            append_log(db, job_id, f"Voice embedding capture skipped: {emb_err}")

        n_speakers = len(speaker_map)
        update_asset(db, media_id, speaker_count=n_speakers, processing_stage="diarized", processing_progress=75.0)
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        append_log(db, job_id, f"Diarization complete: {n_speakers} speakers found")

        # Queue cross-asset person identification
        from tasks.base import create_job
        ident_job_id = create_job(db, media_id, "identify")
        from tasks.identify import identify_people
        identify_people.delay(media_id, ident_job_id)

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
