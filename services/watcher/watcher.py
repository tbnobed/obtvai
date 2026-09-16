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
INBOX_RECONCILE_SECONDS = max(
    1, int(os.getenv("CURATOR_INBOX_RECONCILE_SECONDS", str(POLL_INTERVAL)))
)
ROOT_RETRY_SECONDS = max(
    1, int(os.getenv("WATCHER_ROOT_RETRY_SECONDS", str(POLL_INTERVAL)))
)
HEALTH_PATH = os.getenv(
    "WATCHER_HEALTH_FILE",
    os.getenv("WATCHER_HEALTH_PATH", "/tmp/watcher-health.json"),
)

pending: dict[str, dict] = {}

# Curator manifests whose exact proxy is not ready yet are retried while the
# XML remains in the inbox. Restart recovery comes from rescanning that inbox.
XML_RETRY_SECONDS = int(os.getenv("CURATOR_XML_RETRY_SECONDS", "120"))
XML_MAX_RETRIES = int(os.getenv("CURATOR_XML_MAX_RETRIES", "720"))  # ~24h at 120s
xml_retries: dict[str, int] = {}

# These are deliberately process-local.  The XML file is the durable queue;
# these records only prevent a watchdog event or a reconciliation pass from
# resetting a stability/retry deadline while an item is already pending.
_watch_states: dict[str, dict] = {}
_last_inbox_scan_at: float | None = None
_last_inbox_scan_ok = False


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
                if _should_ingest(p) and _queue_pending(p):
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


def _size_state(path: str) -> tuple[int | None, bool]:
    """Return (size, readable).

    ``None`` from ``_size`` historically meant either a missing file or a
    transient SMB read error.  The watcher must distinguish those cases:
    missing files can leave the queue, while an access/read error must remain
    queued for a later attempt.
    """
    try:
        return os.path.getsize(path), True
    except FileNotFoundError:
        return None, True
    except OSError as e:
        log.warning("Could not read size for %s; will retry: %s", path, e)
        return None, False


def _queue_pending(path: str, detected_at: float | None = None) -> bool:
    """Queue a path without changing an existing item's deadline.

    Watchdog can emit several created/modified/moved events for one file, and
    the periodic inbox reconciliation intentionally observes the same files.
    Treating either as a new queue item would reset stability and, for XML,
    could reset the retry budget.  A path already present in ``pending`` is
    therefore authoritative until its current attempt completes.
    """
    if path in pending:
        return False
    now = time.time() if detected_at is None else detected_at
    candidate = {
        "path": path,
        "detected_at": now,
        "next_attempt_at": now + STABLE_SECONDS,
        "size": _size(path),
    }
    # Stat'ing an SMB path can yield to the watchdog thread.  Never overwrite
    # an item that arrived between the fast check and this assignment.
    return pending.setdefault(path, candidate) is candidate


def _defer_pending(
    info: dict, now: float, delay: float, *, refresh_size: bool = True
) -> None:
    """Move an existing queue item to a future deadline without replacing it."""
    info["detected_at"] = now + delay - STABLE_SECONDS
    info["next_attempt_at"] = now + delay
    if refresh_size and info.get("path"):
        size = _size(info["path"])
        if size is not None:
            info["size"] = size
    info["processing"] = False


