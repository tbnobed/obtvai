"""Chat-driven project editing.

The user converses with an editorial assistant; each turn can revise the
project's draft cut (a versioned clip list). The agent loop runs as an API
background task (same pattern as socials channel analysis):

  1. PLAN — one LLM call decides whether the turn is a question or an edit,
     and emits search queries plus removal intents.
  2. SELECT — transcript moments are retrieved for those queries (same
     embedding + Qdrant path as reels), then a second LLM call composes the
     new cut from the current clips and the candidates.

Locked clips are enforced server-side: the model can never drop or reorder
them out of the cut.
"""
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc, func, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db, AsyncSessionLocal
from ..models import (
    Project, ProjectChatMessage, ProjectCutRevision, ReelJob, MediaAsset, Scene,
)
from types import SimpleNamespace

from ..schemas import (
    ProjectChatMessageOut, ProjectChatMessageIn, ProjectCutOut, CutClip,
    CutUpdateIn, CutRevertIn, CutRenderIn, ReelJobOut,
)
from ..worker_client import enqueue_reel
from .projects import touch_project
from .reels import _select_clips, _fill_to_target, _merge_overlaps, _to_out as _reel_to_out


def _fmt_ts(seconds: float) -> str:
    m, sec = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


async def _visual_segments(
    queries: list[str], media_ids: list[str] | None, db: AsyncSession,
) -> list[tuple[str, str, str, list[list[float]]]]:
    """Search scene keyframes (vision-embedding space) and merge contiguous
    matching scenes into segments. Returns (query, media_id, filename,
    segments) tuples. Vision matches APPEARANCE, not identity or speech — this
    finds footage that LOOKS like the query even when nobody talks about it.
    """
    from ..services.embedding import get_clip_text_embedding
    from ..services.qdrant_client import search_vectors
    from .search import _rescale_clip_score, _MIN_VISUAL_SCORE, _is_black_thumbnail

    out: list[tuple[str, str, str, list[list[float]]]] = []
    for q in queries[:3]:
        scene_ids: list[str] = []
        try:
            vec = await get_clip_text_embedding(f"a photo of {q}")
            hits = await search_vectors(
                collection="scenes", vector=vec, limit=48, media_ids=media_ids,
            )
        except Exception:
            logger.exception("visual research failed for query %r", q)
            continue
        for h in hits:
            try:
                if _rescale_clip_score(h.score) < _MIN_VISUAL_SCORE:
                    continue
                payload = h.payload if isinstance(h.payload, dict) else {}
                sid = payload.get("scene_id")
            except Exception:
                continue
            if isinstance(sid, str) and sid:
                scene_ids.append(sid)
        if not scene_ids:
            continue
        rows = (await db.execute(
            select(Scene, MediaAsset.filename)
            .join(MediaAsset, Scene.media_id == MediaAsset.id)
            .where(Scene.id.in_(scene_ids))
        )).all()
        by_media: dict[str, list] = {}
        fnames: dict[str, str] = {}
        for scene, fname in rows:
            if _is_black_thumbnail(scene.thumbnail_url):
                continue
            by_media.setdefault(scene.media_id, []).append(scene)
            fnames[scene.media_id] = fname
        for mid, scenes in by_media.items():
            scenes.sort(key=lambda sc: sc.start_time)
            # Merge scenes separated by <30s into one countable segment — a
            # performance is many consecutive shots, not many performances.
            segs: list[list[float]] = []
            for sc in scenes:
                if segs and sc.start_time - segs[-1][1] <= 30.0:
                    segs[-1][1] = max(segs[-1][1], sc.end_time)
                else:
                    segs.append([sc.start_time, sc.end_time])
            out.append((q, mid, fnames[mid], segs))
    return out


def _merge_segments(segs: list[list[float]], gap: float = 30.0) -> list[list[float]]:
    segs = sorted(segs, key=lambda ab: ab[0])
    merged: list[list[float]] = []
    for a, b in segs:
        if merged and a - merged[-1][1] <= gap:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


async def _visual_research(
    queries: list[str], media_ids: list[str] | None, db: AsyncSession,
) -> list[str]:
    """Answer-mode evidence lines built from _visual_segments."""
    lines: list[str] = []
    union_by_media: dict[str, list[list[float]]] = {}
    union_fnames: dict[str, str] = {}
    for q, mid, fname, segs in await _visual_segments(queries, media_ids, db):
        span = ", ".join(f"{_fmt_ts(a)}-{_fmt_ts(b)}" for a, b in segs[:12])
        q_clean = re.sub(r'[\r\n"]+', " ", q).strip()[:80]
        lines.append(
            f"- [{fname}] looks like \"{q_clean}\": "
            f"{len(segs)} distinct segment(s) at {span}"
        )
        union_by_media.setdefault(mid, []).extend(segs)
        union_fnames[mid] = fname

    # The vision model matches APPEARANCE, not identity — name-specific queries
    # ("<artist> performing") all hit the same stage footage, so per-query
    # counts double-count or under-split. The union across queries is the
    # honest per-file count; tell the answer model to use it.
    if len(queries) > 1:
        for mid, segs in union_by_media.items():
            merged = _merge_segments(segs)
            span = ", ".join(f"{_fmt_ts(a)}-{_fmt_ts(b)}" for a, b in merged[:16])
            lines.append(
                f"- [{union_fnames[mid]}] ALL queries COMBINED (use this for "
                f"counting): {len(merged)} distinct segment(s) at {span}"
            )
    return lines


_MAX_VISUAL_CANDIDATES = 24
_VISUAL_CLIP_MAX_SECONDS = 45.0


