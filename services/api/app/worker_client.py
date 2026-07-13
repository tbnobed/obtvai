"""Async helpers for enqueuing Celery tasks via Redis.

Uses the real Celery client so messages are published in the Celery/kombu
wire format the workers expect. Hand-rolled JSON pushed straight to the
Redis list crashes workers with KeyError('properties').
"""
import uuid
from celery import Celery
from fastapi.concurrency import run_in_threadpool
from .config import settings

_celery = Celery("obtv_api", broker=settings.redis_url, backend=settings.redis_url)
_celery.conf.task_serializer = "json"
_celery.conf.broker_connection_retry_on_startup = True


async def _publish(queue: str, task_name: str, kwargs: dict, task_id: str):
    # send_task is blocking (sync Redis connection), so run it off the event loop.
    await run_in_threadpool(
        _celery.send_task,
        task_name,
        kwargs=kwargs,
        queue=queue,
        task_id=task_id,
    )


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
        "analyze": ("gpu", "tasks.analyze.analyze_media"),
        "highlight": ("cpu", "tasks.highlight.build_highlight"),
    }
    queue, task_name = task_map.get(job_type, ("cpu", f"tasks.{job_type}.run"))
    await _publish(queue, task_name, {"media_id": media_id, "job_id": job_id}, str(uuid.uuid4()))
    return job_id
