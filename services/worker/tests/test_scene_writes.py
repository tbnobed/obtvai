"""Regression coverage for concurrent embedding and caption scene writes."""
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tasks.scene_writes import write_scene_result


class _PgDeadlock(Exception):
    pgcode = "40P01"


def _error(code=None):
    cause = _PgDeadlock() if code == "40P01" else Exception("connection broken")
    return OperationalError("UPDATE scenes", {}, cause)


class SceneWritesTests(unittest.TestCase):
    def test_deadlock_rolls_back_then_retries_only_the_write(self):
        db = Mock()
        db.execute.side_effect = [_error("40P01"), _error("40P01"), Mock(rowcount=1)]
        with patch("tasks.scene_writes.time.sleep") as sleep:
            self.assertTrue(write_scene_result(db, "scene", "description", "real caption", only_empty=True))
        self.assertEqual(db.rollback.call_count, 2)
        db.commit.assert_called_once()
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(db.execute.call_count, 3)
        for call in db.execute.call_args_list:
            self.assertEqual(call.args[1], {"value": "real caption", "sid": "scene"})
            self.assertIn("description IS NULL", str(call.args[0]))

    def test_only_deadlocks_retry_and_exhaustion_fails_loudly(self):
        db = Mock()
        db.execute.side_effect = _error()
        with self.assertRaises(OperationalError):
            write_scene_result(db, "scene", "embedding_id", "scene")
        db.rollback.assert_called_once()
        db.commit.assert_not_called()
        db.reset_mock()
        db.execute.side_effect = _error("40P01")
        with patch("tasks.scene_writes.time.sleep"):
            with self.assertRaises(OperationalError):
                write_scene_result(db, "scene", "embedding_id", "scene")
        self.assertEqual(db.execute.call_count, 4)
        self.assertEqual(db.rollback.call_count, 4)
        db.commit.assert_not_called()

    def test_competing_captions_preserve_first_nonempty_result(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = create_engine(f"sqlite:///{temp}/scenes.db")
            with engine.begin() as conn:
                conn.execute(text(
                    "CREATE TABLE scenes (id TEXT PRIMARY KEY, description TEXT, embedding_id TEXT)"
                ))
                conn.execute(text("INSERT INTO scenes (id, description) VALUES ('scene', '')"))
            barrier = threading.Barrier(2)
            results = []
            errors = []

            def worker(caption):
                try:
                    with Session(engine) as db:
                        barrier.wait(timeout=5)
                        results.append(write_scene_result(
                            db, "scene", "description", caption, only_empty=True
                        ))
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(caption,))
                       for caption in ("Florence", "BAGEL")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertCountEqual(results, [True, False])
            with Session(engine) as db:
                self.assertIn(db.execute(text("SELECT description FROM scenes")).scalar(),
                              ("Florence", "BAGEL"))

    def test_embedding_and_caption_can_write_same_scenes_in_opposite_order(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = create_engine(f"sqlite:///{temp}/scenes.db")
            with engine.begin() as conn:
                conn.execute(text(
                    "CREATE TABLE scenes (id TEXT PRIMARY KEY, description TEXT, embedding_id TEXT)"
                ))
                conn.execute(text("INSERT INTO scenes (id) VALUES ('one'), ('two')"))
            barrier = threading.Barrier(2)
            errors = []

            def worker(column, ids):
                try:
                    with Session(engine) as db:
                        barrier.wait(timeout=5)
                        for scene_id in ids:
                            write_scene_result(db, scene_id, column, scene_id,
                                               only_empty=column == "description")
                except Exception as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(target=worker, args=("description", ("one", "two"))),
                threading.Thread(target=worker, args=("embedding_id", ("two", "one"))),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            with Session(engine) as db:
                self.assertEqual(db.execute(text(
                    "SELECT id, description, embedding_id FROM scenes ORDER BY id"
                )).fetchall(), [("one", "one", "one"), ("two", "two", "two")])

    def test_invalid_column_rejected(self):
        with self.assertRaises(ValueError):
            write_scene_result(Mock(), "scene", "status", "success")


if __name__ == "__main__":
    unittest.main()