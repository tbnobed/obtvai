#!/usr/bin/env python3
"""Authorized, bounded playback load. Dry run by default; httpx at execution only.

Use an existing API container (httpx is already in its requirements). Session
credentials are read from PLAYBACK_LOAD_TOKEN, never CLI arguments or output.
"""
import argparse
import asyncio
from array import array
from collections import Counter, deque
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import random
import re
import signal
import time
from urllib.parse import urlsplit

SEGMENT_SECONDS = 6
MAX_VIEWERS = 500
MAX_SECONDS = 1800
MAX_SEGMENT_BYTES = 12 * 1024 * 1024
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def origin(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ("http", "https") or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
        or parsed.query or parsed.fragment or parsed.path not in ("", "/")
    ):
        raise ValueError("Target must be an http(s) origin, without credentials, path, query, or fragment")
    # Access port to reject malformed ports; preserve the explicit authority.
    _ = parsed.port
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def positive_float(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("Must be a positive finite number")
    return result


def read_ids(path):
    text = Path(path).read_text()
    values = json.loads(text) if text.lstrip().startswith("[") else text.splitlines()
    if not isinstance(values, list) or not values:
        raise ValueError("Media ID file must contain a nonempty JSON array or one ID per line")
    if any(not isinstance(value, str) or not ID_PATTERN.fullmatch(value) for value in values):
        raise ValueError("Media ID file contains an invalid ID")
    if len(set(values)) != len(values):
        raise ValueError("Media ID file must not contain duplicates")
    if len(values) > MAX_VIEWERS:
        raise ValueError("Media ID file may contain at most 500 IDs")
    return values


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--target", required=True, help="Exact authorized nginx origin, including port")
    result.add_argument("--ack-target", help="Repeat the exact --target to authorize network execution")
    result.add_argument("--execute", action="store_true", help="Actually send load (default: offline plan)")
    result.add_argument("--max-users", type=int, required=True, help="Explicit viewer cap, at most 500")
    result.add_argument("--max-duration", type=positive_float, required=True, help="Explicit wall-clock cap, at most 1800s")
    result.add_argument("--stages", default="100,250,500", help="100 or 100,250 or 100,250,500")
    result.add_argument("--stage-seconds", type=positive_float, default=120, help="Includes the ramp")
    result.add_argument("--ramp-seconds", type=positive_float, default=30)
    result.add_argument("--baseline-seconds", type=positive_float, default=30)
    result.add_argument("--scenario", choices=("same", "distinct"), required=True)
    result.add_argument("--media-ids", required=True, help="Real authorized archive media IDs, JSON or one per line")
    result.add_argument("--search-query", required=True, help="Real semantic query; never logged")
    result.add_argument("--background-users", type=int, default=5, help="Additional browse/search clients, 1..20")
    result.add_argument("--browse-interval", type=positive_float, default=5)
    result.add_argument("--search-interval", type=positive_float, default=15)
    result.add_argument("--seek-interval", type=positive_float, default=30)
    result.add_argument("--timeout", type=positive_float, default=15)
    result.add_argument("--output", help="Optional JSON report file; contains no tokens, queries, or asset IDs")
    return result


def validate(args):
    args.target = origin(args.target)
    if not 1 <= args.max_users <= MAX_VIEWERS:
        raise ValueError("--max-users must be between 1 and 500")
    if args.max_duration > MAX_SECONDS:
        raise ValueError("--max-duration cannot exceed 1800 seconds")
    if args.stages not in ("100", "100,250", "100,250,500"):
        raise ValueError("--stages must be a controlled 100/250/500 ramp")
    args.stages = tuple(map(int, args.stages.split(",")))
    if max(args.stages) > args.max_users:
        raise ValueError("Stages exceed the acknowledged viewer cap")
    if args.stage_seconds > 300 or args.stage_seconds < args.ramp_seconds + 6:
        raise ValueError("Stage duration must be <=300s and at least ramp duration + 6s")
    if args.ramp_seconds < 10 or args.baseline_seconds < 10:
        raise ValueError("Ramp and browsing/search baseline must each be at least 10s")
    if not 1 <= args.background_users <= 20:
        raise ValueError("--background-users must be between 1 and 20")
    if (
        args.browse_interval < 5 or args.search_interval < 10
        or args.seek_interval < 12 or args.timeout > 30
    ):
        raise ValueError("Minimum browse/search/seek intervals: 5/10/12s; maximum timeout: 30s")
    planned = args.baseline_seconds + len(args.stages) * args.stage_seconds
    if planned >= args.max_duration:
        raise ValueError("Wall-clock cap must exceed the baseline and stages (allow preflight time)")
    if not args.search_query.strip() or len(args.search_query) > 1000:
        raise ValueError("Provide a nonempty real search query, at most 1000 characters")
    args.ids = read_ids(args.media_ids)
    if args.scenario == "same" and len(args.ids) != 1:
        raise ValueError("Same-clip scenario requires exactly one media ID")
    if args.scenario == "distinct" and len(args.ids) < max(args.stages):
        raise ValueError("Distinct-clip scenario requires one different real media ID per viewer")
    if args.execute and (not args.ack_target or origin(args.ack_target) != args.target):
        raise ValueError("Execution requires --ack-target equal to --target")
    return args


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 4)


