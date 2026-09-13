"""Exercise actual FFmpeg sample preparation without a database or GPU."""
import ast
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


TASKS = Path(__file__).resolve().parents[1] / "tasks"


def load_sample_functions():
    # Only omit worker startup/model imports; execute the actual sample functions.
    tree = ast.parse((TASKS / "voice.py").read_text())
    names = {"_probe_duration", "_sample_audio_inputs", "prepare_voice_sample"}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in functions:
        node.decorator_list = []
    module = types.ModuleType("sample_test")
    module.__dict__.update(os=os, json=json, subprocess=subprocess, contextlib=contextlib, SAMPLE_RATE=24000)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(TASKS / "voice.py"), "exec"), module.__dict__)
    return module


class VoiceSampleAudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.voice = load_sample_functions()
        self.voice.VOICES_DIR = str(self.root / "voices")
        spec = importlib.util.spec_from_file_location("tasks.curator", TASKS / "curator.py")
        curator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(curator)
        sqlalchemy = types.ModuleType("sqlalchemy")
        sqlalchemy.text = lambda sql: sql
        modules = patch.dict(sys.modules, {"tasks.curator": curator, "sqlalchemy": sqlalchemy})
        modules.start()
        self.addCleanup(modules.stop)

    def ffmpeg(self, *args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True)

    def prepare(self, source, path):
        db = Mock()
        db.execute.return_value.fetchone.side_effect = [
            (source, "asset", 1, 3, str(path) if source == "upload" else None),
            (str(path),),
        ]
        self.voice.get_session = lambda: db
        self.voice._update_sample = Mock()
        self.voice.prepare_voice_sample(None, "sample")
        update = self.voice._update_sample.call_args.kwargs
        self.assertEqual(update["status"], "ready")
        self.assertTrue(Path(update["audio_path"]).is_file())
        self.assertGreater(update["duration_seconds"], 1)
        return update

    def test_split_curator_audio_is_cut_and_mixed(self):
        video = self.root / "clip_video.mp4"
        self.ffmpeg("-f", "lavfi", "-i", "color=s=16x16:d=4", "-an", str(video))
        for index, freq in enumerate((440, 660)):
            self.ffmpeg("-f", "lavfi", "-i", f"sine=frequency={freq}:duration=4",
                        "-c:a", "aac", str(self.root / f"clip_audio{index}.mp4"))
        update = self.prepare("segment", video)
        self.assertLess(update["duration_seconds"], 2.2)

    def test_uploaded_audio_still_normalizes(self):
        audio = self.root / "upload.wav"
        self.ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(audio))
        self.prepare("upload", audio)

    def test_missing_sidecar_has_actionable_error(self):
        video = self.root / "clip_video.mp4"
        self.ffmpeg("-f", "lavfi", "-i", "color=s=16x16:d=2", "-an", str(video))
        with self.assertRaisesRegex(RuntimeError, "no Curator audio sidecars"):
            self.prepare("segment", video)
        self.assertEqual(self.voice._update_sample.call_args.kwargs["status"], "error")


if __name__ == "__main__":
    unittest.main()