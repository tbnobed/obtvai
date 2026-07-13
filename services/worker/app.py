from celery import Celery
from config import REDIS_URL

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
        "tasks.analyze",
        "tasks.highlight",
        "tasks.social",
        "tasks.translate",
        "tasks.dub",
    ],
)
celery_app.config_from_object("celeryconfig")