def _reconcile_curator_inbox(now: float | None = None) -> bool:
    """Reconcile only top-level XML files in the manifest inbox.

    This is deliberately not an ``os.walk`` and never touches media roots.
    A failed directory/entry read is reported as an unsuccessful scan, so the
    next pass retries it and health does not incorrectly become green.
    """
    global _last_inbox_scan_at, _last_inbox_scan_ok
    scan_time = time.time() if now is None else now
    count = 0
    try:
        with os.scandir(CURATOR_INBOX_ROOT) as entries:
            for entry in entries:
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    path = entry.path
                    if _is_inbox_manifest(path):
                        if _queue_pending(path, detected_at=scan_time):
                            count += 1
                except OSError as e:
                    raise OSError(f"reading inbox entry {entry.path}: {e}") from e
    except OSError as e:
        _last_inbox_scan_ok = False
        log.error("Could not reconcile Curator inbox %s: %s", CURATOR_INBOX_ROOT, e)
        return False
    _last_inbox_scan_at = scan_time
    _last_inbox_scan_ok = True
    log.info("Reconciled Curator inbox: %s manifest(s) queued", count)
    return True


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
    except OSError as e:
        # A manifest may be visible before its contents are readable on SMB.
        # Keep it in the durable inbox queue rather than killing the watcher.
        return "retry", f"Could not read manifest: {e}"
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
    except OSError as e:
        return "retry", f"Could not read legacy XML: {e}"
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
            if _queue_pending(path):
                log.info(f"New file detected: {path}")

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
        try:
            for dirpath, _dirnames, filenames in os.walk(root):
                for fn in filenames:
                    path = os.path.join(dirpath, fn)
                    if _should_ingest(path, filenames) and _queue_pending(path):
                        count += 1
        except OSError as e:
            # The polling emitter is responsible for recovering this mount;
            # startup scanning must not prevent other roots from starting.
            log.error("Could not scan media root %s: %s", root, e)
        log.info(f"Initial scan of {root}: {count} video file(s) queued")
    _reconcile_curator_inbox()


def _find_emitter(observer, watch):
    """Find the emitter belonging to an ObservedWatch.

    ``emitters`` is a public watchdog property, while a few lightweight test
    observers only expose the backing ``_emitters`` set.  Supporting both also
    keeps recovery independent of watchdog's internal container type.
    """
    emitters = getattr(observer, "emitters", None)
    if emitters is None:
        emitters = getattr(observer, "_emitters", ())
    if isinstance(emitters, dict):
        emitters = emitters.values()
    for emitter in emitters:
        emitter_watch = getattr(emitter, "watch", None)
        if emitter_watch is watch or emitter_watch == watch:
            return emitter
        if (
            emitter_watch is not None
            and watch is not None
            and getattr(emitter_watch, "path", None) == getattr(watch, "path", None)
        ):
            return emitter
    return None


def _emitter_live(observer, state: dict) -> bool:
    watch = state.get("watch")
    if watch is None:
        return False
    emitter = _find_emitter(observer, watch)
    if emitter is None:
        return False
    try:
        return bool(emitter.is_alive())
    except Exception:
        return False


def _dispatcher_live(observer) -> bool:
    """Return whether the watchdog dispatcher thread is running."""
    if observer is None:
        return False
    is_alive = getattr(observer, "is_alive", None)
    if callable(is_alive):
        try:
            return bool(is_alive())
        except Exception:
            return False
    dispatcher_thread = getattr(observer, "_thread", None)
    thread_alive = getattr(dispatcher_thread, "is_alive", None)
    if callable(thread_alive):
        try:
            return bool(thread_alive())
        except Exception:
            return False
    return False


