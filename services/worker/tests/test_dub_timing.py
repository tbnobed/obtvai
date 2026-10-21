"""Exercise production timing code without loading GPU models."""
import ast
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import types
import sys
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
             and n.name in {"_fit_dub_clip", "_atempo", "_spoken_dub_rows", "_fit_or_regenerate", "_duration_adapt_text", "_group_dub_rows", "_plan_dub_room"}]
    module = types.ModuleType("timing")
    constants = [n for n in tree.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id in
                         {"_MAX_ATEMPO", "_MAX_ATEMPO_FORCE", "_MAX_LATENESS_S"}
                         for t in n.targets)]
    module.__dict__.update(os=os, subprocess=subprocess, math=math, json=json)
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

    def test_connected_phrases_share_a_window_without_losing_words(self):
        self.assertEqual(self.mod._group_dub_rows([
            (0, 2, "First", "A"), (2.1, 4, "second", "A"),
            (4.1, 6, "Another voice", "B"), (8, 9, "After silence", "B"),
        ]), [(0, 4, "First second", "A"), (4.1, 6, "Another voice", "B"),
             (8, 9, "After silence", "B")])

    def test_room_is_shared_backwards_without_overlap(self):
        placements = [
            {"start": 10, "offset": 10000, "audio": Clip(2000)},
            {"start": 12, "offset": 12000, "audio": Clip(3000)},
        ]
        self.assertEqual(self.mod._plan_dub_room(placements, 14000, 1000), [9000, 11000])
        self.assertEqual([p["offset"] for p in placements], [10000, 12000])

    def test_room_planner_never_exceeds_sync_budget(self):
        placements = [{"start": 10, "offset": 10000, "audio": Clip(3000)}]
        self.assertIsNone(self.mod._plan_dub_room(placements, 11000, 1000))
        self.assertEqual(placements[0]["offset"], 10000)

    def test_grouping_is_bounded_and_does_not_merge_unknown_speakers(self):
        rows = [(0, 14, "one", "A"), (14, 28, "two", "A"),
                (28, 29, "three", None), (29, 30, "four", None)]
        self.assertEqual(self.mod._group_dub_rows(rows), rows)

    def test_short_clip_unchanged(self):
        clip, offset, forced = self.fit(1000)
        self.assertEqual((clip.size, offset, forced), (1000, 0, False))
        self.mod._atempo.assert_not_called()

    def adapt(self, responses):
        remote = types.ModuleType("tasks.llm_remote")
        remote.remote_chat = Mock(side_effect=responses)
        translate = types.ModuleType("tasks.translate")
        translate._parse_llm_json = json.loads
        with unittest.mock.patch.dict(sys.modules, {
            "tasks.llm_remote": remote, "tasks.translate": translate,
        }):
            return self.mod._duration_adapt_text("Hello everyone", "Hola a todos ustedes", "es", 2)

    def test_adaptation_requires_independent_meaning_check(self):
        self.assertEqual(self.adapt([
            '{"text":"Hola a todos","meaning_preserved":true}', '{"equivalent":true}',
        ]), "Hola a todos")
        with self.assertRaisesRegex(RuntimeError, "meaning check"):
            self.adapt(['{"text":"Hola","meaning_preserved":true}', '{"equivalent":false}'])

    def test_impossible_or_malformed_adaptation_is_rejected(self):
        for reply in ('null', '[]', '{"text":null,"meaning_preserved":false}'):
            with self.subTest(reply=reply), self.assertRaisesRegex(RuntimeError, "timing review"):
                self.adapt([reply])

    def test_failed_audio_is_rejected_and_regenerated_once(self):
        bad, fresh = Clip(24000), Clip(8000)
        fit = Mock(side_effect=[RuntimeError("cannot fit"), ("fitted", 0, True)])
        regenerate, reject, save = Mock(return_value=fresh), Mock(), Mock()
        self.assertEqual(
            self.mod._fit_or_regenerate(bad, fit, regenerate, reject, save),
            ("fitted", 0, True),
        )
        regenerate.assert_called_once_with()
        reject.assert_called_once_with()
        save.assert_called_once_with(fresh)

    def test_failed_regeneration_is_not_cached_or_retried_forever(self):
        fit = Mock(side_effect=RuntimeError("cannot fit"))
        regenerate, reject, save = Mock(return_value=Clip(24000)), Mock(), Mock()
        with self.assertRaisesRegex(RuntimeError, "cannot fit"):
            self.mod._fit_or_regenerate(Clip(24000), fit, regenerate, reject, save)
        regenerate.assert_called_once_with()
        save.assert_not_called()

    def test_good_audio_never_regenerates(self):
        regenerate, reject, save = Mock(), Mock(), Mock()
        self.mod._fit_or_regenerate(Clip(1000), Mock(return_value=(Clip(1000), 0, False)),
                                    regenerate, reject, save)
        regenerate.assert_not_called()
        reject.assert_not_called()

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
            clip, offset, _ = self.fit(1100, start, start + 1, 29, cursor)
            self.assertGreaterEqual(offset, cursor)
            cursor = offset + clip.size
            self.assertLessEqual(cursor, min(29, start + 2.5) * 1000)

    def test_previously_dropped_late_clip_is_fitted(self):
        clip, offset, forced = self.fit(1700, start=2, next_start=4, cursor=3900)
        self.assertEqual(offset, 3900)
        self.assertLessEqual(offset + clip.size, 5500)

    def test_impossible_clip_fails_instead_of_dropping(self):
        with self.assertRaisesRegex(RuntimeError, "no words were trimmed"):
            self.fit(12000)

    def test_reported_193x_segment_requires_review(self):
        with self.assertRaisesRegex(RuntimeError, "no words were trimmed"):
            self.fit(5790, start=61.32, next_start=62.82, duration=70)

    def test_dense_dialogue_does_not_accumulate_avoidable_delay(self):
        cursor = 0
        for start in range(20):
            clip, offset, _ = self.fit(1100, start, start + 1, 21, cursor)
            cursor = offset + clip.size
            self.assertLessEqual(cursor, (start + 1) * 1000)

    def test_uses_free_lead_in_instead_of_spending_next_cues_time(self):
        clip, offset, _ = self.fit(3400, start=10, next_start=12, duration=20, cursor=8000)
        self.assertGreaterEqual(offset, 8500)
        self.assertLess(offset, 10000)
        self.assertLessEqual(offset + clip.size, 12001)  # one-sample rounding

    def test_short_final_cue_borrows_only_unoccupied_lead_in(self):
        clip, offset, _ = self.fit(2200, start=20.78, next_start=22.022, duration=22.022)
        self.assertGreaterEqual(offset, 19280)
        self.assertLess(offset, 20780)
        self.assertLessEqual(offset + clip.size, 22022)
        self.assertLessEqual(self.mod._atempo.call_args.args[2], 1.15)

    def test_lead_in_cannot_overlap_previous_dialogue(self):
        with self.assertRaisesRegex(RuntimeError, "no words were trimmed"):
            self.fit(5430, start=20.78, next_start=22.022, duration=22.022, cursor=20780)

    def test_no_room_fails_instead_of_dropping(self):
        with self.assertRaisesRegex(RuntimeError, "no segment was dropped"):
            self.fit(1000, start=10, next_start=10, duration=10, cursor=10000)

    def test_last_segment_does_not_run_past_video(self):
        clip, offset, forced = self.fit(1500, start=9, next_start=10, duration=10)
        self.assertLessEqual(self.mod._atempo.call_args.args[2], 1.15)
        self.assertLessEqual(offset + clip.size, 10000)

    def test_ffmpeg_duration_rounding_retries_original(self):
        self.mod._atempo.side_effect = [Clip(1010), Clip(995)]
        self.fit(1100, start=9, next_start=10, duration=10)
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
        for factor in (1.05, 1.10):
            with self.subTest(factor=factor), tempfile.TemporaryDirectory() as wd:
                clip, offset, forced = mod._fit_dub_clip(
                    Clip(round(rate * factor)), rate, 9, 10, 10, 0, wd)
                self.assertFalse(forced)
                self.assertLessEqual(offset + clip.size, 10 * rate)


if __name__ == "__main__":
    unittest.main()