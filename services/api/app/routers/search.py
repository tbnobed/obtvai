import time
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from ..database import get_db
from ..models import MediaAsset, TranscriptSegment, Scene, SearchHistory
from ..schemas import (
    SearchQuery, SearchResponse, SearchResultOut, SearchHistoryItemOut,
    ScriptMatchRequest, ScriptMatchLineOut, ScriptMatchResponse,
)
from ..config import settings

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def semantic_search(body: SearchQuery, db: AsyncSession = Depends(get_db)):
    t0 = time.time()
    results: list[SearchResultOut] = []

    try:
        from ..services.embedding import get_text_embedding, get_clip_text_embedding
        from ..services.qdrant_client import search_vectors

        query_embedding = await get_text_embedding(body.query)

        if body.search_type in ("transcript", "combined"):
            transcript_hits = await search_vectors(
                collection="transcripts",
                vector=query_embedding,
                limit=body.limit,
                media_id=body.media_id,
            )
            for hit in transcript_hits:
                seg_id = hit.payload.get("segment_id")
                seg_q = await db.execute(
                    select(TranscriptSegment, MediaAsset)
                    .join(MediaAsset, TranscriptSegment.media_id == MediaAsset.id)
                    .where(TranscriptSegment.id == seg_id)
                )
                row = seg_q.first()
                if row:
                    seg, asset = row
                    results.append(SearchResultOut(
                        media_id=asset.id,
                        filename=asset.filename,
                        thumbnail_url=asset.thumbnail_url,
                        start_time=seg.start_time,
                        end_time=seg.end_time,
                        score=hit.score,
                        match_type="transcript",
                        snippet=seg.text,
                    ))

        if body.search_type in ("visual", "combined"):
            # Visual search must query in CLIP space, not sentence-transformer space
            clip_query_embedding = await get_clip_text_embedding(body.query)
            visual_hits = await search_vectors(
                collection="scenes",
                vector=clip_query_embedding,
                limit=body.limit,
                media_id=body.media_id,
            )
            for hit in visual_hits:
                scene_id = hit.payload.get("scene_id")
                scene_q = await db.execute(
                    select(Scene, MediaAsset)
                    .join(MediaAsset, Scene.media_id == MediaAsset.id)
                    .where(Scene.id == scene_id)
                )
                row = scene_q.first()
                if row:
                    scene, asset = row
                    results.append(SearchResultOut(
                        media_id=asset.id,
                        filename=asset.filename,
                        thumbnail_url=scene.thumbnail_url or asset.thumbnail_url,
                        start_time=scene.start_time,
                        end_time=scene.end_time,
                        score=hit.score,
                        match_type="visual",
                        snippet=scene.description,
                    ))

    except Exception:
        import logging
        logging.getLogger("obtv.search").exception(
            "Vector search failed for query %r — falling back to text search", body.query
        )

    if not results:
        results = await _fallback_text_search(body, db)

    results.sort(key=lambda r: r.score, reverse=True)
    results = results[: body.limit]

    hist = SearchHistory(
        id=str(uuid.uuid4()),
        query=body.query,
        result_count=len(results),
        searched_at=datetime.utcnow(),
    )
    db.add(hist)
    await db.commit()

    took_ms = (time.time() - t0) * 1000
    return SearchResponse(results=results, query=body.query, took_ms=took_ms)


async def _fallback_text_search(body: SearchQuery, db: AsyncSession) -> list[SearchResultOut]:
    q = select(TranscriptSegment, MediaAsset).join(
        MediaAsset, TranscriptSegment.media_id == MediaAsset.id
    ).where(
        TranscriptSegment.text.ilike(f"%{body.query}%")
    )
    if body.media_id:
        q = q.where(TranscriptSegment.media_id == body.media_id)
    q = q.limit(body.limit)
    rows = (await db.execute(q)).all()
    return [
        SearchResultOut(
            media_id=asset.id,
            filename=asset.filename,
            thumbnail_url=asset.thumbnail_url,
            start_time=seg.start_time,
            end_time=seg.end_time,
            score=0.5,
            match_type="transcript",
            snippet=seg.text,
        )
        for seg, asset in rows
    ]


_MAX_SCRIPT_LINES = 50


def _split_script(script: str) -> list[str]:
    """Split a script into matchable lines: non-empty lines, long ones kept whole."""
    lines = [ln.strip() for ln in script.splitlines()]
    return [ln for ln in lines if len(ln) >= 3][:_MAX_SCRIPT_LINES]


@router.post("/script-match", response_model=ScriptMatchResponse)
async def script_match(body: ScriptMatchRequest, db: AsyncSession = Depends(get_db)):
    t0 = time.time()
    lines = _split_script(body.script)
    if not lines:
        return ScriptMatchResponse(lines=[], took_ms=0.0)
    per_line = min(max(body.matches_per_line, 1), 10)

    out_lines: list[ScriptMatchLineOut] = []
    embed_ok = True
    try:
        from ..services.embedding import get_text_embedding
        from ..services.qdrant_client import search_vectors
    except Exception:
        embed_ok = False

    for line in lines:
        matches: list[SearchResultOut] = []
        if embed_ok:
            try:
                vec = await get_text_embedding(line)
                hits = await search_vectors(
                    collection="transcripts",
                    vector=vec,
                    limit=per_line,
                    media_id=body.media_id,
                )
                for hit in hits:
                    seg_id = hit.payload.get("segment_id")
                    row = (await db.execute(
                        select(TranscriptSegment, MediaAsset)
                        .join(MediaAsset, TranscriptSegment.media_id == MediaAsset.id)
                        .where(TranscriptSegment.id == seg_id)
                    )).first()
                    if row:
                        seg, asset = row
                        matches.append(SearchResultOut(
                            media_id=asset.id,
                            filename=asset.filename,
                            thumbnail_url=asset.thumbnail_url,
                            start_time=seg.start_time,
                            end_time=seg.end_time,
                            score=hit.score,
                            match_type="transcript",
                            snippet=seg.text,
                        ))
            except Exception:
                import logging
                logging.getLogger("obtv.search").exception(
                    "Script-match vector search failed for line %r", line[:80]
                )
        if not matches:
            fallback_query = SearchQuery(
                query=line, media_id=body.media_id,
                search_type="transcript", limit=per_line,
            )
            matches = await _fallback_text_search(fallback_query, db)
        out_lines.append(ScriptMatchLineOut(line=line, matches=matches))

    took_ms = (time.time() - t0) * 1000
    return ScriptMatchResponse(lines=out_lines, took_ms=took_ms)


@router.get("/history", response_model=list[SearchHistoryItemOut])
async def get_search_history(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SearchHistory).order_by(desc(SearchHistory.searched_at)).limit(50)
    )
    return [SearchHistoryItemOut.model_validate(h) for h in result.scalars().all()]
