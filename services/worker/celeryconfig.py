import os

broker_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
result_backend = os.getenv("REDIS_URL", "redis://redis:6379/0")
task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]
task_track_started = True
task_acks_late = True
worker_prefetch_multiplier = 1
broker_connection_retry_on_startup = True

# Periodic tasks (worker-cpu runs with -B / embedded beat).
beat_schedule = {
    "sync-youtube-stats": {
        "task": "tasks.social_stats.sync_youtube_stats",
        "schedule": 3600.0,  # hourly; videos.list is 1 quota unit per 50 videos
        "options": {"queue": "cpu"},
    },
}