async def _visual_candidates(
    queries: list[str], media_ids: list[str] | None, db: AsyncSession,
) -> list[dict]:
    """Edit-mode clip candidates from visual segments. Transcript search can
    only find moments people TALK about; this admits footage that merely LOOKS
    right (a performance, a location) so cuts can include unspoken moments.
    """
    union_by_media: dict[str, list[list[float]]] = {}
    fnames: dict[str, str] = {}
    q_by_media: dict[str, str] = {}
    for q, mid, fname, segs in await _visual_segments(queries, media_ids, db):
        union_by_media.setdefault(mid, []).extend(segs)
        fnames[mid] = fname
        q_by_media.setdefault(mid, q)
    clips: list[dict] = []
    for mid, segs in union_by_media.items():
        for a, b in _merge_segments(segs):
            if b - a < 3.0:
                continue
            q_clean = re.sub(r'[\r\n"]+', " ", q_by_media[mid]).strip()[:60]
            clips.append({
                "media_id": mid,
                "filename": fnames[mid],
                "start_time": round(a, 2),
                "end_time": round(min(b, a + _VISUAL_CLIP_MAX_SECONDS), 2),
                "snippet": f"[visual match — looks like \"{q_clean}\"; no dialog indexed here]",
                "thumbnail_url": None,
            })
    clips.sort(key=lambda c: (c["media_id"], c["start_time"]))
    return clips[:_MAX_VISUAL_CANDIDATES]


router = APIRouter(prefix="/projects/{project_id}/chat", tags=["project-chat"])
cut_router = APIRouter(prefix="/projects/{project_id}/cut", tags=["project-cut"])

logger = logging.getLogger("obtv.project_chat")

_turn_tasks: dict[str, asyncio.Task] = {}
_turn_locks: dict[str, asyncio.Lock] = {}

_MAX_HISTORY = 16
_MAX_CANDIDATES = 40
_MAX_CUT_LINES = 80
_SNIPPET_CHARS = 400


# ---------------------------------------------------------------- helpers

def _msg_out(m: ProjectChatMessage) -> ProjectChatMessageOut:
    return ProjectChatMessageOut(
        id=m.id, role=m.role, content=m.content, status=m.status,
        cut_version=m.cut_version, created_at=m.created_at,
    )


def _clip_duration(c: dict) -> float:
    return float(c.get("end_time", 0)) - float(c.get("start_time", 0))


