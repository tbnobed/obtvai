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

# Curator XMLs that parsed fine but had no library match yet (media may still
# be ingesting): path -> attempts so far. Retried every XML_RETRY_SECONDS.
XML_RETRY_SECONDS = int(os.getenv("CURATOR_XML_RETRY_SECONDS", "120"))
XML_MAX_RETRIES = int(os.getenv("CURATOR_XML_MAX_RETRIES", "720"))  # ~24h at 120s
xml_retries: dict[str, int] = {}


def _is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS


CURATOR_ROOT = os.getenv("CURATOR_PROXY_ROOT", "/curator").rstrip("/")

# Selective Curator ingest: only clips under admin-selected folders (polled
# from the API) are ingested. CURATOR_DIRECT_INGEST=1 keeps the old
# ingest-everything behavior.
CURATOR_INGEST_ALL = os.getenv("CURATOR_DIRECT_INGEST", "") in ("1", "true", "yes")
CURATOR_SELECTED_REFRESH = int(os.getenv("CURATOR_SELECTED_REFRESH", "45"))
curator_selected: set[str] = set()


def _curator_selected(path: str) -> bool:
    """True when the file lives under an admin-selected Curator folder."""
    rel = path[len(CURATOR_ROOT) + 1:]
    return any(rel == s or rel.startswith(s + "/") for s in curator_selected)


