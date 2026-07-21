import os

broker_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
result_backend = os.getenv("REDIS_URL", "redis://redis:6379/0")
task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]
task_track_started = True
task_acks_late = True
worker_prefetch_multiplier = 1
# With acks_late + Redis, an unacked task is re-delivered after the visibility
# timeout (default 1 h). Long GPU jobs (dub + lip sync) run for many hours and
# were being restarted mid-run every hour. 24 h covers the longest jobs.
broker_transport_options = {"visibility_timeout": 86400}
broker_connection_retry_on_startup = True

# Periodic tasks (worker-cpu runs with -B / embedded beat).
beat_schedule = {
    "sync-youtube-stats": {
        "task": "tasks.social_stats.sync_youtube_stats",
        "schedule": 3600.0,  # hourly; videos.list is 1 quota unit per 50 videos
        "options": {"queue": "cpu"},
    },
    "fetch-external-trends": {
        "task": "tasks.trends.fetch_trends",
        "schedule": 10800.0,  # every 3 h; 1 YouTube quota unit + ~25 SearXNG queries
        "options": {"queue": "cpu"},
    },
}
