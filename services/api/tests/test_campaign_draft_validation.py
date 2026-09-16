"""The production schema must accept the same partially filled draft as the UI."""
import unittest

from pydantic import ValidationError
from app.schemas import CampaignCreate, CampaignUpdate


class CampaignDraftValidationTests(unittest.TestCase):
    def payload(self):
        return dict(
            project_action={"name": "Launch Project"}, name="Launch",
            brief="Announce the program", objective="", audience="",
            key_message="", tone="", call_to_action="",
            channels=[], languages=["en"], selected_clips=[], status="draft",
        )

    def test_name_and_brief_only_form_can_create_draft(self):
        draft = CampaignCreate(**self.payload())
        self.assertEqual(draft.objective, "")
        self.assertEqual(draft.channels, [])

    def test_optional_details_can_be_cleared_when_editing(self):
        draft = CampaignUpdate(objective="", audience="", key_message="",
                               tone="", call_to_action="", channels=[], languages=[])
        self.assertEqual(draft.channels, [])

    def test_name_and_brief_still_required(self):
        for field in ("name", "brief"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                CampaignCreate(**{**self.payload(), field: ""})

    def test_null_and_invalid_project_links_still_rejected(self):
        with self.assertRaises(ValidationError):
            CampaignUpdate(objective=None)
        with self.assertRaises(ValidationError):
            CampaignCreate(**{**self.payload(), "project_id": "another-project"})