"""Explicit Audio/Image pipelines; source SMB files are never copied or modified."""
import json
import math
import os
import subprocess
import uuid
from datetime import datetime

from app import celery_app
from db import get_session
from tasks.base import update_job, update_asset, append_log, create_job


def audio_metadata(source):
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format",
        "-of", "json", source,
    ], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError("Audio source ffprobe failed: " + result.stderr[-400:])
    probe = json.loads(result.stdout)
    streams = probe.get("streams", [])
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    moving_video = any(s.get("codec_type") == "video" and not
                       s.get("disposition", {}).get("attached_pic") for s in streams)
    if not audio or moving_video:
        raise RuntimeError("Audio asset must contain audio, not moving video")
    duration = float(probe.get("format", {}).get("duration", 0))
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError("Audio source has no valid duration")
    return duration, audio.get("codec_name")


def prepare_image(source, media_id):
    from PIL import Image, ImageOps
    from config import THUMBNAILS_DIR
    with Image.open(source) as original:
        if getattr(original, "n_frames", 1) != 1:
            raise RuntimeError("Animated/multipage images are not supported")
        original.load()  # malformed images must fail before any success status
        width, height = original.size
        codec = original.format
        image = ImageOps.exif_transpose(original).convert("RGB")
        image.thumbnail((1280, 1280))
        os.makedirs(THUMBNAILS_DIR, exist_ok=True)
        name = f"{media_id}_image.jpg"
        target = os.path.join(THUMBNAILS_DIR, name)
        temp = target + ".tmp"
        try:
            image.save(temp, format="JPEG", quality=90)
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return width, height, codec, name


@celery_app.task(bind=True, name="tasks.catalog_media.ingest", queue="ingest")
def ingest(self, media_id: str, job_id: str, asset_type: str):
    from sqlalchemy import text
    db = get_session()
    locked = False
    try:
        locked = bool(db.execute(text(
            "SELECT pg_try_advisory_lock(hashtext(:key))"
        ), {"key": "obtv_ingest:" + media_id}).scalar())
        if not locked:
            return
        prior = db.execute(text("SELECT status FROM processing_jobs WHERE id=:id"),
                           {"id": job_id}).scalar()
        if prior in ("success", "cancelled"):
            return
        if prior is None:
            raise RuntimeError("Catalog ingest job is missing")
        from catalog_storage import require_archive_storage
        require_archive_storage()
        update_job(db, job_id, status="running", started_at=datetime.utcnow(),
                   celery_task_id=self.request.id)
        source = db.execute(text("SELECT original_path FROM media_assets WHERE id=:id"),
                            {"id": media_id}).scalar()
        if not source or not os.path.isfile(source):
            raise RuntimeError("Catalog source file is unavailable")
        update_asset(db, media_id, status="processing", processing_stage="metadata",
                     processing_progress=5)
        if asset_type == "Audio":
            duration, codec = audio_metadata(source)
            update_asset(db, media_id, duration_seconds=duration, codec=codec)
            # Existing audio extraction chains to real transcription, diarization,
            # and transcript indexing; no video proxy or scene detector is queued.
            from tasks.audio import extract_audio
            stage = create_job(db, media_id, "audio_extract")
            extract_audio.delay(media_id, stage)
            append_log(db, job_id, "Audio-only extraction/transcription/index pipeline queued")
        elif asset_type == "Image":
            width, height, codec, thumb = prepare_image(source, media_id)
            scene_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "catalog-image:" + media_id))
            db.execute(text("""
                INSERT INTO scenes (id, media_id, start_time, end_time, thumbnail_url)
                VALUES (:id, :mid, 0, 0, :thumb)
                ON CONFLICT (id) DO UPDATE SET thumbnail_url=EXCLUDED.thumbnail_url
            """), {"id": scene_id, "mid": media_id, "thumb": thumb})
            db.commit()
            update_asset(db, media_id, width=width, height=height, codec=codec,
                         duration_seconds=0, thumbnail_url=thumb, scene_count=1)
            # This task is explicitly routed to gpu for Image by the API.
            # Synchronous substage execution preserves honest readiness/failure.
            from tasks.visual_embed import embed_scenes
            stage = create_job(db, media_id, "visual_embed")
            embed_scenes.run(media_id, stage)
            embedded = db.execute(text("SELECT embedding_id FROM scenes WHERE id=:id"),
                                  {"id": scene_id}).scalar()
            if not embedded:
                raise RuntimeError("Image did not produce a searchable visual embedding")
            from tasks.florence_caption import caption_scenes
            stage = create_job(db, media_id, "florence_caption")
            caption_scenes.run(media_id, stage)
            description = db.execute(text("SELECT description FROM scenes WHERE id=:id"),
                                     {"id": scene_id}).scalar()
            if not description:
                raise RuntimeError("Image captioning produced no description")
            update_asset(db, media_id, status="ready", processing_stage="complete",
                         processing_progress=100)
            append_log(db, job_id, "Image thumbnail, visual embedding and caption complete")
        else:
            raise RuntimeError(f"Unsupported catalog asset type: {asset_type}")
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100)
    except Exception as exc:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(exc)[:2000],
                   finished_at=datetime.utcnow())
        update_asset(db, media_id, status="error", processing_stage="ingest_failed")
        raise
    finally:
        if locked:
            db.rollback()
            db.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"),
                       {"key": "obtv_ingest:" + media_id})
            db.commit()
        db.close()