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
    Project, ProjectChatMessage, ProjectCutRevision, ReelJob, MediaAsset,
)
from ..schemas import (
    ProjectChatMessageOut, ProjectChatMessageIn, ProjectCutOut, CutClip,
    CutUpdateIn, CutRevertIn, CutRenderIn, ReelJobOut,
)
from ..worker_client import enqueue_reel
from .projects import touch_project
from .reels import _select_clips, _fill_to_target, _merge_overlaps, _to_out as _reel_to_out

router = APIRouter(prefix="/projects/{project_id}/chat", tags=["project-chat"])
cut_router = APIRouter(prefix="/projects/{project_id}/cut", tags=["project-cut"])

logger = logging.getLogger("obtv.project_chat")

_turn_tasks: dict[str, asyncio.Task] = {}
_turn_locks: dict[str, asyncio.Lock] = {}

_MAX_HISTORY = 16
_MAX_CANDIDATES = 40
_MAX_CUT_LINES = 80
_SNIPPET_CHARS = 220


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
    '"searches": ["up to 3 transcript search queries to find new material"], '
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
    "phrases, speakers), not editing instructions.\n"
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
        plan_prompt = (
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

        if mode == "answer":
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

        if mode == "adjust":
            # Reshape the existing cut — runtime, removals, per-clip resize.
            new_cut = [c for i, c in enumerate(cut, 1) if i not in removals or c.get("locked")]
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
                # Nothing actually changed — reply without saving a revision.
                reply = (plan.get("reply") or "").strip() or (
                    "That leaves the cut as it is — tell me what you'd like different."
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

        # Round-robin across source files so every episode stays visible even
        # after the cap, instead of the top-scoring file eating the whole list.
        by_file: dict[str, list[dict]] = {}
        for c in candidates:
            by_file.setdefault(c["media_id"], []).append(c)
        interleaved: list[dict] = []
        while len(interleaved) < _MAX_CANDIDATES and any(by_file.values()):
            for lst in by_file.values():
                if lst:
                    interleaved.append(lst.pop(0))
        candidates = interleaved[:_MAX_CANDIDATES]

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
