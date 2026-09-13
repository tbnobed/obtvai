"""Exercise production timing code without loading GPU models."""
import ast
import math
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import types
import unittest
import wave
from unittest.mock import Mock


class Clip:
    def __init__(self, size):
        self.size = size


def load_timing():
    path = Path(__file__).resolve().parents[1] / "tasks" / "dub.py"
    tree = ast.parse(path.read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name in {"_fit_dub_clip", "_atempo", "_spoken_dub_rows"}]
    module = types.ModuleType("timing")
    constants = [n for n in tree.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id in
                         {"_MAX_ATEMPO", "_MAX_ATEMPO_FORCE", "_MAX_LATENESS_S"}
                         for t in n.targets)]
    module.__dict__.update(os=os, subprocess=subprocess)
    with unittest.mock.patch.dict(os.environ, {"DUB_MAX_LATENESS": "1.5"}):
        exec(compile(ast.Module(body=constants, type_ignores=[]), str(path), "exec"),
             module.__dict__)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"),
         module.__dict__)
    return module


class DubTimingTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_timing()
        self.mod._atempo = Mock(side_effect=lambda c, sr, f, wd: Clip(math.ceil(c.size / f)))

    def fit(self, size, start=0, next_start=2, duration=10, cursor=0):
        return self.mod._fit_dub_clip(Clip(size), 1000, start, next_start, duration, cursor, "/tmp")

    def test_short_clip_unchanged(self):
        clip, offset, forced = self.fit(1000)
        self.assertEqual((clip.size, offset, forced), (1000, 0, False))
        self.mod._atempo.assert_not_called()

    def test_blank_translation_does_not_shorten_speech_window(self):
        rows = self.mod._spoken_dub_rows([
            (0, 1, "Hola", "A"), (1, 2, "  ", "A"),
            (2, 3, "", "A"), (8, 10, "Adiós", "A"),
        ])
        self.assertEqual(len(rows), 2)
        clip, offset, _ = self.fit(6000, next_start=rows[1][0])
        self.assertEqual((clip.size, offset), (6000, 0))

    def test_dense_dialogue_has_no_drop_or_overlap(self):
        cursor = 0
        for start in range(29):
            clip, offset, _ = self.fit(1300, start, start + 1, 29, cursor)
            self.assertGreaterEqual(offset, cursor)
            cursor = offset + clip.size
            self.assertLessEqual(cursor, min(29, start + 2.5) * 1000)

    def test_previously_dropped_late_clip_is_fitted(self):
        clip, offset, forced = self.fit(1800, start=2, next_start=4, cursor=3900)
        self.assertEqual(offset, 3900)
        self.assertLessEqual(offset + clip.size, 5500)

    def test_impossible_clip_fails_instead_of_dropping(self):
        with self.assertRaisesRegex(RuntimeError, "no words were trimmed"):
            self.fit(12000)

    def test_reported_193x_segment_fits(self):
        clip, offset, forced = self.fit(
            5790, start=61.32, next_start=62.82, duration=70)
        self.assertTrue(forced)
        self.assertEqual(offset, 61320)
        self.assertLessEqual(offset + clip.size, 64320)
        # Decimal timestamps may lose one sample when converted to integers.
        self.assertAlmostEqual(self.mod._atempo.call_args.args[2], 1.93, delta=0.001)

    def test_no_room_fails_instead_of_dropping(self):
        with self.assertRaisesRegex(RuntimeError, "no segment was dropped"):
            self.fit(1000, start=10, next_start=10, duration=10, cursor=10000)

    def test_last_segment_does_not_run_past_video(self):
        clip, offset, forced = self.fit(1500, start=9, next_start=10, duration=10)
        self.assertTrue(forced)
        self.assertLessEqual(offset + clip.size, 10000)

    def test_ffmpeg_duration_rounding_retries_original(self):
        self.mod._atempo.side_effect = [Clip(1010), Clip(995)]
        self.fit(1500, start=9, next_start=10, duration=10)
        calls = self.mod._atempo.call_args_list
        self.assertIs(calls[0].args[0], calls[1].args[0])

    def test_real_ffmpeg_preserves_tail_audio(self):
        mod = load_timing()
        rate = 24000

        def write(path, clip, sample_rate):
            # Distinct audible tail checks that fitting processes the whole clip.
            with wave.open(path, "wb") as wf:
                wf.setparams((1, 2, sample_rate, 0, "NONE", "not compressed"))
                wf.writeframes(b"".join(struct.pack("<h", int(9000 * math.sin(
                    2 * math.pi * (440 if i < clip.size * .75 else 880) * i / sample_rate
                ))) for i in range(clip.size)))

        def read(path):
            with wave.open(path, "rb") as wf:
                count = wf.getnframes()
                raw = wf.readframes(count)
                pcm = struct.unpack(f"<{count}h", raw)
                self.assertGreater(max(abs(x) for x in pcm[-2400:]), 1000)
                return Clip(count), wf.getframerate()

        mod._write_wav, mod._read_wav = write, read
        for factor in (1.5, 1.93, 2.3):
            with self.subTest(factor=factor), tempfile.TemporaryDirectory() as wd:
                clip, offset, forced = mod._fit_dub_clip(
                    Clip(round(rate * factor)), rate, 9, 10, 10, 0, wd)
                self.assertTrue(forced)
                self.assertLessEqual(offset + clip.size, 10 * rate)


if __name__ == "__main__":
    unittest.main()