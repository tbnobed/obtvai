"""
File system watcher that monitors a media directory and automatically
triggers ingestion when new video files appear and finish copying.
"""
import os
import time
import logging
import hashlib
import httpx
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("watcher")

MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/media")
API_URL = os.getenv("API_URL", "http://api:8000/api")
STABLE_SECONDS = int(os.getenv("STABLE_SECONDS", "5"))
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".mxf", ".ts", ".m2ts", ".wmv", ".flv", ".webm"}

pending: dict[str, dict] = {}


def _is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS


def _file_stable(path: str) -> bool:
    try:
        size1 = os.path.getsize(path)
        time.sleep(STABLE_SECONDS)
        size2 = os.path.getsize(path)
        return size1 == size2 and size2 > 0
    except OSError:
        return False


def _ingest(path: str):
    log.info(f"Ingesting: {path}")
    try:
        resp = httpx.post(
            f"{API_URL}/media",
            json={"file_path": path},
            timeout=30,
        )
        resp.raise_for_status()
        log.info(f"Ingest queued: {resp.json().get('id')}")
    except Exception as e:
        log.error(f"Ingest failed for {path}: {e}")


class VideoHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        if _is_video(event.src_path):
            log.info(f"New file detected: {event.src_path}")
            pending[event.src_path] = {"detected_at": time.time()}

    def on_modified(self, event):
        if event.is_directory:
            return
        if _is_video(event.src_path) and event.src_path not in pending:
            pending[event.src_path] = {"detected_at": time.time()}


def main():
    log.info(f"Watching: {MEDIA_ROOT}")
    os.makedirs(MEDIA_ROOT, exist_ok=True)

    observer = Observer()
    observer.schedule(VideoHandler(), MEDIA_ROOT, recursive=True)
    observer.start()

    try:
        while True:
            now = time.time()
            to_process = []
            for path, info in list(pending.items()):
                age = now - info["detected_at"]
                if age >= STABLE_SECONDS:
                    if os.path.exists(path) and _file_stable(path):
                        to_process.append(path)
                    else:
                        del pending[path]

            for path in to_process:
                del pending[path]
                _ingest(path)

            time.sleep(2)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
