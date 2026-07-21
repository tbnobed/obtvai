"""Visual awareness helpers for the AI editor passes (reel/story curation).

Gives the LLM curator eyes: for any clip span we can report who is on
camera, how visually busy the span is (shot changes), and a SigLIP visual
fingerprint (mean of the span's scene embeddings, fetched from Qdrant).
That fingerprint lets the assembler detect back-to-back visually
near-identical clips and reorder for variety.

Everything here degrades gracefully: assets without face/scene/embedding
data simply yield an empty profile and no similarity signal.
"""
import uuid

_qdrant_client = None


def _get_qdrant_cached():
    """One Qdrant client per worker process — profiles are fetched in bulk
    during a curation pass and reconnecting per clip is wasteful."""
    global _qdrant_client
    if _qdrant_client is None:
        from tasks.qdrant_util import get_qdrant
        _qdrant_client = get_qdrant()
    return _qdrant_client


def _fetch_scene_vectors(scene_ids: list[str]) -> dict[str, list[float]]:
    """Retrieve scene embeddings from Qdrant by scene id. Best-effort."""
    if not scene_ids:
        return {}
    try:
        from tasks.qdrant_util import qdrant_retry
        qdrant = _get_qdrant_cached()
        point_ids = [str(uuid.uuid5(uuid.NAMESPACE_DNS, sid)) for sid in scene_ids]
        points = qdrant_retry(
            qdrant.retrieve,
            collection_name="scenes",
            ids=point_ids,
            with_vectors=True,
            with_payload=True,
        )
        out = {}
        for p in points or []:
            sid = (p.payload or {}).get("scene_id")
            if sid and p.vector:
                out[sid] = list(p.vector)
        return out
    except Exception:
        return {}


def clip_visual_profile(db, media_id: str, start: float, end: float) -> dict:
    """Visual profile of one clip span.

    Returns {"people": [names], "scene_count": int, "vector": [..] | None}.

    Uses its OWN short-lived read session (the `db` argument is accepted for
    call-site symmetry but not used for queries) so a failed read can never
    abort or roll back the caller's in-flight transaction.
    """
    from sqlalchemy import text
    from db import get_session

    profile: dict = {"people": [], "scene_count": 0, "vector": None}
    span = max(0.5, float(end) - float(start))
    rdb = get_session()

    # Who is on camera: face-cluster appearances overlapping the span,
    # resolved to person names where identify has linked them.
    try:
        rows = rdb.execute(
            text("""
                SELECT fc.cluster_id, fc.label, fc.appearances, p.display_name
                FROM face_clusters fc
                LEFT JOIN person_appearances pa
                    ON pa.face_cluster_id = fc.cluster_id AND pa.media_id = fc.media_id
                LEFT JOIN people p ON p.id = pa.person_id
                WHERE fc.media_id = :mid
            """),
            {"mid": media_id},
        ).fetchall()
        names = []
        for _cid, label, appearances, display_name in rows:
            for a in (appearances or []):
                try:
                    if float(a["end_time"]) >= start and float(a["start_time"]) <= end:
                        names.append(display_name or label or "unidentified person")
                        break
                except (KeyError, TypeError, ValueError):
                    continue
        # De-dupe, keep order
        seen = set()
        profile["people"] = [n for n in names if not (n in seen or seen.add(n))][:6]
    except Exception:
        rdb.rollback()

    # Shot density + embedding source: scenes overlapping the span.
    try:
        scene_rows = rdb.execute(
            text("""
                SELECT id, embedding_id FROM scenes
                WHERE media_id = :mid AND end_time >= :s AND start_time <= :e
                ORDER BY start_time
            """),
            {"mid": media_id, "s": float(start), "e": float(end)},
        ).fetchall()
        profile["scene_count"] = len(scene_rows)
        embedded_ids = [r[0] for r in scene_rows if r[1]][:8]
        vectors = _fetch_scene_vectors(embedded_ids)
        if vectors:
            dim = len(next(iter(vectors.values())))
            mean = [0.0] * dim
            for v in vectors.values():
                for i, x in enumerate(v):
                    mean[i] += x
            n = len(vectors)
            mean = [x / n for x in mean]
            norm = sum(x * x for x in mean) ** 0.5
            if norm > 1e-6:
                profile["vector"] = [x / norm for x in mean]
    except Exception:
        rdb.rollback()
    finally:
        rdb.close()

    profile["shot_changes_per_min"] = round(max(0, profile["scene_count"] - 1) / (span / 60.0), 1)
    return profile


def describe_profile(profile: dict) -> str:
    """Compact one-line visual description for the LLM prompt."""
    parts = []
    if profile.get("people"):
        parts.append("on camera: " + ", ".join(profile["people"]))
    sc = profile.get("scene_count") or 0
    if sc > 1:
        parts.append(f"{sc} shots ({profile.get('shot_changes_per_min', 0)} cuts/min)")
    elif sc == 1:
        parts.append("single static shot")
    return "; ".join(parts) if parts else "no visual data"


def visual_similarity(a: dict, b: dict) -> float | None:
    """Cosine similarity of two clip profiles, or None when unavailable."""
    va, vb = a.get("vector"), b.get("vector")
    if not va or not vb or len(va) != len(vb):
        return None
    dot = sum(x * y for x, y in zip(va, vb))
    return max(-1.0, min(1.0, dot))


# Above this cosine similarity two adjacent clips look like "the same shot
# again" (same framing, same person, same set) — SigLIP same-scene pairs
# typically land 0.9+ while different setups of the same event sit ~0.6-0.8.
SIMILAR_SHOT_THRESHOLD = 0.88


def _too_similar(a: dict, b: dict) -> bool:
    sim = visual_similarity(a, b)
    if sim is not None and sim >= SIMILAR_SHOT_THRESHOLD:
        return True
    # No embeddings: fall back to "same single person filling both frames".
    if sim is None:
        pa, pb = a.get("people") or [], b.get("people") or []
        if pa and pa == pb and len(pa) == 1 and (a.get("scene_count", 0) <= 1 and b.get("scene_count", 0) <= 1):
            return True
    return False


def diversify_order(clips: list, profiles: list[dict], keep_first: int = 1, keep_last: int = 1) -> list:
    """Break up runs of visually near-identical adjacent clips.

    Keeps the LLM's narrative order as much as possible: walks the sequence
    and, when clip i+1 looks like clip i, swaps in the nearest later clip
    that doesn't. The hook (first clip) and the closer (last clip) are never
    moved. `clips` and `profiles` must be index-aligned.
    """
    if len(clips) < 3 or len(clips) != len(profiles):
        return clips
    order = list(range(len(clips)))
    lo = max(1, keep_first)
    hi = len(order) - max(1, keep_last)
    for i in range(lo, hi):
        if not _too_similar(profiles[order[i - 1]], profiles[order[i]]):
            continue
        for j in range(i + 1, hi):
            if not _too_similar(profiles[order[i - 1]], profiles[order[j]]):
                order[i], order[j] = order[j], order[i]
                break
    return [clips[k] for k in order]
