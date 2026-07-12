from celery import Celery
from .config import REDIS_URL

celery_app = Celery(
    "obtv_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
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
celery_app.config_from_object("celeryconfig")
