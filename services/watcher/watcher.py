"""
File system watcher that monitors a media directory and automatically
triggers ingestion when new video files appear and finish copying.
"""
import os
import time
import logging
import hashlib
import httpx
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("watcher")

# Colon-separated list of roots (MEDIA_ROOTS="/media:/media2").
# Falls back to the single MEDIA_ROOT for backwards compatibility.
# Each root is watched independently (docker-compose sets MEDIA_ROOTS for
# the watcher; the second source is mounted at /media2, not nested).
MEDIA_ROOTS = [
    p for p in os.getenv("MEDIA_ROOTS", os.getenv("MEDIA_ROOT", "/media")).split(":") if p
]
API_URL = os.getenv("API_URL", "http://api:8000/api")
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "")
_HEADERS = {"X-Internal-Token": INTERNAL_API_TOKEN} if INTERNAL_API_TOKEN else {}
STABLE_SECONDS = int(os.getenv("STABLE_SECONDS", "5"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))
SCAN_ON_START = os.getenv("SCAN_ON_START", "1") not in ("0", "false", "no")
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
            headers=_HEADERS,
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


def _initial_scan():
    """Queue every existing video across all roots. The API dedupes by source
    path, so rescanning on every start is safe — it only picks up files that
    appeared while the watcher was down (or on a newly added mount)."""
    for root in MEDIA_ROOTS:
        count = 0
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                path = os.path.join(dirpath, fn)
                if _is_video(path) and path not in pending:
                    pending[path] = {"detected_at": time.time()}
                    count += 1
        log.info(f"Initial scan of {root}: {count} video file(s) queued")


def main():
    # PollingObserver instead of inotify: inotify events never fire for files
    # created remotely on network mounts (SMB/NFS), which is exactly where
    # production footage lives.
    observer = PollingObserver(timeout=POLL_INTERVAL)
    handler = VideoHandler()
    seen_roots = set()
    for root in MEDIA_ROOTS:
        real = os.path.realpath(root)
        if real in seen_roots:
            continue
        seen_roots.add(real)
        os.makedirs(root, exist_ok=True)
        log.info(f"Watching: {root} (poll every {POLL_INTERVAL}s)")
        observer.schedule(handler, root, recursive=True)
    observer.start()

    if SCAN_ON_START:
        _initial_scan()

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
