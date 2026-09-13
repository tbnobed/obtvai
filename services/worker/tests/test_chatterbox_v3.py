"""Focused tests for the pinned Chatterbox V3 loader.

These tests exercise manifest/cache behavior with ordinary files and mocks;
they never import torch, the isolated runtime, or a GPU model.
"""

from pathlib import Path
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "tasks" / "chatterbox_v3.py"
SPEC = importlib.util.spec_from_file_location("chatterbox_v3_under_test", MODULE_PATH)
chatterbox_v3 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = chatterbox_v3
SPEC.loader.exec_module(chatterbox_v3)


class ChatterboxV3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hf_home = Path(self.tmp.name) / "huggingface"
        self.sources = Path(self.tmp.name) / "hub-files"
        self.sources.mkdir()
        self.addCleanup(self.tmp.cleanup)

        # Do not retain lazy-loaded dependencies between tests.
        chatterbox_v3.FileLock = None
        chatterbox_v3.hf_hub_download = None
        chatterbox_v3.ChatterboxTTS = None

        class TestLock:
            def __init__(self, _path):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        # filelock is a worker-image dependency; keep this focused suite
        # runnable in the minimal repository test environment.
        chatterbox_v3.FileLock = TestLock

    def _downloader(self):
        calls = []

        def download(*, repo_id, filename, revision, **kwargs):
            calls.append(
                {
                    "repo_id": repo_id,
                    "filename": filename,
                    "revision": revision,
                    **kwargs,
                }
            )
            source = self.sources / f"{revision}-{filename}"
            source.write_bytes(f"{repo_id}:{filename}".encode())
            return str(source)

        return calls, download

    def test_routing_and_stable_revision_tags(self):
        self.assertIn(chatterbox_v3.ES_REVISION, chatterbox_v3.chatterbox_variant("es"))
        self.assertIn(chatterbox_v3.BASE_REVISION, chatterbox_v3.chatterbox_variant("en"))
        self.assertNotEqual(
            chatterbox_v3.chatterbox_variant("es"),
            chatterbox_v3.chatterbox_variant("en"),
        )
        self.assertIn(chatterbox_v3.ES_REVISION, chatterbox_v3.chatterbox_variant("es-MX"))
        self.assertIn(chatterbox_v3.BASE_REVISION, chatterbox_v3.chatterbox_variant("zh-cn"))

    def test_pinned_assets_are_routed_and_isolated(self):
        calls, download = self._downloader()
        with patch.dict(os.environ, {"HF_HOME": str(self.hf_home)}, clear=False), patch.object(
            chatterbox_v3, "hf_hub_download", side_effect=download
        ):
            es_dir = chatterbox_v3.prepare_chatterbox_v3("es")
            base_dir = chatterbox_v3.prepare_chatterbox_v3("fr")

        self.assertNotEqual(es_dir, base_dir)
        self.assertIn(chatterbox_v3.ES_REVISION, es_dir.name)
        self.assertIn(chatterbox_v3.BASE_REVISION, es_dir.name)
        self.assertIn(chatterbox_v3.BASE_REVISION, base_dir.name)

        es_calls = calls[:4]
        base_calls = calls[4:]
        self.assertEqual(
            {(c["repo_id"], c["filename"], c["revision"]) for c in es_calls},
            {
                (chatterbox_v3.ES_REPO_ID, chatterbox_v3.ES_T3_FILENAME, chatterbox_v3.ES_REVISION),
                (chatterbox_v3.ES_REPO_ID, chatterbox_v3.S3GEN_FILENAME, chatterbox_v3.ES_REVISION),
                (chatterbox_v3.ES_REPO_ID, chatterbox_v3.TOKENIZER_FILENAME, chatterbox_v3.ES_REVISION),
                (chatterbox_v3.BASE_REPO_ID, chatterbox_v3.VE_FILENAME, chatterbox_v3.BASE_REVISION),
            },
        )
        self.assertEqual(
            {(c["repo_id"], c["filename"], c["revision"]) for c in base_calls},
            {
                (chatterbox_v3.BASE_REPO_ID, chatterbox_v3.BASE_T3_FILENAME, chatterbox_v3.BASE_REVISION),
                (chatterbox_v3.BASE_REPO_ID, chatterbox_v3.S3GEN_FILENAME, chatterbox_v3.BASE_REVISION),
                (chatterbox_v3.BASE_REPO_ID, chatterbox_v3.TOKENIZER_FILENAME, chatterbox_v3.BASE_REVISION),
                (chatterbox_v3.BASE_REPO_ID, chatterbox_v3.VE_FILENAME, chatterbox_v3.BASE_REVISION),
            },
        )
        self.assertFalse(any(c["filename"] == "conds.pt" for c in calls))

        for directory, t3_name, repo_revision in (
            (es_dir, chatterbox_v3.ES_T3_FILENAME, chatterbox_v3.ES_REVISION),
            (base_dir, chatterbox_v3.BASE_T3_FILENAME, chatterbox_v3.BASE_REVISION),
        ):
            for name in (
                t3_name,
                chatterbox_v3.S3GEN_FILENAME,
                chatterbox_v3.VE_FILENAME,
                chatterbox_v3.TOKENIZER_FILENAME,
            ):
                path = directory / name
                self.assertTrue(path.is_symlink(), name)
                self.assertTrue(path.resolve().is_file(), name)
            self.assertIn(repo_revision, (directory / t3_name).resolve().name)

        self.assertNotEqual(
            (es_dir / chatterbox_v3.TOKENIZER_FILENAME).resolve(),
            (base_dir / chatterbox_v3.TOKENIZER_FILENAME).resolve(),
        )

    def test_existing_snapshot_is_not_overwritten(self):
        calls, download = self._downloader()
        with patch.dict(os.environ, {"HF_HOME": str(self.hf_home)}, clear=False), patch.object(
            chatterbox_v3, "hf_hub_download", side_effect=download
        ):
            directory = chatterbox_v3.prepare_chatterbox_v3("es")
            links_before = {
                name: os.readlink(directory / name)
                for name, _, _ in chatterbox_v3._expected_inputs(chatterbox_v3._ES_VARIANT)
            }
            result = chatterbox_v3.prepare_chatterbox_v3("es")

        self.assertEqual(directory, result)
        self.assertEqual(len(calls), 4)
        self.assertEqual(
            links_before,
            {
                name: os.readlink(directory / name)
                for name, _, _ in chatterbox_v3._expected_inputs(chatterbox_v3._ES_VARIANT)
            },
        )

    def test_invalid_existing_snapshot_is_not_repaired(self):
        variant = chatterbox_v3._ES_VARIANT
        root = self.hf_home / "obtv-chatterbox-v3"
        destination = root / variant.cache_name
        destination.mkdir(parents=True)
        sentinel = destination / variant.t3_filename
        sentinel.write_text("sentinel")

        with patch.dict(os.environ, {"HF_HOME": str(self.hf_home)}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "incomplete or invalid"):
                chatterbox_v3.prepare_chatterbox_v3("es")
        self.assertTrue(sentinel.is_file())
        self.assertEqual(sentinel.read_text(), "sentinel")

    def test_load_calls_official_class_and_sets_model_id(self):
        directory = Path(self.tmp.name) / "assembled"
        model = types.SimpleNamespace()
        model_class = Mock()
        model_class.from_local.return_value = model
        with patch.object(
            chatterbox_v3, "_assemble_variant", return_value=directory
        ) as assemble, patch.object(
            chatterbox_v3, "_get_chatterbox_tts", return_value=model_class
        ):
            result = chatterbox_v3.load_chatterbox_v3("cpu", "es")

        self.assertIs(result, model)
        assemble.assert_called_once_with(chatterbox_v3._ES_VARIANT)
        model_class.from_local.assert_called_once_with(
            directory,
            "cpu",
            t3_filename=chatterbox_v3.ES_T3_FILENAME,
            s3gen_filename="s3gen_v3.pt",
        )
        self.assertEqual(model.obtv_model_id, chatterbox_v3.chatterbox_variant("es"))

    def test_download_and_model_errors_propagate(self):
        download_error = OSError("hub unavailable")
        with patch.dict(os.environ, {"HF_HOME": str(self.hf_home)}, clear=False), patch.object(
            chatterbox_v3, "hf_hub_download", side_effect=download_error
        ):
            with self.assertRaises(OSError) as raised:
                chatterbox_v3.prepare_chatterbox_v3("en")
            self.assertIs(raised.exception, download_error)

        model_error = RuntimeError("checkpoint incompatible")
        model_class = Mock()
        model_class.from_local.side_effect = model_error
        with patch.object(
            chatterbox_v3, "_assemble_variant", return_value=Path(self.tmp.name)
        ), patch.object(
            chatterbox_v3, "_get_chatterbox_tts", return_value=model_class
        ):
            with self.assertRaises(RuntimeError) as raised:
                chatterbox_v3.load_chatterbox_v3("cpu", "en")
            self.assertIs(raised.exception, model_error)


if __name__ == "__main__":
    unittest.main()