def _fmt_tc(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


def _extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of an LLM reply (handles code fences)."""
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    return None
    return None


async def _lock_project_writes(db: AsyncSession, project_id: str) -> None:
    """Serialize revision/message writes per project. Advisory xact lock is
    released automatically at commit/rollback, so version assignment
    (latest + 1) is race-free across API workers."""
    await db.execute(
        sql_text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"obtv_cut:{project_id}"},
    )


async def _require_project(db: AsyncSession, project_id: str) -> Project:
    project = (await db.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _latest_revision(db: AsyncSession, project_id: str) -> ProjectCutRevision | None:
    return (await db.execute(
        select(ProjectCutRevision)
        .where(ProjectCutRevision.project_id == project_id)
        .order_by(desc(ProjectCutRevision.version))
        .limit(1)
    )).scalars().first()


async def _save_revision(
    db: AsyncSession, project_id: str, clips: list[dict],
    summary: str | None, source: str,
) -> ProjectCutRevision:
    latest = await _latest_revision(db, project_id)
    rev = ProjectCutRevision(
        id=str(uuid.uuid4()),
        project_id=project_id,
        version=(latest.version + 1) if latest else 1,
        clips=clips,
        summary=summary,
        source=source,
    )
    db.add(rev)
    return rev


def _sanitize_clips(clips: list) -> list[dict]:
    """Keep only known fields; drop malformed entries."""
    out = []
    for c in clips or []:
        try:
            d = {
                "media_id": str(c["media_id"]),
                "filename": str(c["filename"]),
                "start_time": float(c["start_time"]),
                "end_time": float(c["end_time"]),
                "snippet": (str(c.get("snippet")) if c.get("snippet") else None),
                "thumbnail_url": (str(c.get("thumbnail_url")) if c.get("thumbnail_url") else None),
                "locked": bool(c.get("locked", False)),
            }
        except (KeyError, TypeError, ValueError):
            continue
        if d["end_time"] > d["start_time"] >= 0:
            out.append(d)
    return out


_ALL_SOURCES_RE = re.compile(
    r"\b(?:every|each|all(?:\s+\d+)?)\s+(?:episodes?|sources?|files?|assets?)\b",
    re.IGNORECASE,
)

_UNIFORM_LEN_RE = re.compile(
    r"(?:\b(?:same|equal|uniform|consistent)\b.{0,20}|\bmatch\b.{0,30})\b(?:leng?th|lenght|duration|size|time)\b",
    re.IGNORECASE,
)

_RUNTIME_RE = re.compile(
    r"(?<![\w./-])(\d+(?:\.\d+)?)[ \t]*(minutes?|mins?|seconds?|secs?)\b(?![\w./-])",
    re.IGNORECASE,
)


def _requested_runtime(text: str) -> float | None:
    """Cheap regex fallback: pull an explicit runtime out of the user message."""
    m = _RUNTIME_RE.search(text or "")
    if not m:
        return None
    val = float(m.group(1))
    secs = val * 60.0 if m.group(2).lower().startswith("m") else val
    return secs if 10.0 <= secs <= 7200.0 else None


_MIN_TRIMMED_CLIP = 5.0


def _trim_to_target(clips: list[dict], target: float) -> None:
    """The inverse of _fill_to_target: when the cut runs long, first shorten
    all unlocked clips proportionally (preserving the cut's shape and every
    clip in it), and only drop clips from the end as a last resort."""
    def total() -> float:
        return sum(_clip_duration(c) for c in clips)

    tol = max(5.0, target * 0.05)
    excess = total() - target
    if excess <= tol:
        return
    # Phase 1: proportional shortening, never below _MIN_TRIMMED_CLIP.
    shrinkable = sum(
        max(0.0, _clip_duration(c) - _MIN_TRIMMED_CLIP)
        for c in clips if not c.get("locked")
    )
    if shrinkable > 0:
        factor = min(1.0, excess / shrinkable)
        for c in clips:
            if c.get("locked"):
                continue
            room = max(0.0, _clip_duration(c) - _MIN_TRIMMED_CLIP)
            if room > 0:
                c["end_time"] -= room * factor
    # Phase 2: still long (locks or min-lengths in the way) — drop from the end.
    while total() > target + tol:
        idx = next((i for i in range(len(clips) - 1, -1, -1) if not clips[i].get("locked")), None)
        if idx is None or len(clips) <= 1:
            return
        if total() - _clip_duration(clips[idx]) < target - tol:
            break
        clips.pop(idx)


# ---------------------------------------------------------------- agent loop

_PLAN_SYSTEM = (
    "You are a friendly, collaborative video editor working with the user on a "
    "cut (an ordered list of clips) built from their project's footage. Decide "
    "what this turn needs and respond ONLY with a JSON object, no other text:\n"
    '{"mode": "edit" | "adjust" | "answer", '
    '"reply": "conversational reply to the user (always fill this in)", '
    '"searches": ["up to 3 search queries to find material — each also runs '
    'against the VISUALS (keyframes), which match appearance only, never '
    'identity: for questions about what is shown, include one generic '
    'appearance query like \'musician performing on stage\' instead of '
    'people\'s names"], '
    '"remove": [clip numbers to drop from the current cut], '
    '"clip_seconds": desired per-clip length in seconds if the user asked '
    'for uniform or specific clip lengths (e.g. \'same length\' -> total/count), else null, '
    '"all_sources": true if the user wants every episode/source file '
    'represented in the cut, else false, '
    '"target_seconds": runtime in seconds if the user asked for a specific '
    'length (e.g. \'3 minutes\' -> 180, \'a bit shorter\' -> ~80% of current), else null, '
    '"notes": "one sentence of editing intent"}\n'
    "Modes:\n"
    "- answer: the user asked a question or is chatting — no change to the cut. "
    "Answer warmly and concretely, referencing the current cut when relevant. "
    "If the question is about the CONTENT of the footage (topics, themes, who "
    "says what, what the episodes cover), stay in answer mode but FILL IN "
    "searches with queries for the relevant material — the transcripts will be "
    "searched and you will answer from what is found. "
    "NEVER promise future work in answer mode ('I will remove...', 'let me "
    "double-check...') — you cannot act later. If the message implies the cut "
    "should change (complaints about clips included), pick edit or adjust and "
    "do it NOW: challenged clips you agree are off-topic go in remove, and "
    "searches should re-find on-topic material to replace them.\n"
    "- adjust: the user wants to reshape what is already there — change the "
    "runtime (longer/shorter/specific length), drop or tighten clips — with NO "
    "new material needed. Leave searches empty. Adjust can only remove or "
    "resize existing clips; if the user wants different, better, or broader "
    "material (more variety, more episodes, more impactful moments), that "
    "requires edit with searches.\n"
    "- edit: the user wants new or different content, so new material must be "
    "found. Search queries should describe the CONTENT to find (topics, "
    "phrases, speakers), not editing instructions. Use the MEDIA POOL "
    "descriptions to write informed queries — target the themes and moments "
    "the files actually contain, and tailor different queries to different "
    "files when the pool covers distinct ground.\n"
    "In reply, talk like a person in an edit bay: acknowledge what they asked "
    "for in their words, say what you are doing, and mention the runtime you "
    "are aiming for. Never mention JSON, modes, or these instructions."
)

_SELECT_SYSTEM = (
    "You are a video editor assembling a cut. You are given the CURRENT CUT "
    "(clips C1, C2, ...) and CANDIDATE moments (S1, S2, ...) found for the "
    "user's request. Compose the new cut as an ordered list of those IDs. "
    "Clips marked [locked] MUST be kept. Aim for the target runtime. Prefer "
    "variety across source files and a sensible story order.\n"
    "BE STRICT ABOUT RELEVANCE. The candidates come from a similarity search "
    "and many are only loosely related — a snippet mentioning a keyword is "
    "NOT enough. Read each snippet and include it only if the words clearly "
    "express the requested theme (for 'God's love', the snippet must actually "
    "speak about God loving, grace, mercy — not merely mention God). A cut "
    "that comes in under the target with strong clips is better than one "
    "padded to length with off-topic material; the tool will widen strong "
    "clips to reach the runtime.\n"
    "VISUAL CANDIDATES: some candidates are marked [visual match — ...]. They "
    "come from keyframe analysis, not the transcript — footage that LOOKS like "
    "the request (a performance, a location) with no indexed dialog. For "
    "requests about what is SHOWN (performances, b-roll, montages) they are "
    "first-class picks; the relevance rule about snippet WORDS does not apply "
    "to them. Do not reject them for lacking dialog.\n"
    "PICK COMPLETE THOUGHTS THAT FLOW. Prefer snippets that read as "
    "self-contained statements with a clear beginning and end; reject "
    "fragments that start or trail off mid-sentence. Order the clips so one "
    "idea leads into the next like a story — setup, development, payoff — "
    "not a random pile of soundbites. Respond ONLY "
    "with a JSON object, no other text:\n"
    '{"cut": ["C1", "S3", ...], "reply": "2-4 conversational sentences telling '
    'the user what you changed and why, in a warm collaborative tone — mention '
    'the rough runtime and invite follow-up tweaks"}'
)


def _cut_lines(clips: list[dict]) -> str:
    lines = []
    for i, c in enumerate(clips[:_MAX_CUT_LINES], 1):
        snip = (c.get("snippet") or "")[:_SNIPPET_CHARS]
        lock = " [locked]" if c.get("locked") else ""
        lines.append(
            f"C{i}{lock} {c['filename']} {_fmt_tc(c['start_time'])}-{_fmt_tc(c['end_time'])} "
            f"({_clip_duration(c):.0f}s) \"{snip}\""
        )
    return "\n".join(lines) if lines else "(empty — no clips yet)"


def _cand_lines(cands: list[dict]) -> str:
    lines = []
    for i, c in enumerate(cands, 1):
        snip = (c.get("snippet") or "")[:_SNIPPET_CHARS]
        lines.append(
            f"S{i} {c['filename']} {_fmt_tc(c['start_time'])}-{_fmt_tc(c['end_time'])} "
            f"({_clip_duration(c):.0f}s) \"{snip}\""
        )
    return "\n".join(lines) if lines else "(none found)"


def _clamp_to_range(c: dict, ranges: dict) -> bool:
    """Clamp a clip to its asset's usable region (Media Pool trim). Returns
    False when the clip falls entirely outside the region or gets too short."""
    r = ranges.get(c["media_id"])
    if not r:
        return True
    try:
        lo, hi = float(r["in"]), float(r["out"])
    except (KeyError, TypeError, ValueError):
        return True
    c["start_time"] = max(c["start_time"], lo)
    c["end_time"] = min(c["end_time"], hi)
    return c["end_time"] - c["start_time"] >= 2.0


def _overlaps_existing(c: dict, existing: list[dict]) -> bool:
    for e in existing:
        if e["media_id"] == c["media_id"] and not (
            c["start_time"] >= e["end_time"] or c["end_time"] <= e["start_time"]
        ):
            return True
    return False


async def _run_turn(project_id: str, assistant_id: str, user_text: str) -> None:
    from ..services.llm import generate_response
    lock = _turn_locks.setdefault(project_id, asyncio.Lock())
    async with lock:
        try:
            await _run_turn_inner(project_id, assistant_id, user_text, generate_response)
        except Exception:
            logger.exception("Chat turn failed for project %s", project_id)
            async with AsyncSessionLocal() as db:
                msg = (await db.execute(
                    select(ProjectChatMessage).where(ProjectChatMessage.id == assistant_id)
                )).scalar_one_or_none()
                if msg is not None:
                    msg.status = "error"
                    msg.content = "Something went wrong while working on that — try again."
                    db.add(msg)
                    await db.commit()


async def _run_turn_inner(project_id: str, assistant_id: str, user_text: str, generate_response) -> None:
    async with AsyncSessionLocal() as db:
        project = (await db.execute(
            select(Project).where(Project.id == project_id)
        )).scalar_one_or_none()
        if project is None:
            return
        # None = user hasn't set a run time (and none requested in chat) —
        # in that case we never pad or trim, the cut is whatever fits the ask.
        target: float | None = (
            float(project.target_runtime_seconds)
            if project.target_runtime_seconds else None
        )
        media_ids = list(project.media_ids or []) or None

        history_rows = (await db.execute(
            select(ProjectChatMessage)
            .where(ProjectChatMessage.project_id == project_id,
                   ProjectChatMessage.status == "ready")
            .order_by(desc(ProjectChatMessage.created_at))
            .limit(_MAX_HISTORY)
        )).scalars().all()
        history = [
            {"role": m.role, "content": m.content}
            for m in reversed(history_rows) if m.content
        ]

        latest = await _latest_revision(db, project_id)
        cut = _sanitize_clips(latest.clips) if latest is not None else []

        # ---- PLAN
        total = sum(_clip_duration(c) for c in cut)
        target_line = (
            f"Target runtime: {_fmt_tc(target)} ({target:.0f}s)."
            if target is not None else
            "Target runtime: none set — size the cut to the user's request."
        )
        pool_line = ""
        if media_ids:
            pool_rows = (await db.execute(
                select(MediaAsset.filename, MediaAsset.synopsis)
                .where(MediaAsset.id.in_(media_ids))
                .order_by(MediaAsset.filename)
            )).all()
            if pool_rows:
                # Cap the payload: full synopses for small pools, names only
                # beyond that, hard char budget overall.
                _POOL_SYNOPSES_MAX = 20
                _POOL_CHAR_BUDGET = 6000
                ep_lines, used = [], 0
                for i, (fname, syn) in enumerate(pool_rows):
                    syn = (syn or "").strip().replace("\n", " ")
                    if i < _POOL_SYNOPSES_MAX and syn and used < _POOL_CHAR_BUDGET:
                        line = f"- {fname}: {syn[:280]}"
                    else:
                        line = f"- {fname}" + ("" if syn else ": (not yet analyzed)")
                    used += len(line)
                    ep_lines.append(line)
                pool_line = (
                    f"MEDIA POOL — what each of the {len(pool_rows)} files contains:\n"
                    + "\n".join(ep_lines) + "\n\n"
                )
        plan_prompt = (
            f"{pool_line}"
            f"{target_line}\n"
            f"Current cut: {len(cut)} clips, {_fmt_tc(total)} total.\n"
            f"{_cut_lines(cut)}\n\n"
            f"User request: {user_text}"
        )
        plan_raw = await generate_response(
            plan_prompt, history=history, system=_PLAN_SYSTEM, max_new_tokens=500,
        )
        plan = _extract_json(plan_raw) or {}
        mode = plan.get("mode") or "edit"

        # Honor a runtime asked for in chat ("make it 3 minutes") over the
        # project default, and persist it so later turns keep the new length.
        req_target = None
        try:
            v = plan.get("target_seconds")
            if isinstance(v, (int, float)) and 10.0 <= float(v) <= 7200.0:
                req_target = float(v)
        except (TypeError, ValueError):
            req_target = None
        if req_target is None:
            req_target = _requested_runtime(user_text)
        if req_target is not None:
            target = req_target
            project.target_runtime_seconds = int(req_target)
            db.add(project)

        _acts = bool(
            plan.get("remove") or plan.get("clip_seconds")
            or plan.get("all_sources")
        )
        _is_question = user_text.rstrip().endswith("?") or bool(re.match(
            r"\s*(?:are|is|was|were|do|does|did|why|how|what|which|who|can|could|would|should)\b",
            user_text, re.IGNORECASE,
        ))
        if mode == "answer" and not _is_question and (_acts or _UNIFORM_LEN_RE.search(user_text)):
            # The model wants to talk while the request needs work — force it.
            mode = "adjust" if not plan.get("searches") else "edit"
        if mode == "answer":
            a_searches = [
                q for q in (plan.get("searches") or [])
                if isinstance(q, str) and q.strip()
            ][:3]
            if a_searches and media_ids:
                found: list[dict] = []
                seen: set[tuple] = set()
                for q in a_searches:
                    for c in await _select_clips(q.strip(), 12, db, media_ids=media_ids):
                        key = (c["media_id"], round(c["start_time"], 1))
                        if key not in seen and c.get("snippet"):
                            seen.add(key)
                            found.append(c)
                try:
                    vis_lines = await _visual_research(a_searches, media_ids, db)
                except Exception:
                    logger.exception("visual research failed — answering from transcripts only")
                    vis_lines = []
                if found or vis_lines:
                    sections = []
                    if found:
                        lines = "\n".join(
                            "- [{}] {}".format(
                                c["filename"],
                                re.sub(r"\s+", " ", c["snippet"])[:300],
                            )
                            for c in found[:24]
                        )
                        sections.append(f"TRANSCRIPT EXCERPTS found for it:\n{lines}")
                    if vis_lines:
                        sections.append(
                            "VISUAL SCENE MATCHES (keyframe analysis — footage that "
                            "LOOKS like the query even when nobody talks about it; "
                            "each segment merges matching shots within ~30s of each "
                            "other, so segment counts closely estimate distinct "
                            "occurrences):\n"
                            + "\n".join(vis_lines[:12])
                        )
                    context = "\n\n".join(sections)
                    reply = (await generate_response(
                        "The user asked about the footage in their media pool "
                        f"({len(media_ids)} files). QUESTION:\n{user_text}\n\n"
                        f"{context}\n\n"
                        "Answer the question concretely from this evidence, "
                        "citing episode filenames and timestamps where useful. "
                        "Transcripts only cover what is SAID — for questions about "
                        "what is SHOWN (performances, locations, visuals), trust "
                        "the visual scene matches and count their segments. If the "
                        "evidence doesn't cover it, say what IS there instead. Plain "
                        "conversational text, no JSON, no promises of future work.",
                        history=history,
                        system="You are a friendly, sharp video editor who knows this footage well.",
                        max_new_tokens=500,
                    )).strip()
                    await _finish(db, assistant_id, reply or "I couldn't pull anything useful from the footage for that.", None)
                    return
            reply = (plan.get("reply") or "").strip() or plan_raw.strip()[:1500]
            await _finish(db, assistant_id, reply, None)
            return

        removals = {int(i) for i in (plan.get("remove") or []) if isinstance(i, (int, float))}
        ranges = project.media_ranges or {}

        if mode == "adjust" and not cut:
            reply = (plan.get("reply") or "").strip() or (
                "There's no cut to adjust yet — tell me what the piece is about "
                "and I'll pull together a first draft."
            )
            await _finish(db, assistant_id, reply, None)
            return

        clip_seconds = None
        try:
            v = plan.get("clip_seconds")
            if isinstance(v, (int, float)) and 3.0 <= float(v) <= 600.0:
                clip_seconds = float(v)
        except (TypeError, ValueError):
            clip_seconds = None
        if clip_seconds is None and cut and not _is_question and _UNIFORM_LEN_RE.search(user_text):
            # "make each clip the same length" — derive it: runtime / clips.
            basis = target if target is not None else sum(_clip_duration(c) for c in cut)
            clip_seconds = max(3.0, min(600.0, basis / len(cut)))

        if mode == "adjust":
            # Reshape the existing cut — runtime, removals, per-clip resize.
            # COPY the clip dicts: resizing must not mutate `cut`, which the
            # no-op comparison below uses as its baseline.
            new_cut = [dict(c) for i, c in enumerate(cut, 1) if i not in removals or c.get("locked")]
            if clip_seconds is not None:
                # First choice: shorten long clips to the asked length — this
                # keeps the story (one moment per clip). Splitting a long clip
                # into consecutive chunks is a fallback ONLY when shortening
                # would leave the cut far under the runtime target (e.g. a
                # single 60s clip at a 60s target).
                orig_durs = {id(c): _clip_duration(c) for c in new_cut}
                for c in new_cut:
                    if not c.get("locked") and _clip_duration(c) > clip_seconds:
                        c["end_time"] = c["start_time"] + clip_seconds
                short_total = sum(_clip_duration(c) for c in new_cut)
                if target is not None and short_total < target * 0.75:
                    resized: list[dict] = []
                    for c in new_cut:
                        dur = orig_durs[id(c)]
                        if c.get("locked") or dur <= clip_seconds * 1.5:
                            resized.append(c)
                            continue
                        n = max(1, round(dur / clip_seconds))
                        chunk = dur / n
                        for k in range(n):
                            piece = dict(c)
                            piece["start_time"] = c["start_time"] + k * chunk
                            piece["end_time"] = c["start_time"] + (k + 1) * chunk
                            if k > 0:
                                piece["snippet"] = None  # chunk text unknown — don't repeat the same line
                            resized.append(piece)
                    new_cut = resized
            if target is not None:
                _fill_to_target(new_cut, target)
                _trim_to_target(new_cut, target)
            if ranges:
                new_cut = [c for c in new_cut if _clamp_to_range(c, ranges)]
            if not new_cut:
                # Removals wiped the cut and there is nothing to add back —
                # never save an empty revision; fall through to the edit path
                # so replacement material gets searched for instead.
                mode = "edit"
            elif [
                (c["media_id"], round(c["start_time"], 2), round(c["end_time"], 2))
                for c in new_cut
            ] == [
                (c["media_id"], round(c["start_time"], 2), round(c["end_time"], 2))
                for c in cut
            ]:
                # Nothing actually changed — say so honestly; never echo the
                # model's promise-text as if work was done.
                reply = (
                    "That request didn't change the cut — it's already "
                    f"{len(cut)} clips · "
                    f"{_fmt_tc(sum(_clip_duration(c) for c in cut))}. "
                    "Tell me what you'd like different."
                )
                await _finish(db, assistant_id, reply, None)
                return
            else:
                adj_stats = (
                    f"{len(new_cut)} clips · "
                    f"{_fmt_tc(sum(_clip_duration(c) for c in new_cut))}"
                )
                if clip_seconds is not None:
                    stuck = [
                        i + 1 for i, c in enumerate(new_cut)
                        if c.get("locked") and abs(_clip_duration(c) - clip_seconds) > clip_seconds * 0.25
                    ]
                    if stuck:
                        adj_stats += (
                            " — clip" + ("s" if len(stuck) > 1 else "")
                            + " " + ", ".join(str(i) for i in stuck)
                            + " left untouched because they're locked; unlock them if you want them resized"
                        )
                reply = (plan.get("reply") or "").strip()
                reply = (
                    f"{reply}\n\n({adj_stats})" if reply
                    else f"Reworked the cut — {adj_stats}. Tell me if you want it tighter or looser."
                )
                await _lock_project_writes(db, project_id)
                rev = await _save_revision(db, project_id, [
                    {k: v for k, v in c.items() if k != "_dur"} for c in new_cut
                ], reply, "assistant")
                await db.flush()
                await _finish(db, assistant_id, reply, rev.version)
                return

        # ---- gather candidates
        searches = [s for s in (plan.get("searches") or []) if isinstance(s, str) and s.strip()][:3]
        if not searches:
            searches = [user_text]
        kept = [c for i, c in enumerate(cut, 1) if i not in removals or c.get("locked")]

        candidates: list[dict] = []

        def _admit(found: list[dict]) -> None:
            for c in found:
                c["locked"] = False
                if not _clamp_to_range(c, ranges):
                    continue
                if not _overlaps_existing(c, kept) and not _overlaps_existing(c, candidates):
                    candidates.append(c)

        if media_ids and len(media_ids) <= 12:
            # Small pool: search each asset separately — a global similarity
            # search lets one or two chatty files crowd out all the others.
            for q in searches:
                for mid in media_ids:
                    _admit(await _select_clips(q.strip(), 6, db, media_id=mid))
        else:
            for q in searches:
                _admit(await _select_clips(q.strip(), 30, db, media_ids=media_ids))
                if len(candidates) >= _MAX_CANDIDATES:
                    break

        # Visual candidates: transcript search only finds moments people TALK
        # about — performances, b-roll and locations that are merely SHOWN
        # would never make the cut without this channel. They deliberately
        # bypass the overlap check against transcript candidates: intro
        # snippets ("please welcome...") sit right at the start of the very
        # footage the visual segment covers, and dropping the visual clip for
        # that overlap would leave only the intros. Duplicate coverage is fine
        # — the SELECT model picks one.
        vis_cands: list[dict] = []
        try:
            for c in await _visual_candidates(searches, media_ids, db):
                c["locked"] = False
                if not _clamp_to_range(c, ranges):
                    continue
                if not _overlaps_existing(c, kept):
                    vis_cands.append(c)
        except Exception:
            logger.exception("visual candidate search failed — transcript candidates only")
        logger.info(
            "edit-mode candidates: %d transcript, %d visual (searches=%r)",
            len(candidates), len(vis_cands), searches,
        )

        # Round-robin across source files so every episode stays visible even
        # after the cap, instead of the top-scoring file eating the whole list.
        by_file: dict[str, list[dict]] = {}
        for c in candidates:
            by_file.setdefault(c["media_id"], []).append(c)
        interleaved: list[dict] = []
        transcript_cap = max(_MAX_CANDIDATES - len(vis_cands), _MAX_CANDIDATES // 2)
        while len(interleaved) < transcript_cap and any(by_file.values()):
            for lst in by_file.values():
                if lst:
                    interleaved.append(lst.pop(0))
        candidates = interleaved[:transcript_cap]
        candidates.extend(vis_cands[: _MAX_CANDIDATES - len(candidates)])

        # ---- SELECT
        target_line = (
            f"Target runtime: {_fmt_tc(target)} ({target:.0f}s)."
            if target is not None else
            "Target runtime: none set — size the cut to the user's request."
        )
        select_prompt = (
            f"{target_line}\n"
            f"User request: {user_text}\n"
            f"Editing intent: {plan.get('notes') or 'follow the user request'}\n\n"
            f"CURRENT CUT ({_fmt_tc(sum(_clip_duration(c) for c in kept))} total):\n"
            f"{_cut_lines(kept)}\n\n"
            f"CANDIDATES:\n{_cand_lines(candidates)}"
        )
        sel_raw = await generate_response(
            select_prompt, system=_SELECT_SYSTEM, max_new_tokens=1200,
        )
        sel = _extract_json(sel_raw) or {}

        new_cut = _apply_selection(sel.get("cut"), kept, candidates)
        if not new_cut:
            # Model gave nothing usable — fall back to kept cut + best candidates.
            new_cut = list(kept)
            for c in candidates:
                # Blind fallback: take only the top-ranked half of the target,
                # _fill_to_target widens the rest — avoids padding the tail
                # with weakly related matches.
                if target is not None and sum(_clip_duration(x) for x in new_cut) >= target * 0.5:
                    break
                new_cut.append(c)

        if not new_cut:
            await _finish(
                db, assistant_id,
                "I couldn't find any matching moments in this project's footage — "
                "try describing the content differently.", None,
            )
            return

        # Meet the runtime target the same way reels do, then re-clamp —
        # widening must not push clips past their Media Pool trim ranges.
        if target is not None:
            _fill_to_target(new_cut, target)
            _trim_to_target(new_cut, target)
        if ranges:
            new_cut = [c for c in new_cut if _clamp_to_range(c, ranges)]
        if not new_cut:
            await _finish(
                db, assistant_id,
                "That change would have left the cut empty, so I kept the "
                "current version — try telling me what to replace the clips "
                "with.", None,
            )
            return

        # Coverage is enforced HERE, not trusted to the model — it has claimed
        # "all episodes included" while the cut said otherwise.
        require_all = bool(plan.get("all_sources")) or bool(_ALL_SOURCES_RE.search(user_text))
        uncovered: list[str] = []
        if require_all and media_ids:
            present = {c["media_id"] for c in new_cut}
            used = {(c["media_id"], c["start_time"]) for c in new_cut}
            for mid in media_ids:
                if mid in present:
                    continue
                best = next(
                    (c for c in candidates
                     if c["media_id"] == mid and (c["media_id"], c["start_time"]) not in used),
                    None,
                )
                if best is None:
                    uncovered.append(mid)
                    continue
                b = dict(best)
                if b["end_time"] - b["start_time"] > 10.0:
                    b["end_time"] = b["start_time"] + 10.0
                new_cut.append(b)
        coverage_added = require_all and bool(media_ids) and (
            len(new_cut) > 0 and target is not None
            and sum(_clip_duration(c) for c in new_cut) > target * 1.1
        )
        if uncovered:
            names = (await db.execute(
                select(MediaAsset.filename).where(MediaAsset.id.in_(uncovered))
            )).scalars().all()
            missing_note = (
                " I couldn't find any usable transcript moments in: "
                + ", ".join(names or uncovered)
                + " — those files may not be transcribed/indexed yet."
            )
        else:
            missing_note = ""
        if coverage_added:
            missing_note += (
                " Covering every source pushed the runtime a little over the "
                "target — say the word if you'd rather stay strict on length."
            )

        n_files = len({c["media_id"] for c in new_cut})
        pool_n = len(media_ids) if media_ids else None
        stats = (
            f"{len(new_cut)} clips · {_fmt_tc(sum(_clip_duration(c) for c in new_cut))}"
            + (f" · {n_files} of {pool_n} sources" if pool_n else f" · {n_files} sources")
        )
        reply = (sel.get("reply") or "").strip()
        reply = f"{reply}\n\n({stats})" if reply else f"Updated the cut — {stats}."
        if missing_note:
            reply += missing_note
        await _lock_project_writes(db, project_id)
        rev = await _save_revision(db, project_id, [
            {k: v for k, v in c.items() if k != "_dur"} for c in new_cut
        ], reply, "assistant")
        await db.flush()
        await _finish(db, assistant_id, reply, rev.version)


def _apply_selection(order: list | None, kept: list[dict], candidates: list[dict]) -> list[dict]:
    """Map C#/S# ids back to clips; enforce that locked clips stay in."""
    if not isinstance(order, list):
        return []
    out: list[dict] = []
    seen: set[int] = set()
    for ref in order:
        if not isinstance(ref, str):
            continue
        m = re.fullmatch(r"([CS])(\d+)", ref.strip().upper())
        if not m:
            continue
        pool = kept if m.group(1) == "C" else candidates
        idx = int(m.group(2)) - 1
        if 0 <= idx < len(pool):
            key = id(pool[idx])
            if key not in seen:
                seen.add(key)
                out.append(pool[idx])
    if not out:
        return []
    # Re-insert locked clips the model dropped, at their original position.
    for i, c in enumerate(kept):
        if c.get("locked") and id(c) not in seen:
            pos = min(i, len(out))
            out.insert(pos, c)
            seen.add(id(c))
    # Locked clips must also keep their original relative order — reassign
    # the locked slots in `out` to the locked clips in `kept` order.
    locked_slots = [i for i, c in enumerate(out) if c.get("locked")]
    locked_in_order = [c for c in kept if c.get("locked") and id(c) in seen]
    for slot, clip in zip(locked_slots, locked_in_order):
        out[slot] = clip
    return out


async def _finish(db: AsyncSession, assistant_id: str, content: str, cut_version: int | None) -> None:
    msg = (await db.execute(
        select(ProjectChatMessage).where(ProjectChatMessage.id == assistant_id)
    )).scalar_one_or_none()
    if msg is None:
        return
    msg.content = content
    msg.status = "ready"
    msg.cut_version = cut_version
    db.add(msg)
    await db.commit()


# ---------------------------------------------------------------- chat routes

@router.get("", response_model=list[ProjectChatMessageOut])
async def list_messages(project_id: str, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(ProjectChatMessage)
        .where(ProjectChatMessage.project_id == project_id)
        .order_by(ProjectChatMessage.created_at)
        .limit(500)
    )).scalars().all()
    return [_msg_out(m) for m in rows]


