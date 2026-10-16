"""Recovery state-machine tests use only SQLite and mocked model transport."""
import os
import unittest
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import test_curator_catalog_state as state_tests
from app import catalog_autorecovery as recovery
from app.catalog_recovery import pause
from app.catalog_models import CatalogCheckpoint
from app.catalog_service import CatalogOptions, _run
from app.models import ProcessingJob

REASON = "Shared infrastructure failure: " + recovery.PREFIX + "ConnectTimeout: timed out"


class PolicyTests(unittest.TestCase):
    def test_narrow_allowlist(self):
        self.assertTrue(recovery.recoverable(REASON))
        for unsafe in ("operator pause", "CUDA out of memory", "storage watermark", "redis ConnectTimeout",
                       recovery.PREFIX + "HTTPStatusError: 401",
                       REASON + "; stale file handle", REASON + "; CUDA error"):
            self.assertFalse(recovery.recoverable(unsafe), unsafe)

    def test_backoff_and_consecutive_successes(self):
        r = recovery.begin_pause({}, REASON, 0)["llm_recovery"]
        self.assertEqual(r["next_probe"], 60)
        for now, delay in ((60, 120), (180, 300), (480, 600), (1080, 600)):
            r = recovery.record_probe(r, False, now)
            self.assertEqual(r["next_probe"], now + delay)
        r = recovery.record_probe(r, True, 2000)
        self.assertEqual((r["successes"], r["next_probe"]), (1, 2060))
        self.assertEqual(recovery.record_probe(r, False, 2060)["successes"], 0)
        self.assertEqual(recovery.record_probe(r, True, 2060)["successes"], 2)

    def test_three_outages_lock_and_old_history_expires(self):
        state = {}
        for now in (0, 100, 200):
            state = recovery.begin_pause(state, REASON, now)
        self.assertTrue(state["llm_recovery"]["locked"])
        self.assertFalse(recovery.begin_pause(state, REASON, 4000)["llm_recovery"]["locked"])

    def test_unsafe_and_manual_pauses_never_become_recoverable(self):
        self.assertNotIn("llm_recovery", recovery.begin_pause({"paused": True}, REASON, 0))
        state = recovery.begin_pause({}, REASON, 0)
        state["paused"] = True
        state = recovery.begin_pause(state, "storage unavailable", 1)
        self.assertNotIn("llm_recovery", state)
        self.assertNotIn("llm_recovery", recovery.begin_pause(state, REASON, 2))


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = state_tests.StateTests.asyncSetUp
    asyncTearDown = state_tests.StateTests.asyncTearDown
    candidate = state_tests.StateTests.candidate

    @contextmanager
    def runtime(self, now, probe=(True, False, ""), locked=True):
        connection = AsyncMock()
        connection.execute.return_value = Mock(scalar=Mock(return_value=locked))
        engine = Mock()
        engine.connect.return_value.__aenter__ = AsyncMock(return_value=connection)
        engine.connect.return_value.__aexit__ = AsyncMock()
        with patch.object(recovery, "engine", engine), \
             patch.object(recovery, "AsyncSessionLocal", self.session), \
             patch.object(recovery.time, "time", return_value=now), \
             patch.object(recovery, "probe_model", new=AsyncMock(return_value=probe)) as p:
            yield p

    async def seed(self, state=None):
        async with self.session() as db:
            row = CatalogCheckpoint(id="runner", cursor=state or {}, stats={})
            db.add(row)
            with patch("time.time", return_value=0):
                await pause(db, REASON)
            await db.commit()

    async def state(self):
        async with self.session() as db:
            return (await db.get(CatalogCheckpoint, "runner")).cursor

    async def test_two_probes_durable_restart_and_reconcile_before_resume(self):
        await self.seed()
        for now in (59, 60, 119, 120):
            with self.runtime(now) as probe, \
                 patch("app.catalog_service.reconcile", new=AsyncMock()) as reconcile:
                await recovery.recovery_tick(CatalogOptions())
                self.assertEqual(probe.await_count, int(now in (60, 120)))
            state = await self.state()
            self.assertEqual(state["paused"], now < 120)
        self.assertIsNotNone(state["recovery_canary"])

    async def test_lock_contention_and_manual_pause_do_not_probe(self):
        await self.seed({"paused": True})
        with self.runtime(100) as probe:
            await recovery.recovery_tick(CatalogOptions())
            probe.assert_not_awaited()
        with self.runtime(100, locked=False) as probe:
            await recovery.recovery_tick(CatalogOptions())
            probe.assert_not_awaited()

    async def test_auth_failure_locks_without_clearing_pause(self):
        await self.seed()
        with self.runtime(60, (False, True, "Model probe HTTP 401")):
            await recovery.recovery_tick(CatalogOptions())
        state = await self.state()
        self.assertTrue(state["paused"])
        self.assertTrue(state["llm_recovery"]["locked"])
        self.assertIn("401", state["recovery_alert"])

    async def test_thirty_minute_alert_continues_probes(self):
        await self.seed()
        with self.runtime(1800, (False, False, "timeout")) as probe:
            await recovery.recovery_tick(CatalogOptions())
            probe.assert_awaited_once()
        state = await self.state()
        self.assertIn("30 minutes", state["recovery_alert"])
        self.assertFalse(state["llm_recovery"]["locked"])

    async def test_new_storage_failure_during_reconcile_blocks_resume(self):
        await self.seed()
        async with self.session() as db:
            await self.candidate(db)
        async def unsafe(db, options):
            await pause(db, "archive mount unavailable")
            await db.commit()
        with self.runtime(60):
            await recovery.recovery_tick(CatalogOptions())
        with self.runtime(120), patch("app.catalog_service.reconcile", side_effect=unsafe):
            await recovery.recovery_tick(CatalogOptions())
        self.assertTrue((await self.state())["paused"])
        self.assertNotIn("llm_recovery", await self.state())

    async def test_canary_waits_for_fresh_analysis_not_root_or_old_success(self):
        async with self.session() as db:
            candidate = await self.candidate(db)
            candidate.status = "queued"
            row = CatalogCheckpoint(id="runner", cursor={
                "recovery_canary": {"started": 100, "asset_id": candidate.asset_id}}, stats={})
            db.add(row)
            job = ProcessingJob(id="analysis", media_id=candidate.media_id, job_type="analyze",
                                status="success", created_at=datetime.utcfromtimestamp(99))
            db.add(job)
            await db.commit()
            with patch.object(recovery.time, "time", return_value=200):
                self.assertTrue(await recovery.canary_waiting(db, row))
                job.created_at = datetime.utcfromtimestamp(101)
                await db.commit()
                self.assertTrue(await recovery.canary_waiting(db, row))
                job.logs = ["Analysis complete: 2 key moments, 1 topics"]
                await db.commit()
                self.assertFalse(await recovery.canary_waiting(db, row))
            self.assertIsNone(row.cursor["recovery_canary"])

    async def test_canary_single_admission_and_blocks_next_batch(self):
        async with self.session() as db:
            from app.catalog_models import CatalogAsset
            import time
            row = CatalogCheckpoint(id="runner", cursor={
                "recovery_canary": {"started": time.time(), "asset_id": None}}, stats={})
            db.add(row)
            for i in range(3):
                db.add(CatalogAsset(asset_id=str(i), asset_type="Media", status="eligible",
                       metadata_snapshot={"Id": str(i), "IngestCompleteDate": "2026-01-01"}))
            await db.commit()
            client = Mock()
            client.page.return_value = []
            async def import_reserved(db, candidate):
                # Reservation is durable before the importer can publish.
                await db.refresh(row)
                self.assertEqual(row.cursor["recovery_canary"]["asset_id"], candidate.asset_id)
                return None, "queued"
            with patch("app.catalog_service.CatalogClient", return_value=client), \
                 patch("app.catalog_service.storage_available", return_value=True), \
                 patch("app.catalog_service.import_asset", new=AsyncMock(side_effect=import_reserved)) as importer:
                result = await _run(db, CatalogOptions(dry_run=False, max_assets=10))
                self.assertEqual(result["stats"]["admitted"], 1)
                self.assertEqual(importer.await_count, 1)
                # Isolate the gate from reconciliation of this synthetic media.
                with patch("app.catalog_service.reconcile", new=AsyncMock(return_value=0)):
                    result = await _run(db, CatalogOptions(dry_run=False, max_assets=10))
                self.assertEqual(result["stats"]["stop"], "recovery_canary")
                self.assertEqual(importer.await_count, 1)


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_generation_required_and_auth_is_permanent(self):
        import httpx
        client_class = httpx.AsyncClient
        for status, permanent in ((200, False), (401, True), (503, False)):
            paths = []
            def handle(request):
                paths.append(request.url.path)
                return httpx.Response(status, json={"choices": [{"message": {"content": "READY"}}]})
            with patch.dict(os.environ, {"LLM_BASE_URL": "http://test/v1", "LLM_REMOTE_MODEL": "gpt-oss"}), \
                 patch("httpx.AsyncClient", side_effect=lambda **kw: client_class(
                     transport=httpx.MockTransport(handle), **kw)):
                ok, blocked, _ = await recovery.probe_model()
            self.assertEqual(ok, status == 200)
            self.assertEqual(blocked, permanent)
            self.assertEqual(paths, ["/v1/chat/completions"])
