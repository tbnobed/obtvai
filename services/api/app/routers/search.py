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

# CLIP text->image cosine scores live in a much lower band (~0.15-0.35) than
# sentence-transformer text-text scores (~0.3-0.6). Sorting the merged list by
# raw score buries every visual hit below the transcript hits, so visual
# results never survive the top-N cut. Rescale CLIP scores into a comparable
# 0-1 band before merging.
_CLIP_SCORE_FLOOR = 0.15
_CLIP_SCORE_CEIL = 0.35
# Below this rescaled score a visual hit is essentially noise — CLIP assigns
# ~floor-level similarity to *everything*, including black frames, so weak
# hits must be dropped rather than shown.
_MIN_VISUAL_SCORE = 0.25


def _rescale_clip_score(score: float) -> float:
    span = _CLIP_SCORE_CEIL - _CLIP_SCORE_FLOOR
    return max(0.0, min(1.0, (score - _CLIP_SCORE_FLOOR) / span))


def _is_black_thumbnail(thumbnail_url: str | None) -> bool:
    """Query-time guard against black/uniform scenes that were embedded before
    the worker learned to skip them (legacy vectors persist in Qdrant)."""
    if not thumbnail_url:
        return False
    import os
    path = os.path.join(settings.thumbnails_dir, os.path.basename(thumbnail_url))
    if not os.path.exists(path):
        return False
    try:
        from PIL import Image
        import numpy as np
        with Image.open(path) as img:
            arr = np.asarray(img.convert("RGB").resize((64, 64)))
        return bool(arr.mean() < 10 or arr.std() < 5)
    except Exception:
        return False


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
            # Visual search must query in CLIP space, not sentence-transformer space.
            # CLIP was trained on captioned photos — "a photo of a watch" retrieves
            # far better than the bare word "watch".
            clip_query_embedding = await get_clip_text_embedding(f"a photo of {body.query}")
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
                    rescaled = _rescale_clip_score(hit.score)
                    if rescaled < _MIN_VISUAL_SCORE:
                        continue
                    if _is_black_thumbnail(scene.thumbnail_url):
                        continue
                    results.append(SearchResultOut(
                        media_id=asset.id,
                        filename=asset.filename,
                        thumbnail_url=scene.thumbnail_url or asset.thumbnail_url,
                        start_time=scene.start_time,
                        end_time=scene.end_time,
                        score=rescaled,
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
    if body.search_type == "combined":
        # Guarantee visual representation: even after rescaling, a wall of
        # transcript hits must not push every visual match past the cut.
        visual = [r for r in results if r.match_type == "visual"]
        transcript_r = [r for r in results if r.match_type != "visual"]
        reserve = min(len(visual), body.limit, max(3, body.limit // 4))
        kept = transcript_r[: max(0, body.limit - reserve)] + visual[:reserve]
        # Anything left competes for remaining slots on score alone.
        leftover = [r for r in results if r not in kept]
        kept += leftover[: body.limit - len(kept)]
        results = sorted(kept, key=lambda r: r.score, reverse=True)
    else:
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