@router.post("/messages", response_model=list[ProjectChatMessageOut], status_code=202)
async def post_message(project_id: str, body: ProjectChatMessageIn, db: AsyncSession = Depends(get_db)):
    await _require_project(db, project_id)
    # Lock before the running-check so two concurrent posts can't both pass
    # it and start duplicate assistant turns.
    await _lock_project_writes(db, project_id)
    running = (await db.execute(
        select(func.count()).select_from(ProjectChatMessage).where(
            ProjectChatMessage.project_id == project_id,
            ProjectChatMessage.status == "running",
        )
    )).scalar_one()
    if running:
        raise HTTPException(status_code=409, detail="The assistant is still working on the previous message")

    text = body.content.strip()
    user_msg = ProjectChatMessage(
        id=str(uuid.uuid4()), project_id=project_id, role="user",
        content=text, status="ready",
    )
    assistant_msg = ProjectChatMessage(
        id=str(uuid.uuid4()), project_id=project_id, role="assistant",
        content=None, status="running",
    )
    db.add_all([user_msg, assistant_msg])
    await touch_project(db, project_id)
    await db.commit()

    task = asyncio.create_task(_run_turn(project_id, assistant_msg.id, text))
    _turn_tasks[assistant_msg.id] = task
    task.add_done_callback(lambda t: _turn_tasks.pop(assistant_msg.id, None))
    return [_msg_out(user_msg), _msg_out(assistant_msg)]


