"""SQLite transaction tests; never connect to the configured production database."""
import os
import sys
import types
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

_original_database_url = os.environ.get("DATABASE_URL")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

from app.catalog import INITIAL_CURSOR
from app.catalog_models import CatalogAsset, CatalogCheckpoint, CatalogRun
from app.catalog_service import CatalogOptions, _run, prepare_dispatch, publish_dispatch, reconcile
from app.models import MediaAsset, ProcessingJob

if _original_database_url is None:
    os.environ.pop("DATABASE_URL", None)
else:
    os.environ["DATABASE_URL"] = _original_database_url


@compiles(JSONB, "sqlite")
def jsonb_for_test(type_, compiler, **kw):
    return "JSON"


class StateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        tables = [CatalogAsset.__table__, CatalogRun.__table__, CatalogCheckpoint.__table__,
                  MediaAsset.__table__, ProcessingJob.__table__]
        async with self.engine.begin() as conn:
            for table in tables:
                await conn.run_sync(table.create)
        self.session = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def candidate(self, db):
        media = MediaAsset(id="media1", filename="image.png", original_path="/curator/image.png", status="pending")
        candidate = CatalogAsset(asset_id="exact1", asset_type="Image", media_id="media1",
                                 metadata_snapshot={"Id": "exact1", "IngestCompleteDate": "2023-01-01"},
                                 status="retry", attempts=1)
        db.add_all([media, candidate])
        await db.commit()
        return candidate

    async def test_broker_failure_keeps_outbox_and_same_task_on_resume(self):
        publisher = AsyncMock(side_effect=RuntimeError("broker unavailable"))
        module = types.SimpleNamespace(_publish=publisher)
        with patch.dict(sys.modules, {"app.worker_client": module}):
            async with self.session() as db:
                candidate = await self.candidate(db)
                await prepare_dispatch(db, candidate)
                job_id, task_id = candidate.job_id, candidate.task_id
                with self.assertRaisesRegex(RuntimeError, "broker unavailable"):
                    await publish_dispatch(db, candidate)
                await db.rollback()
            async with self.session() as db:
                candidate = await db.get(CatalogAsset, "exact1")
                self.assertEqual(candidate.dispatch_state, "pending")
                self.assertEqual(candidate.job_id, job_id)
                publisher.side_effect = None
                result = await publish_dispatch(db, candidate)
                self.assertEqual(result, ("media1", "queued"))
                self.assertEqual(publisher.call_args.args[3], task_id)
                self.assertEqual((await db.execute(select(func.count()).select_from(ProcessingJob))).scalar(), 1)

    async def test_publish_commit_gap_worker_success_is_not_republished(self):
        publisher = AsyncMock()
        with patch.dict(sys.modules, {"app.worker_client": types.SimpleNamespace(_publish=publisher)}):
            async with self.session() as db:
                candidate = await self.candidate(db)
                await prepare_dispatch(db, candidate)
                # Broker delivered; API died before the "published" commit.
                job = await db.get(ProcessingJob, candidate.job_id)
                job.status = "success"
                await db.commit()
                await publish_dispatch(db, candidate)
                publisher.assert_not_called()
                self.assertEqual(candidate.dispatch_state, "published")

    async def test_admission_resumes_failed_publish_at_inflight_ceiling(self):
        publisher = AsyncMock(side_effect=RuntimeError("broker unavailable"))
        client = Mock()
        client.page.return_value = []
        options = CatalogOptions(dry_run=False, max_inflight=1)
        with patch.dict(sys.modules, {"app.worker_client": types.SimpleNamespace(_publish=publisher)}), \
                patch("app.catalog_service.CatalogClient", return_value=client), \
                patch("app.catalog_service.storage_available", return_value=True):
            async with self.session() as db:
                candidate = await self.candidate(db)
                await prepare_dispatch(db, candidate)
                original_job = candidate.job_id
                result = await _run(db, options)
                self.assertEqual(result["stats"]["errors"], 1)
                candidate = await db.get(CatalogAsset, "exact1")
                self.assertEqual(candidate.status, "retry")
            publisher.side_effect = None
            async with self.session() as db:
                runner = await db.get(CatalogCheckpoint, "runner")
                self.assertTrue(runner.cursor["paused"])
                runner.cursor = {**runner.cursor, "paused": False}
                await db.commit()
                result = await _run(db, options)
                self.assertEqual(result["stats"]["admitted"], 1)
                candidate = await db.get(CatalogAsset, "exact1")
                self.assertEqual(candidate.job_id, original_job)
                self.assertEqual(candidate.status, "queued")
                self.assertEqual((await db.execute(select(func.count()).select_from(ProcessingJob))).scalar(), 1)

    async def test_worker_failure_retries_bounded_and_ignores_historical_errors(self):
        async with self.session() as db:
            candidate = await self.candidate(db)
            await prepare_dispatch(db, candidate)
            candidate.status = "queued"
            job = await db.get(ProcessingJob, candidate.job_id)
            job.status = "error"
            job.created_at = datetime.utcnow() - timedelta(seconds=20)
            media = await db.get(MediaAsset, candidate.media_id)
            media.status = "error"
            await db.commit()
            await reconcile(db, CatalogOptions())
            self.assertEqual(candidate.status, "retry")
            self.assertEqual(candidate.dispatch_state, "failed")
            first_job = candidate.job_id
            candidate.attempts = 2
            await prepare_dispatch(db, candidate)
            self.assertNotEqual(candidate.job_id, first_job)
            second = await db.get(ProcessingJob, candidate.job_id)
            second.status, candidate.status, media.status = "success", "queued", "ready"
            await db.commit()
            await reconcile(db, CatalogOptions())
            self.assertEqual(candidate.status, "complete")
            second.status, candidate.status, media.status = "error", "queued", "error"
            candidate.attempts = 3
            await db.commit()
            await reconcile(db, CatalogOptions())
            self.assertEqual(candidate.status, "failed")

    async def test_active_processing_not_retried(self):
        async with self.session() as db:
            candidate = await self.candidate(db)
            await prepare_dispatch(db, candidate)
            candidate.status = "queued"
            job = await db.get(ProcessingJob, candidate.job_id)
            job.status = "running"
            await db.commit()
            await reconcile(db, CatalogOptions())
            self.assertEqual(candidate.status, "queued")

    async def test_page_dedup_resume_and_failure_leave_cursor_committed(self):
        client = Mock()
        client.page.return_value = [
            {"Id": "one", "IngestCompleteDate": "2023-01-01"},
            {"Id": "one", "IngestCompleteDate": "2023-01-01"},
            {"Id": "two"},  # Missing date is durably reviewable.
        ]
        with patch("app.catalog_service.CatalogClient", return_value=client):
            async with self.session() as db:
                result = await _run(db, CatalogOptions())
                self.assertEqual(result["cursor"]["lanes"]["0"]["offset"], 3)
                self.assertEqual(result["stats"]["new"], 2)
                self.assertEqual(result["stats"]["duplicates"], 1)
            client.page.side_effect = RuntimeError("network failure")
            async with self.session() as db:
                failed = await _run(db, CatalogOptions())
                self.assertEqual(failed["cursor"]["lanes"]["0"]["offset"], 3)
                self.assertEqual(failed["stats"]["stop"], "error")
                self.assertIn("network failure", failed["error"])
                rows = (await db.execute(select(CatalogAsset))).scalars().all()
                self.assertEqual(len(rows), 2)
                self.assertEqual((await db.get(CatalogAsset, "two")).status, "review")
            client.page.side_effect = None
            client.page.return_value = [{"Id": "two"}, {"Id": "three", "IngestCompleteDate": "2024-01-01"}]
            async with self.session() as db:
                checkpoint = await db.get(CatalogCheckpoint, "catalog")
                checkpoint.cursor = {**checkpoint.cursor, "type_index": 0, "offset": 3}
                await db.commit()
                resumed = await _run(db, CatalogOptions())
                self.assertEqual(resumed["cursor"]["lanes"]["0"]["offset"], 5)
                self.assertEqual((await db.execute(select(func.count()).select_from(CatalogAsset))).scalar(), 3)

    async def test_invalid_id_rolls_back_entire_page(self):
        client = Mock()
        client.page.return_value = [{"Id": "valid", "IngestCompleteDate": "2023-01-01"}, {"Name": "no id"}]
        with patch("app.catalog_service.CatalogClient", return_value=client):
            async with self.session() as db:
                result = await _run(db, CatalogOptions())
                self.assertEqual(result["cursor"], INITIAL_CURSOR)
                self.assertEqual((await db.execute(select(func.count()).select_from(CatalogAsset))).scalar(), 0)

    async def test_inflight_and_storage_watermarks_stop_admission(self):
        client = Mock()
        client.page.return_value = []

        async def import_one(db, candidate):
            db.add(MediaAsset(id=candidate.asset_id, filename="fixture", status="pending"))
            await db.commit()
            return candidate.asset_id, "queued"

        async with self.session() as db:
            for asset_id in ("one", "two"):
                db.add(CatalogAsset(asset_id=asset_id, asset_type="Image",
                                    metadata_snapshot={"Id": asset_id, "IngestCompleteDate": "2023-01-01"},
                                    status="eligible", attempts=0))
            await db.commit()
            with patch("app.catalog_service.CatalogClient", return_value=client), \
                    patch("app.catalog_service.storage_available", return_value=False), \
                    patch("app.catalog_service.import_asset", new=AsyncMock()) as importer:
                result = await _run(db, CatalogOptions(dry_run=False))
                self.assertEqual(result["stats"]["stop"], "storage_watermark")
                importer.assert_not_called()
            runner = await db.get(CatalogCheckpoint, "runner")
            self.assertTrue(runner.cursor["paused"])
            runner.cursor = {**runner.cursor, "paused": False}
            await db.commit()
            with patch("app.catalog_service.CatalogClient", return_value=client), \
                    patch("app.catalog_service.storage_available", return_value=True), \
                    patch("app.catalog_service.import_asset", side_effect=import_one) as importer:
                result = await _run(db, CatalogOptions(dry_run=False, max_assets=10, max_inflight=1))
                self.assertEqual(result["stats"]["stop"], "max_inflight")
                self.assertEqual(result["stats"]["admitted"], 1)
                self.assertEqual(importer.call_count, 1)

    async def test_per_run_asset_cap_does_not_queue_inventory(self):
        client = Mock()
        client.page.return_value = [{"Id": str(i), "IngestCompleteDate": "2023-01-01"} for i in range(20)]
        with patch("app.catalog_service.CatalogClient", return_value=client), \
                patch("app.catalog_service.storage_available", return_value=True), \
                patch("app.catalog_service.import_asset", new=AsyncMock(return_value=(None, "queued"))) as importer:
            async with self.session() as db:
                result = await _run(db, CatalogOptions(dry_run=False, max_assets=2, max_inflight=100))
                self.assertEqual(result["stats"]["new"], 20)
                self.assertEqual(result["stats"]["admitted"], 2)
                self.assertEqual(importer.call_count, 2)

    async def test_new_cutoff_rechecks_stored_eligible_and_retry_without_deletion(self):
        client = Mock()
        client.page.return_value = []
        async with self.session() as db:
            for name, status, day in (("a", "eligible", "2024-01-01"),
                                      ("b", "retry", "2024-12-31"),
                                      ("c", "eligible", "2025-01-01")):
                db.add(CatalogAsset(asset_id=name, asset_type="Media", status=status,
                                   attempts=0, metadata_snapshot={"Id": name, "IngestCompleteDate": day}))
            db.add(MediaAsset(id="historical", filename="old", status="ready"))
            await db.commit()
            with patch.dict(os.environ, {"CURATOR_CATALOG_CUTOFF": "2025-01-01"}), \
                    patch("app.catalog_service.CatalogClient", return_value=client), \
                    patch("app.catalog_service.storage_available", return_value=True), \
                    patch("app.catalog_service.import_asset", new=AsyncMock(return_value=(None, "queued"))) as importer:
                result = await _run(db, CatalogOptions(dry_run=False, max_assets=1))
                await _run(db, CatalogOptions(dry_run=False, max_assets=1))
            self.assertEqual(result["stats"]["admitted"], 1)
            self.assertEqual(importer.call_args.args[1].asset_id, "c")
            self.assertEqual((await db.get(CatalogAsset, "a")).status, "excluded")
            self.assertEqual((await db.get(CatalogAsset, "b")).status, "excluded")
            self.assertEqual((await db.get(MediaAsset, "historical")).status, "ready")

    async def test_recurring_isolated_worker_failure_does_not_pause(self):
        from app.commands.curator_catalog import recurring_tick, parser
        args = parser().parse_args(["--apply", "--enable-recurring", "--max-assets", "1", "--max-inflight", "1"])
        with patch("app.database.AsyncSessionLocal", self.session), \
                patch("app.database.engine", types.SimpleNamespace(dispose=AsyncMock())), \
                patch("app.commands.curator_catalog.execute", new=AsyncMock(return_value={
                    "run_id": "test", "stats": {"worker_failures": 1, "errors": 0}, "error": None,
                })) as execute:
            await recurring_tick(args)
            result = await recurring_tick(args)
            self.assertNotIn("paused", result)
            self.assertEqual(execute.await_count, 2)
            async with self.session() as db:
                row = await db.get(CatalogCheckpoint, "runner")
                self.assertFalse(row.cursor["paused"])
                self.assertEqual(row.cursor["state"], "waiting")
                self.assertEqual(row.cursor["consecutive_errors"], 0)
                self.assertIsNone(row.last_error)

    async def test_recurring_infrastructure_error_pauses_immediately(self):
        from app.commands.curator_catalog import recurring_tick, parser
        args = parser().parse_args(["--apply", "--enable-recurring"])
        with patch("app.database.AsyncSessionLocal", self.session), \
                patch("app.database.engine", types.SimpleNamespace(dispose=AsyncMock())), \
                patch("app.commands.curator_catalog.execute", new=AsyncMock(
                    side_effect=RuntimeError("Archive storage preflight failed: CIFS unavailable"))) as execute:
            await recurring_tick(args)
            result = await recurring_tick(args)
            self.assertTrue(result["paused"])
            self.assertEqual(execute.await_count, 1)
            async with self.session() as db:
                row = await db.get(CatalogCheckpoint, "runner")
                self.assertTrue(row.cursor["paused"])
                self.assertIn("CIFS unavailable", row.last_error)

    async def test_recurring_three_errors_pause_without_restart_reset(self):
        from app.commands.curator_catalog import recurring_tick, parser
        args = parser().parse_args(["--apply", "--enable-recurring"])
        with patch("app.database.AsyncSessionLocal", self.session), \
                patch("app.database.engine", types.SimpleNamespace(dispose=AsyncMock())), \
                patch("app.commands.curator_catalog.execute", new=AsyncMock(return_value={
                    "stats": {"errors": 1}, "error": "Gateway unavailable",
                })) as execute:
            for _ in range(4):
                await recurring_tick(args)
            self.assertEqual(execute.await_count, 3)
            async with self.session() as db:
                row = await db.get(CatalogCheckpoint, "runner")
                self.assertTrue(row.cursor["paused"])
                self.assertEqual(row.last_error, "Gateway unavailable")

    async def test_manual_dryrun_cannot_consume_infrastructure_failure_before_runner(self):
        from app.commands.curator_catalog import recurring_tick, parser
        client = Mock()
        client.page.return_value = []
        async with self.session() as db:
            candidate = await self.candidate(db)
            await prepare_dispatch(db, candidate)
            candidate.status, candidate.dispatch_state = "queued", "published"
            job = await db.get(ProcessingJob, candidate.job_id)
            job.status = "error"
            job.error_message = "Redis connection refused"
            media = await db.get(MediaAsset, candidate.media_id)
            media.status = "error"
            await db.commit()
            with patch("app.catalog_service.CatalogClient", return_value=client):
                result = await _run(db, CatalogOptions(dry_run=True))
            self.assertEqual(result["stats"]["worker_failures"], 1)
            self.assertTrue((await db.get(CatalogCheckpoint, "runner")).cursor["paused"])
        args = parser().parse_args(["--apply", "--enable-recurring"])
        with patch("app.database.AsyncSessionLocal", self.session), \
                patch("app.database.engine", types.SimpleNamespace(dispose=AsyncMock())), \
                patch("app.commands.curator_catalog.execute", new=AsyncMock()) as execute:
            result = await recurring_tick(args)
            self.assertTrue(result["paused"])
            execute.assert_not_called()

    async def test_recovered_asset_completes_even_when_attempt_budget_exhausted(self):
        async with self.session() as db:
            candidate = await self.candidate(db)
            await prepare_dispatch(db, candidate)
            candidate.status, candidate.dispatch_state, candidate.attempts = "retry", "failed", 3
            job = await db.get(ProcessingJob, candidate.job_id)
            job.status, job.retry_count = "success", 1
            media = await db.get(MediaAsset, candidate.media_id)
            media.status = "ready"
            await db.commit()
            self.assertEqual(await reconcile(db, CatalogOptions()), 0)
            self.assertEqual(candidate.status, "complete")
            self.assertEqual((await db.execute(select(func.count()).select_from(ProcessingJob))).scalar(), 1)

    async def test_isolated_failure_quarantines_and_next_asset_is_admitted(self):
        client = Mock()
        client.page.return_value = []
        async with self.session() as db:
            candidate = await self.candidate(db)
            await prepare_dispatch(db, candidate)
            candidate.status, candidate.dispatch_state = "queued", "published"
            job = await db.get(ProcessingJob, candidate.job_id)
            job.status, job.error_message = "error", "Unparseable LLM output"
            media = await db.get(MediaAsset, candidate.media_id)
            media.status = "ready"
            await db.commit()
            for attempt in (1, 2, 3):
                candidate.attempts = attempt
                if attempt > 1:
                    await prepare_dispatch(db, candidate)
                    job = await db.get(ProcessingJob, candidate.job_id)
                    job.status, job.error_message, media.status = "error", "Invalid model output", "ready"
                await db.commit()
                await reconcile(db, CatalogOptions())
                self.assertEqual(candidate.status, "retry" if attempt < 3 else "failed")
                self.assertIsNone(await db.get(CatalogCheckpoint, "runner"))
            fresh = CatalogAsset(asset_id="fresh", asset_type="Image", attempts=0, status="eligible",
                                 metadata_snapshot={"Id": "fresh", "IngestCompleteDate": "2026-01-01"})
            db.add(fresh)
            await db.commit()
            importer = AsyncMock(return_value=("new-media", "queued"))
            with patch("app.catalog_service.CatalogClient", return_value=client), \
                    patch("app.catalog_service.storage_available", return_value=True), \
                    patch("app.catalog_service.import_asset", importer):
                result = await _run(db, CatalogOptions(dry_run=False, max_assets=1))
            self.assertEqual(result["stats"]["admitted"], 1)
            self.assertEqual(importer.call_args.args[1].asset_id, "fresh")

    async def test_three_distinct_gpu_failures_durable_across_dry_runs(self):
        client = Mock()
        client.page.return_value = []
        async with self.session() as db:
            candidate = await self.candidate(db)
            media = await db.get(MediaAsset, candidate.media_id)
            for attempt in (1, 2, 3):
                candidate.attempts = attempt
                await prepare_dispatch(db, candidate)
                job = await db.get(ProcessingJob, candidate.job_id)
                job.status, job.error_message = "error", "CUDA out of memory"
                candidate.status, media.status = "queued", "error"
                await db.commit()
                with patch("app.catalog_service.CatalogClient", return_value=client):
                    first = await _run(db, CatalogOptions())
                    second = await _run(db, CatalogOptions())
                self.assertEqual(first["stats"]["worker_failures"], 1)
                self.assertEqual(second["stats"]["worker_failures"], 0)
                circuit = await db.get(CatalogCheckpoint, "gpu_failures")
                self.assertEqual(len(circuit.cursor["times"]), attempt)
                runner = await db.get(CatalogCheckpoint, "runner")
                self.assertEqual(bool(runner and runner.cursor.get("paused")), attempt == 3)

    async def test_cancelled_child_never_retried(self):
        async with self.session() as db:
            candidate = await self.candidate(db)
            await prepare_dispatch(db, candidate)
            root = await db.get(ProcessingJob, candidate.job_id)
            root.status = "success"
            db.add(ProcessingJob(id="child", media_id=candidate.media_id, job_type="analyze",
                                 status="cancelled", created_at=root.created_at + timedelta(seconds=1)))
            await db.commit()
            await reconcile(db, CatalogOptions())
            self.assertEqual(candidate.status, "failed")
            self.assertIn("cancelled", candidate.error)

    async def test_changed_failed_children_do_not_multiply_gpu_events(self):
        async with self.session() as db:
            candidate = await self.candidate(db)
            await prepare_dispatch(db, candidate)
            root = await db.get(ProcessingJob, candidate.job_id)
            root.status = "success"
            media = await db.get(MediaAsset, candidate.media_id)
            media.status = "ready"
            children = [ProcessingJob(id=f"gpu{i}", media_id=candidate.media_id,
                                      job_type="visual_embed", status="error",
                                      error_message="CUDA out of memory",
                                      created_at=root.created_at + timedelta(seconds=1))
                        for i in range(3)]
            db.add_all(children)
            await db.commit()
            for child in children:
                await reconcile(db, CatalogOptions())
                circuit = await db.get(CatalogCheckpoint, "gpu_failures")
                self.assertEqual(len(circuit.cursor["times"]), 1)
                self.assertIsNone(await db.get(CatalogCheckpoint, "runner"))
                child.status = "success"
                await db.commit()
            await reconcile(db, CatalogOptions())
            self.assertEqual(candidate.status, "complete")

    async def test_retry_with_active_child_does_not_enqueue_new_pipeline(self):
        client = Mock()
        client.page.return_value = []
        async with self.session() as db:
            candidate = await self.candidate(db)
            await prepare_dispatch(db, candidate)
            root = await db.get(ProcessingJob, candidate.job_id)
            root.status, root.error_message = "error", "Malformed output"
            candidate.status, candidate.dispatch_state = "retry", "failed"
            db.add(ProcessingJob(id="running-child", media_id=candidate.media_id,
                                 job_type="transcribe", status="running",
                                 created_at=root.created_at + timedelta(seconds=1)))
            await db.commit()
            with patch("app.catalog_service.CatalogClient", return_value=client), \
                    patch("app.catalog_service.storage_available", return_value=True), \
                    patch("app.catalog_service.import_asset", new=AsyncMock()) as importer:
                result = await _run(db, CatalogOptions(dry_run=False))
            importer.assert_not_called()
            self.assertEqual(result["stats"]["admitted"], 0)
            self.assertEqual(candidate.attempts, 1)

    async def test_unrelated_reports_do_not_poison_successful_ingest(self):
        async with self.session() as db:
            candidate = await self.candidate(db)
            await prepare_dispatch(db, candidate)
            root = await db.get(ProcessingJob, candidate.job_id)
            root.status = "success"
            media = await db.get(MediaAsset, candidate.media_id)
            media.status = "ready"
            for kind, state in (("media_report", "error"), ("render", "cancelled")):
                db.add(ProcessingJob(id=kind, job_type=kind, status=state,
                                     media_id=candidate.media_id,
                                     error_message="CUDA out of memory",
                                     created_at=root.created_at + timedelta(seconds=1)))
            await db.commit()
            await reconcile(db, CatalogOptions())
            self.assertEqual(candidate.status, "complete")
            self.assertIsNone(await db.get(CatalogCheckpoint, "runner"))
            self.assertIsNone(await db.get(CatalogCheckpoint, "gpu_failures"))

    async def test_manual_preflight_failure_latches_pause_before_raising(self):
        from app.catalog_service import run_catalog
        from app.commands.import_curator_workbook import ImportFailure
        lock = AsyncMock()
        lock.__aenter__.return_value = lock
        lock.execute.return_value.scalar = Mock(return_value=True)
        fake_engine = types.SimpleNamespace(connect=Mock(return_value=lock))
        with patch("app.catalog_service.engine", fake_engine), \
                patch("app.catalog_service.AsyncSessionLocal", self.session), \
                patch("app.catalog_storage.require_archive_storage",
                      side_effect=RuntimeError("CIFS source unavailable")):
            with self.assertRaisesRegex(ImportFailure, "Archive storage preflight failed"):
                await run_catalog(CatalogOptions(dry_run=False, confirm="QUEUE_BOUNDED_CATALOG"))
        async with self.session() as db:
            row = await db.get(CatalogCheckpoint, "runner")
            self.assertTrue(row.cursor["paused"])
            self.assertIn("CIFS source unavailable", row.last_error)