def _write_health(observer=None, now: float | None = None) -> dict:
    """Publish the local watcher heartbeat and return the written snapshot.

    The required contract is intentionally small: ``updated_at`` is an epoch
    number and ``healthy`` is true only when every configured watch has a live
    emitter and a successful inbox scan is recent.  Additional diagnostics are
    useful when a particular SMB mount is unhealthy but do not change the
    contract consumed by the health checker.
    """
    current = time.time() if now is None else now
    root_details = {}
    for key, state in _watch_states.items():
        live = _emitter_live(observer, state) if observer is not None else bool(
            state.get("healthy", False)
        )
        root_details[key] = {
            "path": state.get("path", key),
            "healthy": live,
            "error": state.get("error"),
        }

    # A scan is considered stale before the external heartbeat's 180-second
    # freshness limit.  This prevents a permanently failing inbox from
    # looking healthy merely because the heartbeat writer itself is alive.
    scan_max_age = min(
        180,
        max(60, INBOX_RECONCILE_SECONDS * 2, POLL_INTERVAL * 2),
    )
    scan_recent = bool(
        _last_inbox_scan_ok
        and _last_inbox_scan_at is not None
        and current - _last_inbox_scan_at <= scan_max_age
    )
    dispatcher_live = _dispatcher_live(observer)
    healthy = dispatcher_live and bool(root_details) and all(
        detail["healthy"] for detail in root_details.values()
    ) and scan_recent
    snapshot = {
        "updated_at": current,
        "healthy": healthy,
        "dispatcher": {"healthy": dispatcher_live},
        "roots": root_details,
        "inbox_scan": {
            "healthy": scan_recent,
            "updated_at": _last_inbox_scan_at,
        },
    }
    try:
        directory = os.path.dirname(HEALTH_PATH)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temporary = HEALTH_PATH + ".tmp"
        with open(temporary, "w", encoding="utf-8") as f:
            import json
            json.dump(snapshot, f, separators=(",", ":"))
        os.replace(temporary, HEALTH_PATH)
    except OSError as e:
        # Failure to write diagnostics must not stop ingest.  The previous
        # heartbeat remains visible to the external health checker.
        log.error("Could not write watcher health file %s: %s", HEALTH_PATH, e)
    return snapshot


def _schedule_watch(observer, handler, state: dict, now: float | None = None) -> bool:
    """Schedule one root, retaining a retryable state on startup failure."""
    current = time.time() if now is None else now
    if state.get("watch") is not None:
        return True
    if current < state.get("next_retry_at", 0):
        return False
    try:
        state["watch"] = observer.schedule(
            handler,
            state["path"],
            recursive=state["recursive"],
        )
    except Exception as e:
        state["watch"] = None
        state["error"] = str(e)
        state["next_retry_at"] = current + ROOT_RETRY_SECONDS
        log.error("Could not watch %s; retrying: %s", state["path"], e)
        return False
    state["error"] = None
    state["next_retry_at"] = 0
    return True


def _recover_dead_emitters(
    observer, handler, states: dict[str, dict] | None = None, now: float | None = None
) -> None:
    """Restart only dead polling emitters; never rescan media roots.

    A PollingObserver can remain alive after an individual PollingEmitter
    exits (notably after an SMB ``OSError``).  Unscheduling and scheduling just
    that watch recreates its emitter and lets watchdog discover missed events.
    """
    current = time.time() if now is None else now
    states = _watch_states if states is None else states
    # A dead dispatcher cannot create a working emitter.  Keep all states
    # unhealthy and let the process supervisor deal with a dispatcher failure
    # rather than repeatedly scheduling watches on a stopped thread.
    if not _dispatcher_live(observer):
        return
    for state in states.values():
        watch = state.get("watch")
        if watch is not None and _emitter_live(observer, state):
            continue
        if watch is not None:
            try:
                observer.unschedule(watch)
            except Exception as e:
                log.warning("Could not unschedule dead watch %s: %s", state["path"], e)
            state["watch"] = None
            state["next_retry_at"] = current
        _schedule_watch(observer, handler, state, current)


def _archive_pending(path: str, info: dict, target_dir: str, error: str | None,
                     now: float) -> None:
    """Archive an already-submitted XML, retrying archive only on failure."""
    info["archive_pending"] = True
    info["archive_target"] = target_dir
    info["archive_error"] = error
    info["processing"] = True
    try:
        _archive_manifest(path, target_dir, error)
    except OSError as e:
        # Keep the submitted marker in pending.  Future events/reconciliation
        # therefore retry this move, never the API submission.
        log.error("Could not archive manifest %s: %s", path, e)
        _defer_pending(info, now, XML_RETRY_SECONDS)
        pending[path] = info
        return
    if info.pop("clear_retry_budget", False):
        xml_retries.pop(path, None)
    pending.pop(path, None)


