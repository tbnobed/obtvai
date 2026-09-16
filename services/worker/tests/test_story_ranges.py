import unittest

from tasks.story_ranges import constrain_candidate, normalise_clip_ranges


class StoryRangeTests(unittest.TestCase):
    def test_normalise_rejects_malformed_windows_and_groups_valid_windows(self):
        ranges = normalise_clip_ranges(
            [
                {"media_id": "a", "start_time": 10, "end_time": 20},
                {"media_id": "a", "start_time": 30, "end_time": 40},
                {"media_id": "a", "start_time": 20, "end_time": 20},
                {"media_id": "b", "start_time": "not-a-number", "end_time": 2},
            ]
        )
        self.assertEqual(ranges, {"a": [(10.0, 20.0), (30.0, 40.0)]})

    def test_candidate_is_clipped_to_selected_window(self):
        windows = normalise_clip_ranges(
            [{"media_id": "a", "start_time": 10, "end_time": 20}]
        )
        constrained = constrain_candidate(
            {"media_id": "a", "start": 5, "end": 25, "title": "moment"},
            windows,
        )
        self.assertEqual(constrained[0]["start"], 10.0)
        self.assertEqual(constrained[0]["end"], 20.0)

    def test_candidate_can_be_clipped_into_each_selected_window(self):
        windows = normalise_clip_ranges(
            [
                {"media_id": "a", "start_time": 10, "end_time": 20},
                {"media_id": "a", "start_time": 40, "end_time": 50},
            ]
        )
        constrained = constrain_candidate(
            {"media_id": "a", "start": 0, "end": 60, "title": "moment"},
            windows,
        )
        self.assertEqual(
            [(item["start"], item["end"]) for item in constrained],
            [(10.0, 20.0), (40.0, 50.0)],
        )

    def test_candidate_outside_selected_windows_is_dropped(self):
        windows = normalise_clip_ranges(
            [{"media_id": "a", "start_time": 10, "end_time": 20}]
        )
        self.assertEqual(
            constrain_candidate({"media_id": "a", "start": 0, "end": 5}, windows),
            [],
        )
        # Legacy story jobs without campaign windows remain unrestricted.
        candidate = {"media_id": "legacy", "start": 0, "end": 5}
        self.assertEqual(constrain_candidate(candidate, {}), [candidate])


if __name__ == "__main__":
    unittest.main()