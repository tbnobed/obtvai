import re
import time
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from ..database import get_db
from ..models import MediaAsset, TranscriptSegment, Scene, SearchHistory, Person, PersonAppearance
from ..schemas import (
    SearchQuery, SearchResponse, SearchResultOut, SearchHistoryItemOut,
    ScriptMatchRequest, ScriptMatchLineOut, ScriptMatchResponse,
    ReanalyzeOut,
)
from ..config import settings

router = APIRouter(prefix="/search", tags=["search"])

# Vision text->image cosine scores live in a much lower band than
# sentence-transformer text-text scores (~0.3-0.6). Sorting the merged list by
# raw score buries every visual hit below the transcript hits, so visual
# results never survive the top-N cut. Rescale vision scores into a comparable
# 0-1 band before merging. The band is model-family specific:
# - CLIP: matches land ~0.15-0.35
# - SigLIP/SigLIP-2 (sigmoid-trained, no softmax calibration): cosine sims are
#   lower overall — non-matches sit near 0, good matches ~0.05-0.25.
if "siglip" in settings.vision_model.lower():
    _CLIP_SCORE_FLOOR = 0.02
    _CLIP_SCORE_CEIL = 0.22
else:
    _CLIP_SCORE_FLOOR = 0.15
    _CLIP_SCORE_CEIL = 0.35
