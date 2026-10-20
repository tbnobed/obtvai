"""Opt-in routing for user-requested secondary GPU work."""
import os

INTERACTIVE_TASKS = frozenset({
    "tasks.translate.translate_transcript",
    "tasks.dub.generate_dub",
    "tasks.voice.generate_speech",
    "tasks.voice.lipsync_video",
})


def publication_queue(default_queue: str, task_name: str) -> str:
    if task_name not in INTERACTIVE_TASKS:
        return default_queue
    queue = os.environ.get("INTERACTIVE_GPU_QUEUE", default_queue).strip()
    if not queue:
        raise ValueError("INTERACTIVE_GPU_QUEUE must not be empty")
    return queue