# ---------------------------------------------------------------- cut routes

def _cut_out(rev: ProjectCutRevision | None, versions: list[int]) -> ProjectCutOut:
    if rev is None:
        return ProjectCutOut(version=0, clips=[], versions=versions)
    return ProjectCutOut(
        version=rev.version,
        clips=[CutClip(**c) for c in _sanitize_clips(rev.clips)],
        summary=rev.summary,
        source=rev.source,
        created_at=rev.created_at,
        versions=versions,
    )


async def _versions(db: AsyncSession, project_id: str) -> list[int]:
    rows = (await db.execute(
        select(ProjectCutRevision.version)
        .where(ProjectCutRevision.project_id == project_id)
        .order_by(ProjectCutRevision.version)
    )).scalars().all()
    return list(rows)


@cut_router.get("", response_model=ProjectCutOut)
async def get_cut(project_id: str, version: int | None = None, db: AsyncSession = Depends(get_db)):
    if version is not None:
        rev = (await db.execute(
            select(ProjectCutRevision).where(
                ProjectCutRevision.project_id == project_id,
                ProjectCutRevision.version == version,
            )
        )).scalars().first()
        if rev is None:
            raise HTTPException(status_code=404, detail="Cut version not found")
    else:
        rev = await _latest_revision(db, project_id)
    return _cut_out(rev, await _versions(db, project_id))


