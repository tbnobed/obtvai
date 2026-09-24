"""Validate deliberate empty curation without loading models or touching media."""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class CreativeEmptyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake_celery = types.SimpleNamespace(task=lambda **kw: lambda fn: fn)
        spec = importlib.util.spec_from_file_location(
            "creative_under_test", Path(__file__).resolve().parents[1] / "tasks/creative.py")
        cls.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "app": types.SimpleNamespace(celery_app=fake_celery),
            "db": types.SimpleNamespace(get_session=Mock()),
            "tasks.base": types.SimpleNamespace(update_job=Mock(), append_log=Mock()),
            "config": types.SimpleNamespace(LLM_MODEL="test"),
        }):
            spec.loader.exec_module(cls.module)

    def test_valid_empty_is_not_a_failure(self):
        self.assertTrue(self.module._deliberately_empty(
            True, {"logline": "Insufficient spoken material", "story_beats": [], "editorial_notes": []}))

    def test_failed_or_nonempty_map_cannot_become_empty_success(self):
        self.assertFalse(self.module._deliberately_empty(
            False, {"logline": "No arc", "story_beats": [], "editorial_notes": []}))

    def test_malformed_reduce_remains_failure(self):
        for payload in (None, [], {}, {"story_beats": [], "editorial_notes": []},
                        {"logline": "No arc", "story_beats": None, "editorial_notes": []},
                        {"logline": "No arc", "story_beats": [], "editorial_notes": "invalid"},
                        {"logline": "No arc", "story_beats": [], "editorial_notes": [{}]}):
            self.assertFalse(self.module._deliberately_empty(True, payload))

    def test_nonempty_but_rejected_beats_cannot_become_empty_success(self):
        self.assertFalse(self.module._deliberately_empty(
            True, {"logline": "Arc", "story_beats": [{}], "editorial_notes": []}))

    def run_pass(self, first):
        statements = []
        def execute(query, params):
            statements.append((str(query), params))
            return Mock(fetchall=lambda: [(0.3, "speaker", "[music]")],
                        fetchone=lambda: (None,) if "synopsis" in str(query) else (115.7,))
        db = Mock(execute=execute)
        analysis = types.SimpleNamespace(
            _load_llm=lambda: (None, None),
            _generate=Mock(side_effect=[first, json.dumps({
                "logline": "No spoken narrative", "story_beats": [], "editorial_notes": []})]),
            _extract_json=json.loads, _build_chunks=lambda rows: [("[music]", 0.3, 115.7)],
            _format_timecode=str, _timecode_to_seconds=float,
            CREATIVE_PERSONA="", EDITOR_RULES="",
        )
        with patch.dict(sys.modules, {"tasks.analyze": analysis}), \
                patch.object(self.module, "get_session", return_value=db), \
                patch.object(self.module, "update_job") as update:
            self.module.creative_pass(types.SimpleNamespace(request=types.SimpleNamespace(id="task")), "media", "job")
            return statements, update

    def test_stage_persists_truthful_empty_reason_and_success(self):
        statements, update = self.run_pass(json.dumps({"clips": [], "segment_note": "Only music"}))
        result = json.loads(next(params["c"] for query, params in statements if query.startswith("UPDATE")))
        self.assertEqual(result["outcome"], "no_suggestions")
        self.assertEqual(result["clip_suggestions"], [])
        self.assertIn("model selected no qualifying", result["empty_reason"])
        self.assertEqual(update.call_args.kwargs["status"], "success")

    def test_stage_parse_failure_is_not_empty_success(self):
        with self.assertRaisesRegex(RuntimeError, "no usable output"):
            self.run_pass("unparseable")