def _process_pending(now: float | None = None) -> None:
    """Process one due pass of the in-memory queue."""
    current = time.time() if now is None else now
    for path, info in list(pending.items()):
        if pending.get(path) is not info or info.get("processing"):
            continue
        info.setdefault("path", path)
        due_at = info.get(
            "next_attempt_at",
            info.get("detected_at", current) + STABLE_SECONDS,
        )
        if current < due_at:
            continue

        # An archive failure is a completed API submission.  It has a
        # separate state so archive retries cannot submit the same XML again.
        if info.get("archive_pending"):
            _archive_pending(
                path,
                info,
                info["archive_target"],
                info.get("archive_error"),
                current,
            )
            continue

        size, readable = _size_state(path)
        if not readable:
            # Do not carry a pre-failure baseline across an unreadable SMB
            # window.  Recovery must establish a fresh size and then wait the
            # complete stability interval before submission.
            info["size"] = None
            _defer_pending(
                info,
                current,
                STABLE_SECONDS,
                refresh_size=False,
            )
            continue
        if size is None:
            pending.pop(path, None)
            continue
        expected_size = info.get("size")
        if expected_size is None:
            # The initial stat may have raced an SMB write/readability window.
            # A first successful size is only a baseline; it must still
            # remain unchanged for the full stability interval.
            info["size"] = size
            info["detected_at"] = current
            info["next_attempt_at"] = current + STABLE_SECONDS
            continue
        if size <= 0 or size != expected_size:
            info["size"] = size
            info["detected_at"] = current
            info["next_attempt_at"] = current + STABLE_SECONDS
            continue

        info["processing"] = True
        if _is_inbox_manifest(path):
            outcome, detail = _submit_curator_manifest(path)
            if outcome == "retry":
                tries = xml_retries.get(path, 0) + 1
                if tries <= XML_MAX_RETRIES:
                    xml_retries[path] = tries
                    log.warning(
                        "Curator manifest retry %s/%s for %s: %s",
                        tries, XML_MAX_RETRIES, path, detail,
                    )
                    _defer_pending(info, current, XML_RETRY_SECONDS)
                    pending[path] = info
                else:
                    error = (
                        f"Retry budget exhausted after {tries - 1} attempts. "
                        f"Last error: {detail or 'unknown'}"
                    )
                    log.error("Giving up on Curator manifest: %s: %s", path, error)
                    info["clear_retry_budget"] = True
                    _archive_pending(path, info, CURATOR_FAILED_DIR, error, current)
            elif outcome == "failed":
                log.error("Invalid Curator manifest %s: %s", path, detail)
                info["clear_retry_budget"] = True
                _archive_pending(
                    path, info, CURATOR_FAILED_DIR, detail or "Invalid manifest", current
                )
            else:
                log.info("Curator manifest processed: %s", path)
                info["clear_retry_budget"] = True
                _archive_pending(path, info, CURATOR_PROCESSED_DIR, None, current)
        elif _is_legacy_curator_xml(path):
            outcome, detail = _submit_legacy_curator_xml(path)
            if outcome == "retry":
                tries = xml_retries.get(path, 0) + 1
                if tries <= XML_MAX_RETRIES:
                    xml_retries[path] = tries
                    _defer_pending(info, current, XML_RETRY_SECONDS)
                    pending[path] = info
                    log.warning(
                        "Legacy Curator XML retry %s/%s for %s: %s",
                        tries, XML_MAX_RETRIES, path, detail,
                    )
                else:
                    log.error(
                        "Giving up on legacy Curator XML after %s retries: %s",
                        tries - 1,
                        path,
                    )
                    xml_retries.pop(path, None)
                    pending.pop(path, None)
            else:
                xml_retries.pop(path, None)
                pending.pop(path, None)
        elif _should_ingest(path):
            # Re-check selection at ingest time, as before.
            _ingest(path)
            pending.pop(path, None)
        else:
            pending.pop(path, None)


