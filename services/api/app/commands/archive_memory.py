"""Explicit, bounded archive memory maintenance. Never runs expensive DDL at boot."""
import argparse
import asyncio
import json
import logging
import uuid

from sqlalchemy import text, select

from ..database import engine, AsyncSessionLocal
from ..models import MediaAsset
from ..services.archive_memory import collection_name, summary_text, fingerprint, installed

log = logging.getLogger("obtv.archive_memory")

# Trigrams retain substring/name/phrase semantics used by QA and search. A LIMIT
# by itself does not prevent a full transcript scan.
INDEXES = {
    "ix_archive_transcript_trgm": "ON transcript_segments USING gin (text gin_trgm_ops)",
    "ix_archive_person_trgm": "ON people USING gin (display_name gin_trgm_ops)",
}


async def migrate():
    from .archive_memory_schema import STATEMENTS, trigger_statements
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL lock_timeout='2s'"))
        for statement in STATEMENTS + trigger_statements():
            await conn.execute(text(statement))
    # CONCURRENTLY cannot run in a transaction; an interrupted build can leave
    # an invalid index, which IF NOT EXISTS would silently preserve.
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("SET lock_timeout='2s'"))
        for name, definition in INDEXES.items():
            valid = (await conn.execute(text(
                "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
                "WHERE c.relname=:name"
            ), {"name": name})).scalar()
            if valid is False:
                await conn.execute(text(f"DROP INDEX CONCURRENTLY {name}"))
            if valid is not True:
                await conn.execute(text(f"CREATE INDEX CONCURRENTLY {name} {definition}"))


async def backfill(limit, after):
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(
            "SELECT id FROM media_assets WHERE id > :after ORDER BY id LIMIT :limit"
        ), {"after": after, "limit": limit})
        ids = list(result.scalars())
        for media_id in ids:
            await db.execute(text(
                "INSERT INTO archive_memory_dirty(media_id,revision) "
                "VALUES(:id,nextval('archive_memory_revision_seq')) ON CONFLICT(media_id) "
                "DO UPDATE SET revision=EXCLUDED.revision, queued_at=CURRENT_TIMESTAMP"
            ), {"id": media_id})
        await db.commit()
        return {"enqueued": len(ids), "next_after": ids[-1] if ids else after}


async def drain(limit):
    """One maintenance process at a time, with a durable retryable SQL outbox.

    A failed Qdrant write never acknowledges work. Revision-conditional deletion
    prevents edits during embedding from being lost. No full-library vector scan.
    """
    from ..services.embedding import get_text_embedding
    from ..services.qdrant_client import get_client
    from qdrant_client.models import Distance, VectorParams, PointStruct
    processed = 0
    async with engine.connect() as lock:
        if not (await lock.execute(text(
            "SELECT pg_try_advisory_lock(hashtext('archive_memory_drain'))"
        ))).scalar():
            return {"processed": 0, "busy": True}
        try:
            async with AsyncSessionLocal() as db:
                if not await installed(db):
                    raise RuntimeError("Run archive_memory migrate before drain")
                await db.execute(text(
                    "DELETE FROM archive_memory_cache WHERE key IN "
                    "(SELECT key FROM archive_memory_cache WHERE expires_at < CURRENT_TIMESTAMP "
                    "LIMIT 1000)"
                ))
                await db.commit()
                rows = (await db.execute(text(
                    "SELECT media_id,revision FROM archive_memory_dirty "
                    "ORDER BY queued_at,media_id LIMIT :limit"
                ), {"limit": limit})).all()
                await db.rollback()
                client = get_client()
                name = collection_name()
                exists = await client.collection_exists(name)
                for mid, revision in rows:
                    asset = await db.get(MediaAsset, mid)
                    document = summary_text(asset) if asset else ""
                    await db.rollback()
                    point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "asset-memory:" + mid))
                    if document:
                        vector = await get_text_embedding(document)
                        if not exists:
                            await client.create_collection(name, vectors_config=VectorParams(
                                size=len(vector), distance=Distance.COSINE))
                            exists = True
                        info = await client.get_collection(name)
                        if info.config.params.vectors.size != len(vector):
                            raise RuntimeError("Asset memory vector dimension mismatch; refusing destructive recreation")
                        await client.upsert(name, points=[PointStruct(
                            id=point_id, vector=vector,
                            payload={"media_id": mid, "fingerprint": fingerprint(document)}
                        )], wait=True)
                    elif exists:
                        await client.delete(name, points_selector=[point_id], wait=True)
                    await db.execute(text(
                        "DELETE FROM archive_memory_dirty WHERE media_id=:id AND revision=:revision"
                    ), {"id": mid, "revision": revision})
                    await db.commit()
                    processed += 1
        finally:
            await lock.execute(text("SELECT pg_advisory_unlock(hashtext('archive_memory_drain'))"))
    return {"processed": processed}


