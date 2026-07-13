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


async def enqueue_job(job_type: str, media_id: str | None, job_id: str, extra: dict | None = None) -> str:
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
        "social": ("gpu", "tasks.social.score_social"),
        "translate": ("gpu", "tasks.translate.translate_transcript"),
        "dub": ("gpu", "tasks.dub.generate_dub"),
        "identify": ("gpu", "tasks.identify.identify_people"),
        "insights": ("gpu", "tasks.insights.generate_insights"),
    }
    queue, task_name = task_map.get(job_type, ("cpu", f"tasks.{job_type}.run"))
    payload = {"media_id": media_id, "job_id": job_id}
    if extra:
        payload.update(extra)
    await _publish(queue, task_name, payload, str(uuid.uuid4()))
    return job_id


async def enqueue_render(render_id: str) -> str:
    await _publish("cpu", "tasks.render.render_clip", {"render_id": render_id}, str(uuid.uuid4()))
    return render_id


async def enqueue_reel(reel_id: str) -> str:
    await _publish("cpu", "tasks.reel.build_reel", {"reel_id": reel_id}, str(uuid.uuid4()))
    return reel_id


async def enqueue_publish(render_id: str) -> str:
    await _publish("cpu", "tasks.publish.publish_render", {"render_id": render_id}, str(uuid.uuid4()))
    return render_id
