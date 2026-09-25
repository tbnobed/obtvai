"""Durable failure accounting, shared by manual runs and the recurring runner."""
from datetime import datetime, timedelta

from .catalog_models import CatalogCheckpoint

GPU_FAILURE_LIMIT = 3
GPU_FAILURE_WINDOW_SECONDS = 1800


def failure_kind(message):
    value = str(message or "").lower()
    if any(word in value for word in (
        "cuda out of memory", "cuda error", "cudnn", "cublas", "gpu out of memory",
        "device-side assert", "nvml", "no cuda", "cuda unavailable", "cuda-capable",
    )):
        return "gpu"
    if any(word in value for word in (
        "broker", "redis", "kombu", "connection refused", "connection reset",
        "could not connect", "connection timed out", "network is unreachable",
        "server closed the connection", "operationalerror", "psycopg",
        "asyncpg", "database unavailable", "too many connections", "connecterror",
        "connecttimeout", "readtimeout",
        "no space left", "disk quota", "read-only file system", "stale file handle",
        "input/output error", "host is down", "cifs", "smb", "archive mount",
        "storage watermark", "storage_paths", "storage path", "archive storage",
        "archive mode", "archive_mode", "watermark path", "write probe",
    )):
        return "infrastructure"
    return "asset"


async def pause(db, reason):
    runner = await db.get(CatalogCheckpoint, "runner")
    if runner is None:
        runner = CatalogCheckpoint(id="runner", cursor={}, stats={})
        db.add(runner)
    runner.cursor = {**runner.cursor, "paused": True, "state": "paused"}
    runner.last_error = reason
    return runner


async def record_failure(db, candidate, token, kind, reason):
    """One event per asset attempt, even if several observers reconcile it.

    Per-asset checkpoint avoids an ever-growing global deduplication list and
    does not evict old identities while terminal failures are still polled.
    The caller owns the catalog advisory lock and commits event + policy state.
    """
    key = "failure:" + candidate.asset_id
    event = await db.get(CatalogCheckpoint, key)
    now = datetime.utcnow()
    if event is None:
        event = CatalogCheckpoint(id=key, cursor={}, stats={})
        db.add(event)
    kinds = event.cursor.get("kinds", [event.cursor.get("kind")]) if event.cursor.get("token") == token else []
    already_seen = kind in kinds
    event.cursor = {"token": token, "kind": kind, "kinds": list(dict.fromkeys([*kinds, kind]))}
    event.last_error, event.updated_at = reason, now
    if already_seen:
        return False
    if kind == "infrastructure":
        await pause(db, "Shared infrastructure failure: " + reason)
    elif kind == "gpu":
        circuit = await db.get(CatalogCheckpoint, "gpu_failures")
        if circuit is None:
            circuit = CatalogCheckpoint(id="gpu_failures", cursor={}, stats={})
            db.add(circuit)
        floor = now - timedelta(seconds=GPU_FAILURE_WINDOW_SECONDS)
        times = [value for value in circuit.cursor.get("times", [])
                 if datetime.fromisoformat(value) >= floor]
        times.append(now.isoformat())
        circuit.cursor = {"times": times[-GPU_FAILURE_LIMIT:]}
        circuit.updated_at = now
        if len(times) >= GPU_FAILURE_LIMIT:
            await pause(db, "Three GPU failures within 30 minutes; inspect GPU capacity before resuming")
    return True