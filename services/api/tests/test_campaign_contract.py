"""Dependency-light contract tests for Campaign Builder validation.

These tests intentionally exercise the request/response contract without
opening a database connection, loading an LLM, or requiring a worker/ComfyUI.
"""

import unittest
from pathlib import Path

try:
    from pydantic import ValidationError
except ModuleNotFoundError:  # The API image installs pydantic; local smoke tests may not.
    ValidationError = None

if ValidationError is not None:
    from app.schemas import (
        CampaignClip,
        CampaignCreate,
        CampaignDeliverableCreate,
        DeliverableStatus,
    )


class CampaignContractTests(unittest.TestCase):
    def test_contract_and_route_keep_terminal_draft_status(self):
        root = Path(__file__).resolve().parents[3]
        contract = (root / ".local" / "campaign-contract.md").read_text()
        route = (root / "services" / "api" / "app" / "routers" / "campaigns.py").read_text()
        spec = (root / "lib" / "api-spec" / "openapi.yaml").read_text()
        generated = (root / "lib" / "api-client-react" / "src" / "generated" / "api.schemas.ts").read_text()
        self.assertIn("draft_ready", contract)
        self.assertIn("dispatch_unknown", contract)
        self.assertIn("draft_ready", spec)
        self.assertIn("CampaignErrorResponse", spec)
        self.assertIn("CampaignError", spec)
        self.assertIn("draft_ready", generated)
        self.assertIn("operation_id=\"executeCampaignDeliverable\"", route)
        self.assertIn("StoryJob", route)
        self.assertIn("ReelJob", route)
        self.assertIn("GraphicsGeneration", route)

    @unittest.skipIf(ValidationError is None, "pydantic is unavailable in this local smoke environment")
    def _create_payload(self, **overrides):
        payload = {
            "project_id": "project-1",
            "name": "Launch",
            "brief": "Launch the new product",
            "objective": "Drive trial",
            "audience": "Editors",
            "key_message": "Fast, clear, useful",
            "tone": "Confident",
            "call_to_action": "Try it today",
            "channels": ["instagram"],
            "languages": ["en"],
        }
        payload.update(overrides)
        return payload

    @unittest.skipIf(ValidationError is None, "pydantic is unavailable in this local smoke environment")
    def test_campaign_requires_exactly_one_project_link_action(self):
        with self.assertRaises(ValidationError):
            CampaignCreate(**self._create_payload(project_id=None))

        with self.assertRaises(ValidationError):
            CampaignCreate(
                **self._create_payload(
                    project_action={"name": "New project"},
                )
            )

        created = CampaignCreate(
            **self._create_payload(
                project_id=None,
                project_action={"name": "New project"},
            )
        )
        self.assertEqual(created.project_action.name, "New project")

    @unittest.skipIf(ValidationError is None, "pydantic is unavailable in this local smoke environment")
    def test_clip_requires_positive_ordered_timecodes(self):
        with self.assertRaises(ValidationError):
            CampaignClip(media_id="media-1", start_time=4, end_time=4)
        with self.assertRaises(ValidationError):
            CampaignClip(media_id="media-1", start_time=5, end_time=4)

        clip = CampaignClip(
            media_id="media-1",
            start_time=0,
            end_time=12.5,
            filename="source.mp4",
        )
        self.assertEqual(clip.end_time, 12.5)

    @unittest.skipIf(ValidationError is None, "pydantic is unavailable in this local smoke environment")
    def test_deliverable_contract_and_terminal_draft_status(self):
        deliverable = CampaignDeliverableCreate(
            kind="reel",
            label="Vertical cut",
            channel="instagram",
            language="en",
            target_duration_seconds=30,
            aspect_ratio="9:16",
        )
        self.assertEqual(deliverable.kind.value, "reel")
        self.assertIn("draft_ready", {status.value for status in DeliverableStatus})

    @unittest.skipIf(ValidationError is None, "pydantic is unavailable in this local smoke environment")
    def test_patch_rejects_null_for_non_nullable_persisted_fields(self):
        from app.schemas import CampaignDeliverableUpdate, CampaignUpdate

        with self.assertRaises(ValidationError):
            CampaignUpdate(name=None)
        with self.assertRaises(ValidationError):
            CampaignUpdate(selected_clips=None)
        with self.assertRaises(ValidationError):
            CampaignDeliverableUpdate(label=None)
        with self.assertRaises(ValidationError):
            CampaignDeliverableUpdate(aspect_ratio=None)

        # These are explicitly nullable in the stable contract.
        self.assertIsNone(CampaignUpdate(due_date=None).due_date)
        self.assertIsNone(
            CampaignDeliverableUpdate(target_duration_seconds=None).target_duration_seconds
        )


if __name__ == "__main__":
    unittest.main()