"""Process-local playback reuse primitives; no filesystem or network writes.

These objects are used on one asyncio event loop. Limits include cancelling
flights until their cleanup finishes, not just work currently using a codec.
"""
import asyncio
from collections import OrderedDict
import math
import os
import sys
import time


def env_int(name, default, maximum, minimum=0):
    try:
        value = int(os.getenv(name, str(default)))
    except (ValueError, TypeError):
        value = default
    return max(minimum, min(maximum, value))


def env_seconds(name, default, maximum=3600):
    try:
        value = float(os.getenv(name, str(default)))
        if not math.isfinite(value):
            value = default
    except (ValueError, TypeError):
        value = default
    return max(0, min(maximum, value))


def retained_size(key, value):
    """Charge keys, payloads and approximate entry/container overhead.

    Count limits separately bound Python allocator/LRU overhead. Playback keys
    and values contain only tuples, strings, numbers and immutable bytes.
    """
    def size(item):
        return sys.getsizeof(item) + (
            sum(size(part) for part in item) if isinstance(item, tuple) else 0
        )
    return 256 + size(key) + size(value)


class TTLCache:
    def __init__(self, max_entries, max_bytes, ttl, clock=time.monotonic):
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.ttl = ttl
        self.clock = clock
        self.entries = OrderedDict()
        self.bytes = 0

    def _remove(self, key):
        _, size, _ = self.entries.pop(key)
        self.bytes -= size

    def _expire(self):
        now = self.clock()
        for key, (_, _, expires) in list(self.entries.items()):
            if expires <= now:
                self._remove(key)

    def get(self, key):
        self._expire()
        entry = self.entries.get(key)
        if entry is None:
            return None
        self.entries.move_to_end(key)
        return entry[0]

    def put(self, key, value, size=None):
        self._expire()
        if key in self.entries:
            self._remove(key)
        size = retained_size(key, value) if size is None else size
        if not self.max_entries or not self.ttl or size > self.max_bytes:
            return False
        while self.entries and (
            len(self.entries) >= self.max_entries or self.bytes + size > self.max_bytes
        ):
            self._remove(next(iter(self.entries)))
        self.entries[key] = (value, size, self.clock() + self.ttl)
        self.bytes += size
        return True

    def discard_where(self, predicate):
        self._expire()
        for key in list(self.entries):
            if predicate(key):
                self._remove(key)


class CapacityReached(Exception):
    pass


class ViewerDisconnected(Exception):
    pass


class PendingQueue:
    """Bound reservations waiting for an existing compute/delivery semaphore."""
    def __init__(self, maximum):
        self.maximum = maximum
        self.pending = 0

    async def acquire(self, semaphore, timeout=2):
        # A free permit must remain usable even when queuing is disabled.
        if not semaphore.locked():
            await semaphore.acquire()
            return
        if self.pending >= self.maximum:
            raise CapacityReached()
        self.pending += 1
        try:
            try:
                await asyncio.wait_for(semaphore.acquire(), timeout)
            except asyncio.TimeoutError:
                raise CapacityReached() from None
        finally:
            self.pending -= 1


class _Flight:
    def __init__(self, task):
        self.task = task
        self.waiters = 0
        self.closing = False


class SingleFlight:
    """Share work, not a request's cancellation or disconnect watcher.

    Factories receive no viewer request. The last departing waiter cancels the
    factory and waits for its cleanup, shielded against repeated cancellation.
    A cancelling flight keeps its reservation and cannot accept new viewers.
    """
    def __init__(self, max_flights, max_waiters, poll_seconds=.2):
        self.max_flights = max_flights
        self.max_waiters = max_waiters
        self.poll_seconds = poll_seconds
        self.flights = {}
        self.waiters = 0

    def _completed(self, key, flight):
        if self.flights.get(key) is flight:
            del self.flights[key]
        if not flight.task.cancelled():
            flight.task.exception()  # Retrieve abandoned failures.

    async def run(self, key, factory, disconnected=None):
        if self.waiters >= self.max_waiters:
            raise CapacityReached()
        flight = self.flights.get(key)
        if flight is not None and flight.closing:
            raise CapacityReached()
        if flight is None:
            if len(self.flights) >= self.max_flights:
                raise CapacityReached()
            flight = _Flight(asyncio.create_task(factory()))
            self.flights[key] = flight
            flight.task.add_done_callback(lambda _: self._completed(key, flight))
        flight.waiters += 1
        self.waiters += 1
        try:
            if disconnected is None:
                return await asyncio.shield(flight.task)
            while True:
                if await disconnected():
                    raise ViewerDisconnected()
                if flight.task.done():
                    return flight.task.result()
                await asyncio.wait([flight.task], timeout=self.poll_seconds)
        finally:
            flight.waiters -= 1
            self.waiters -= 1
            if flight.waiters == 0 and not flight.task.done():
                flight.closing = True
                flight.task.cancel()
                cancelled = False
                while not flight.task.done():
                    try:
                        await asyncio.shield(flight.task)
                    except asyncio.CancelledError:
                        # Includes the factory's own cancellation and any new
                        # cancellation of this waiter during child cleanup.
                        if not flight.task.done():
                            cancelled = True
                    except Exception:
                        break
                if cancelled:
                    raise asyncio.CancelledError