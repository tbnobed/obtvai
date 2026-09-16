import unittest

from app.campaign_execution import (
    execution_conflict,
    merge_media_ranges,
    selected_media_ids,
    selected_media_ranges,
)


class CampaignExecutionStateTests(unittest.TestCase):
    def test_project_sync_tracks_exact_selected_windows_per_media(self):
        clips = [
            {"media_id": "a", "start_time": 12, "end_time": 18},
            {"media_id": "a", "start_time": 4, "end_time": 9},
            {"media_id": "b", "start_time": 1, "end_time": 3},
        ]
        self.assertEqual(selected_media_ids(clips), ["a", "b"])
        self.assertEqual(
            selected_media_ranges(clips),
            {
                "a": {"in": 4.0, "out": 18.0},
                "b": {"in": 1.0, "out": 3.0},
            },
        )

    def test_project_sync_does_not_narrow_existing_same_media_range(self):
        self.assertEqual(
            merge_media_ranges(
                {"a": {"in": 0, "out": 100}, "unrelated": {"in": 5, "out": 9}},
                {"a": {"in": 20, "out": 30}, "new": {"in": 2, "out": 4}},
            ),
            {
                "a": {"in": 0.0, "out": 100.0},
                "unrelated": {"in": 5.0, "out": 9.0},
                "new": {"in": 2, "out": 4},
            },
        )

    def test_active_rows_are_not_dispatchable_or_double_published(self):
        self.assertEqual(
            execution_conflict("queued", "published", retry=False),
            "Deliverable is already queued or running",
        )
        self.assertEqual(
            execution_conflict("running", "published", retry=False),
            "Deliverable is already queued or running",
        )

    def test_ambiguous_publish_is_never_retryable(self):
        message = execution_conflict("queued", "ambiguous", retry=True)
        self.assertIn("not safely retryable", message)
        self.assertIn(
            "not safely retryable",
            execution_conflict("dispatch_unknown", "published", retry=False),
        )
        # Once the referenced source job is definitively failed, explicit
        # retry is safe even if the original publish acknowledgement was lost.
        self.assertIsNone(execution_conflict("failed", "publishing", retry=True))

    def test_only_explicit_failed_retry_can_dispatch(self):
        self.assertIsNone(execution_conflict("failed", "published", retry=True))
        self.assertIn(
            "retry=true",
            execution_conflict("failed", "published", retry=False),
        )
        self.assertIn(
            "already completed",
            execution_conflict("draft_ready", "published", retry=True),
        )


if __name__ == "__main__":
    unittest.main()