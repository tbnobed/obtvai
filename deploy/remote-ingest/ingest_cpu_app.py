"""CPU-worker entrypoint: isolate ingestion preparation from general CPU jobs.

Use on both the main CPU worker (which publishes ingest children) and remote
CPU consumers. GPU tasks and API publications retain their existing routes.
The main CPU worker also consumes cpu-ingest, providing fallback capacity.
"""
from app import celery_app

INGEST_CPU_TASKS = (
    "tasks.audio.extract_audio",
    "tasks.proxy.create_proxy",
    "tasks.scene_detect.detect_scenes",
    "tasks.sprites.generate_sprite",
    "tasks.qc.run_qc",
    "tasks.qc.run_editorial_qc",
    "tasks.index.build_index",
)

# Celery applies annotations when task classes bind, after decorator defaults.
# Set these before the loader imports task modules; do not mutate live tasks.
celery_app.conf.task_annotations = {
    name: {"queue": "cpu-ingest"} for name in INGEST_CPU_TASKS
}
