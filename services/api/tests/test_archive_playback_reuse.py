"""Playback reuse/security integration, with codec I/O injected at the boundary.

The final test uses a real child to cover last-viewer process/slot ownership.
The existing archive playback suite retains the real ffmpeg/paused-PIPE tests.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parents[1]))
from app import playback
from app.playback_cache import PendingQueue, SingleFlight, TTLCache

PROBE = json.dumps({
    "format": {"duration": "24"}, "streams": [{"codec_type": "video"}],
}).encode()


class PlaybackReuseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "a_video.mp4"
        self.path.write_bytes(b"source")
        self.asset = SimpleNamespace(proxy_path=None, original_path=str(self.path),
                                     duration_seconds=24)
        self.env = patch.dict(os.environ, {
            "CURATOR_ARCHIVE_MODE": "true", "CURATOR_ARCHIVE_ROOTS": str(self.root),
        })
        self.env.start()
        self.mounts = patch.object(playback, "mount_points", return_value=[self.root])
        self.mounts.start()
        self.now = 0
        self.jobs = []
        self.probes = []
        self.renders = []
        playback._slots = asyncio.Semaphore(2)
        playback._deliveries = asyncio.Semaphore(2)
        playback._compute_queue = PendingQueue(2)
        playback._delivery_queue = PendingQueue(2)
        playback._shared = SingleFlight(8, 32, poll_seconds=.001)
        playback._metadata = TTLCache(10, 128 * 1024, 10, clock=lambda: self.now)
        playback._segments = TTLCache(10, 128 * 1024, 5, clock=lambda: self.now)
        self.codec = patch.object(playback, "run_bounded", new=AsyncMock(side_effect=self.encode))
        self.codec.start()

    async def asyncTearDown(self):
        for job in self.jobs:
            if not job.done():
                job.cancel()
        await asyncio.gather(*self.jobs, return_exceptions=True)
        for flight in list(playback._shared.flights.values()):
            flight.task.cancel()
            await asyncio.gather(flight.task, return_exceptions=True)
        self.codec.stop()
        self.mounts.stop()
        self.env.stop()
        self.temp.cleanup()

    async def encode(self, cmd, request=None, **kwargs):
        # Shared generation may not be attached to a viewer's disconnect state.
        self.assertIsNone(request)
        if cmd[0] == "ffprobe":
            self.probes.append(cmd)
            return PROBE
        self.renders.append(cmd)
        return f"segment-{len(self.renders)}".encode()

    def viewer(self, number=0, request=None, asset=None):
        job = asyncio.create_task(playback.segment(asset or self.asset, number, request))
        self.jobs.append(job)
        return job

    async def until(self, predicate):
        async def poll():
            while not predicate():
                await asyncio.sleep(.001)
        await asyncio.wait_for(poll(), 1)

    async def status(self, awaitable, status, retry=False):
        with self.assertRaises(playback.HTTPException) as error:
            await awaitable
        self.assertEqual(error.exception.status_code, status)
        if retry:
            self.assertEqual(error.exception.headers, {"Retry-After": "2"})

    async def warm(self):
        data = await playback.segment(self.asset, 0, None)
        self.assertEqual(len(self.probes), 1)
        self.assertEqual(len(self.renders), 1)
        return data

    async def test_concurrent_metadata_and_segment_singleflight(self):
        probe_gate, render_gate = asyncio.Event(), asyncio.Event()
        async def encode(cmd, request=None, **kwargs):
            data = await self.encode(cmd, request, **kwargs)
            await (probe_gate if cmd[0] == "ffprobe" else render_gate).wait()
            return data
        playback.run_bounded.side_effect = encode
        jobs = [self.viewer() for _ in range(8)]
        await self.until(lambda: len(self.probes) == 1 and playback._shared.waiters == 8)
        probe_gate.set()
        await self.until(lambda: len(self.renders) == 1 and playback._shared.waiters == 8)
        render_gate.set()
        data = await asyncio.gather(*jobs)
        self.assertTrue(all(value is data[0] for value in data))
        self.assertEqual((len(self.probes), len(self.renders)), (1, 1))
        self.assertEqual(await playback.segment(self.asset, 0, None), data[0])
        self.assertEqual((len(self.probes), len(self.renders)), (1, 1))
        info = await playback.describe(self.asset)
        self.assertEqual(info, (self.path, 24, True, False, []))

    async def test_count_lru_and_independent_ttl_expiry(self):
        playback._segments.max_entries = 2
        first = await self.warm()
        await playback.segment(self.asset, 1, None)
        self.assertIs(await playback.segment(self.asset, 0, None), first)
        await playback.segment(self.asset, 2, None)  # Evicts segment one.
        await playback.segment(self.asset, 1, None)
        self.assertEqual((len(self.probes), len(self.renders)), (1, 4))
        self.assertLessEqual(len(playback._segments.entries), 2)
        self.now = 6
        await playback.segment(self.asset, 1, None)
        self.assertEqual((len(self.probes), len(self.renders)), (1, 5))
        self.now = 11
        await playback.segment(self.asset, 1, None)
        self.assertEqual((len(self.probes), len(self.renders)), (2, 6))

    async def test_oversized_segment_not_cached_but_metadata_is_reused(self):
        playback._segments.max_bytes = 1
        first = await self.warm()
        second = await playback.segment(self.asset, 0, None)
        self.assertNotEqual(first, second)
        self.assertEqual((len(self.probes), len(self.renders)), (1, 2))
        self.assertFalse(playback._segments.entries)
        self.assertEqual(playback._segments.bytes, 0)

    async def test_source_stat_change_invalidates_metadata_and_segments(self):
        first = await self.warm()
        stat = self.path.stat()
        self.path.write_bytes(b"edited")  # Same size; timestamp still matters.
        os.utime(self.path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        second = await playback.segment(self.asset, 0, None)
        self.assertNotEqual(first, second)
        self.assertEqual((len(self.probes), len(self.renders)), (2, 2))
        self.assertEqual(len(playback._metadata.entries), 1)
        self.assertEqual(len(playback._segments.entries), 1)

    async def test_same_size_mtime_replacement_uses_inode_identity(self):
        first = await self.warm()
        before = self.path.stat()
        replacement = self.root / "replacement"
        replacement.write_bytes(b"edited")
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        replacement.replace(self.path)
        second = await playback.segment(self.asset, 0, None)
        self.assertNotEqual(first, second)
        self.assertEqual((len(self.probes), len(self.renders)), (2, 2))

    async def test_ctime_detects_edit_even_when_mtime_is_restored(self):
        first = await self.warm()
        before = self.path.stat()
        # Let even low-resolution filesystems advance their change timestamp.
        await asyncio.sleep(.01)
        self.path.write_bytes(b"edited")
        os.utime(self.path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertNotEqual(before.st_ctime_ns, self.path.stat().st_ctime_ns)
        self.assertNotEqual(first, await playback.segment(self.asset, 0, None))
        self.assertEqual((len(self.probes), len(self.renders)), (2, 2))

    async def test_sidecar_add_edit_remove_invalidates_both_caches(self):
        data = [await self.warm()]
        audio = self.root / "a_audio0.m4a"
        audio.write_bytes(b"audio")
        data.append(await playback.segment(self.asset, 0, None))
        self.assertIn(str(audio), self.renders[-1])
        audio.write_bytes(b"audio-longer")
        data.append(await playback.segment(self.asset, 0, None))
        audio.unlink()
        data.append(await playback.segment(self.asset, 0, None))
        self.assertNotIn(str(audio), self.renders[-1])
        self.assertEqual(len(set(data)), 4)
        self.assertEqual((len(self.probes), len(self.renders)), (4, 4))
        self.assertEqual(len(playback._segments.entries), 1)
        self.assertEqual(len(playback._metadata.entries), 1)

    async def test_mount_source_permission_and_containment_checked_on_hits(self):
        await self.warm()
        with patch.object(playback, "mount_points", return_value=[]):
            await self.status(playback.describe(self.asset), 503)
            await self.status(playback.segment(self.asset, 0, None), 503)
        real_access = os.access
        with patch.object(playback.os, "access",
                          side_effect=lambda p, flags: False if Path(p) == self.path else real_access(p, flags)):
            await self.status(playback.segment(self.asset, 0, None), 404)
        nested = self.root / "other-root"
        nested.mkdir()
        with patch.dict(os.environ, {"CURATOR_ARCHIVE_ROOTS": str(nested)}):
            await self.status(playback.segment(self.asset, 0, None), 404)
        self.assertEqual((len(self.probes), len(self.renders)), (1, 1))

    async def test_deleted_source_and_escape_symlink_cannot_serve_cached_bytes(self):
        await self.warm()
        self.path.unlink()
        await self.status(playback.segment(self.asset, 0, None), 404)
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "secret.mp4"
            target.write_bytes(b"outside-secret")
            self.path.symlink_to(target)
            await self.status(playback.segment(self.asset, 0, None), 404)
        self.assertEqual((len(self.probes), len(self.renders)), (1, 1))

    async def test_sidecar_escape_never_encoded_or_reused(self):
        target = self.root / "sound.m4a"
        target.write_bytes(b"audio")
        sidecar = self.root / "a_audio0.m4a"
        sidecar.symlink_to(target)
        first = await self.warm()
        self.assertIn(str(target), self.renders[-1])
        with tempfile.TemporaryDirectory() as outside:
            secret = Path(outside) / "secret.m4a"
            secret.write_bytes(b"secret")
            sidecar.unlink()
            sidecar.symlink_to(secret)
            self.assertNotEqual(first, await playback.segment(self.asset, 0, None))
            self.assertNotIn(str(secret), self.renders[-1])
            self.assertNotIn(str(target), self.renders[-1])
        self.assertEqual((len(self.probes), len(self.renders)), (2, 2))

    async def test_changes_during_probe_are_not_published(self):
        gate = asyncio.Event()
        async def encode(cmd, request=None, **kwargs):
            data = await self.encode(cmd, request, **kwargs)
            await gate.wait()
            return data
        playback.run_bounded.side_effect = encode
        viewer = self.viewer()
        await self.until(lambda: len(self.probes) == 1)
        self.path.write_bytes(b"changed-during-probe")
        gate.set()
        await self.status(viewer, 503, retry=True)
        self.assertFalse(playback._metadata.entries)
        self.assertFalse(playback._segments.entries)
        playback.run_bounded.side_effect = self.encode
        await playback.segment(self.asset, 0, None)
        self.assertEqual((len(self.probes), len(self.renders)), (2, 1))

    async def test_changes_during_generation_are_not_published(self):
        await playback.describe(self.asset)
        gate = asyncio.Event()
        async def encode(cmd, request=None, **kwargs):
            data = await self.encode(cmd, request, **kwargs)
            await gate.wait()
            return data
        playback.run_bounded.side_effect = encode
        viewer = self.viewer()
        await self.until(lambda: len(self.renders) == 1)
        (self.root / "a_audio1.m4a").write_bytes(b"new-audio")
        gate.set()
        await self.status(viewer, 503, retry=True)
        self.assertFalse(playback._segments.entries)
        self.assertFalse(playback._metadata.entries)
        playback.run_bounded.side_effect = self.encode
        await playback.segment(self.asset, 0, None)
        self.assertEqual((len(self.probes), len(self.renders)), (2, 2))

    async def test_fallback_duration_and_profile_are_part_of_identity(self):
        async def encode(cmd, request=None, **kwargs):
            data = await self.encode(cmd, request, **kwargs)
            if cmd[0] == "ffprobe":
                return b'{"streams":[{"codec_type":"video"}]}'
            return data
        playback.run_bounded.side_effect = encode
        one = SimpleNamespace(**vars(self.asset))
        two = SimpleNamespace(**vars(self.asset))
        one.duration_seconds, two.duration_seconds = 12, 18
        self.assertEqual((await playback.describe(one))[1], 12)
        self.assertEqual((await playback.describe(two))[1], 18)
        first = await playback.segment(one, 0, None)
        second = await playback.segment(two, 0, None)
        self.assertNotEqual(first, second)
        with patch.object(playback, "SEGMENT_PROFILE", ("test-new-profile", 6)):
            self.assertNotEqual(first, await playback.segment(one, 0, None))
        self.assertEqual((len(self.probes), len(self.renders)), (2, 3))

    async def test_failure_does_not_poison_cache(self):
        playback.run_bounded.side_effect = lambda *_, **__: b"not-json"
        await self.status(playback.describe(self.asset), 422)
        self.assertFalse(playback._metadata.entries)
        playback.run_bounded.side_effect = self.encode
        await playback.describe(self.asset)
        playback.run_bounded.side_effect = playback.HTTPException(502, "decode failed")
        await self.status(playback.segment(self.asset, 0, None), 502)
        self.assertFalse(playback._segments.entries)
        playback.run_bounded.side_effect = self.encode
        await playback.segment(self.asset, 0, None)
        self.assertEqual((len(self.probes), len(self.renders)), (1, 1))

    async def test_first_disconnect_and_cancel_leave_surviving_viewer(self):
        await playback.describe(self.asset)
        gate = asyncio.Event()
        gone = asyncio.Event()
        async def disconnected():
            return gone.is_set()
        request = SimpleNamespace(is_disconnected=disconnected)
        async def encode(cmd, request=None, **kwargs):
            data = await self.encode(cmd, request, **kwargs)
            await gate.wait()
            return data
        playback.run_bounded.side_effect = encode
        first = self.viewer(request=request)
        await self.until(lambda: len(self.renders) == 1)
        second, survivor = self.viewer(), self.viewer()
        await self.until(lambda: playback._shared.waiters == 3)
        gone.set()
        await self.status(first, 499)
        second.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await second
        self.assertFalse(survivor.done())
        self.assertFalse(next(iter(playback._shared.flights.values())).task.cancelled())
        gate.set()
        self.assertEqual(await survivor, b"segment-1")
        self.assertEqual(len(self.renders), 1)

    async def test_singleflight_overload_is_retryable_and_shared_join_is_bounded(self):
        await playback.describe(self.asset)
        playback._shared = SingleFlight(1, 2, poll_seconds=.001)
        gate = asyncio.Event()
        async def encode(cmd, request=None, **kwargs):
            data = await self.encode(cmd, request, **kwargs)
            await gate.wait()
            return data
        playback.run_bounded.side_effect = encode
        first, second = self.viewer(), self.viewer()
        await self.until(lambda: playback._shared.waiters == 2)
        await self.status(playback.segment(self.asset, 0, None), 503, retry=True)
        await self.status(playback.segment(self.asset, 1, None), 503, retry=True)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        # There is waiter space now, but a different key needs a new flight.
        await self.status(playback.segment(self.asset, 1, None), 503, retry=True)
        gate.set()
        await second
        self.assertEqual(len(self.renders), 1)

    async def test_delivery_quota_applies_to_cache_hits_and_pending_is_bounded(self):
        await self.warm()
        playback._delivery_queue = PendingQueue(0)
        responses = [await playback.segment_response(self.asset, 0, None) for _ in range(2)]
        self.assertEqual(playback._deliveries._value, 0)
        await self.status(playback.segment_response(self.asset, 0, None), 503, retry=True)
        self.assertEqual((len(self.probes), len(self.renders)), (1, 1))
        async def receive():
            await asyncio.sleep(10)
        async def send(_):
            pass
        for response in responses:
            await response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send)
        self.assertEqual(playback._deliveries._value, 2)

    async def test_compute_and_delivery_pending_overload_release_on_cancel(self):
        # Undo only the boundary mock: no permit means no codec is launched.
        self.codec.stop()
        playback._slots = asyncio.Semaphore(0)
        playback._deliveries = asyncio.Semaphore(0)
        playback._compute_queue = PendingQueue(1)
        playback._delivery_queue = PendingQueue(1)
        compute = asyncio.create_task(playback.run_bounded(["must-not-launch"]))
        delivery = asyncio.create_task(playback.segment_response(self.asset, 0, None))
        self.jobs.extend([compute, delivery])
        await self.until(lambda: playback._compute_queue.pending == playback._delivery_queue.pending == 1)
        await self.status(playback.run_bounded(["must-not-launch"]), 503, retry=True)
        await self.status(playback.segment_response(self.asset, 0, None), 503, retry=True)
        for job in (compute, delivery):
            job.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await job
        self.assertEqual(playback._compute_queue.pending, 0)
        self.assertEqual(playback._delivery_queue.pending, 0)

    async def test_last_viewer_disconnect_reaps_shared_real_child(self):
        # Keep the actual run_bounded cleanup logic under the shared task.
        self.codec.stop()
        run = playback.run_bounded
        spawn = asyncio.create_subprocess_exec
        processes = []
        gone = asyncio.Event()
        async def disconnected():
            return gone.is_set()
        request = SimpleNamespace(is_disconnected=disconnected)
        async def create(*args, **kwargs):
            proc = await spawn(*args, **kwargs)
            processes.append(proc)
            return proc
        async def encode(cmd, request=None, **kwargs):
            if cmd[0] == "ffprobe":
                return PROBE
            self.assertIsNone(request)
            return await run([sys.executable, "-c", "import time;time.sleep(20)"])
        with patch.object(playback, "run_bounded", side_effect=encode), \
                patch.object(playback.asyncio, "create_subprocess_exec", side_effect=create):
            first = self.viewer()
            await self.until(lambda: bool(processes))
            survivor = self.viewer(request=request)
            await self.until(lambda: playback._shared.waiters == 2)
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            self.assertIsNone(processes[0].returncode)
            self.assertEqual(playback._slots._value, 1)
            gone.set()
            await self.status(asyncio.wait_for(survivor, 2), 499)
        self.assertIsNotNone(processes[0].returncode)
        self.assertTrue(processes[0]._transport.is_closing())
        with self.assertRaises(ProcessLookupError):
            os.kill(processes[0].pid, 0)
        self.assertEqual(playback._slots._value, 2)
        self.assertFalse(playback._segments.entries)
        self.assertEqual(playback._shared.waiters, 0)


if __name__ == "__main__":
    unittest.main()