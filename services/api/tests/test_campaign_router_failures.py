"""Router-level Campaign Builder failure and reconciliation tests."""

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from app.routers import campaigns
    from app.schemas import CampaignExecute
except ModuleNotFoundError:
    campaigns = None
    CampaignExecute = None


@unittest.skipIf(campaigns is None, "API runtime dependencies are unavailable")
class CampaignRouterFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_execute_refuses_persisted_active_attempt(self):
        campaign = SimpleNamespace(project_id="project-1")
        deliverable = SimpleNamespace(
            status="queued",
            dispatch_state="published",
            job_reference={"type": "reel_job", "id": "reel-1"},
        )
        with (
            patch.object(campaigns, "_load_campaign", new=AsyncMock(return_value=campaign)),
            patch.object(
                campaigns, "_load_deliverable", new=AsyncMock(return_value=deliverable)
            ),
            patch.object(campaigns, "_persist_derived_state", new=AsyncMock()),
        ):
            with self.assertRaises(campaigns.CampaignAPIError) as raised:
                await campaigns.execute_campaign_deliverable(
                    "campaign-1",
                    "deliverable-1",
                    CampaignExecute(),
                    None,
                    None,
                    SimpleNamespace(id="user-1"),
                )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("already queued", raised.exception.detail)

    async def test_enqueue_failure_persists_ambiguous_non_retryable_state(self):
        campaign = SimpleNamespace(
            id="campaign-1",
            project_id="project-1",
            name="Campaign",
            brief="Campaign brief",
            objective="Awareness",
            audience="Viewers",
            key_message="Watch the program",
            tone="Clear",
            call_to_action="Watch now",
            selected_clips=[{
                "media_id": "media-1",
                "start_time": 20,
                "end_time": 30,
                "filename": "source.mp4",
            }],
        )
        deliverable = SimpleNamespace(
            id="deliverable-1",
            campaign_id="campaign-1",
            kind="reel",
            label="cut",
            channel="instagram",
            language="en",
            aspect_ratio="9:16",
            target_duration_seconds=10,
            notes=None,
            status="pending",
            dispatch_state="not_started",
            job_reference=None,
            idempotency_key=None,
            execution_lock=None,
            execution_started_at=None,
            execution_attempt=0,
            error=None,
            output_url=None,
            output_text=None,
            updated_at=None,
        )

        class Result:
            def scalar_one_or_none(self):
                return SimpleNamespace(target_runtime_seconds=None)

        class FakeDB:
            def __init__(self):
                self.commits = 0

            async def execute(self, _query):
                return Result()

            def add(self, _value):
                return None

            async def commit(self):
                self.commits += 1

            async def refresh(self, _value):
                return None

        db = FakeDB()
        with (
            patch.object(campaigns, "_load_campaign", new=AsyncMock(return_value=campaign)),
            patch.object(
                campaigns, "_load_deliverable", new=AsyncMock(return_value=deliverable)
            ),
            patch.object(campaigns, "_persist_derived_state", new=AsyncMock()),
            patch.object(campaigns, "touch_project", new=AsyncMock()),
            patch.object(
                campaigns.worker_client,
                "enqueue_reel",
                new=AsyncMock(side_effect=RuntimeError("broker acknowledgement lost")),
            ),
        ):
            with self.assertRaises(campaigns.CampaignAPIError) as raised:
                await campaigns.execute_campaign_deliverable(
                    "campaign-1",
                    "deliverable-1",
                    CampaignExecute(),
                    None,
                    db,
                    SimpleNamespace(id="user-1"),
                )
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(deliverable.status, "dispatch_unknown")
        self.assertEqual(deliverable.dispatch_state, "ambiguous")
        self.assertIn("Do not retry", deliverable.error)
        self.assertGreaterEqual(db.commits, 2)

    async def test_stale_pending_source_is_unknown_but_later_run_reconciles(self):
        class Result:
            def __init__(self, job):
                self.job = job

            def scalar_one_or_none(self):
                return self.job

        class FakeDB:
            def __init__(self, job):
                self.job = job
                self.commits = 0

            async def execute(self, _query):
                return Result(self.job)

            def add(self, _value):
                return None

            async def commit(self):
                self.commits += 1

        old = datetime.utcnow() - timedelta(
            seconds=campaigns._PUBLISHING_STALE_SECONDS + 1
        )
        deliverable = SimpleNamespace(
            job_reference={"type": "story_job", "id": "story-1"},
            dispatch_state="publishing",
            execution_started_at=old,
            error=None,
            status="queued",
            output_url=None,
            output_text=None,
            execution_lock="lock-1",
        )
        pending_db = FakeDB(SimpleNamespace(status="pending"))
        self.assertEqual(
            (await campaigns._job_state(deliverable, pending_db))[0],
            "dispatch_unknown",
        )
        await campaigns._persist_derived_state(deliverable, pending_db)
        self.assertEqual(deliverable.status, "dispatch_unknown")
        self.assertIsNone(deliverable.execution_lock)
        self.assertEqual(
            (
                await campaigns._job_state(
                    deliverable, FakeDB(SimpleNamespace(status="running"))
                )
            )[0],
            "running",
        )
        await campaigns._persist_derived_state(
            deliverable, FakeDB(SimpleNamespace(status="running"))
        )
        self.assertEqual(deliverable.status, "running")


if __name__ == "__main__":
    unittest.main()