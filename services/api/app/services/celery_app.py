from celery import Celery
from ..config import settings

celery_app = Celery(
    "obtv_worker",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "tasks.ingest",
        "tasks.proxy",
        "tasks.audio",
        "tasks.transcribe",
        "tasks.diarize",
        "tasks.scene_detect",
        "tasks.visual_embed",
        "tasks.face_detect",
        "tasks.index",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Must match services/worker/celeryconfig.py — Redis re-delivers unacked
    # tasks after this timeout; long GPU jobs need far more than the 1 h default.
    broker_transport_options={"visibility_timeout": 86400},
    task_routes={
        "tasks.ingest.*": {"queue": "ingest"},
        "tasks.transcribe.*": {"queue": "gpu"},
        "tasks.visual_embed.*": {"queue": "gpu"},
        "tasks.face_detect.*": {"queue": "gpu"},
        "tasks.diarize.*": {"queue": "gpu"},
        "tasks.scene_detect.*": {"queue": "cpu"},
        "tasks.proxy.*": {"queue": "cpu"},
        "tasks.audio.*": {"queue": "cpu"},
        "tasks.index.*": {"queue": "cpu"},
    },
)