@dataclass
class Measurements:
    started: float = field(default_factory=time.monotonic)
    counts: Counter = field(default_factory=Counter)
    codes: Counter = field(default_factory=Counter)
    latencies: dict = field(default_factory=dict)
    transferred: Counter = field(default_factory=Counter)
    successful_transferred: Counter = field(default_factory=Counter)
    recent: deque = field(default_factory=lambda: deque(maxlen=100))
    segment_misses: int = 0
    seek_count: int = 0

    def record(self, kind, status, elapsed, size, failed):
        self.counts[f"{kind}_requests"] += 1
        self.counts["requests"] += 1
        self.counts["failures"] += int(failed)
        self.counts[f"{kind}_failures"] += int(failed)
        self.counts["timeouts"] += int(status == "timeout")
        self.codes[f"{kind}:{status}"] += 1
        self.latencies.setdefault(kind, array("d")).append(elapsed)
        self.transferred[kind] += size
        if not failed:
            self.successful_transferred[kind] += size
        if kind == "segment" and elapsed >= SEGMENT_SECONDS:
            self.segment_misses += 1
        self.recent.append(bool(failed))

    def unsafe(self):
        return len(self.recent) >= 20 and sum(self.recent) / len(self.recent) > .05

    def report(self):
        elapsed = max(time.monotonic() - self.started, .001)
        return {
            "elapsed_seconds": round(elapsed, 3),
            "counts": dict(self.counts), "statuses": dict(self.codes),
            "failure_fraction": round(self.counts["failures"] / max(self.counts["requests"], 1), 5),
            "latency_seconds": {
                kind: {"p50": percentile(values, .5), "p95": percentile(values, .95), "max": round(max(values), 4)}
                for kind, values in self.latencies.items()
            },
            "bytes_received": dict(self.transferred),
            "successful_bytes_received": dict(self.successful_transferred),
            "segment_mbps": round(self.successful_transferred["segment"] * 8 / elapsed / 1_000_000, 3),
            "segment_deadline_misses": self.segment_misses,
            "seek_events": self.seek_count,
        }


