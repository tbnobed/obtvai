"""Media watcher plus Curator SendToOBTV manifest inbox.

Normal media roots retain their existing video ingest behavior. Curator
editor requests arrive as small XML manifests in one dedicated inbox; each
manifest identifies the exact WebProxy folder, so the huge proxy tree is not
walked or watched during normal operation.
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

# Curator manifests whose exact proxy is not ready yet are retried while the
# XML remains in the inbox. Restart recovery comes from rescanning that inbox.
XML_RETRY_SECONDS = int(os.getenv("CURATOR_XML_RETRY_SECONDS", "120"))
XML_MAX_RETRIES = int(os.getenv("CURATOR_XML_MAX_RETRIES", "720"))  # ~24h at 120s
xml_retries: dict[str, int] = {}


def _is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS


CURATOR_ROOT = os.getenv("CURATOR_PROXY_ROOT", "/curator").rstrip("/")
CURATOR_INBOX_ROOT = os.getenv(
    "CURATOR_INBOX_ROOT", "/curator-inbox"
).rstrip("/")
CURATOR_PROCESSED_DIR = os.getenv(
    "CURATOR_INBOX_PROCESSED_DIR",
    os.path.join(CURATOR_INBOX_ROOT, "processed"),
)
CURATOR_FAILED_DIR = os.getenv(
    "CURATOR_INBOX_FAILED_DIR",
    os.path.join(CURATOR_INBOX_ROOT, "failed"),
)
CURATOR_LEGACY_FOLDER_WATCH = os.getenv(
    "CURATOR_LEGACY_FOLDER_WATCH", ""
).lower() in ("1", "true", "yes")
if CURATOR_LEGACY_FOLDER_WATCH and CURATOR_ROOT not in MEDIA_ROOTS:
    MEDIA_ROOTS.append(CURATOR_ROOT)

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
    if _is_legacy_curator_xml(path):
        return True
    if not _is_video(path):
        return False
    if not path.startswith(CURATOR_ROOT + "/"):
        return True
    if not os.path.basename(path).lower().endswith("_video.mp4"):
        return False
    return (
        CURATOR_LEGACY_FOLDER_WATCH
        and (CURATOR_INGEST_ALL or _curator_selected(path))
    )


def _size(path: str) -> int | None:
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def _is_inbox_manifest(path: str) -> bool:
    """Only top-level XML files in the dedicated inbox are import requests."""
    if os.path.splitext(path)[1].lower() != ".xml":
        return False
    try:
        return (
            os.path.realpath(os.path.dirname(path))
            == os.path.realpath(CURATOR_INBOX_ROOT)
        )
    except OSError:
        return False


_CURATOR_NOISE_XML = (
    "_index.xml",
    "_metadata_initial.xml",
    "_metadata_complete.xml",
)


def _is_legacy_curator_xml(path: str) -> bool:
    """Old proxy-tree XML linking, available only during legacy backfills."""
    if not CURATOR_LEGACY_FOLDER_WATCH:
        return False
    if os.path.splitext(path)[1].lower() != ".xml":
        return False
    if os.path.basename(path).lower().endswith(_CURATOR_NOISE_XML):
        return False
    try:
        return os.path.commonpath((
            os.path.realpath(CURATOR_ROOT),
            os.path.realpath(path),
        )) == os.path.realpath(CURATOR_ROOT)
    except (OSError, ValueError):
        return False


def _parse_curator_manifest(path: str) -> dict:
    """Parse Jack's SendToOBTV <assets> XML into the API batch contract."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise ValueError(f"Unparseable XML: {e}") from e
    if root.tag != "assets":
        raise ValueError(f"Expected <assets> root, got <{root.tag}>")
    records = []
    for asset in root.findall("asset"):
        def txt(tag: str) -> str:
            el = asset.find(tag)
            return (el.text or "").strip() if el is not None else ""
        asset_id = txt("asset.asset_id")
        if not asset_id:
            raise ValueError("Manifest asset is missing asset.asset_id")
        proxy_path = txt("WebProxyPath")
        if not proxy_path:
            raise ValueError(f"Manifest asset {asset_id} is missing WebProxyPath")
        records.append({
            "asset_id": asset_id,
            "name": txt("asset.name") or None,
            "web_proxy_path": proxy_path,
            "folder_path": txt("asset.folder_path") or None,
            "requested_by": txt("user.realname") or None,
        })
    if not records:
        raise ValueError("Manifest contains no <asset> records")
    return {"manifest_name": os.path.basename(path), "assets": records}


