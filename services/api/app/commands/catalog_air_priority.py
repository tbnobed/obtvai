"""Resumable metadata-only scan; never queues, resets, or retries media jobs."""
import argparse
import asyncio
from datetime import datetime

from sqlalchemy import select, text
from fastapi.concurrency import run_in_threadpool
from app.catalog import CatalogClient, PAGE_SIZE, enabled_asset_types, exact_id, eligibility
from app.catalog_models import CatalogAsset, CatalogCheckpoint
from app.database import AsyncSessionLocal


async def run(max_pages):
    client = CatalogClient()
    types = enabled_asset_types()
    for _ in range(max_pages):
        async with AsyncSessionLocal() as db:
            checkpoint = await db.get(CatalogCheckpoint, "original-air-discovery")
            cursor = dict(checkpoint.cursor) if checkpoint else {"type_index": 0, "offset": 0}
            if cursor["type_index"] >= len(types):
                print("Original-air metadata scan complete", flush=True)
                return
            kind = types[cursor["type_index"]]
            page = await run_in_threadpool(
                client.page, kind, cursor["offset"], dated=False, air_dated=True)
            # Coordinate with admission without holding its lock during HTTP.
            await db.rollback()
            while not (await db.execute(text(
                "SELECT pg_try_advisory_xact_lock(hashtext('obtv_catalog_run'))"
            ))).scalar():
                await db.rollback()
                await asyncio.sleep(1)
            checkpoint = await db.get(CatalogCheckpoint, "original-air-discovery")
            if checkpoint and checkpoint.cursor != cursor:
                await db.rollback()
                continue
            ids = [exact_id(asset) for asset in page]
            rows = (await db.execute(select(CatalogAsset).where(
                CatalogAsset.asset_id.in_(ids)))).scalars().all()
            existing = {row.asset_id: row for row in rows}
            priority_count = 0
            for asset, asset_id in zip(page, ids):
                state, error = eligibility(asset)
                row = existing.get(asset_id)
                if row is None:
                    db.add(CatalogAsset(asset_id=asset_id, asset_type=kind,
                        metadata_snapshot=asset, status=state, error=error))
                else:
                    row.metadata_snapshot = asset
                    # Preserve attempts, job IDs, active status, and FIFO age.
                    if row.status in ("eligible", "review", "excluded"):
                        row.status, row.error = state, error
                priority_count += asset.get("_obtv_original_air_year") == 2026
            next_cursor = dict(cursor)
            if len(page) < PAGE_SIZE:
                next_cursor.update(type_index=cursor["type_index"] + 1, offset=0)
            else:
                next_cursor["offset"] += len(page)
            if checkpoint is None:
                checkpoint = CatalogCheckpoint(id="original-air-discovery", cursor=next_cursor)
                db.add(checkpoint)
            else:
                checkpoint.cursor = next_cursor
            checkpoint.updated_at = datetime.utcnow()
            await db.commit()
            print(f"{kind} offset={cursor['offset']} checked={len(page)} year2026={priority_count}", flush=True)
        await asyncio.sleep(0.2)
    print("Page budget reached; rerun to resume", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-pages", type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.max_pages <= 2000:
        parser.error("max-pages must be between 1 and 2000")
    asyncio.run(run(args.max_pages))