class Harness:
    def __init__(self, args, client):
        self.args, self.client = args, client
        self.stop = asyncio.Event()
        self.stats = Measurements()
        self.reports = []
        self.clips = {}
        self.abort_reason = None

    async def request(self, kind, method, path, payload=None, collect=False):
        started = time.monotonic()
        size, status, failed, body = 0, "cancelled", True, bytearray()
        ts_prefix = bytearray()
        try:
            async with asyncio.timeout(self.args.timeout):
                async with self.client.stream(method, path, json=payload) as response:
                    status = str(response.status_code)
                    failed = response.status_code != 200
                    length = response.headers.get("content-length")
                    async for chunk in response.aiter_bytes(65536):
                        size += len(chunk)
                        cap = MAX_SEGMENT_BYTES if kind == "segment" else 2 * 1024 * 1024
                        if size > cap:
                            status, failed = "oversize", True
                            break
                        if collect:
                            body.extend(chunk)
                        if kind == "segment" and len(ts_prefix) < 564:
                            ts_prefix.extend(chunk[:564 - len(ts_prefix)])
                    if kind == "segment" and (not size or (length and int(length) != size)):
                        status, failed = "incomplete", True
                    elif kind == "segment" and not failed and (
                        size % 188 or any(ts_prefix[offset] != 0x47 for offset in range(0, len(ts_prefix), 188))
                    ):
                        status, failed = "invalid_mpegts", True
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            status, failed = "timeout", True
        except Exception as error:
            # Never print exception repr: http clients may include auth headers/URLs.
            status = "timeout" if "Timeout" in type(error).__name__ else "transport_error"
            failed = True
        finally:
            # Assign to the phase in which the request COMPLETES; replacing a
            # collector while requests are in flight must not lose measurements.
            if status != "cancelled":
                self.stats.record(kind, status, time.monotonic() - started, size, failed)
                if self.stats.unsafe():
                    self.abort_reason = "Failure rate exceeded 5% in the last 20..100 requests"
                    self.stop.set()
        return None if failed else bytes(body)

    async def preflight(self):
        # Confirm each asset really negotiates HLS; do not fabricate duration or IDs.
        gate = asyncio.Semaphore(4)

        async def check(media_id):
            async with gate:
                if self.stop.is_set():
                    return
                raw = await self.request("metadata", "GET", f"/api/media/{media_id}/playback", collect=True)
                try:
                    info = json.loads(raw)
                    duration = float(info["duration"])
                    if (
                        info["type"] != "hls" or not math.isfinite(duration)
                        or not 0 < duration <= 7 * 24 * 3600
                        or info["url"] != f"/api/media/{media_id}/hls.m3u8"
                    ):
                        raise ValueError()
                except (ValueError, TypeError, KeyError):
                    raise RuntimeError("Preflight failed: a supplied asset is not playable archive HLS") from None
                raw = await self.request("playlist", "GET", info["url"], collect=True)
                if raw is None or not raw.startswith(b"#EXTM3U"):
                    raise RuntimeError("Preflight failed: HLS playlist unavailable")
                self.clips[media_id] = math.ceil(duration / SEGMENT_SECONDS)

        await asyncio.gather(*(check(media_id) for media_id in self.args.ids))
        if self.stop.is_set():
            raise RuntimeError(self.abort_reason)
        self.finish_phase("preflight", 0)

    async def sleep(self, seconds):
        try:
            await asyncio.wait_for(self.stop.wait(), max(seconds, .001))
        except asyncio.TimeoutError:
            pass

    async def background(self, number):
        await self.sleep(number * self.args.browse_interval / self.args.background_users)
        next_search = time.monotonic()
        while not self.stop.is_set():
            started = time.monotonic()
            await self.request("browse", "GET", "/api/media?limit=25&offset=0&media_type=hide_images")
            if time.monotonic() >= next_search and not self.stop.is_set():
                await self.request("search", "POST", "/api/search", {
                    "query": self.args.search_query, "search_type": "combined", "limit": 10,
                })
                next_search = time.monotonic() + self.args.search_interval
            await self.sleep(max(0, self.args.browse_interval - (time.monotonic() - started)))

    async def viewer(self, number, delay):
        await self.sleep(delay)
        media_id = self.args.ids[0] if self.args.scenario == "same" else self.args.ids[number]
        count = self.clips[media_id]
        rng = random.Random(number + 314159)
        segment = 0 if self.args.scenario == "same" else rng.randrange(count)
        next_seek = time.monotonic() + self.args.seek_interval + rng.uniform(0, 6)
        # Real navigation on the ramp, as well as pooled metadata preflight.
        await self.request("metadata", "GET", f"/api/media/{media_id}/playback")
        await self.request("playlist", "GET", f"/api/media/{media_id}/hls.m3u8")
        while not self.stop.is_set():
            started = time.monotonic()
            if started >= next_seek:
                segment = rng.randrange(count)
                self.stats.seek_count += 1
                next_seek = started + self.args.seek_interval
            await self.request("segment", "GET", f"/api/media/{media_id}/segments/{segment}.ts")
            segment = (segment + 1) % count
            # Never catch up with a request storm after a slow segment. One
            # in-flight request per viewer, paced at six seconds or slower.
            await self.sleep(max(0, SEGMENT_SECONDS - (time.monotonic() - started)))

    def finish_phase(self, label, viewers):
        report = {"phase": label, "viewers_target": viewers, **self.stats.report()}
        self.reports.append(report)
        print(json.dumps(report), flush=True)
        self.stats = Measurements()

    async def run(self):
        background, viewers = [], []
        try:
            await self.preflight()
            background = [asyncio.create_task(self.background(n)) for n in range(self.args.background_users)]
            await self.sleep(self.args.baseline_seconds)
            self.finish_phase("browsing_baseline", 0)
            for target in self.args.stages:
                if self.stop.is_set():
                    break
                added = target - len(viewers)
                for n in range(added):
                    viewers.append(asyncio.create_task(self.viewer(
                        len(viewers), n * self.args.ramp_seconds / added,
                    )))
                await self.sleep(self.args.ramp_seconds)
                self.finish_phase(f"ramp_{target}", target)
                if not self.stop.is_set():
                    await self.sleep(self.args.stage_seconds - self.args.ramp_seconds)
                    self.finish_phase(f"steady_{target}", target)
        finally:
            self.stop.set()
            for task in background + viewers:
                task.cancel()
            await asyncio.gather(*background, *viewers, return_exceptions=True)


