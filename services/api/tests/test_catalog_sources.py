import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
from app.catalog_service import exact_nonvideo_source
from app.commands.import_curator_workbook import ImportFailure


class Sources(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.render = self.root / "render"
        self.render.mkdir()
        self.env = patch.dict(os.environ, {"CURATOR_PROXY_ROOT": str(self.root)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def audio(self):
        (self.render / "render.m3u8").write_text(
            '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,URI="render_audio0.m3u8"\n')
        (self.render / "render_audio0.m3u8").write_text(
            '#EXTM3U\n#EXT-X-MAP:URI="render_audio0.mp4"\nrender_audio0.mp4\n')
        (self.render / "render_audio0.mp4").write_bytes(b"test bytes")
        (self.render / "render_video.mp4").write_bytes(b"not the audio")

    def test_verified_audio_track_not_video(self):
        self.audio()
        self.assertEqual(exact_nonvideo_source(str(self.render), "Audio"),
                         str(self.render / "render_audio0.mp4"))

    def test_audio_rejects_multiple_tracks_wrong_prefix_and_escape(self):
        self.audio()
        for content in (
            '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,URI="render_audio0.m3u8"\n'
            '#EXT-X-MEDIA:TYPE=AUDIO,URI="render_audio1.m3u8"\n',
            '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,URI="other_audio0.m3u8"\n',
            '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,URI="../render_audio0.m3u8"\n',
        ):
            (self.render / "render.m3u8").write_text(content)
            with self.assertRaises(ImportFailure):
                exact_nonvideo_source(str(self.render), "Audio")

    def test_audio_rejects_mismatched_media_reference(self):
        self.audio()
        (self.render / "render_audio0.m3u8").write_text(
            '#EXTM3U\n#EXT-X-MAP:URI="render_audio0.mp4"\nrender_video.mp4\n')
        with self.assertRaises(ImportFailure):
            exact_nonvideo_source(str(self.render), "Audio")

    def test_single_same_basename_image_only(self):
        (self.render / "other.png").write_bytes(b"other")
        with self.assertRaises(ImportFailure):
            exact_nonvideo_source(str(self.render), "Image")
        (self.render / "render.png").write_bytes(b"image")
        self.assertEqual(exact_nonvideo_source(str(self.render), "Image"),
                         str(self.render / "render.png"))
        (self.render / "render.jpg").write_bytes(b"ambiguous")
        with self.assertRaises(ImportFailure):
            exact_nonvideo_source(str(self.render), "Image")

    def test_wrong_type_and_symlink_escape(self):
        self.audio()
        with self.assertRaises(ImportFailure):
            exact_nonvideo_source(str(self.render), "Image")
        outside = self.root / "outside.png"
        outside.write_bytes(b"image")
        (self.render / "render.png").symlink_to(outside)
        with self.assertRaises(ImportFailure):
            exact_nonvideo_source(str(self.render), "Image")