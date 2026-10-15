"""No broker writes: validate final publish options in the production image."""
from ingest_cpu_app import INGEST_CPU_TASKS, celery_app
from unittest.mock import patch

celery_app.loader.import_default_modules()
celery_app.finalize()

for name in INGEST_CPU_TASKS:
    task = celery_app.tasks[name]
    with patch.object(task, "typing", False), patch.object(celery_app, "send_task") as publish:
        task.apply_async(args=("routing-probe-only",))
        assert publish.call_args.kwargs["queue"] == "cpu-ingest", name

for name, expected in {
    "tasks.ingest.run_ingest_pipeline": "ingest",
    "tasks.catalog_media.ingest": "ingest",
    "tasks.transcribe.transcribe_audio": "gpu",
    "tasks.visual_embed.embed_scenes": "gpu",
    "tasks.render.render_clip": "cpu",
    "tasks.publish.publish_render": "cpu",
    "tasks.reel.build_reel": "cpu",
    "tasks.social_sync.sync_social_channels": "cpu",
}.items():
    task = celery_app.tasks[name]
    with patch.object(task, "typing", False), patch.object(celery_app, "send_task") as publish:
        task.apply_async(args=("routing-probe-only",))
        assert publish.call_args.kwargs["queue"] == expected, name

print("CPU ingestion routing verified; GPU and unrelated CPU routes preserved")