def _refresh_curator_selected() -> None:
    """Poll the selected-folder list; newly selected folders get an immediate
    rescan so their existing clips ingest without waiting for FS events."""
    global curator_selected
    try:
        resp = httpx.get(f"{API_URL}/curator/selected", headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        new = set(resp.json().get("paths", []))
    except Exception as e:
        log.warning(f"Could not refresh Curator selections: {e}")
        return
    added = new - curator_selected
    curator_selected = new
    for rel in added:
        root = os.path.join(CURATOR_ROOT, rel)
        count = 0
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                if p not in pending and _should_ingest(p):
                    pending[p] = {"detected_at": time.time(), "size": _size(p)}
                    count += 1
        log.info(f"Curator folder selected '{rel}': {count} file(s) queued")


def _should_ingest(path: str, dir_files: list[str] | None = None) -> bool:
    """Under the Curator proxy root, only the *_video.mp4 per proxy folder is
    media — audioN.mp4 renditions and thumbnails must not become library
    assets, and (unless CURATOR_DIRECT_INGEST=1) only clips under
    admin-selected folders ingest. Outside /curator, every video ingests
    exactly as before."""
    if _is_curator_xml(path):
        # Dropped Curator asset XMLs (any root, incl. the proxy share): watched
        # so they can be linked to existing library media, not ingested as
        # media. Non-<assets> XMLs are parsed locally and dropped without an
        # API call, so rescans stay cheap.
        return True
    if not _is_video(path):
        return False
    if not path.startswith(CURATOR_ROOT + "/"):
        return True
    if not os.path.basename(path).lower().endswith("_video.mp4"):
        return False
    return CURATOR_INGEST_ALL or _curator_selected(path)


def _size(path: str) -> int | None:
    try:
        return os.path.getsize(path)
    except OSError:
        return None


# Curator's own per-clip metadata sidecars — parsed by the worker for source
# discovery, never asset-link XMLs. Cheap name filter so the initial rescan of
# a large proxy share doesn't parse thousands of them.
_CURATOR_NOISE_XML = ("_index.xml", "_metadata_initial.xml", "_metadata_complete.xml")


def _is_curator_xml(path: str) -> bool:
    if os.path.splitext(path)[1].lower() != ".xml":
        return False
    return not os.path.basename(path).lower().endswith(_CURATOR_NOISE_XML)


def _link_curator_xml(path: str) -> bool:
    """Parse a dropped Curator <assets> XML and post each asset record to the
    API so it can be linked to existing library media. Non-Curator XMLs
    (no <asset.asset_id>) are ignored silently.

    Returns True when the file is done (all records linked, or terminally
    unusable); False when at least one record found no match yet — the XML may
    have arrived before its media finished ingesting, so the caller should
    retry later."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        log.warning(f"Unparseable XML {path}: {e}")
        return True
    if root.tag != "assets":
        return True
    done = True
    for asset in root.findall("asset"):
        def txt(tag: str) -> str:
            el = asset.find(tag)
            return (el.text or "").strip() if el is not None else ""
        asset_id = txt("asset.asset_id")
        if not asset_id:
            continue
        payload = {
            "asset_id": asset_id,
            "name": txt("asset.name") or None,
            "web_proxy_path": txt("WebProxyPath") or None,
            "folder_path": txt("asset.folder_path") or None,
        }
        try:
            resp = httpx.post(
                f"{API_URL}/media/curator-link", json=payload, headers=_HEADERS, timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            matched = data.get("matched_media_ids", [])
            if matched:
                log.info(f"Curator link {asset_id}: matched {len(matched)} media asset(s)")
            elif data.get("ambiguous"):
                log.warning(f"Curator link {asset_id} ({payload['name']}): ambiguous — multiple candidates, not linked")
            else:
                log.warning(f"Curator link {asset_id} ({payload['name']}): no library match yet")
                done = False
        except Exception as e:
            log.error(f"Curator link failed for {asset_id} in {path}: {e}")
            done = False
    return done


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
        if _should_ingest(event.src_path):
            log.info(f"New file detected: {event.src_path}")
            pending[event.src_path] = {"detected_at": time.time(), "size": _size(event.src_path)}

    def on_modified(self, event):
        if event.is_directory:
            return
        if event.src_path not in pending and _should_ingest(event.src_path):
            pending[event.src_path] = {"detected_at": time.time(), "size": _size(event.src_path)}


def _initial_scan():
    """Queue every existing video across all roots. The API dedupes by source
    path, so rescanning on every start is safe — it only picks up files that
    appeared while the watcher was down (or on a newly added mount)."""
    for root in MEDIA_ROOTS:
        count = 0
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                path = os.path.join(dirpath, fn)
                if path not in pending and _should_ingest(path, filenames):
                    pending[path] = {"detected_at": time.time(), "size": _size(path)}
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

    curator_watched = any(os.path.realpath(r) == os.path.realpath(CURATOR_ROOT) for r in MEDIA_ROOTS)
    if curator_watched and not CURATOR_INGEST_ALL:
        _refresh_curator_selected()

    if SCAN_ON_START:
        _initial_scan()

    last_selected_refresh = time.time()
    try:
        while True:
            now = time.time()
            if curator_watched and not CURATOR_INGEST_ALL and now - last_selected_refresh >= CURATOR_SELECTED_REFRESH:
                last_selected_refresh = now
                _refresh_curator_selected()
            to_process = []
            for path, info in list(pending.items()):
                age = now - info["detected_at"]
                if age < STABLE_SECONDS:
                    continue
                # Stability = size unchanged across the STABLE_SECONDS window,
                # compared against the size recorded at detection time — no
                # per-file sleep, so a 100-file startup rescan clears in one
                # pass instead of 5 s x N serially.
                size = _size(path)
                if size is None:
                    del pending[path]
                elif size > 0 and size == info.get("size"):
                    to_process.append(path)
                else:
                    info["size"] = size
                    info["detected_at"] = now

            for path in to_process:
                del pending[path]
                if _is_curator_xml(path):
                    if not _link_curator_xml(path):
                        # XML may have arrived before its media finished
                        # ingesting — retry with backoff until it links or
                        # the retry budget runs out.
                        tries = xml_retries.get(path, 0) + 1
                        if tries <= XML_MAX_RETRIES:
                            xml_retries[path] = tries
                            pending[path] = {
                                "detected_at": now + XML_RETRY_SECONDS - STABLE_SECONDS,
                                "size": _size(path),
                            }
                        else:
                            log.error(f"Giving up on Curator XML after {tries - 1} retries: {path}")
                            xml_retries.pop(path, None)
                    else:
                        xml_retries.pop(path, None)
                elif _should_ingest(path):
                    # Re-checked at ingest time: an admin may have deselected
                    # the folder while the file sat in the stability window.
                    _ingest(path)

            time.sleep(2)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
