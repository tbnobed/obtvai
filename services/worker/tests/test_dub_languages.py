"""Dependency-light language routing coverage for dubbing and voice synthesis.

The worker image has the real model dependencies, but this suite deliberately
loads only the routing constants/functions from dub.py.  It therefore catches
menu/API drift and engine-language boundary regressions on an ordinary Python
test runner without importing Celery, torch, XTTS, or Chatterbox.
"""

import ast
import os
from pathlib import Path
import re
import types
import unittest
from unittest.mock import patch


WORKER_ROOT = Path(__file__).resolve().parents[1]
DUB_PATH = WORKER_ROOT / "tasks" / "dub.py"
CHATTERBOX_V3_PATH = WORKER_ROOT / "tasks" / "chatterbox_v3.py"
VOICE_PATH = WORKER_ROOT / "tasks" / "voice.py"
API_MEDIA_PATH = WORKER_ROOT.parent / "api" / "app" / "routers" / "media.py"
FRONTEND_ASSET_PATH = (
    WORKER_ROOT.parent.parent / "artifacts" / "frontend" / "src"
    / "pages" / "asset-detail.tsx"
)
MOCK_API_PATH = (
    WORKER_ROOT.parent.parent / "artifacts" / "api-server" / "src"
    / "routes" / "mock.ts"
)
ROUTING_ASSIGNMENTS = {"MMS_LANG_CODES", "XTTS_LANGS", "CHATTERBOX_LANGS"}
ROUTING_FUNCTIONS = {
    "_normalize_language_code", "_to_xtts_lang", "_to_chatterbox_lang",
    "_resolve_dub_route",
}


def _load_routing_module():
    """Execute only dependency-free routing nodes from the production module."""
    tree = ast.parse(DUB_PATH.read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        names = set()
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {target.id for target in targets if isinstance(target, ast.Name)}
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = {node.name}
        if names & (ROUTING_ASSIGNMENTS | ROUTING_FUNCTIONS):
            nodes.append(node)

    module = types.ModuleType("dub_routing")
    module.__dict__["os"] = os
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(DUB_PATH), "exec"),
         module.__dict__)
    return module


def _source_set(path: Path, name: str) -> set[str]:
    """Read one literal set assignment without importing its production module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name
                   for target in node.targets):
            continue
        value_node = node.value
        # chatterbox_v3 wraps its literal in frozenset(...).
        if (
            isinstance(value_node, ast.Call)
            and isinstance(value_node.func, ast.Name)
            and value_node.func.id == "frozenset"
        ):
            value_node = value_node.args[0]
        value = ast.literal_eval(value_node)
        return set(value)
    raise AssertionError(f"{name} assignment not found in {path}")


def _frontend_menu_languages() -> set[str]:
    source = FRONTEND_ASSET_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"const\s+TRANSLATION_LANGUAGES\b[^=]*=\s*\[(.*?)\];",
        source,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError("TRANSLATION_LANGUAGES menu not found in frontend")
    return set(re.findall(r'\bcode:\s*"([a-z]{2})"', match.group(1)))


def _mock_supported_languages() -> set[str]:
    source = MOCK_API_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"const\s+SUPPORTED_LANGS\s*=\s*\[(.*?)\];",
        source,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError("SUPPORTED_LANGS gate not found in mock API")
    return set(re.findall(r'"([a-z]{2})"', match.group(1)))


class DubLanguageRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_routing_module()
        cls.menu_languages = _frontend_menu_languages()

    def test_frontend_menu_matches_production_and_mock_gates(self):
        frontend_source = FRONTEND_ASSET_PATH.read_text(encoding="utf-8")
        mock_source = MOCK_API_PATH.read_text(encoding="utf-8")
        api_languages = _source_set(API_MEDIA_PATH, "SUPPORTED_DUB_LANGUAGES")
        self.assertEqual(self.menu_languages, api_languages)
        self.assertEqual(self.menu_languages, _mock_supported_languages())
        self.assertRegex(
            frontend_source,
            r"const\s+DUB_LANGUAGES\s*=\s*TRANSLATION_LANGUAGES\.map\(\s*\(\{\s*code\s*\}\)\s*=>\s*code\s*\)",
        )
        self.assertRegex(mock_source, r"const\s+DUB_LANGS\s*=\s*SUPPORTED_LANGS\s*;")

    def test_every_menu_language_has_worker_and_chatterbox_routes(self):
        chatterbox_v3_languages = _source_set(
            CHATTERBOX_V3_PATH, "SUPPORTED_LANGUAGES"
        )
        self.assertTrue(self.menu_languages <= self.mod.XTTS_LANGS)
        self.assertTrue(self.menu_languages <= self.mod.CHATTERBOX_LANGS)
        self.assertTrue(self.menu_languages <= chatterbox_v3_languages)
        for language in sorted(self.menu_languages):
            with self.subTest(language=language):
                route = self.mod._resolve_dub_route(language)
                self.assertEqual(route["engine"], "xtts-stock")
                self.assertIsNotNone(route["xtts"])
                self.assertIsNotNone(route["chatterbox"])

    def test_normalization_keeps_menu_code_but_maps_engine_locales(self):
        self.assertEqual(self.mod._normalize_language_code("  ZH_CN "), "zh-cn")
        self.assertEqual(self.mod._normalize_language_code(" PT "), "pt")
        self.assertEqual(self.mod._to_xtts_lang(" zh "), "zh-cn")
        self.assertEqual(self.mod._to_chatterbox_lang(" zh-cn "), "zh")
        route = self.mod._resolve_dub_route("  ZH ")
        self.assertEqual(route["target"], "zh")
        self.assertEqual(route["xtts"], "zh-cn")
        self.assertEqual(route["chatterbox"], "zh")

    def test_default_cloned_route_uses_chatterbox_v3_for_every_menu_language(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DUB_ENGINE", None)
            for language in sorted(self.menu_languages):
                with self.subTest(language=language):
                    route = self.mod._resolve_dub_route(language, cloned_voice=True)
                    self.assertEqual(route["engine"], "chatterbox-clone")
                    self.assertEqual(route["chatterbox"], language)

    def test_explicit_xtts_clone_is_not_silently_routed_to_chatterbox(self):
        with patch.dict(os.environ, {"DUB_ENGINE": "xtts"}):
            for language in sorted(self.menu_languages):
                with self.subTest(language=language):
                    route = self.mod._resolve_dub_route(language, cloned_voice=True)
                    self.assertEqual(route["engine"], "xtts-clone")
                    expected = "zh-cn" if language == "zh" else language
                    self.assertEqual(route["xtts"], expected)

    def test_voice_worker_keeps_the_same_chinese_boundary(self):
        voice_source = VOICE_PATH.read_text(encoding="utf-8")
        self.assertIn("from tasks.dub import _to_xtts_lang", voice_source)
        self.assertIn("synthesize_cloned(tts, text_value, xtts_language", voice_source)


if __name__ == "__main__":
    unittest.main()