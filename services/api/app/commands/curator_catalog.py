"""Operator command; default is one bounded dry-run, never scheduled at startup."""
import argparse
import asyncio
import json
import time
from datetime import datetime


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--confirm", default="")
    p.add_argument("--max-pages", type=int, default=1)
    p.add_argument("--max-assets", type=int, default=10)
    p.add_argument("--max-inflight", type=int, default=10)
    p.add_argument("--max-attempts", type=int, default=3)
    p.add_argument("--storage-path", action="append", default=[])
    p.add_argument("--min-free-gib", type=int, default=20)
    p.add_argument("--reserve-per-asset-mib", type=int, default=1024)
    p.add_argument("--enable-recurring", action="store_true")
    p.add_argument("--interval-seconds", type=int, default=3600)
    return p


async def execute(args):
    from ..catalog_service import CatalogOptions, run_catalog
    from ..database import engine
    options = CatalogOptions(
        dry_run=not args.apply, confirm=args.confirm, max_pages=args.max_pages,
        max_assets=args.max_assets, max_inflight=args.max_inflight,
        max_attempts=args.max_attempts,
        storage_paths=args.storage_path, min_free_bytes=args.min_free_gib * 1024**3,
        reserve_per_asset_bytes=args.reserve_per_asset_mib * 1024**2,
    )
    try:
        return await run_catalog(options)
    finally:
        await engine.dispose()


async def recurring_tick(args):
    """Durable pause/error budget survives Docker restarts. No invisible retries."""
    from ..catalog_models import CatalogCheckpoint
    from ..database import AsyncSessionLocal, engine
    from ..catalog import cutoff
    from .import_curator_workbook import _safe_error
    try:
        async with AsyncSessionLocal() as db:
            row = await db.get(CatalogCheckpoint, "runner")
            if row is None:
                row = CatalogCheckpoint(id="runner", cursor={}, stats={})
                db.add(row)
            state = dict(row.cursor)
            state.update(interval_seconds=args.interval_seconds, cutoff=cutoff().isoformat(),
                         max_inflight=args.max_inflight, max_assets=args.max_assets,
                         dry_run=not args.apply)
            state["state"] = "paused" if state.get("paused") else "running"
            row.cursor, row.updated_at = state, datetime.utcnow()
            await db.commit()
            if state.get("paused"):
                return {"paused": True, "error": row.last_error}
        try:
            result = await execute(args)
        except Exception as exc:
            result = {"error": _safe_error(exc), "stats": {"errors": 1, "stop": "error"}}
        async with AsyncSessionLocal() as db:
            row = await db.get(CatalogCheckpoint, "runner")
            state = dict(row.cursor)
            stats = result.get("stats", {})
            if stats.get("errors"):
                state["consecutive_errors"] = state.get("consecutive_errors", 0) + 1
            elif stats.get("admitted"):
                state["consecutive_errors"] = 0
            paused = bool(state.get("paused") or stats.get("worker_failures") or state.get("consecutive_errors", 0) >= 3)
            state.update(paused=paused, state="paused" if paused else "waiting",
                         last_run_id=result.get("run_id"))
            row.cursor, row.stats, row.updated_at = state, stats, datetime.utcnow()
            row.last_error = result.get("error")
            if paused:
                row.last_error = row.last_error or (
                    "Worker processing failed; inspect catalog/jobs before resuming"
                    if stats.get("worker_failures") else "Three admission/discovery failures; inspect latest runs")
            await db.commit()
        return result
    finally:
        await engine.dispose()


def main():
    args = parser().parse_args()
    if args.interval_seconds < 60:
        raise SystemExit("--interval-seconds must be at least 60")
    while True:
        try:
            result = asyncio.run(recurring_tick(args) if args.enable_recurring else execute(args))
        except Exception as exc:
            from .import_curator_workbook import _safe_error
            print(json.dumps({"error": _safe_error(exc)}), flush=True)
            raise SystemExit(1) from None
        print(json.dumps(result, default=str), flush=True)
        if not args.enable_recurring:
            raise SystemExit(1 if result["stats"]["errors"] else 0)
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()