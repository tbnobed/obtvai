"""Dependency-light regression tests for watcher recovery state.

The production image supplies watchdog/httpx.  These tests intentionally use
small local stand-ins when those packages are unavailable, so queue and
recovery behavior can be checked without a running API, SMB share, or Docker.
"""
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
import time
from pathlib import Path
from unittest import mock


try:
    from watchdog.observers.polling import PollingObserver as RealPollingObserver
except ModuleNotFoundError:
    RealPollingObserver = None


def _load_watcher():
    if "httpx" not in sys.modules:
        httpx = types.ModuleType("httpx")
        httpx.get = lambda *args, **kwargs: None
        httpx.post = lambda *args, **kwargs: None
        sys.modules["httpx"] = httpx
    try:
        import watchdog  # noqa: F401
    except ModuleNotFoundError:
        watchdog = types.ModuleType("watchdog")
        events = types.ModuleType("watchdog.events")
        polling = types.ModuleType("watchdog.observers.polling")
        observers = types.ModuleType("watchdog.observers")

        class FileSystemEventHandler:
            pass

        class PollingObserver:
            def __init__(self, *args, **kwargs):
                pass

        events.FileSystemEventHandler = FileSystemEventHandler
        polling.PollingObserver = PollingObserver
        polling.PollingObserverVFS = PollingObserver
        observers.polling = polling
        watchdog.events = events
        watchdog.observers = observers
        sys.modules.update({
            "watchdog": watchdog,
            "watchdog.events": events,
            "watchdog.observers": observers,
            "watchdog.observers.polling": polling,
        })

    path = Path(__file__).parents[1] / "watcher.py"
    spec = importlib.util.spec_from_file_location("watcher_recovery_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


w = _load_watcher()


class _Event:
    is_directory = False

    def __init__(self, path):
        self.src_path = path
        self.dest_path = path


class _Watch:
    def __init__(self, path):
        self.path = path


class _Emitter:
    def __init__(self, watch, alive=True):
        self.watch = watch
        self.alive = alive

    def is_alive(self):
        return self.alive


class _Observer:
    def __init__(self):
        self.emitters = []
        self.scheduled = []
        self.unscheduled = []
        self.started = False

    def schedule(self, handler, path, recursive):
        watch = _Watch(path)
        self.scheduled.append((handler, path, recursive))
        self.emitters.append(_Emitter(watch))
        return watch

    def unschedule(self, watch):
        self.unscheduled.append(watch)
        self.emitters = [e for e in self.emitters if e.watch is not watch]

    def start(self):
        self.started = True

    def is_alive(self):
        return self.started

    def stop(self):
        self.started = False

    def join(self):
        return None


def _wait_for_emitter(observer, state):
    for _ in range(60):
        emitter = w._find_emitter(observer, state["watch"])
        if emitter is not None and emitter.is_alive():
            return True
        time.sleep(0.05)
    return False


class WatcherRecoveryTests(unittest.TestCase):
    def setUp(self):
        w.pending.clear()
        w.xml_retries.clear()
        w._watch_states.clear()
        w._last_inbox_scan_at = None
        w._last_inbox_scan_ok = False
        self.old_values = {
            "STABLE_SECONDS": w.STABLE_SECONDS,
            "XML_RETRY_SECONDS": w.XML_RETRY_SECONDS,
            "XML_MAX_RETRIES": w.XML_MAX_RETRIES,
        }

    def tearDown(self):
        for name, value in self.old_values.items():
            setattr(w, name, value)
        w.pending.clear()
        w.xml_retries.clear()
        w._watch_states.clear()

    def _inbox(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        w.CURATOR_INBOX_ROOT = directory.name
        w.CURATOR_PROCESSED_DIR = os.path.join(directory.name, "processed")
        w.CURATOR_FAILED_DIR = os.path.join(directory.name, "failed")
        return directory.name

    def test_dead_emitter_is_restarted_without_media_rescan(self):
        observer = _Observer()
        handler = object()
        observer.start()
        watch = observer.schedule(handler, "/smb/media", recursive=True)
        observer.emitters[0].alive = False
        states = {
            "/smb/media": {
                "path": "/smb/media",
                "recursive": True,
                "watch": watch,
                "next_retry_at": 0,
                "error": None,
            }
        }
        with mock.patch.object(w, "os", wraps=os) as os_mock:
            w._recover_dead_emitters(observer, handler, states, now=10)
            self.assertEqual(len(observer.unscheduled), 1)
            self.assertEqual(len(observer.scheduled), 2)
            os_mock.walk.assert_not_called()

    def test_root_schedule_failure_is_recorded_without_stopping_dispatcher(self):
        class FailingObserver(_Observer):
            def schedule(self, handler, path, recursive):
                raise OSError("SMB root unavailable")

        observer = FailingObserver()
        observer.start()
        state = {
            "path": "/smb/unavailable",
            "recursive": True,
            "watch": None,
            "next_retry_at": 0,
            "error": None,
        }
        self.assertFalse(w._schedule_watch(observer, object(), state, now=10))
        self.assertIn("SMB root unavailable", state["error"])
        self.assertTrue(observer.is_alive())

    def test_reconciliation_finds_missed_xml_and_is_top_level_only(self):
        inbox = self._inbox()
        manifest = os.path.join(inbox, "missed.xml")
        Path(manifest).write_text("<assets><asset /></assets>", encoding="utf-8")
        with mock.patch.object(w.os, "walk", side_effect=AssertionError("media walk")):
            self.assertTrue(w._reconcile_curator_inbox(now=100))
        self.assertIn(manifest, w.pending)
        self.assertEqual(w.pending[manifest]["detected_at"], 100)
        self.assertTrue(w._last_inbox_scan_ok)

    def test_queue_stat_race_does_not_overwrite_existing_item(self):
        inbox = self._inbox()
        manifest = os.path.join(inbox, "race.xml")
        existing = {"path": manifest, "detected_at": 7, "size": 12}

        def stat_then_event(_path):
            w.pending[manifest] = existing
            return 12

        with mock.patch.object(w, "_size", side_effect=stat_then_event):
            self.assertFalse(w._queue_pending(manifest, detected_at=1))
        self.assertIs(w.pending[manifest], existing)

    def test_event_and_reconciliation_preserve_retry_deadline(self):
        inbox = self._inbox()
        manifest = os.path.join(inbox, "retry.xml")
        Path(manifest).write_text("<assets><asset /></assets>", encoding="utf-8")
        w.STABLE_SECONDS = 1
        w.XML_RETRY_SECONDS = 20
        with mock.patch.object(w, "_submit_curator_manifest", return_value=("retry", "SMB")):
            w._queue_pending(manifest, detected_at=0)
            w._process_pending(now=1)
        deadline = w.pending[manifest]["next_attempt_at"]
        w.VideoHandler().on_created(_Event(manifest))
        w._reconcile_curator_inbox(now=5)
        self.assertEqual(w.pending[manifest]["next_attempt_at"], deadline)
        self.assertEqual(w.xml_retries[manifest], 1)
        with mock.patch.object(w, "_submit_curator_manifest", return_value=("retry", "SMB")) as submit:
            w._process_pending(now=deadline - 1)
            submit.assert_not_called()

    def test_archive_retry_does_not_resubmit_manifest(self):
        inbox = self._inbox()
        manifest = os.path.join(inbox, "archive.xml")
        Path(manifest).write_text("<assets><asset /></assets>", encoding="utf-8")
        w.STABLE_SECONDS = 1
        w.XML_RETRY_SECONDS = 20
        archive = mock.Mock(side_effect=[OSError("share unavailable"), None])
        with mock.patch.object(
            w, "_submit_curator_manifest", return_value=("success", None)
        ) as submit, mock.patch.object(w, "_archive_manifest", archive):
            w._queue_pending(manifest, detected_at=0)
            w._process_pending(now=1)
            self.assertTrue(w.pending[manifest]["archive_pending"])
            w.VideoHandler().on_modified(_Event(manifest))
            w._reconcile_curator_inbox(now=2)
            w._process_pending(now=21)
        self.assertEqual(submit.call_count, 1)
        self.assertNotIn(manifest, w.pending)
        self.assertEqual(archive.call_count, 2)

    def test_manifest_read_oserror_is_retryable(self):
        with mock.patch.object(
            w, "_parse_curator_manifest", side_effect=OSError("SMB read")
        ):
            self.assertEqual(
                w._submit_curator_manifest("/inbox/read-error.xml"),
                ("retry", "Could not read manifest: SMB read"),
            )

    def test_smb_size_failure_stays_queued_for_later_read(self):
        inbox = self._inbox()
        manifest = os.path.join(inbox, "size-error.xml")
        Path(manifest).write_text("<assets><asset /></assets>", encoding="utf-8")
        w.STABLE_SECONDS = 1
        w._queue_pending(manifest, detected_at=0)
        with mock.patch.object(
            w.os.path, "getsize", side_effect=PermissionError("SMB unavailable")
        ), mock.patch.object(
            w, "_submit_curator_manifest"
        ) as submit:
            w._process_pending(now=1)
            submit.assert_not_called()
        self.assertIn(manifest, w.pending)
        self.assertIsNone(w.pending[manifest]["size"])
        with mock.patch.object(
            w, "_submit_curator_manifest", return_value=("success", None)
        ) as submit, mock.patch.object(w, "_archive_manifest"):
            w._process_pending(now=2)
            submit.assert_not_called()
            self.assertEqual(w.pending[manifest]["next_attempt_at"], 3)
            w._process_pending(now=3)
            submit.assert_called_once()

    def test_first_readable_size_establishes_stability_baseline(self):
        inbox = self._inbox()
        manifest = os.path.join(inbox, "late-readable.xml")
        Path(manifest).write_text("<assets><asset /></assets>", encoding="utf-8")
        w.STABLE_SECONDS = 5
        w.pending[manifest] = {
            "path": manifest,
            "detected_at": 0,
            "next_attempt_at": 5,
            "size": None,
        }
        with mock.patch.object(
            w, "_submit_curator_manifest"
        ) as submit:
            w._process_pending(now=5)
            submit.assert_not_called()
        self.assertEqual(w.pending[manifest]["size"], os.path.getsize(manifest))
        self.assertEqual(w.pending[manifest]["next_attempt_at"], 10)

    def test_health_contains_epoch_boolean_and_per_root_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            health_path = os.path.join(directory, "watcher-health.json")
            w.HEALTH_PATH = health_path
            observer = _Observer()
            observer.start()
            watch = observer.schedule(object(), "/media", recursive=True)
            w._watch_states["/media"] = {
                "path": "/media",
                "watch": watch,
                "recursive": True,
                "error": None,
            }
            w._last_inbox_scan_at = 100
            w._last_inbox_scan_ok = True
            snapshot = w._write_health(observer, now=101)
            self.assertIsInstance(snapshot["updated_at"], (int, float))
            self.assertIs(snapshot["healthy"], True)
            self.assertEqual(json.loads(Path(health_path).read_text())["healthy"], True)

    def test_health_is_unhealthy_when_dispatcher_or_scan_is_degraded(self):
        with tempfile.TemporaryDirectory() as directory:
            w.HEALTH_PATH = os.path.join(directory, "watcher-health.json")
            observer = _Observer()
            observer.start()
            watch = observer.schedule(object(), "/media", recursive=True)
            w._watch_states["/media"] = {
                "path": "/media",
                "watch": watch,
                "recursive": True,
                "error": None,
            }
            w._last_inbox_scan_at = 100
            w._last_inbox_scan_ok = False
            snapshot = w._write_health(observer, now=101)
            self.assertFalse(snapshot["healthy"])
            self.assertTrue(snapshot["dispatcher"]["healthy"])
            observer.stop()
            snapshot = w._write_health(observer, now=102)
            self.assertFalse(snapshot["healthy"])
            self.assertFalse(snapshot["dispatcher"]["healthy"])

    def test_inbox_scan_oserror_is_retried_and_recovers(self):
        inbox = self._inbox()
        manifest = os.path.join(inbox, "after-scan-error.xml")
        Path(manifest).write_text("<assets><asset /></assets>", encoding="utf-8")
        with mock.patch.object(
            w.os, "scandir", side_effect=PermissionError("SMB unavailable")
        ):
            self.assertFalse(w._reconcile_curator_inbox(now=100))
        self.assertFalse(w._last_inbox_scan_ok)
        self.assertTrue(w._reconcile_curator_inbox(now=101))
        self.assertIn(manifest, w.pending)

    def test_retry_exhaustion_archive_failure_does_not_resubmit(self):
        inbox = self._inbox()
        manifest = os.path.join(inbox, "exhausted.xml")
        Path(manifest).write_text("<assets><asset /></assets>", encoding="utf-8")
        w.STABLE_SECONDS = 1
        w.XML_RETRY_SECONDS = 20
        w.XML_MAX_RETRIES = 1
        w.xml_retries[manifest] = 1
        archive = mock.Mock(side_effect=[OSError("archive SMB unavailable"), None])
        with mock.patch.object(
            w, "_submit_curator_manifest", return_value=("retry", "proxy unavailable")
        ) as submit, mock.patch.object(w, "_archive_manifest", archive):
            w._queue_pending(manifest, detected_at=0)
            w._process_pending(now=1)
            self.assertTrue(w.pending[manifest]["archive_pending"])
            self.assertEqual(w.xml_retries[manifest], 1)
            w._process_pending(now=21)
        self.assertEqual(submit.call_count, 1)
        self.assertEqual(archive.call_count, 2)
        self.assertNotIn(manifest, w.pending)
        self.assertNotIn(manifest, w.xml_retries)

    @unittest.skipUnless(
        RealPollingObserver is not None,
        "watchdog 6 is not installed",
    )
    def test_real_emitter_restart_recovers_missed_inbox_xml(self):
        """Exercise the real PollingEmitter failure path when available."""
        inbox = self._inbox()
        observer = RealPollingObserver(timeout=0.05)
        handler = w.VideoHandler()
        state = {
            "path": inbox,
            "recursive": False,
            "watch": None,
            "next_retry_at": 0,
            "error": None,
        }
        observer.start()  # Start empty, matching production startup ordering.
        try:
            self.assertTrue(w._schedule_watch(observer, handler, state, now=0))
            emitter = w._find_emitter(observer, state["watch"])
            self.assertIsNotNone(emitter)
            original_take_snapshot = emitter._take_snapshot

            def fail_snapshot():
                raise OSError("simulated SMB snapshot failure")

            emitter._take_snapshot = fail_snapshot
            for _ in range(60):
                if not emitter.is_alive():
                    break
                time.sleep(0.05)
            # Some watchdog patch releases catch polling OSError and keep
            # the emitter alive.  Stop that emitter explicitly in that case;
            # the recovery path under test is the same dead-emitter path.
            if emitter.is_alive():
                emitter.stop()
                emitter.join()
            self.assertFalse(emitter.is_alive())
            emitter._take_snapshot = original_take_snapshot

            missed = os.path.join(inbox, "missed-while-emitter-dead.xml")
            Path(missed).write_text(
                "<assets><asset /></assets>",
                encoding="utf-8",
            )
            w._recover_dead_emitters(observer, handler, {"inbox": state})
            self.assertTrue(_wait_for_emitter(observer, state))
            self.assertTrue(w._reconcile_curator_inbox(now=time.time()))
            self.assertIn(missed, w.pending)
        finally:
            observer.stop()
            observer.join()

    @unittest.skipUnless(
        RealPollingObserver is not None,
        "watchdog 6 is not installed",
    )
    def test_real_initial_snapshot_failure_recovers_after_directory_mounts(self):
        """A live dispatcher must survive one root being absent at startup."""
        with tempfile.TemporaryDirectory() as parent:
            missing = os.path.join(parent, "not-mounted-yet")
            observer = RealPollingObserver(timeout=0.05)
            observer.start()
            state = {
                "path": missing,
                "recursive": False,
                "watch": None,
                "next_retry_at": 0,
                "error": None,
            }
            try:
                self.assertFalse(
                    w._schedule_watch(observer, w.VideoHandler(), state, now=0)
                )
                self.assertIsNone(state["watch"])
                os.mkdir(missing)
                state["next_retry_at"] = 0
                w._recover_dead_emitters(
                    observer,
                    w.VideoHandler(),
                    {"missing-root": state},
                    now=1,
                )
                self.assertTrue(_wait_for_emitter(observer, state))
            finally:
                observer.stop()
                observer.join()


class WatcherExclusionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.media = self.root / "media"
        self.output = self.media / "ipv" / "OBTV-AI"
        self.output.mkdir(parents=True)
        self.allowed = self.media / "shows" / "OBTV-AI"
        self.allowed.mkdir(parents=True)
        self.excluded_video = self.output / "export.mp4"
        self.excluded_video.write_bytes(b"output")
        self.allowed_video = self.allowed / "program.mp4"
        self.allowed_video.write_bytes(b"source")
        self.original = (
            w.WATCHER_EXCLUDE_ROOTS, w.MEDIA_ROOTS, w.CURATOR_ROOT,
            w.CURATOR_INBOX_ROOT, w.STABLE_SECONDS, w.curator_selected,
            w.CURATOR_LEGACY_FOLDER_WATCH,
        )
        w.WATCHER_EXCLUDE_ROOTS = [os.path.realpath(self.output)]
        w.MEDIA_ROOTS = [str(self.media)]
        w.CURATOR_ROOT = str(self.root / "curator")
        w.CURATOR_INBOX_ROOT = str(self.root / "inbox")
        Path(w.CURATOR_INBOX_ROOT).mkdir()
        w.STABLE_SECONDS = 0
        w.curator_selected = set()
        w.CURATOR_LEGACY_FOLDER_WATCH = False
        w.pending.clear()

    def tearDown(self):
        (
            w.WATCHER_EXCLUDE_ROOTS, w.MEDIA_ROOTS, w.CURATOR_ROOT,
            w.CURATOR_INBOX_ROOT, w.STABLE_SECONDS, w.curator_selected,
            w.CURATOR_LEGACY_FOLDER_WATCH,
        ) = self.original
        w.pending.clear()
        w.xml_retries.clear()

    def test_defaults_only_identify_artifacts_not_arbitrary_obtv_ai(self):
        self.assertIn("/artifacts", self.original[0])
        self.assertTrue(w._excluded(str(self.excluded_video)))
        self.assertFalse(w._excluded(str(self.allowed_video)))
        self.assertFalse(w._excluded(str(self.media / "OBTV-AI" / "legitimate.mp4")))
        self.assertFalse(w._excluded(str(self.output.parent / "OBTV-AI-other" / "clip.mp4")))

    def test_env_paths_are_normalized_and_do_not_exclude_by_basename(self):
        with mock.patch.dict(os.environ, {
            "WATCHER_EXCLUDE_ROOTS": f"{self.output}/../OBTV-AI:{self.root}/another-output",
        }):
            configured = _load_watcher()
        self.assertIn(str(self.output), configured.WATCHER_EXCLUDE_ROOTS)
        self.assertIn(str(self.root / "another-output"), configured.WATCHER_EXCLUDE_ROOTS)
        self.assertFalse(configured._excluded(str(self.allowed_video)))

    def test_pruned_startup_selection_and_polling_recursion(self):
        self.assertNotIn(str(self.output), [str(p) for p, _ in w._media_walk(str(self.media))])
        self.assertNotIn("ipv", [e.name for e in w._media_scandir(str(self.media / "ipv"))])
        w._initial_scan()
        self.assertNotIn(str(self.excluded_video), w.pending)
        self.assertIn(str(self.allowed_video), w.pending)
        w.pending.clear()
        w.CURATOR_ROOT = str(self.media)
        w.CURATOR_LEGACY_FOLDER_WATCH = True
        excluded_proxy = self.output / "proxy_video.mp4"
        excluded_proxy.write_bytes(b"output")
        allowed_proxy = self.allowed / "proxy_video.mp4"
        allowed_proxy.write_bytes(b"source")
        with mock.patch.object(w.httpx, "get") as get:
            get.return_value.json.return_value = {"paths": ["ipv", "shows"]}
            get.return_value.raise_for_status.return_value = None
            w._refresh_curator_selected()
        self.assertNotIn(str(excluded_proxy), w.pending)
        self.assertIn(str(allowed_proxy), w.pending)

    def test_symlink_events_queue_and_due_recheck(self):
        alias = self.media / "linked-output"
        alias.symlink_to(self.output, target_is_directory=True)
        linked_video = str(alias / "export.mp4")
        self.assertTrue(w._excluded(linked_video))
        handler = w.VideoHandler()
        handler.on_created(_Event(linked_video))
        handler.on_modified(_Event(str(self.excluded_video)))
        handler.on_moved(_Event(linked_video))
        self.assertFalse(w._queue_pending(linked_video))
        self.assertFalse(w._should_ingest(linked_video))
        self.assertFalse(w.pending)
        # Simulate an already queued path becoming excluded after a config change.
        w.pending[str(self.excluded_video)] = {"size": 6, "detected_at": 0}
        with mock.patch.object(w, "_ingest") as ingest:
            w._process_pending(now=100)
            ingest.assert_not_called()
        self.assertFalse(w.pending)

    def test_inbox_xml_survives_even_when_in_excluded_tree(self):
        inbox = self.output / "xml-inbox"
        inbox.mkdir()
        w.CURATOR_INBOX_ROOT = str(inbox)
        manifest = inbox / "request.xml"
        manifest.write_text("<assets/>", encoding="utf-8")
        self.assertNotIn("xml-inbox", [e.name for e in w._media_scandir(str(self.output))])
        self.assertIn("request.xml", [e.name for e in w._media_scandir(str(inbox))])
        w.VideoHandler().on_created(_Event(str(manifest)))
        self.assertIn(str(manifest), w.pending)
        w.pending.clear()
        self.assertTrue(w._reconcile_curator_inbox(now=1))
        self.assertIn(str(manifest), w.pending)
        w.CURATOR_LEGACY_FOLDER_WATCH = True
        w.CURATOR_ROOT = str(self.media)
        legacy = self.output / "legacy.xml"
        legacy.write_text("<assets/>", encoding="utf-8")
        self.assertFalse(w._should_ingest(str(legacy)))


if __name__ == "__main__":
    unittest.main()