# Below this rescaled score a visual hit is essentially noise — the vision
# model assigns ~floor-level similarity to *everything*, including black
# frames, so weak hits must be dropped rather than shown.
_MIN_VISUAL_SCORE = 0.25
# Small/background objects ("soda can on the desk") legitimately score well
# below _MIN_VISUAL_SCORE — the object covers a tiny part of the frame. When
# the user *explicitly* asked for visual search and nothing clears the main
# bar, surface the best few hits above this lower noise floor rather than
# returning a hard zero.
_MIN_VISUAL_SCORE_RELAXED = 0.10
_RELAXED_VISUAL_LIMIT = 24
# First-pass cap on visual scenes from a single asset: broadcast footage has
# many near-identical shots, and without a cap one file's duplicates push
# every other asset's valid match past the result limit.
_MAX_VISUAL_PER_ASSET = 3


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

    # Quoted queries ("israeli flag") mean the exact phrase: transcript
    # matching becomes a literal substring search, and the visual query is
    # embedded without the quote marks.
    phrase_m = re.match(r'^\s*["“\']\s*(.+?)\s*["”\']\s*$', body.query or "")
    exact_phrase = phrase_m.group(1) if phrase_m else None
    query_text = exact_phrase or body.query

    # Person-identity search: CLIP/SigLIP embeds the query as generic visual
    # concepts — it has no idea who a specific named person is. Identities live
    # in the People system, so when the query names a known person, surface
    # their identified appearances directly instead of relying on the vision
    # model to guess from pixels.
    person_media_ids: set[str] = set()
    q_norm = query_text.strip().lower()
    if q_norm:
        people_q = await db.execute(select(Person))
        matched = [
            p for p in people_q.scalars().all()
            if p.display_name and (
                p.display_name.lower() == q_norm or p.display_name.lower() in q_norm
            )
        ]
        for person in matched:
            app_q = await db.execute(
                select(PersonAppearance, MediaAsset)
                .join(MediaAsset, PersonAppearance.media_id == MediaAsset.id)
                .where(PersonAppearance.person_id == person.id)
            )
            for appearance, asset in app_q.all():
                if body.media_id and asset.id != body.media_id:
                    continue
                if body.media_ids and asset.id not in body.media_ids:
                    continue
                if asset.id in person_media_ids:
                    continue
                person_media_ids.add(asset.id)
                start = appearance.first_spoken_at or 0.0
                # Prefer a scene frame near where the person first appears
                # over the asset's generic poster thumbnail.
                scene_q = await db.execute(
                    select(Scene)
                    .where(Scene.media_id == asset.id, Scene.start_time <= start + 2.0)
                    .order_by(desc(Scene.start_time))
                    .limit(1)
                )
                scene = scene_q.scalar_one_or_none()
                thumb = None
                if scene and not _is_black_thumbnail(scene.thumbnail_url):
                    thumb = scene.thumbnail_url
                mins = int((appearance.speaking_seconds or 0) // 60)
                snippet = f"{person.display_name} identified in this asset"
                if mins:
                    snippet += f" · speaks for {mins} min"
                results.append(SearchResultOut(
                    media_id=asset.id,
                    filename=asset.filename,
                    thumbnail_url=thumb or asset.thumbnail_url,
                    start_time=start,
                    end_time=start + (appearance.speaking_seconds or 0.0),
                    score=1.0,
                    match_type="person",
                    snippet=snippet,
                ))

    try:
        from ..services.embedding import get_text_embedding, get_clip_text_embedding
        from ..services.qdrant_client import search_vectors

        query_embedding = await get_text_embedding(query_text)

        if exact_phrase and body.search_type in ("transcript", "combined"):
            q = select(TranscriptSegment, MediaAsset).join(
                MediaAsset, TranscriptSegment.media_id == MediaAsset.id
            ).where(TranscriptSegment.text.ilike(f"%{exact_phrase}%"))
            if body.media_id:
                q = q.where(TranscriptSegment.media_id == body.media_id)
            elif body.media_ids:
                q = q.where(TranscriptSegment.media_id.in_(body.media_ids))
            q = q.order_by(MediaAsset.filename, TranscriptSegment.start_time).limit(body.limit)
            for seg, asset in (await db.execute(q)).all():
                results.append(SearchResultOut(
                    media_id=asset.id,
                    filename=asset.filename,
                    thumbnail_url=asset.thumbnail_url,
                    start_time=seg.start_time,
                    end_time=seg.end_time,
                    score=1.0,
                    match_type="transcript",
                    snippet=seg.text,
                ))
        elif body.search_type in ("transcript", "combined"):
            transcript_hits = await search_vectors(
                collection="transcripts",
                vector=query_embedding,
                limit=body.limit,
                media_id=body.media_id,
                media_ids=body.media_ids,
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
            # Prompt ensembling: a single caption template biases retrieval
            # toward one framing of the concept (close-up product shots).
            # Embedding several phrasings and keeping each scene's best score
            # catches the same object in context — held, on a podium, in the
            # background — which a lone "a photo of X" query misses.
            prompts = [
                f"a photo of {query_text}",
                f"a close-up photo of a {query_text}",
                f"a photo of a person with a {query_text}",
                f"a scene showing {query_text}",
            ]
            fetch_limit = min(max(body.limit * 5, 50), 1000)
            # Fetch well past the requested limit: broadcast footage is full of
            # near-duplicate scenes (e.g. 20 shots of the same flags), and a
            # shallow fetch lets one asset crowd every other match out of the
            # candidate pool before diversity capping can help.
            best_hits: dict = {}
            for prompt in prompts:
                clip_query_embedding = await get_clip_text_embedding(prompt)
                for hit in await search_vectors(
                    collection="scenes",
                    vector=clip_query_embedding,
                    limit=fetch_limit,
                    media_id=body.media_id,
                    media_ids=body.media_ids,
                ):
                    sid = hit.payload.get("scene_id")
                    prev = best_hits.get(sid)
                    if prev is None or hit.score > prev.score:
                        best_hits[sid] = hit
            visual_hits = sorted(best_hits.values(), key=lambda h: h.score, reverse=True)
            visual_candidates: list[tuple[float, SearchResultOut]] = []
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
                    # Single-asset searches keep even weak candidates: the
                    # pool is tiny and the user explicitly asked about THIS
                    # file, so a best-effort ranked list beats "0 results"
                    # (small objects like a mic score well below the floor).
                    floor = 0.02 if body.media_id else _MIN_VISUAL_SCORE_RELAXED
                    if rescaled < floor:
                        continue
                    if _is_black_thumbnail(scene.thumbnail_url):
                        continue
                    # Densely-sampled frame vectors carry the exact frame time —
                    # point the result at that moment instead of the whole scene.
                    ft = hit.payload.get("frame_time")
                    r_start = max(scene.start_time, float(ft) - 2.0) if ft is not None else scene.start_time
                    r_end = min(scene.end_time, float(ft) + 3.0) if ft is not None else scene.end_time
                    visual_candidates.append((rescaled, SearchResultOut(
                        media_id=asset.id,
                        filename=asset.filename,
                        thumbnail_url=scene.thumbnail_url or asset.thumbnail_url,
                        start_time=r_start,
                        end_time=max(r_end, r_start + 1.0),
                        score=rescaled,
                        match_type="visual",
                        snippet=scene.description,
                    )))
            # Diversity cap: at most _MAX_VISUAL_PER_ASSET scenes per asset in
            # the first pass, so 20 near-identical shots from one file don't
            # bury a valid match from another (fill remaining slots afterwards).
            visual_candidates.sort(key=lambda t: t[0], reverse=True)
            per_asset: dict[str, int] = {}
            capped: list[tuple[float, SearchResultOut]] = []
            overflow: list[tuple[float, SearchResultOut]] = []
            for s, r in visual_candidates:
                n = per_asset.get(r.media_id, 0)
                if n < _MAX_VISUAL_PER_ASSET:
                    per_asset[r.media_id] = n + 1
                    capped.append((s, r))
                else:
                    overflow.append((s, r))
            confident = [r for s, r in capped if s >= _MIN_VISUAL_SCORE]
            if confident:
                if len(confident) < body.limit:
                    confident.extend(
                        r for s, r in overflow if s >= _MIN_VISUAL_SCORE
                    )
                results.extend(confident[: body.limit])
            elif (body.search_type == "visual" or body.media_id) and visual_candidates:
                # Explicit visual search: best-effort weak matches beat a
                # hard "0 results" (small objects score below the main bar).
                visual_candidates.sort(key=lambda t: t[0], reverse=True)
                results.extend(r for _, r in visual_candidates[:_RELAXED_VISUAL_LIMIT])

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


@router.post("/reindex", response_model=ReanalyzeOut, status_code=202)
async def reindex_library(db: AsyncSession = Depends(get_db)):
    """Rebuild search indexes across the whole library after an embedding /
    vision model change: re-runs visual_embed (scene vectors) and index
    (transcript vectors) on every ready asset. Old-dimension Qdrant
    collections are auto-recreated by the workers."""
    from sqlalchemy import text as sa_text
    from ..models import ProcessingJob
    from .jobs import prune_finished_jobs
    from ..worker_client import enqueue_job

    # Serialize concurrent reindex requests: the lock is held until this
    # transaction commits, so a second caller waits and then sees the pending
    # jobs the first one created (its active-job check skips those assets).
    await db.execute(sa_text("SELECT pg_advisory_xact_lock(hashtext('obtv_reindex'))"))

    assets = (
        await db.execute(
            select(MediaAsset.id, MediaAsset.sprite_url).where(MediaAsset.status == "ready")
        )
    ).all()

    assets_queued = 0
    jobs_created = 0
    pending: list[tuple[str, str, str]] = []

    for media_id, sprite_url in assets:
        active = (
            await db.execute(
                select(ProcessingJob.id).where(
                    ProcessingJob.media_id == media_id,
                    ProcessingJob.job_type.in_(("visual_embed", "index", "sprite")),
                    ProcessingJob.status.in_(("pending", "running")),
                )
            )
        ).scalars().first()
        if active:
            continue

        has_scenes = (
            await db.execute(
                sa_text("SELECT 1 FROM scenes WHERE media_id = :mid LIMIT 1"),
                {"mid": media_id},
            )
        ).first()

        queued_any = False
        job_types = ["index"]
        # Sprite first: dense visual embedding crops frames from the sprite
        # sheet (falls back to slow per-frame ffmpeg seeks without it).
        if not sprite_url:
            job_types.insert(0, "sprite")
        if has_scenes:
            job_types.append("visual_embed")
        for job_type in job_types:
            await prune_finished_jobs(db, media_id, job_type)
            job = ProcessingJob(media_id=media_id, job_type=job_type, status="pending", logs=[])
            db.add(job)
            await db.flush()
            pending.append((job_type, media_id, job.id))
            jobs_created += 1
            queued_any = True
        if queued_any:
            assets_queued += 1

    await db.commit()

    for job_type, media_id, job_id in pending:
        await enqueue_job(job_type, media_id, job_id)

    return ReanalyzeOut(assets_queued=assets_queued, jobs_created=jobs_created)


async def _fallback_text_search(body: SearchQuery, db: AsyncSession) -> list[SearchResultOut]:
    q = select(TranscriptSegment, MediaAsset).join(
        MediaAsset, TranscriptSegment.media_id == MediaAsset.id
    ).where(
        TranscriptSegment.text.ilike(f"%{body.query}%")
    )
    if body.media_id:
        q = q.where(TranscriptSegment.media_id == body.media_id)
    elif body.media_ids:
        q = q.where(TranscriptSegment.media_id.in_(body.media_ids))
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
                    media_ids=body.media_ids,
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
                query=line, media_id=body.media_id, media_ids=body.media_ids,
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
