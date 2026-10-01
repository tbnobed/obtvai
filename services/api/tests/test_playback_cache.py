"""RAM-only reuse primitives: run without FastAPI, codecs, DB or Redis."""
import asyncio
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
from app.playback_cache import (
    CapacityReached, PendingQueue, SingleFlight, TTLCache, ViewerDisconnected,
    env_int, env_seconds, retained_size,
)


class CacheTests(unittest.TestCase):
    def test_count_lru_and_absolute_ttl(self):
        now = [0]
        cache = TTLCache(2, 100, 10, clock=lambda: now[0])
        cache.put("a", b"a", size=10)
        cache.put("b", b"b", size=10)
        self.assertEqual(cache.get("a"), b"a")
        cache.put("c", b"c", size=10)
        self.assertIsNone(cache.get("b"))
        self.assertEqual(list(cache.entries), ["a", "c"])
        now[0] = 9
        self.assertEqual(cache.get("a"), b"a")
        now[0] = 10
        self.assertIsNone(cache.get("a"))  # A hit never extends the TTL.
        self.assertEqual(cache.bytes, 0)
        self.assertFalse(cache.entries)

    def test_byte_bound_replacement_oversize_and_invalidation(self):
        cache = TTLCache(10, 8, 10)
        cache.put("a", b"a", size=3)
        cache.put("b", b"b", size=3)
        cache.put("c", b"c", size=3)
        self.assertIsNone(cache.get("a"))
        self.assertEqual(cache.bytes, 6)
        cache.put("b", b"bb", size=5)
        self.assertEqual(cache.bytes, 8)
        self.assertFalse(cache.put("huge", b"x", size=9))
        self.assertEqual(cache.bytes, 8)
        cache.discard_where(lambda key: key == "b")
        self.assertEqual(cache.bytes, 3)
        cache.discard_where(lambda _: True)
        self.assertEqual(cache.bytes, 0)

    def test_disabled_and_accounting_includes_keys(self):
        for count, limit, ttl in [(0, 10, 1), (1, 0, 1), (1, 10, 0)]:
            cache = TTLCache(count, limit, ttl)
            self.assertFalse(cache.put("a", b"x", size=1))
            self.assertIsNone(cache.get("a"))
        key = ("long-path-" * 100, (1, 2, 3))
        size = retained_size(key, b"x" * 10)
        self.assertGreater(size, 1000)
        cache = TTLCache(3, size, 10)
        self.assertTrue(cache.put(key, b"x" * 10))
        self.assertEqual(cache.bytes, size)

    def test_environment_clamps_invalid_and_nonfinite_limits(self):
        for value, expected in [("bad", 5), ("-3", 0), ("100000", 10), ("0", 0)]:
            with patch.dict(os.environ, {"TEST_PLAYBACK": value}):
                self.assertEqual(env_int("TEST_PLAYBACK", 5, 10), expected)
        with patch.dict(os.environ, {"TEST_PLAYBACK": "0"}):
            self.assertEqual(env_int("TEST_PLAYBACK", 5, 10, minimum=1), 1)
        for value, expected in [("nan", 5), ("inf", 5), ("bad", 5),
                                ("-3", 0), ("100000", 10), ("0.25", .25)]:
            with patch.dict(os.environ, {"TEST_PLAYBACK": value}):
                self.assertEqual(env_seconds("TEST_PLAYBACK", 5, 10), expected)


class SingleFlightTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.shared = SingleFlight(2, 3, poll_seconds=.001)
        self.gate = asyncio.Event()
        self.started = asyncio.Event()
        self.calls = 0
        self.cancelled = 0
        self.jobs = []

    async def asyncTearDown(self):
        self.gate.set()
        for job in self.jobs:
            if not job.done():
                job.cancel()
        await asyncio.gather(*self.jobs, return_exceptions=True)
        for flight in list(self.shared.flights.values()):
            flight.task.cancel()
            await asyncio.gather(flight.task, return_exceptions=True)

    async def generate(self):
        self.calls += 1
        self.started.set()
        try:
            await self.gate.wait()
            return b"shared"
        except asyncio.CancelledError:
            self.cancelled += 1
            raise

    def viewer(self, key="same", disconnected=None, factory=None):
        job = asyncio.create_task(self.shared.run(
            key, factory or self.generate, disconnected,
        ))
        self.jobs.append(job)
        return job

    async def until(self, predicate):
        async def poll():
            while not predicate():
                await asyncio.sleep(.001)
        await asyncio.wait_for(poll(), 1)

    async def test_identical_requests_run_one_factory(self):
        jobs = [self.viewer() for _ in range(3)]
        await self.started.wait()
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.shared.waiters, 3)
        self.gate.set()
        self.assertEqual(await asyncio.gather(*jobs), [b"shared"] * 3)
        await asyncio.sleep(0)
        self.assertFalse(self.shared.flights)
        self.assertEqual(self.shared.waiters, 0)

    async def test_first_viewer_cancellation_does_not_cancel_survivor(self):
        first = self.viewer()
        await self.started.wait()
        survivor = self.viewer()
        await self.until(lambda: self.shared.waiters == 2)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertEqual(self.cancelled, 0)
        self.gate.set()
        self.assertEqual(await survivor, b"shared")
        self.assertEqual(self.calls, 1)

    async def test_first_viewer_disconnect_is_independent(self):
        gone = asyncio.Event()
        async def disconnected():
            return gone.is_set()
        first = self.viewer(disconnected=disconnected)
        await self.started.wait()
        survivor = self.viewer()
        await self.until(lambda: self.shared.waiters == 2)
        gone.set()
        with self.assertRaises(ViewerDisconnected):
            await first
        self.assertEqual(self.cancelled, 0)
        self.gate.set()
        self.assertEqual(await survivor, b"shared")

    async def test_last_viewer_disconnect_cancels_generation(self):
        gone = asyncio.Event()
        async def disconnected():
            return gone.is_set()
        viewer = self.viewer(disconnected=disconnected)
        await self.started.wait()
        gone.set()
        with self.assertRaises(ViewerDisconnected):
            await viewer
        self.assertEqual(self.cancelled, 1)
        self.assertEqual(self.shared.waiters, 0)
        await asyncio.sleep(0)
        self.assertFalse(self.shared.flights)

    async def test_last_waiter_repeated_cancel_holds_flight_until_cleanup(self):
        draining = asyncio.Event()
        drain_gate = asyncio.Event()
        async def generate():
            self.started.set()
            try:
                await self.gate.wait()
            finally:
                draining.set()
                await drain_gate.wait()
        viewer = self.viewer(factory=generate)
        await self.started.wait()
        viewer.cancel()
        await draining.wait()
        for _ in range(2):
            viewer.cancel()
            await asyncio.sleep(0)
        self.assertFalse(viewer.done())
        self.assertTrue(self.shared.flights["same"].closing)
        self.assertEqual(self.shared.waiters, 0)
        with self.assertRaises(CapacityReached):
            await self.shared.run("same", self.generate)
        self.assertFalse(self.shared.flights["same"].task.done())
        drain_gate.set()
        with self.assertRaises(asyncio.CancelledError):
            await viewer
        await asyncio.sleep(0)
        self.assertFalse(self.shared.flights)

    async def test_flight_and_total_waiter_limits(self):
        first = self.viewer("one")
        second = self.viewer("two")
        await self.until(lambda: len(self.shared.flights) == 2)
        with self.assertRaises(CapacityReached):
            await self.shared.run("three", self.generate)
        third = self.viewer("one")
        await self.until(lambda: self.shared.waiters == 3)
        with self.assertRaises(CapacityReached):
            await self.shared.run("one", self.generate)
        self.assertEqual(self.calls, 2)
        self.gate.set()
        await asyncio.gather(first, second, third)

    async def test_failure_is_shared_and_not_retained(self):
        async def fail():
            self.calls += 1
            self.started.set()
            await self.gate.wait()
            raise ValueError("decode failed")
        jobs = [self.viewer(factory=fail) for _ in range(2)]
        await self.started.wait()
        self.gate.set()
        results = await asyncio.gather(*jobs, return_exceptions=True)
        self.assertTrue(all(isinstance(result, ValueError) for result in results))
        self.assertEqual(self.calls, 1)
        await asyncio.sleep(0)
        with self.assertRaises(ValueError):
            await self.shared.run("same", fail)
        self.assertEqual(self.calls, 2)


class PendingQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_queue_limits_cancellation_and_timeout(self):
        queue = PendingQueue(1)
        semaphore = asyncio.Semaphore(1)
        await queue.acquire(semaphore)
        waiting = asyncio.create_task(queue.acquire(semaphore))
        await asyncio.sleep(0)
        self.assertEqual(queue.pending, 1)
        with self.assertRaises(CapacityReached):
            await queue.acquire(semaphore)
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        self.assertEqual(queue.pending, 0)
        with self.assertRaises(CapacityReached):
            await queue.acquire(semaphore, timeout=.001)
        self.assertEqual(queue.pending, 0)
        semaphore.release()
        await queue.acquire(semaphore)
        self.assertEqual(semaphore._value, 0)
        semaphore.release()

    async def test_zero_queue_still_allows_free_permits(self):
        queue = PendingQueue(0)
        semaphore = asyncio.Semaphore(1)
        await queue.acquire(semaphore)
        with self.assertRaises(CapacityReached):
            await queue.acquire(semaphore)
        semaphore.release()


if __name__ == "__main__":
    unittest.main()