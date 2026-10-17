import os
import unittest
from unittest.mock import patch, Mock, AsyncMock
import test_curator_catalog_state as fixtures
from app.catalog_limit import library_limit
from app.catalog_models import CatalogAsset, CatalogCheckpoint
from app.models import MediaAsset, ProcessingJob
from app.catalog_service import _run, CatalogOptions


class LimitTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.StateTests.asyncSetUp
    asyncTearDown = fixtures.StateTests.asyncTearDown

    async def test_batch_cannot_cross_limit(self):
        with patch.dict(os.environ, {"CURATOR_CATALOG_READY_LIMIT": "2"}):
            async with self.session() as db:
                for i in range(4):
                    db.add(CatalogAsset(asset_id=str(i), asset_type="Media", status="eligible",
                        metadata_snapshot={"Id": str(i), "IngestCompleteDate": "2026-01-01"}))
                await db.commit()
                async def importer(db, candidate):
                    mid = "media-" + candidate.asset_id
                    db.add(MediaAsset(id=mid, filename=mid, original_path="/x", status="ready"))
                    await db.commit()
                    return mid, "queued"
                client = Mock()
                client.page.return_value = []
                with patch("app.catalog_service.CatalogClient", return_value=client), \
                     patch("app.catalog_service.storage_available", return_value=True), \
                     patch("app.catalog_service.import_asset", new=AsyncMock(side_effect=importer)):
                    result = await _run(db, CatalogOptions(dry_run=False, max_assets=10))
                self.assertEqual(result["stats"]["admitted"], 2)
                self.assertEqual(result["stats"]["stop"], "library_limit_reached")

    async def test_reservations_deduplicate_and_ready_not_double_counted(self):
        with patch.dict(os.environ, {"CURATOR_CATALOG_READY_LIMIT": "3"}):
            async with self.session() as db:
                for mid, state in (("ready", "ready"), ("pending", "pending")):
                    db.add(MediaAsset(id=mid, filename=mid, original_path="/x", status=state))
                    for suffix in ("a", "b"):
                        db.add(ProcessingJob(id=mid+suffix, media_id=mid, job_type="analyze", status="running"))
                await db.commit()
                candidate = CatalogAsset(asset_id="new", media_id=None)
                self.assertIsNone(await library_limit(db, candidate))
                db.add(MediaAsset(id="other", filename="o", original_path="/o", status="processing"))
                await db.commit()
                self.assertEqual(await library_limit(db, candidate), "library_limit_draining")
                candidate.media_id = "pending"
                self.assertIsNone(await library_limit(db, candidate))
                candidate.media_id = "ready"
                self.assertIsNone(await library_limit(db, candidate))

    async def test_latch_survives_resume_and_count_decrease(self):
        with patch.dict(os.environ, {"CURATOR_CATALOG_READY_LIMIT": "1"}):
            async with self.session() as db:
                media = MediaAsset(id="ready", filename="r", original_path="/r", status="ready")
                db.add(media)
                await db.commit()
                self.assertEqual(await library_limit(db), "library_limit_reached")
                runner = await db.get(CatalogCheckpoint, "runner")
                self.assertTrue(runner.cursor["paused"])
                self.assertNotIn("llm_recovery", runner.cursor)
                runner.cursor = {"paused": False}
                media.status = "error"
                await db.commit()
                self.assertEqual(await library_limit(db), "library_limit_reached")

    async def test_disabled_and_failed_assets_not_reserved(self):
        with patch.dict(os.environ, {"CURATOR_CATALOG_READY_LIMIT": "0"}):
            async with self.session() as db:
                self.assertIsNone(await library_limit(db))
                self.assertIsNone(await db.get(CatalogCheckpoint, "library_limit"))
        with patch.dict(os.environ, {"CURATOR_CATALOG_READY_LIMIT": "1"}):
            async with self.session() as db:
                db.add(MediaAsset(id="failed", filename="f", original_path="/f", status="error"))
                await db.commit()
                self.assertIsNone(await library_limit(db, CatalogAsset(asset_id="new")))
