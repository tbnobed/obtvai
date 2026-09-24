import hashlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake_celery = types.SimpleNamespace(task=lambda **kw: lambda fn: fn)
        fake_base = types.SimpleNamespace(**{name: Mock() for name in (
            "update_job", "update_asset", "append_log", "create_job",
        )})
        location = Path(__file__).resolve().parents[1] / "tasks/catalog_media.py"
        spec = importlib.util.spec_from_file_location("catalog_media_under_test", location)
        cls.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "app": types.SimpleNamespace(celery_app=fake_celery),
            "db": types.SimpleNamespace(get_session=Mock()),
            "tasks.base": fake_base,
        }):
            spec.loader.exec_module(cls.module)

    def test_audio_validates_real_stream_metadata_without_copy_command(self):
        result = Mock(returncode=0, stdout=json.dumps({
            "streams": [{"codec_type": "audio", "codec_name": "pcm_s16le"}],
            "format": {"duration": "25.5"},
        }))
        with patch.object(self.module.subprocess, "run", return_value=result) as run:
            self.assertEqual(self.module.audio_metadata("/curator/audio.wav"), (25.5, "pcm_s16le"))
            self.assertEqual(run.call_args.args[0][0], "ffprobe")
            self.assertNotIn("-y", run.call_args.args[0])

    def test_non_audio_bad_duration_and_video_rejected(self):
        for streams, duration in [
            ([], "25"), ([{"codec_type": "audio"}], "NaN"),
            ([{"codec_type": "audio"}], "0"),
            ([{"codec_type": "audio"}, {"codec_type": "video"}], "25"),
        ]:
            result = Mock(returncode=0, stdout=json.dumps({"streams": streams, "format": {"duration": duration}}))
            with patch.object(self.module.subprocess, "run", return_value=result):
                with self.assertRaises(RuntimeError):
                    self.module.audio_metadata("/curator/test")

    def test_image_analysis_thumbnail_preserves_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            Image.new("RGB", (1600, 800), (30, 100, 200)).save(source)
            original_hash = hashlib.sha256(source.read_bytes()).digest()
            output = root / "thumbnails"
            with patch.dict(sys.modules, {"config": types.SimpleNamespace(THUMBNAILS_DIR=str(output))}):
                result = self.module.prepare_image(str(source), "asset1")
            self.assertEqual(result[:3], (1600, 800, "PNG"))
            self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), original_hash)
            with Image.open(output / result[3]) as thumbnail:
                self.assertEqual(thumbnail.size, (1280, 640))
            self.assertEqual([p.name for p in output.iterdir()], ["asset1_image.jpg"])

    def test_animated_image_explicitly_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "animated.gif"
            Image.new("RGB", (10, 10), "red").save(
                source, save_all=True, append_images=[Image.new("RGB", (10, 10), "blue")],
                duration=100, loop=0,
            )
            with patch.dict(sys.modules, {"config": types.SimpleNamespace(THUMBNAILS_DIR=str(root / "out"))}):
                with self.assertRaisesRegex(RuntimeError, "Animated/multipage"):
                    self.module.prepare_image(str(source), "asset")
            self.assertFalse((root / "out").exists())