def _submit_curator_manifest(path: str) -> tuple[str, str | None]:
    """Return (success|retry|failed, detail)."""
    try:
        payload = _parse_curator_manifest(path)
    except ValueError as e:
        return "failed", str(e)
    try:
        resp = httpx.post(
            f"{API_URL}/media/curator-import",
            json=payload,
            headers=_HEADERS,
            timeout=60,
        )
        if 400 <= resp.status_code < 500 and resp.status_code not in (408, 409, 429):
            return "failed", f"API rejected manifest ({resp.status_code}): {resp.text[:1000]}"
        resp.raise_for_status()
        items = resp.json().get("items", [])
        terminal = [
            f"{i.get('asset_id')}: {i.get('error') or 'failed'}"
            for i in items
            if i.get("status") == "failed" and not i.get("retryable")
        ]
        waiting = [
            f"{i.get('asset_id')}: {i.get('error') or i.get('status')}"
            for i in items
            if i.get("retryable") or i.get("status") == "waiting"
        ]
        if waiting:
            # Keep the XML until every retryable sibling is resolved. Terminal
            # siblings remain recorded and move the final manifest to failed/
            # only after the waiting assets have imported.
            detail = waiting + [f"terminal: {e}" for e in terminal]
            return "retry", "; ".join(detail)
        if terminal:
            return "failed", "; ".join(terminal)
        if not items:
            return "failed", "API returned no manifest item results"
        log.info(
            "Curator manifest accepted: %s",
            ", ".join(f"{i.get('asset_id')}={i.get('status')}" for i in items),
        )
        return "success", None
    except Exception as e:
        return "retry", str(e)


