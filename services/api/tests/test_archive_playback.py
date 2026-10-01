"""Archive playback contract and real ffmpeg non-keyframe seek tests."""
import asyncio
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

# The production module imports its process-local reuse helper from app.
sys.path.insert(0, str(Path(__file__).parents[1]))
spec = importlib.util.spec_from_file_location(
    "archive_playback", Path(__file__).parents[1] / "app" / "playback.py",
)
playback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(playback)


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {
            "CURATOR_ARCHIVE_MODE": "true", "CURATOR_ARCHIVE_ROOTS": str(self.root),
        })
        self.env.start()
        self.mounts = patch.object(playback, "mount_points", return_value=[self.root])
        self.mounts.start()
        playback._slots = asyncio.Semaphore(2)
        playback._deliveries = asyncio.Semaphore(2)

    def tearDown(self):
        self.env.stop()
        self.mounts.stop()
        self.temp.cleanup()

    def run_async(self, coro):
        return asyncio.run(coro)

    def test_off_default_and_path_escape(self):
        asset = SimpleNamespace(original_path=str(self.root / "x.mp4"), proxy_path=None)
        self.assertTrue(playback.archive_asset(asset))
        with patch.dict(os.environ, {"CURATOR_ARCHIVE_MODE": ""}):
            self.assertFalse(playback.archive_asset(asset))
        self.assertFalse(playback.contained(self.root / ".." / "outside.mp4"))
        (self.root / "escape").symlink_to("/etc/passwd")
        self.assertFalse(playback.contained(self.root / "escape"))

    def test_mount_unavailable_fails_closed(self):
        with patch.object(playback, "mount_points", return_value=[]):
            with self.assertRaises(Exception) as error:
                playback.validate_roots()
            self.assertEqual(error.exception.status_code, 503)
        with patch.object(os, "access", return_value=False):
            with self.assertRaises(Exception) as error:
                playback.validate_roots()
            self.assertEqual(error.exception.status_code, 503)

    def test_sidecars_are_same_render_and_numerically_ordered(self):
        for name in ["a_video.mp4", "a_audio10.mp4", "a_audio2.mp4", "b_audio0.mp4"]:
            (self.root / name).touch()
        self.assertEqual([p.name for p in playback.audio_sidecars(self.root / "a_video.mp4")],
                         ["a_audio2.mp4", "a_audio10.mp4"])

    def test_vod_playlist_seek_and_final_partial_segment(self):
        text = playback.playlist(13.25)
        self.assertIn("#EXTINF:1.250000,\nsegments/2.ts", text)
        self.assertEqual(text.count("#EXTINF:"), 3)
        self.assertIn("#EXT-X-ENDLIST", text)
        self.assertNotIn(str(self.root), text)

    def test_audio_only_and_no_generated_files(self):
        audio = self.root / "only.m4a"
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440",
            "-t", "1", "-c:a", "aac", str(audio),
        ], check=True)
        asset = SimpleNamespace(proxy_path=None, original_path=str(audio), duration_seconds=1)
        async def render():
            info = await playback.describe(asset)
            self.assertEqual(info[2:], (False, True, []))
            return await playback.segment(asset, 0, None)
        data = self.run_async(render())
        self.assertGreater(len(data), 1000)
        self.assertEqual(list(self.root.iterdir()), [audio])
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", "pipe:0"],
            input=data, capture_output=True, check=True,
        )
        self.assertEqual({s["codec_type"] for s in json.loads(probe.stdout)["streams"]}, {"audio"})

    def test_worker_archive_branch_never_creates_proxy_but_keeps_thumbnail_sprite(self):
        from datetime import datetime
        from types import ModuleType
        video = self.root / "a_video.mp4"
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=size=64x64",
            "-t", "0.2", "-c:v", "libx264", "-threads", "1", str(video),
        ], check=True)
        db = Mock()
        db.execute.return_value.fetchone.return_value = (str(video),)
        update_asset, sprite = Mock(), Mock()
        base = ModuleType("tasks.base")
        base.create_job = Mock(return_value="sprite-job")
        sprites = ModuleType("tasks.sprites")
        sprites.generate_sprite = SimpleNamespace(delay=sprite)
        sqlalchemy = ModuleType("sqlalchemy")
        sqlalchemy.text = lambda value: value
        path = Path(__file__).parents[2] / "worker/tasks/proxy.py"
        tree = ast.parse(path.read_text())
        task = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_proxy")
        task.decorator_list = []
        namespace = dict(
            get_session=lambda: db, update_job=Mock(), update_asset=update_asset,
            _check_archive_mounts=Mock(),
            append_log=Mock(), os=os, subprocess=subprocess, datetime=datetime,
            PROXIES_DIR=str(self.root / "forbidden-proxies"), THUMBNAILS_DIR=str(self.root / "thumbs"),
        )
        with patch.dict(sys.modules, {"sqlalchemy": sqlalchemy, "tasks.base": base, "tasks.sprites": sprites}):
            exec(compile(ast.Module(body=[task], type_ignores=[]), "<actual-worker-task>", "exec"), namespace)
            namespace["create_proxy"](SimpleNamespace(request=SimpleNamespace(id="task")), "asset", "job")
        self.assertFalse((self.root / "forbidden-proxies").exists())
        self.assertTrue((self.root / "thumbs/asset.jpg").exists())
        self.assertEqual(update_asset.call_args.kwargs["proxy_path"], str(video))
        sprite.assert_called_once_with("asset", "sprite-job")
        db.close.assert_called_once()
        for filename in ("audio.m4a", "image.png"):
            src = self.root / filename
            src.touch()
            db.execute.return_value.fetchone.return_value = (str(src),)
            sprite.reset_mock()
            with patch.dict(sys.modules, {"sqlalchemy": sqlalchemy, "tasks.base": base, "tasks.sprites": sprites}):
                namespace["create_proxy"](SimpleNamespace(request=SimpleNamespace(id="task")), "nonvideo", "job")
            self.assertIsNone(update_asset.call_args.kwargs["proxy_path"])
            sprite.assert_not_called()
            self.assertFalse((self.root / "thumbs/nonvideo.jpg").exists())

    def test_routes_authentication_range_and_flag(self):
        """Execute the actual route/middleware AST with only DB/auth lookup
        injected, so this test needs no database, Redis, or ML dependencies."""
        from fastapi import FastAPI, APIRouter, Depends, Request, Response, HTTPException
        from fastapi.testclient import TestClient
        from types import ModuleType
        package = ModuleType("_archive_test")
        package.playback = playback
        sys.modules["_archive_test"] = package
        try:
            router = APIRouter()
            asset = SimpleNamespace(original_path=str(self.root / "photo.png"), proxy_path=None)
            (self.root / "photo.png").write_bytes(b"0123456789")
            db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: asset)))
            async def get_db():
                return db
            class Selection:
                def where(self, *_):
                    return self
            names = {"stream_media", "playback_info", "archive_playlist", "archive_segment"}
            tree = ast.parse((Path(__file__).parents[1] / "app/routers/media.py").read_text())
            nodes = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name in names]
            namespace = dict(
                __package__="_archive_test.routers", router=router, Depends=Depends,
                Request=Request, Response=Response, HTTPException=HTTPException,
                AsyncSession=object, get_db=get_db, MediaAsset=SimpleNamespace(id="id"),
                select=lambda *_: Selection(), os=os,
            )
            exec(compile(ast.Module(body=nodes, type_ignores=[]), "<actual-media-routes>", "exec"), namespace)
            auth_tree = ast.parse((Path(__file__).parents[1] / "app/auth.py").read_text())
            auth_node = next(n for n in auth_tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "auth_middleware")
            auth_ns = dict(
                Request=Request, PUBLIC_PATHS=set(), settings=SimpleNamespace(internal_api_token=""),
                COOKIE_NAME="session", _resolve_user=AsyncMock(return_value=None),
                AUDITED_METHODS=set(), _viewer_may=lambda *_: True,
            )
            exec(compile(ast.Module(body=[auth_node], type_ignores=[]), "<actual-auth-middleware>", "exec"), auth_ns)
            app = FastAPI()
            app.include_router(router, prefix="/api")
            app.middleware("http")(auth_ns["auth_middleware"])
            with TestClient(app) as client:
                for endpoint in ("playback", "stream", "hls.m3u8", "segments/0.ts"):
                    self.assertEqual(client.get(f"/api/x/{endpoint}").status_code, 401)
                auth_ns["_resolve_user"].return_value = SimpleNamespace(role="viewer")
                client.headers["Authorization"] = "Bearer test-session"
                # Router decorators include /{id}, no /media prefix in harness.
                response = client.get("/api/x/playback")
                self.assertEqual(response.json()["type"], "image")
                response = client.get("/api/x/stream", headers={"Range": "bytes=2-5"})
                self.assertEqual(response.status_code, 206)
                self.assertEqual(response.content, b"2345")
                self.assertEqual(response.headers["cache-control"], "private, no-store")
                self.assertEqual(client.get("/api/x/stream", headers={"Range": "bytes=90-99"}).status_code, 416)
                self.assertEqual(client.get("/api/x/segments/0.ts", headers={"Range": "bytes=0-10"}).status_code, 416)
                with patch.dict(os.environ, {"CURATOR_ARCHIVE_MODE": ""}):
                    self.assertEqual(client.get("/api/x/hls.m3u8").status_code, 404)
                    self.assertEqual(client.get("/api/x/playback").json()["type"], "file")
        finally:
            sys.modules.pop("_archive_test", None)

    def test_process_limits_timeout_disconnect_and_cleanup(self):
        async def checks():
            for cmd, kwargs, status in [
                ([sys.executable, "-c", "print('x'*10000)"], {"limit": 10}, 502),
                ([sys.executable, "-c", "import time;time.sleep(5)"], {"timeout": .05}, 504),
            ]:
                with self.assertRaises(Exception) as error:
                    await playback.run_bounded(cmd, **kwargs)
                self.assertEqual(error.exception.status_code, status)
                self.assertEqual(playback._slots._value, 2)
            class Gone:
                async def is_disconnected(self):
                    return True
            with self.assertRaises(Exception) as error:
                await playback.run_bounded(
                    [sys.executable, "-c", "import time;time.sleep(5)"], Gone(),
                )
            self.assertEqual(error.exception.status_code, 499)
            self.assertEqual(playback._slots._value, 2)
        self.run_async(checks())

    def test_slow_client_delivery_reservation_released(self):
        async def checks():
            with patch.object(playback, "segment", new=AsyncMock(return_value=b"x" * 200000)):
                response = await playback.segment_response(None, 0, None)
                self.assertEqual(playback._deliveries._value, 1)
                messages = []
                async def receive():
                    await asyncio.sleep(10)
                async def send(message):
                    messages.append(message)
                await response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send)
                self.assertEqual(playback._deliveries._value, 2)
                chunks = [m.get("body", b"") for m in messages if m["type"] == "http.response.body"]
                self.assertEqual(sum(map(len, chunks)), 200000)
                self.assertLessEqual(max(map(len, chunks)), 65536)
                response = await playback.segment_response(None, 0, None)
                async def disconnect():
                    return {"type": "http.disconnect"}
                await response({"type": "http", "asgi": {"spec_version": "2.3"}}, disconnect, send)
                self.assertEqual(playback._deliveries._value, 2)
        self.run_async(checks())

    def test_real_video_sidecar_audio_and_exact_non_keyframe_seek(self):
        video = self.root / "a_video.mp4"
        audio = self.root / "a_audio0.mp4"
        # GOP=10 seconds: the six-second seek is deliberately not a keyframe.
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30",
            "-t", "13", "-c:v", "libx264", "-threads", "1", "-g", "300",
            "-keyint_min", "300", "-sc_threshold", "0",
            "-movflags", "frag_keyframe+empty_moov", str(video),
        ], check=True)
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=700:sample_rate=48000",
            "-t", "13", "-c:a", "aac", str(audio),
        ], check=True)
        asset = SimpleNamespace(proxy_path=None, original_path=str(video), duration_seconds=13)

        async def render():
            described = await playback.describe(asset)
            self.assertEqual(described[2:], (True, False, [audio]))
            for n in (-1, 3):
                with self.assertRaises(Exception) as error:
                    await playback.segment(asset, n, None)
                self.assertEqual(error.exception.status_code, 416)
            return [await playback.segment(asset, n, None) for n in (0, 1, 2)]
        outputs = self.run_async(render())
        timestamps = []
        audio_ranges = []
        for n, data in enumerate(outputs):
            out = self.root / f"test-only-{n}.ts"
            out.write_bytes(data)  # Only tests write segments, production never does.
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-show_streams", "-show_frames",
                "-of", "json", str(out),
            ], check=True, capture_output=True)
            info = json.loads(probe.stdout)
            self.assertEqual({s["codec_type"] for s in info["streams"]}, {"video", "audio"})
            frames = [f for f in info["frames"] if f["media_type"] == "video"]
            self.assertEqual(len(frames), 180 if n < 2 else 30)
            self.assertEqual(frames[0]["key_frame"], 1)
            times = [float(f["best_effort_timestamp_time"]) for f in frames]
            timestamps.append(times)
            audio_frames = [f for f in info["frames"] if f["media_type"] == "audio"]
            audio_ranges.append((
                float(audio_frames[0]["best_effort_timestamp_time"]),
                float(audio_frames[-1]["best_effort_timestamp_time"]) + audio_frames[-1]["nb_samples"] / 48000,
            ))
            # Audible decoded waveform, not merely an empty audio stream.
            pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-vn",
                                  "-f", "s16le", "pipe:1"], check=True, capture_output=True).stdout
            self.assertTrue(any(pcm))
        for left, right in zip(timestamps, timestamps[1:]):
            self.assertAlmostEqual(right[0] - left[-1], 1 / 30, places=4)
        # AAC has 1024-sample priming; HLS aligns/drops overlapping AAC
        # packets. Bound this to two packets, never seconds of repeated audio.
        for left, right in zip(audio_ranges, audio_ranges[1:]):
            self.assertLessEqual(right[0] - left[1], 1 / 48000)
            self.assertLess(left[1] - right[0], 2 * 1024 / 48000)
        # Source timestamp rather than repeated first GOP: compare decoded
        # frames from the six-second segment with an exact source seek.
        def frame(args):
            return subprocess.run(["ffmpeg", "-v", "error", *args, "-frames:v", "1",
                                   "-pix_fmt", "gray", "-f", "rawvideo", "pipe:1"],
                                  check=True, capture_output=True).stdout
        expected = frame(["-ss", "6", "-i", str(video)])
        actual = frame(["-i", str(self.root / "test-only-1.ts")])
        mean_error = sum(abs(a-b) for a, b in zip(actual, expected)) / len(expected)
        self.assertLess(mean_error, 8)