def main():
    # PollingObserver instead of inotify: inotify events never fire for files
    # created remotely on network mounts (SMB/NFS), which is exactly where
    # production footage lives.
    global _watch_states, _last_inbox_scan_at, _last_inbox_scan_ok
    _watch_states = {}
    _last_inbox_scan_at = None
    _last_inbox_scan_ok = False
    observer = PollingObserver(timeout=POLL_INTERVAL)
    handler = VideoHandler()
    # Start the dispatcher with no watches.  PollingEmitter snapshots happen
    # when a watch is started; scheduling before this point lets one SMB
    # snapshot OSError abort observer.start() for every otherwise healthy
    # root.
    try:
        observer.start()
    except Exception as e:
        log.error("Could not start watcher observer: %s", e)

    seen_roots = set()
    for root in MEDIA_ROOTS:
        try:
            real = os.path.realpath(root)
        except OSError as e:
            # Keep the failed root in diagnostics so health is red and the
            # watcher can retry it without preventing other roots from start.
            real = root
            log.error("Could not resolve media root %s: %s", root, e)
        if real in seen_roots:
            continue
        seen_roots.add(real)
        state = {
            "path": root,
            "recursive": True,
            "watch": None,
            "next_retry_at": 0,
            "error": None,
        }
        _watch_states[root] = state
        try:
            os.makedirs(root, exist_ok=True)
            log.info(f"Watching: {root} (poll every {POLL_INTERVAL}s)")
        except Exception as e:
            # os.makedirs can fail before schedule (for example while an SMB
            # share is offline).  Leave this state retryable.
            state["error"] = str(e)
            state["next_retry_at"] = time.time() + ROOT_RETRY_SECONDS
            log.error("Could not initialize media root %s: %s", root, e)
        if _dispatcher_live(observer):
            _schedule_watch(observer, handler, state)
    try:
        os.makedirs(CURATOR_INBOX_ROOT, exist_ok=True)
        os.makedirs(CURATOR_PROCESSED_DIR, exist_ok=True)
        os.makedirs(CURATOR_FAILED_DIR, exist_ok=True)
    except OSError as e:
        log.error("Could not initialize Curator inbox directories: %s", e)
    try:
        inbox_real = os.path.realpath(CURATOR_INBOX_ROOT)
    except OSError:
        inbox_real = CURATOR_INBOX_ROOT
    if inbox_real not in seen_roots:
        seen_roots.add(inbox_real)
        log.info(
            f"Watching Curator manifest inbox: {CURATOR_INBOX_ROOT} "
            f"(poll every {POLL_INTERVAL}s)"
        )
        # Jack's plug-in writes manifests at the inbox root. Do not recurse
        # into processed/failed archives.
        inbox_state = {
            "path": CURATOR_INBOX_ROOT,
            "recursive": False,
            "watch": None,
            "next_retry_at": 0,
            "error": None,
        }
        _watch_states[CURATOR_INBOX_ROOT] = inbox_state
        if _dispatcher_live(observer):
            _schedule_watch(observer, handler, inbox_state)

    try:
        curator_watched = any(
            os.path.realpath(r) == os.path.realpath(CURATOR_ROOT)
            for r in MEDIA_ROOTS
        )
    except OSError:
        curator_watched = False
    if curator_watched and not CURATOR_INGEST_ALL:
        _refresh_curator_selected()

    if SCAN_ON_START:
        _initial_scan()
    else:
        # Inbox recovery is independent of the optional (and potentially
        # expensive) media-root startup scan.
        _reconcile_curator_inbox()

    last_selected_refresh = time.time()
    last_inbox_reconcile = time.time()
    try:
        while True:
            now = time.time()
            _recover_dead_emitters(observer, handler, _watch_states, now)
            if curator_watched and not CURATOR_INGEST_ALL and now - last_selected_refresh >= CURATOR_SELECTED_REFRESH:
                last_selected_refresh = now
                _refresh_curator_selected()
            if now - last_inbox_reconcile >= INBOX_RECONCILE_SECONDS:
                last_inbox_reconcile = now
                _reconcile_curator_inbox(now)
            _process_pending(now)
            _write_health(observer, now)
            time.sleep(2)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
