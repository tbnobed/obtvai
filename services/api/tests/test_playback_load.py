"""Offline load-harness guardrails; fake transport, never sends real traffic."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("playback_load", ROOT / "scripts" / "playback-load.py")
load = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = load
spec.loader.exec_module(load)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ids = Path(self.temp.name) / "ids.json"
        self.ids.write_text(json.dumps(["actual-test-asset"]))
        self.argv = [
            "--target", "http://authorized.example:5000", "--max-users", "500",
            "--max-duration", "600", "--scenario", "same", "--media-ids", str(self.ids),
            "--search-query", "real query",
        ]

    def tearDown(self):
        self.temp.cleanup()

    def args(self, extra=()):
        return load.parser().parse_args(self.argv + list(extra))

    def test_dry_run_requires_no_credentials_or_httpx(self):
        args = load.validate(self.args())
        self.assertFalse(args.execute)
        self.assertEqual(args.stages, (100, 250, 500))
        self.assertEqual(args.ids, ["actual-test-asset"])

    def test_execute_requires_exact_acknowledged_origin(self):
        for extra in [
            ["--execute"],
            ["--execute", "--ack-target", "http://other.example:5000"],
        ]:
            with self.assertRaises(ValueError):
                load.validate(self.args(extra))
        self.assertTrue(load.validate(self.args([
            "--execute", "--ack-target", "http://authorized.example:5000",
        ])).execute)

    def test_target_cannot_carry_credentials_or_query(self):
        for target in ["http://user:secret@example.com", "http://example.com?token=x",
                       "https://example.com/api", "file:///tmp/file", "http://example.com#secret"]:
            with self.assertRaises(ValueError):
                load.origin(target)

    def test_hard_limits_and_controlled_ramp(self):
        for extra in [
            ["--max-users", "501"], ["--max-users", "250"], ["--max-duration", "1801"],
            ["--max-duration", "100"], ["--stage-seconds", "500"],
            ["--ramp-seconds", "1"], ["--stages", "500"], ["--background-users", "21"],
            ["--browse-interval", "1"], ["--seek-interval", "1"],
            ["--search-interval", "1"], ["--timeout", "31"],
        ]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                load.validate(self.args(extra))

    def test_distinct_requires_distinct_real_ids(self):
        with self.assertRaises(ValueError):
            load.validate(self.args(["--scenario", "distinct"]))
        self.ids.write_text(json.dumps(["same", "same"]))
        with self.assertRaises(ValueError):
            load.read_ids(self.ids)
        self.ids.write_text(json.dumps(["../../escape"]))
        with self.assertRaises(ValueError):
            load.read_ids(self.ids)

    def test_rolling_failure_abort_and_metrics(self):
        stats = load.Measurements()
        for n in range(20):
            stats.record("segment", "503" if n < 2 else "200", n / 10, 1000, n < 2)
        self.assertTrue(stats.unsafe())
        report = stats.report()
        self.assertEqual(report["counts"]["failures"], 2)
        self.assertEqual(report["failure_fraction"], .1)
        self.assertEqual(report["latency_seconds"]["segment"]["p95"], 1.8)

    def test_overlay_routes_only_exact_playback_paths(self):
        config = (ROOT / "nginx" / "playback.conf").read_text()
        import re
        pattern = re.search(r'location ~ "([^"]+)"', config)[1]
        for path in ["/api/media/a/playback", "/api/media/a/hls.m3u8", "/api/media/a/segments/0.ts"]:
            self.assertRegex(path, pattern)
        for path in ["/api/media/a/stream", "/api/media/a/download", "/api/search",
                     "/api/media/a/playback/extra", "/api/media/a/segments/-1.ts",
                     "/api/media/a/hlsXm3u8", "/api/media/a/highlight/stream"]:
            self.assertNotRegex(path, pattern)
        self.assertIn("proxy_max_temp_file_size 0;", config)
        overlay = (ROOT / "playback.compose.yml").read_text()
        self.assertNotIn("capabilities: [gpu]", overlay)
        self.assertNotIn("artifacts_data", overlay)
        self.assertNotIn("models_cache", overlay)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def harness(self, status=200, chunks=(b"\x47" + b"x" * 187,), headers=None):
        class Response:
            status_code = status
            async def aiter_bytes(self, _):
                for chunk in chunks:
                    yield chunk

        Response.headers = headers or {}

        class Context:
            async def __aenter__(self):
                return Response()

            async def __aexit__(self, *_):
                pass

        class Client:
            def stream(self, *_args, **_kwargs):
                return Context()

        from types import SimpleNamespace
        return load.Harness(SimpleNamespace(timeout=1), Client())

    async def test_paced_payload_discard_counts_bytes(self):
        harness = self.harness()
        body = await harness.request("segment", "GET", "/api/media/asset/segments/0.ts")
        self.assertEqual(body, b"")
        self.assertEqual(harness.stats.transferred["segment"], 188)
        self.assertEqual(harness.stats.counts["failures"], 0)

    async def test_incomplete_body_is_failure(self):
        harness = self.harness(headers={"content-length": "500"})
        self.assertIsNone(await harness.request("segment", "GET", "/api/media/asset/segments/0.ts"))
        self.assertEqual(harness.stats.codes["segment:incomplete"], 1)

    async def test_html_200_is_not_successful_video(self):
        harness = self.harness(chunks=(b"x" * 188,))
        self.assertIsNone(await harness.request("segment", "GET", "/api/media/asset/segments/0.ts"))
        self.assertEqual(harness.stats.codes["segment:invalid_mpegts"], 1)
        self.assertEqual(harness.stats.successful_transferred["segment"], 0)

    async def test_503s_halt_without_retry(self):
        harness = self.harness(status=503)
        for _ in range(20):
            await harness.request("segment", "GET", "/api/media/asset/segments/0.ts")
        self.assertTrue(harness.stop.is_set())
        self.assertEqual(harness.stats.counts["requests"], 20)

    async def test_segment_memory_limit(self):
        harness = self.harness(chunks=(b"12345",))
        with patch.object(load, "MAX_SEGMENT_BYTES", 4):
            self.assertIsNone(await harness.request("segment", "GET", "/api/media/asset/segments/0.ts"))
        self.assertEqual(harness.stats.codes["segment:oversize"], 1)

    async def test_timeout_after_200_headers_is_still_failure(self):
        def chunks():
            yield b"\x47" + b"x" * 187
            raise TimeoutError()
        harness = self.harness(chunks=chunks())
        self.assertIsNone(await harness.request("segment", "GET", "/api/media/asset/segments/0.ts"))
        self.assertEqual(harness.stats.counts["timeouts"], 1)
        self.assertEqual(harness.stats.counts["failures"], 1)
        self.assertEqual(harness.stats.successful_transferred["segment"], 0)


if __name__ == "__main__":
    unittest.main()