async def execute(args):
    # Lazy dependency: offline validation and --help use only Python stdlib.
    import httpx

    token = os.getenv("PLAYBACK_LOAD_TOKEN", "").strip()
    if not token or not token.isascii() or any(ord(char) < 33 or ord(char) > 126 for char in token):
        raise ValueError("Set PLAYBACK_LOAD_TOKEN to a valid short-lived app session token")
    async with httpx.AsyncClient(
        base_url=args.target, headers={"Authorization": f"Bearer {token}"},
        timeout=args.timeout, follow_redirects=False, trust_env=False,
        limits=httpx.Limits(
            max_connections=args.max_users + args.background_users + 4,
            max_keepalive_connections=args.max_users + args.background_users + 4,
        ),
    ) as client:
        harness = Harness(args, client)
        loop = asyncio.get_running_loop()
        def interrupted():
            harness.abort_reason = "Interrupted by operator/external safety monitor"
            harness.stop.set()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, interrupted)
        started = time.monotonic()
        try:
            async with asyncio.timeout(args.max_duration):
                await harness.run()
        except TimeoutError:
            harness.abort_reason = "Acknowledged wall-clock cap reached"
        except RuntimeError as error:
            harness.abort_reason = str(error)
        report = {
            "target": args.target, "scenario": args.scenario,
            "max_viewers": args.max_users, "background_clients": args.background_users,
            "duration_seconds": round(time.monotonic() - started, 3),
            "aborted": bool(harness.abort_reason), "abort_reason": harness.abort_reason,
            "phases": harness.reports,
            "note": "Virtual viewers share an authorized session; no unique-user auth claim.",
        }
        if args.output:
            Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report), flush=True)
        return 2 if harness.abort_reason else 0


def main():
    args_parser = parser()
    try:
        args = validate(args_parser.parse_args())
        if not args.execute:
            print(json.dumps({
                "dry_run": True, "network_requests": 0, "target": args.target,
                "scenario": args.scenario, "stages": args.stages,
                "stage_seconds": args.stage_seconds, "ramp_seconds": args.ramp_seconds,
                "baseline_seconds": args.baseline_seconds, "max_viewers": args.max_users,
                "background_clients": args.background_users, "wall_clock_cap": args.max_duration,
                "asset_count": len(args.ids), "segment_pace_seconds": SEGMENT_SECONDS,
                "execute_requires": "--execute --ack-target AND PLAYBACK_LOAD_TOKEN environment variable",
            }))
            return 0
        return asyncio.run(execute(args))
    except (ValueError, OSError, ImportError) as error:
        # Filesystem/dependency errors omit paths and environment contents.
        message = str(error) if isinstance(error, ValueError) else type(error).__name__
        args_parser.error(message)


if __name__ == "__main__":
    raise SystemExit(main())