def _submit_legacy_curator_xml(path: str) -> tuple[str, str | None]:
    """Preserve the old link-only XML behavior for explicit backfills."""
    try:
        payload = _parse_curator_manifest(path)
    except ValueError as e:
        # Curator's proxy tree contains many unrelated XML sidecars. The old
        # watcher ignored those terminally rather than treating them as errors.
        log.debug("Ignoring non-manifest legacy XML %s: %s", path, e)
        return "success", None
    for record in payload["assets"]:
        try:
            resp = httpx.post(
                f"{API_URL}/media/curator-link",
                json=record,
                headers=_HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("matched_media_ids") or data.get("ambiguous"):
                return "retry", (
                    f"{record['asset_id']} has no unambiguous library match yet"
                )
        except Exception as e:
            return "retry", str(e)
    return "success", None


def _archive_manifest(path: str, target_dir: str, error: str | None = None) -> None:
    """Atomically move a completed manifest and optionally write diagnostics."""
    os.makedirs(target_dir, exist_ok=True)
    base = os.path.basename(path)
    destination = os.path.join(target_dir, base)
    if os.path.exists(destination):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        digest = hashlib.sha1(path.encode("utf-8")).hexdigest()[:8]
        stem, ext = os.path.splitext(base)
        destination = os.path.join(
            target_dir, f"{stem}-{stamp}-{digest}{ext}"
        )
    os.replace(path, destination)
    if error:
        try:
            with open(destination + ".error.txt", "w", encoding="utf-8") as f:
                f.write(error[:10000] + "\n")
        except OSError as e:
            log.error("Could not write manifest failure detail: %s", e)


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
    @staticmethod
    def _queue(path: str) -> None:
        if _is_inbox_manifest(path) or _should_ingest(path):
            log.info(f"New file detected: {path}")
            pending[path] = {"detected_at": time.time(), "size": _size(path)}

    def on_created(self, event):
        if event.is_directory:
            return
        self._queue(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        if (
            event.src_path not in pending
            and (_is_inbox_manifest(event.src_path) or _should_ingest(event.src_path))
        ):
            self._queue(event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            return
        # Curator may write a temporary file and atomically rename it to XML.
        self._queue(event.dest_path)


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
    count = 0
    try:
        entries = os.scandir(CURATOR_INBOX_ROOT)
    except OSError as e:
        log.error(f"Could not scan Curator inbox {CURATOR_INBOX_ROOT}: {e}")
        return
    with entries:
        for entry in entries:
            if not entry.is_file(follow_symlinks=False):
                continue
            if _is_inbox_manifest(entry.path) and entry.path not in pending:
                pending[entry.path] = {
                    "detected_at": time.time(),
                    "size": _size(entry.path),
                }
                count += 1
    log.info(f"Initial scan of Curator inbox: {count} manifest(s) queued")


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
    os.makedirs(CURATOR_INBOX_ROOT, exist_ok=True)
    os.makedirs(CURATOR_PROCESSED_DIR, exist_ok=True)
    os.makedirs(CURATOR_FAILED_DIR, exist_ok=True)
    inbox_real = os.path.realpath(CURATOR_INBOX_ROOT)
    if inbox_real not in seen_roots:
        seen_roots.add(inbox_real)
        log.info(
            f"Watching Curator manifest inbox: {CURATOR_INBOX_ROOT} "
            f"(poll every {POLL_INTERVAL}s)"
        )
        # Jack's plug-in writes manifests at the inbox root. Do not recurse
        # into processed/failed archives.
        observer.schedule(handler, CURATOR_INBOX_ROOT, recursive=False)
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
                if _is_inbox_manifest(path):
                    outcome, detail = _submit_curator_manifest(path)
                    if outcome == "retry":
                        # The XML itself is the durable queue record. Keep it
                        # in the inbox until the proxy/API becomes available.
                        tries = xml_retries.get(path, 0) + 1
                        if tries <= XML_MAX_RETRIES:
                            xml_retries[path] = tries
                            log.warning(
                                "Curator manifest retry %s/%s for %s: %s",
                                tries, XML_MAX_RETRIES, path, detail,
                            )
                            pending[path] = {
                                "detected_at": now + XML_RETRY_SECONDS - STABLE_SECONDS,
                                "size": _size(path),
                            }
                        else:
                            error = (
                                f"Retry budget exhausted after {tries - 1} attempts. "
                                f"Last error: {detail or 'unknown'}"
                            )
                            log.error(f"Giving up on Curator manifest: {path}: {error}")
                            try:
                                _archive_manifest(path, CURATOR_FAILED_DIR, error)
                            except OSError as e:
                                log.error(f"Could not archive failed manifest {path}: {e}")
                            xml_retries.pop(path, None)
                    elif outcome == "failed":
                        log.error(f"Invalid Curator manifest {path}: {detail}")
                        try:
                            _archive_manifest(
                                path, CURATOR_FAILED_DIR, detail or "Invalid manifest"
                            )
                        except OSError as e:
                            log.error(f"Could not archive failed manifest {path}: {e}")
                        xml_retries.pop(path, None)
                    else:
                        try:
                            _archive_manifest(path, CURATOR_PROCESSED_DIR)
                            log.info(f"Curator manifest processed: {path}")
                            xml_retries.pop(path, None)
                        except OSError as e:
                            # Import is idempotent; retaining/retrying the XML
                            # is safer than losing the audit manifest.
                            log.error(f"Could not archive processed manifest {path}: {e}")
                            pending[path] = {
                                "detected_at": now + XML_RETRY_SECONDS - STABLE_SECONDS,
                                "size": _size(path),
                            }
                elif _is_legacy_curator_xml(path):
                    outcome, detail = _submit_legacy_curator_xml(path)
                    if outcome == "retry":
                        tries = xml_retries.get(path, 0) + 1
                        if tries <= XML_MAX_RETRIES:
                            xml_retries[path] = tries
                            pending[path] = {
                                "detected_at": now + XML_RETRY_SECONDS - STABLE_SECONDS,
                                "size": _size(path),
                            }
                            log.warning(
                                "Legacy Curator XML retry %s/%s for %s: %s",
                                tries, XML_MAX_RETRIES, path, detail,
                            )
                        else:
                            log.error(
                                "Giving up on legacy Curator XML after %s retries: %s",
                                tries - 1, path,
                            )
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