async def status():
    from ..services.qdrant_client import get_client
    async with AsyncSessionLocal() as db:
        if not await installed(db):
            return {"installed": False}
        dirty = (await db.execute(text("SELECT count(*),min(queued_at) FROM archive_memory_dirty"))).one()
        versions = (await db.execute(text(
            "SELECT name,revision FROM archive_memory_versions ORDER BY name"
        ))).all()
        cache_rows = (await db.execute(text(
            "SELECT count(*) FROM archive_memory_cache WHERE expires_at > CURRENT_TIMESTAMP"
        ))).scalar()
        client = get_client()
        exists = await client.collection_exists(collection_name())
        point_count = (await client.get_collection(collection_name())).points_count if exists else 0
        return {"installed": True, "collection": collection_name(),
                "pending": dirty[0], "oldest_pending": str(dirty[1]) if dirty[1] else None,
                "versions": dict(versions), "unexpired_cache_rows": cache_rows,
                "summary_collection_exists": exists, "summary_points": point_count}


async def benchmark(term):
    """Explicit query timing/plan, bounded by a database timeout; warms count cache."""
    import time
    from ..services.archive_memory import exact_mentions, literal_pattern
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET LOCAL statement_timeout='15s'"))
        plan = (await db.execute(text(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
            "SELECT count(DISTINCT t.media_id) FROM transcript_segments t "
            "JOIN media_assets a ON a.id=t.media_id WHERE t.text ILIKE :pattern ESCAPE '\\'"
        ), {"pattern": literal_pattern(term)})).scalar()
        timings = []
        for _ in range(2):
            start = time.perf_counter()
            count = await exact_mentions(db, term, None)
            timings.append(round(1000 * (time.perf_counter() - start), 2))
        return {"count": count, "count_call_ms": timings, "plan": plan}


async def run(args):
    if args.action == "migrate":
        await migrate()
        print(json.dumps({"migrated": True}))
    elif args.action == "backfill":
        print(json.dumps(await backfill(args.limit, args.after)))
    elif args.action == "status":
        print(json.dumps(await status()))
    elif args.action == "benchmark":
        print(json.dumps(await benchmark(args.term)))
    else:
        while True:
            try:
                print(json.dumps(await drain(args.limit)), flush=True)
            except Exception:
                log.exception("Archive memory drain failed; pending work retained")
                if not args.watch:
                    raise
            if not args.watch:
                break
            await asyncio.sleep(args.interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["migrate", "backfill", "drain", "status", "benchmark"])
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--after", default="")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--term", default="faith")
    args = parser.parse_args()
    if not 1 <= args.limit <= 100 or args.interval < 30:
        parser.error("limit must be 1..100; interval must be >=30 seconds")
    if args.watch and args.action != "drain":
        parser.error("--watch is only valid for drain")
    if not 3 <= len(args.term) <= 120:
        parser.error("term must be 3..120 characters")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()