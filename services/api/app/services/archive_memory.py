"""Versioned archive knowledge. No LLM weights, guessed answers, or segment rebuilds."""
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import select, text

from ..config import settings
from ..models import MediaAsset, TranscriptSegment

log = logging.getLogger("obtv.archive_memory")
SCHEMA_VERSION = 1
CACHE_SECONDS = 300
TOPIC_COUNTS_SQL = """
    SELECT topic, COUNT(DISTINCT id) AS n FROM (
      SELECT id, btrim(regexp_replace(
        regexp_replace(lower(raw_topic), '[_-]+', ' ', 'g'),
        '[[:space:]]+', ' ', 'g')) AS topic
      FROM media_assets, jsonb_array_elements_text(topics) AS raw_topic
      WHERE topics IS NOT NULL
    ) normalized
    WHERE topic <> ''
    GROUP BY topic ORDER BY n DESC, topic LIMIT 20
"""


def collection_name() -> str:
    # Model identity, not merely dimension, defines an embedding space.
    digest = hashlib.sha256(settings.embeddings_model.encode()).hexdigest()[:12]
    return f"asset_memory_v1_{digest}"


def summary_text(asset) -> str:
    """Routing document only; never manufacture a summary for an unanalyzed asset."""
    synopsis = (asset.synopsis or "").strip()
    topics = [str(t) for t in (asset.topics or []) if isinstance(t, str)]
    if not synopsis and not topics:
        return ""
    return f"{asset.filename}\n{synopsis[:6000]}\nTopics: {', '.join(topics)[:1500]}"


def fingerprint(document: str) -> str:
    return hashlib.sha256(document.encode()).hexdigest()


def literal_pattern(term: str) -> str:
    """Escape SQL LIKE wildcards: users ask about literal archive content."""
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def mention_term(question: str) -> str | None:
    # Only an explicitly quoted literal, with no qualifiers outside the quotes.
    # Unquoted "faith or hope", dates, and person filters are not literal phrases.
    match = re.fullmatch(
        r"\s*how many (?:assets|videos|files|clips|recordings) "
        r"""(?:mention|contain the (?:word|phrase))\s+(?:"([^"\r\n]+)"|'([^'\r\n]+)')\s*[?.!]?\s*""",
        question, flags=re.I,
    )
    if not match:
        return None
    term = (match.group(1) or match.group(2)).strip()
    return term if 3 <= len(term) <= 120 else None


async def installed(db) -> bool:
    return bool((await db.execute(text(
        "SELECT to_regclass('public.archive_memory_versions') IS NOT NULL"
    ))).scalar())


async def version(db) -> str:
    rows = (await db.execute(text(
        "SELECT name, revision FROM archive_memory_versions ORDER BY name"
    ))).all()
    return "|".join(f"{name}:{revision}" for name, revision in rows)


async def cached(db, namespace: str, scope: str, builder):
    """Commit-independent durable cache; table triggers invalidate in same transaction.

    Current auth grants each authenticated role the same library. Scope is still
    explicit so single-asset queries cannot reuse global counts. Future ACLs must
    add their permission revision to scope, not share this library-wide namespace.
    """
    key = fingerprint(json.dumps([SCHEMA_VERSION, namespace, scope], ensure_ascii=False))
    revision = None
    try:
        # A missing table/permission/read timeout must not abort the caller's
        # conversation transaction. Catch AFTER savepoint rollback, not inside it.
        async with db.begin_nested():
            if await installed(db):
                revision = await version(db)
                row = (await db.execute(text(
                    "SELECT value FROM archive_memory_cache WHERE key=:key AND revision=:revision "
                    "AND expires_at > CURRENT_TIMESTAMP"
                ), {"key": key, "revision": revision})).first()
                if row:
                    return row[0]
            else:
                log.warning("Archive memory migration not installed; computing uncached")
    except Exception:
        revision = None
        log.warning("Archive memory cache read failed; computing uncached", exc_info=True)
    # Builder errors are real query errors; never hide them as a cache failure.
    result = await builder()
    # A concurrent ingest/delete must not label an old snapshot as current.
    if revision is not None:
        try:
            async with db.begin_nested():
                current_revision = await version(db)
            if current_revision == revision:
                await store_cache(key, revision, result)
        except Exception:
            log.warning("Archive memory cache write failed; returning measured result", exc_info=True)
    return result


async def store_cache(key, revision, result):
    from ..database import AsyncSessionLocal
    # Never hold a cache row's write lock during a remote LLM response.
    async with AsyncSessionLocal.begin() as db:
        await db.execute(text("SET LOCAL lock_timeout='2s'"))
        await db.execute(text(
            "INSERT INTO archive_memory_cache(key,revision,value,expires_at) "
            "VALUES(:key,:revision,CAST(:value AS jsonb),:expires) "
            "ON CONFLICT(key) DO UPDATE SET revision=EXCLUDED.revision, "
            "value=EXCLUDED.value, expires_at=EXCLUDED.expires_at"
        ), {"key": key, "revision": revision, "value": json.dumps(result),
            "expires": datetime.utcnow() + timedelta(seconds=CACHE_SECONDS)})


async def overview(db, builder) -> str:
    return await cached(db, "overview-v1", "shared-library", builder)


async def exact_mentions(db, term: str, media_id: str | None) -> int:
    from sqlalchemy import func

    async def count():
        query = select(func.count(func.distinct(TranscriptSegment.media_id))).join(
            MediaAsset, MediaAsset.id == TranscriptSegment.media_id
        ).where(TranscriptSegment.text.ilike(literal_pattern(term), escape="\\"))
        if media_id:
            query = query.where(MediaAsset.id == media_id)
        return (await db.execute(query)).scalar_one()

    # Python casefold is not PostgreSQL ILIKE equivalence (Straße != STRASSE).
    return await cached(db, "literal-mentions:" + term,
                        f"media:{media_id}" if media_id else "shared-library", count)


async def hierarchical_segments(db, vector, media_id=None, limit=4):
    """Augment global segment ANN with summary-routed evidence. Never replace it."""
    from .qdrant_client import search_vectors
    hits = await search_vectors(collection_name(), vector, limit=8, media_id=media_id)
    if not hits:
        return []
    ids = [h.payload.get("media_id") for h in hits if h.payload]
    query = select(MediaAsset).where(MediaAsset.id.in_(ids))
    if media_id:
        query = query.where(MediaAsset.id == media_id)
    assets = {a.id: a for a in (await db.execute(query)).scalars()}
    # Deleted/edited Qdrant points cannot resurrect stale evidence.
    valid = [h.payload["media_id"] for h in hits
             if h.payload and h.payload.get("media_id") in assets
             and h.payload.get("fingerprint") ==
             fingerprint(summary_text(assets[h.payload["media_id"]]))]
    if not valid:
        return []
    segments = await search_vectors("transcripts", vector, limit=limit, media_ids=valid)
    seg_ids = [h.payload.get("segment_id") for h in segments if h.payload]
    rows = (await db.execute(select(TranscriptSegment, MediaAsset).join(
        MediaAsset, TranscriptSegment.media_id == MediaAsset.id
    ).where(TranscriptSegment.id.in_(seg_ids), MediaAsset.id.in_(valid)))).all()
    by_id = {r[0].id: r for r in rows}
    return [by_id[s] for s in seg_ids if s in by_id]