@cut_router.patch("", response_model=ProjectCutOut)
async def update_cut(project_id: str, body: CutUpdateIn, db: AsyncSession = Depends(get_db)):
    """Manual edits from the UI (lock, remove, reorder, trim) become a new revision."""
    await _require_project(db, project_id)
    await _lock_project_writes(db, project_id)
    clips = _sanitize_clips([c.model_dump() for c in body.clips])
    rev = await _save_revision(db, project_id, clips, "Manual edit", "user")
    await touch_project(db, project_id)
    await db.commit()
    return _cut_out(rev, await _versions(db, project_id))


@cut_router.post("/revert", response_model=ProjectCutOut)
async def revert_cut(project_id: str, body: CutRevertIn, db: AsyncSession = Depends(get_db)):
    await _require_project(db, project_id)
    await _lock_project_writes(db, project_id)
    src = (await db.execute(
        select(ProjectCutRevision).where(
            ProjectCutRevision.project_id == project_id,
            ProjectCutRevision.version == body.version,
        )
    )).scalars().first()
    if src is None:
        raise HTTPException(status_code=404, detail="Cut version not found")
    rev = await _save_revision(
        db, project_id, _sanitize_clips(src.clips),
        f"Reverted to v{body.version}", "revert",
    )
    await touch_project(db, project_id)
    await db.commit()
    return _cut_out(rev, await _versions(db, project_id))


