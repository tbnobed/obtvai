import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.catalog_storage import mount_for, require_archive_storage


class StorageTests(unittest.TestCase):
    def test_root_artifacts_local_but_children_cifs(self):
        info = (
            "1 0 0:1 / / rw - overlay overlay rw\n"
            "2 1 0:2 / /artifacts rw - ext4 /dev/local rw\n"
            "3 2 0:3 /audio /artifacts/audio rw - cifs //server/ipv rw\n"
            "4 2 0:3 /thumbnails /artifacts/thumbnails rw - cifs //server/ipv rw\n"
        )
        self.assertEqual(mount_for("/artifacts", info)[0], "ext4")
        self.assertEqual(mount_for("/artifacts/audio/test.wav", info)[0], "cifs")
        self.assertEqual(mount_for("/artifacts/thumbnails/a.jpg", info)[0], "cifs")
        self.assertEqual(mount_for("/artifacts/audio-not-mounted", info)[0], "ext4")

    def test_disabled_mode_never_probes_filesystem(self):
        with patch.dict(os.environ, {"CURATOR_ARCHIVE_MODE": "0"}), patch.object(Path, "read_text") as read:
            with self.assertRaisesRegex(RuntimeError, "CURATOR_ARCHIVE_MODE"):
                require_archive_storage()
            read.assert_not_called()

    def test_actual_child_write_read_probe_and_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("source", "audio", "thumbnails"):
                (root / name).mkdir()
            info = (
                "1 0 0:1 / / rw - overlay overlay rw\n"
                f"2 1 0:2 / {root / 'source'} ro - cifs //server/proxy rw\n"
                f"3 1 0:3 /audio {root / 'audio'} rw - cifs //server/derived rw\n"
                f"4 1 0:3 /thumbnails {root / 'thumbnails'} rw - cifs //server/derived rw\n"
            )
            env = {"CURATOR_ARCHIVE_MODE": "1", "CURATOR_ARCHIVE_ROOTS": str(root / "source"),
                   "AUDIO_DIR": str(root / "audio"), "THUMBNAILS_DIR": str(root / "thumbnails")}
            with patch.dict(os.environ, env), patch.object(Path, "read_text", return_value=info):
                self.assertEqual(len(require_archive_storage()), 2)
            for name in ("source", "audio", "thumbnails"):
                self.assertEqual(list((root / name).iterdir()), [])
            with patch.dict(os.environ, env), patch.object(Path, "read_text", return_value=info.replace(" - cifs ", " - ext4 ")):
                with self.assertRaisesRegex(RuntimeError, "read-only CIFS"):
                    require_archive_storage()
            with patch.dict(os.environ, env), patch.object(Path, "read_text", return_value=info), \
                    patch("app.catalog_storage.tempfile.NamedTemporaryFile", side_effect=PermissionError("SMB ACL denies write")):
                with self.assertRaisesRegex(PermissionError, "SMB ACL"):
                    require_archive_storage()

    def test_worker_and_api_guards_identical(self):
        workspace = Path(__file__).resolve().parents[3]
        self.assertEqual((workspace / "services/api/app/catalog_storage.py").read_text(),
                         (workspace / "services/worker/catalog_storage.py").read_text())