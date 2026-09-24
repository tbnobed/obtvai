"""Operator command; default is one bounded dry-run, never scheduled at startup."""
import argparse
import asyncio
import json
import time


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


def main():
    args = parser().parse_args()
    if args.interval_seconds < 60:
        raise SystemExit("--interval-seconds must be at least 60")
    while True:
        try:
            result = asyncio.run(execute(args))
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