@cut_router.post("/export")
async def export_cut(project_id: str, body: dict, db: AsyncSession = Depends(get_db)):
    """Export the current draft cut as an NLE timeline (Premiere/Resolve).

    Reuses the clip-list exporters, including Curator relinking: each clip's
    source_path (hi-res original from the Curator sidecar) wins over the
    ingested proxy path, so the timeline relinks to facility originals.
    """
    from .clips import _fcpxml, _otio

    fmt = (body.get("format") or "").lower()
    if fmt not in ("edl", "fcpxml", "otio"):
        raise HTTPException(status_code=400, detail="Format must be edl, fcpxml, or otio")
    rev = await _latest_revision(db, project_id)
    clips = _sanitize_clips(rev.clips) if rev is not None else []
    if not clips:
        raise HTTPException(status_code=400, detail="The cut is empty — nothing to export")
    project = (await db.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    media_ids = {c["media_id"] for c in clips}
    rows = await db.execute(
        select(MediaAsset.id, MediaAsset.filename, MediaAsset.original_path, MediaAsset.source_path)
        .where(MediaAsset.id.in_(media_ids))
    )
    fnames: dict[str, str] = {}
    paths: dict[str, str] = {}
    for mid, fname, op, sp in rows.all():
        fnames[mid] = fname
        if sp or op:
            paths[mid] = sp or op

    ns_clips = [
        SimpleNamespace(
            media_id=c["media_id"],
            filename=c.get("filename") or fnames.get(c["media_id"]) or c["media_id"],
            start_time=float(c["start_time"]),
            end_time=float(c["end_time"]),
            label=(c.get("snippet") or "")[:60] or None,
        )
        for c in clips
    ]
    name = f"{project.name or 'Project'} cut v{rev.version}"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    if fmt == "fcpxml":
        content, filename = _fcpxml(name, ns_clips, paths), f"{safe}.fcpxml"
    elif fmt == "otio":
        content, filename = _otio(name, ns_clips, paths), f"{safe}.otio"
    else:
        lines = ["TITLE: " + name, "FCM: NON-DROP FRAME", ""]
        rec = 0.0
        for i, c in enumerate(ns_clips, 1):
            def tc(secs: float) -> str:
                h = int(secs // 3600); m = int((secs % 3600) // 60)
                sec = int(secs % 60); f = int((secs % 1) * 25)
                return f"{h:02d}:{m:02d}:{sec:02d}:{f:02d}"
            dur = c.end_time - c.start_time
            lines.append(
                f"{i:03d}  AX       V     C        "
                f"{tc(c.start_time)} {tc(c.end_time)} {tc(rec)} {tc(rec + dur)}"
            )
            lines.append(f"* FROM CLIP NAME: {c.filename}")
            src = paths.get(c.media_id)
            if src:
                lines.append(f"* SOURCE FILE: {src}")
            lines.append("")
            rec += dur
        content, filename = "\n".join(lines), f"{safe}.edl"
    return {"format": fmt, "content": content, "filename": filename}


@cut_router.post("/render", response_model=ReelJobOut, status_code=202)
async def render_cut(project_id: str, body: CutRenderIn, db: AsyncSession = Depends(get_db)):
    rev = await _latest_revision(db, project_id)
    clips = _sanitize_clips(rev.clips) if rev is not None else []
    if not clips:
        raise HTTPException(status_code=400, detail="The cut is empty — nothing to render")
    project = (await db.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # The worker's reel contract has no "locked" field.
    reel_clips = [{k: v for k, v in c.items() if k != "locked"} for c in clips]
    r = ReelJob(
        id=str(uuid.uuid4()),
        prompt=f"Chat cut v{rev.version}: {(rev.summary or 'draft cut')[:200]}",
        project_id=project_id,
        cut_version=rev.version,
        preset=body.preset,
        burn_captions=body.burn_captions,
        clips=reel_clips,
        status="pending",
        progress=0.0,
        created_at=datetime.utcnow(),
    )
    db.add(r)
    await touch_project(db, project_id)
    await db.commit()
    try:
        await enqueue_reel(r.id)
    except Exception as exc:
        r.status = "error"
        r.error_message = f"Failed to enqueue reel task: {exc}"
        r.finished_at = datetime.utcnow()
        db.add(r)
        await db.commit()
        raise HTTPException(status_code=503, detail="Queue unavailable — render could not be started")
    return _reel_to_out(r)
