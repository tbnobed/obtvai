import importlib.util
import ast
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock

spec = importlib.util.spec_from_file_location("editorial_brief", Path(__file__).parents[1] / "app/services/editorial_brief.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BriefTests(unittest.IsolatedAsyncioTestCase):
    def test_explicit_runtime_is_not_a_five_percent_estimate(self):
        path = Path(__file__).parents[1] / "app/routers/project_chat.py"
        tree = ast.parse(path.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_trim_to_target")
        namespace = {"_MIN_TRIMMED_CLIP": 5,
                     "_clip_duration": lambda c: c["end_time"] - c["start_time"]}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
        clips = [dict(start_time=0, end_time=180, locked=True), dict(start_time=0, end_time=160)]
        namespace["_trim_to_target"](clips, 330)
        self.assertAlmostEqual(sum(c["end_time"] - c["start_time"] for c in clips), 330)
        self.assertEqual(clips[0]["end_time"], 180)

    def test_selector_receives_entire_reviewed_window(self):
        path = Path(__file__).parents[1] / "app/routers/project_chat.py"
        tree = ast.parse(path.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_cand_lines")
        namespace = {"_SNIPPET_CHARS": 100, "_fmt_tc": str,
                     "_clip_duration": lambda c: c["end_time"] - c["start_time"]}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
        reviewed = "first cue " * 150 + "FINAL CUE MUST BE REVIEWED"
        output = namespace["_cand_lines"]([dict(filename="sample", start_time=0, end_time=100,
                                                snippet="short hit", _review_text=reviewed)])
        self.assertIn(reviewed, output)

    def test_review_window_never_includes_unseen_text(self):
        rows = [(0, 5, "first"), (5, 10, "second"), (10, 15, "third")]
        self.assertEqual(module.reviewed_window(rows, 0, budget=13), (0, 10, "first second"))
        self.assertEqual(module.reviewed_window(rows, 0, maximum=7), (0, 5, "first"))
        self.assertIsNone(module.reviewed_window(rows, 0, budget=2))

    def test_review_window_stops_at_large_silence(self):
        self.assertEqual(module.reviewed_window([(0, 4, "one"), (30, 35, "two")], 0),
                         (0, 4, "one"))

    def setUp(self):
        self.source = "55 minute cut of prominent topics. Must have aired in 2025. Remove Dr. Phil and MS-MNML25-0408."
        self.brief = dict(objective="prominent topics", searches=["major news interviews"],
                          air_year=2025, excluded_people=["Dr. Phil"],
                          excluded_sources=["MS-MNML25-0408"], target_seconds=3300,
                          edit_requested=True, rebuild=True)

    def test_contract(self):
        self.assertEqual(module.parse_brief(json.dumps(self.brief), self.source), self.brief)

    def test_identified_source_complaint_is_not_lost_by_model(self):
        source = self.source + "\nClip MS-MNML25-0408 is of Dr. Phil speaking, why didn't you remove it?"
        result = module.parse_brief(json.dumps({**self.brief, "excluded_sources": []}), source)
        self.assertIn("MS-MNML25-0408", result["excluded_sources"])

    def test_null_model_year_cannot_drop_explicit_air_year(self):
        result = module.parse_brief(json.dumps({**self.brief, "air_year": None}), self.source)
        self.assertEqual(result["air_year"], 2025)

    def test_later_explicit_air_year_wins(self):
        result = module.parse_brief(json.dumps(self.brief), self.source + "\nActually use footage aired in 2026.")
        self.assertEqual(result["air_year"], 2026)

    def test_explicit_person_exclusion_survives_model_omission(self):
        result = module.parse_brief(json.dumps({**self.brief, "excluded_people": []}),
                                    self.source + "\nremove anything that has Dr. Phil in it")
        self.assertIn("Dr. Phil", result["excluded_people"])

    def test_reject_invented_constraints(self):
        for key, value in [("air_year", 2024), ("excluded_people", ["Another Person"]),
                           ("excluded_sources", ["unknown-id"]), ("target_seconds", -5),
                           ("searches", [])]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                module.parse_brief(json.dumps({**self.brief, key: value}), self.source)

    async def test_complaint_keeps_original_user_context(self):
        llm = AsyncMock(return_value=json.dumps(self.brief))
        result = await module.resolve_brief([self.source, "Why aren't you giving me a cut with those parameters?"], llm)
        self.assertEqual(result["target_seconds"], 3300)
        self.assertIn(self.source, llm.call_args.args[0])
        self.assertIn("not the year number", llm.call_args.kwargs["system"])

    async def test_does_not_silently_drop_old_instructions(self):
        llm = AsyncMock()
        with self.assertRaises(ValueError):
            await module.resolve_brief(["x" * 64001], llm)
        llm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
