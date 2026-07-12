"""Async helpers for enqueuing Celery tasks via Redis."""
import json
import uuid
import redis.asyncio as aioredis
from .config import settings


async def _publish(queue: str, task_name: str, kwargs: dict, task_id: str):
    r = aioredis.from_url(settings.redis_url)
    payload = {
        "id": task_id,
        "task": task_name,
        "kwargs": kwargs,
        "retries": 0,
    }
    try:
        await r.rpush(queue, json.dumps(payload))
    finally:
        await r.aclose()


async def enqueue_ingest(media_id: str) -> str:
    task_id = str(uuid.uuid4())
    await _publish("ingest", "tasks.ingest.run_ingest_pipeline", {"media_id": media_id}, task_id)
    return task_id


async def enqueue_job(job_type: str, media_id: str, job_id: str) -> str:
    task_map = {
        "ingest": ("ingest", "tasks.ingest.run_ingest_pipeline"),
        "proxy": ("cpu", "tasks.proxy.create_proxy"),
        "audio_extract": ("cpu", "tasks.audio.extract_audio"),
        "transcribe": ("gpu", "tasks.transcribe.transcribe_audio"),
        "diarize": ("gpu", "tasks.diarize.run_diarization"),
        "scene_detect": ("cpu", "tasks.scene_detect.detect_scenes"),
        "visual_embed": ("gpu", "tasks.visual_embed.embed_scenes"),
        "face_detect": ("gpu", "tasks.face_detect.detect_faces"),
        "index": ("cpu", "tasks.index.build_index"),
    }
    queue, task_name = task_map.get(job_type, ("cpu", f"tasks.{job_type}.run"))
    await _publish(queue, task_name, {"media_id": media_id, "job_id": job_id}, str(uuid.uuid4()))
    return job_id