class BoundedProcessTests(unittest.IsolatedAsyncioTestCase):
    """Real children with paused stdout, not small-output subprocess mocks."""

    WRITER = [sys.executable, "-c",
              "import os; chunk=b'x'*65536\nwhile True: os.write(1, chunk)"]

    def setUp(self):
        playback._slots = asyncio.Semaphore(2)
        self.create_process = asyncio.create_subprocess_exec
        self.processes = []
        self.jobs = []
        self.gates = []
        self.read_sizes = []

    async def asyncTearDown(self):
        # Also clean up a failing regression against the old implementation,
        # whose proc.wait() would otherwise hang the test runner at shutdown.
        for gate in self.gates:
            gate.set()
        for job in self.jobs:
            job.cancel()
        for proc in self.processes:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            proc._transport.close()
        if self.jobs:
            done, pending = await asyncio.wait(self.jobs, timeout=1)
            for job in pending:
                job.cancel()
            await asyncio.gather(*done, return_exceptions=True)
        for proc in self.processes:
            await asyncio.wait_for(proc.wait(), 1)

    def paused_children(self, block_first=False, block_cleanup=False):
        first_started = asyncio.Event()
        cleanup_started = asyncio.Event()
        first_gate = asyncio.Event()
        cleanup_gate = asyncio.Event()
        self.gates.extend([first_gate, cleanup_gate])

        async def spawn(*args, **kwargs):
            proc = await self.create_process(*args, **kwargs)
            self.processes.append(proc)
            if list(args) != self.WRITER:
                return proc
            # Fill the real asyncio StreamReader past its high-water mark
            # before run_bounded can consume any bytes. The writer is blocked
            # in os.write, and killing it does not unblock proc.wait by itself.
            async def paused():
                while not proc.stdout._paused:
                    await asyncio.sleep(.001)
            await asyncio.wait_for(paused(), 1)
            self.assertGreater(len(proc.stdout._buffer), 2 * 65536)
            original_read = proc.stdout.read
            calls = 0

            async def read(size):
                nonlocal calls
                calls += 1
                self.read_sizes.append(size)
                if calls == 1 and block_first:
                    first_started.set()
                    await first_gate.wait()
                if calls == 2 and block_cleanup:
                    cleanup_started.set()
                    await cleanup_gate.wait()
                return await original_read(size)

            proc.stdout.read = read
            return proc

        return (patch.object(playback.asyncio, "create_subprocess_exec", new=spawn),
                first_started, cleanup_started, cleanup_gate)

    def job(self, **kwargs):
        task = asyncio.create_task(playback.run_bounded(self.WRITER, **kwargs))
        self.jobs.append(task)
        return task

    async def finishes(self, task):
        done, _ = await asyncio.wait([task], timeout=1)
        self.assertIn(task, done, "run_bounded hung while cleaning up a paused PIPE")

    async def recovered(self):
        self.assertEqual(playback._slots._value, 2)
        for proc in self.processes:
            self.assertIsNotNone(proc.returncode)
            self.assertTrue(proc._transport.is_closing())
            with self.assertRaises(ProcessLookupError):
                os.kill(proc.pid, 0)
        self.assertTrue(self.read_sizes)
        self.assertTrue(all(0 < size <= 65536 for size in self.read_sizes))
        # Both slots must really be usable again, not just a cosmetic counter.
        outputs = await asyncio.gather(*[
            playback.run_bounded([sys.executable, "-c", "print('recovered')"])
            for _ in range(2)
        ])
        self.assertEqual(outputs, [b"recovered\n", b"recovered\n"])
        self.assertEqual(playback._slots._value, 2)

    async def test_large_output_limit_reaps_and_recovers_both_slots(self):
        patcher, _, _, _ = self.paused_children()
        with patcher:
            jobs = [self.job(limit=10) for _ in range(2)]
            for job in jobs:
                await self.finishes(job)
                with self.assertRaises(playback.HTTPException) as error:
                    await job
                self.assertEqual(error.exception.status_code, 502)
                self.assertIn("memory limit", error.exception.detail)
        await self.recovered()

    async def test_timeout_and_disconnect_with_full_stdout_recover(self):
        class Gone:
            async def is_disconnected(self):
                return True

        for kwargs, status in [({"timeout": .05}, 504), ({"request": Gone()}, 499)]:
            with self.subTest(status=status):
                patcher, _, _, _ = self.paused_children(block_first=True)
                with patcher:
                    job = self.job(**kwargs)
                    await self.finishes(job)
                    with self.assertRaises(playback.HTTPException) as error:
                        await job
                    self.assertEqual(error.exception.status_code, status)
                await self.recovered()

    async def test_repeated_cancellation_during_drain_preserves_cleanup(self):
        patcher, started, draining, drain_gate = self.paused_children(
            block_first=True, block_cleanup=True,
        )
        with patcher:
            job = self.job()
            await asyncio.wait_for(started.wait(), 1)
            self.assertEqual(playback._slots._value, 1)
            job.cancel()
            await asyncio.wait_for(draining.wait(), 1)
            for _ in range(2):
                job.cancel()
                await asyncio.sleep(0)
            self.assertFalse(job.done())
            self.assertEqual(playback._slots._value, 1)
            drain_gate.set()
            await self.finishes(job)
            with self.assertRaises(asyncio.CancelledError):
                await job
        await self.recovered()

    async def test_stalled_drain_has_bounded_transport_close_fallback(self):
        patcher, _, draining, drain_gate = self.paused_children(
            block_first=True, block_cleanup=True,
        )
        with patcher, patch.object(playback, "REAP_TIMEOUT", .05):
            job = self.job(timeout=.01)
            await asyncio.wait_for(draining.wait(), 1)
            await self.finishes(job)
            self.assertFalse(drain_gate.is_set())
            with self.assertRaises(playback.HTTPException) as error:
                await job
            self.assertEqual(error.exception.status_code, 504)
        await self.recovered()

    async def test_concurrency_limit_and_cancelled_slot_waiter(self):
        patcher, _, _, _ = self.paused_children(block_first=True)
        with patcher:
            jobs = [self.job() for _ in range(2)]
            async def both_started():
                while len(self.processes) < 2 or any(
                    not proc.stdout._paused for proc in self.processes
                ):
                    await asyncio.sleep(.001)
            await asyncio.wait_for(both_started(), 1)
            self.assertEqual(playback._slots._value, 0)
            waiting = self.job()
            await asyncio.sleep(.02)
            waiting.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiting
            self.assertEqual(playback._slots._value, 0)
            with self.assertRaises(playback.HTTPException) as error:
                await playback.run_bounded([sys.executable, "-c", "print('no slot')"])
            self.assertEqual(error.exception.status_code, 503)
            self.assertEqual(error.exception.headers, {"Retry-After": "2"})
            self.assertEqual(len(self.processes), 2)
            for job in jobs:
                job.cancel()
            for job in jobs:
                await self.finishes(job)
                with self.assertRaises(asyncio.CancelledError):
                    await job
        await self.recovered()


if __name__ == "__main__":
    unittest.main()