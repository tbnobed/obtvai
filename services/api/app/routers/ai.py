import re
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, delete
from ..database import get_db
from ..models import (
    AIConversation, AIMessage, MediaAsset, TranscriptSegment,
    Person, PersonAppearance, Project,
)
from ..schemas import AIQuestion, AIAnswerOut, AICitationOut, ConversationOut, AIMessageOut
from ..config import settings

router = APIRouter(prefix="/ai", tags=["ai"])

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "do", "does", "did",
    "this", "that", "these", "those", "in", "on", "at", "of", "to",
    "about", "any", "some", "what", "who", "when", "where", "why",
    "how", "it", "its", "and", "or", "not", "sense", "mention",
    "mentions", "talk", "talks", "say", "says", "said", "video",
    "have", "has", "had", "many", "much", "with", "for", "his", "her",
    "their", "they", "she", "him", "them",
}


_MD_HEADER_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_MD_MARKS_RE = re.compile(r"\*\*|```[a-z]*|`")


def _strip_markdown(text: str) -> str:
    """The LLM leaks markdown (###, **, backticks) despite instructions;
    the chat UI renders plain text, so strip the noise. Single underscores
    and asterisks are left alone — filenames contain them."""
    return _MD_MARKS_RE.sub("", _MD_HEADER_RE.sub("", text))


def _question_keywords(question: str) -> list[str]:
    words = [w.strip("?,.!\"'") for w in question.lower().split()]
    return [w for w in words if len(w) > 2 and w not in _STOPWORDS][:6]


async def _keyword_segments(db: AsyncSession, question: str, media_id: str | None, limit: int = 8):
    """Keyword match over transcript text. Runs alongside vector search:
    embeddings miss first-person answers (question names a person, the answer
    says "my wife and I..."), while exact words like "children" still match."""
    from sqlalchemy import or_
    keywords = _question_keywords(question)
    if not keywords:
        return []
    q = select(TranscriptSegment, MediaAsset).join(
        MediaAsset, TranscriptSegment.media_id == MediaAsset.id
    ).where(or_(*[TranscriptSegment.text.ilike(f"%{kw}%") for kw in keywords]))
    if media_id:
        q = q.where(TranscriptSegment.media_id == media_id)
    return list((await db.execute(q.limit(limit))).all())


async def _speaker_names(db: AsyncSession, media_ids: set[str]) -> dict[tuple[str, str], str]:
    """Map (media_id, diarization label) -> identified person display name."""
    if not media_ids:
        return {}
    rows = await db.execute(
        select(PersonAppearance.media_id, PersonAppearance.speaker_label, Person.display_name)
        .join(Person, Person.id == PersonAppearance.person_id)
        .where(
            PersonAppearance.media_id.in_(media_ids),
            PersonAppearance.speaker_label.is_not(None),
        )
    )
    return {(mid, label): name for mid, label, name in rows.all() if label}


async def _conversation_history(db: AsyncSession, conv_id: str, limit: int = 8) -> list[dict]:
    """Last N messages of the conversation as chat history for the LLM."""
    rows = (
        await db.execute(
            select(AIMessage)
            .where(AIMessage.conversation_id == conv_id)
            .order_by(desc(AIMessage.created_at))
            .limit(limit)
        )
    ).scalars().all()
    # Cap per-message length so long chats can't blow up the LLM context
    # window or latency; recent turns matter most, full detail rarely does.
    return [
        {"role": m.role, "content": (m.content or "")[:1500]}
        for m in reversed(rows)
    ]


async def _standalone_question(question: str, history: list[dict]) -> str:
    """Rewrite a follow-up ("dive deeper", "what about her?") into a standalone
    question using the chat history, so retrieval searches for the actual topic
    instead of the literal follow-up words. Falls back to the raw question."""
    if not history:
        return question
    try:
        from ..services.llm import generate_response
        transcript = "\n".join(
            f"{m['role']}: {m['content'][:400]}" for m in history[-6:]
        )
        rewritten = await generate_response(
            (
                f"Conversation so far:\n{transcript}\n\n"
                f"Latest user message: {question}\n\n"
                f"Rewrite the latest user message as a single, fully self-contained "
                f"question about the video library, resolving references like "
                f"\"this\", \"her\", or \"dive deeper\" using the conversation. "
                f"Reply with ONLY the rewritten question."
            ),
            system=(
                "You rewrite follow-up chat messages into standalone search "
                "questions. Output only the rewritten question, nothing else."
            ),
            max_new_tokens=80,
        )
        rewritten = rewritten.strip().strip('"')
        if 5 < len(rewritten) < 400:
            return rewritten
    except Exception:
        pass
    return question


async def _library_overview(db: AsyncSession) -> str:
    """Compact aggregate snapshot of the whole library (topics, people,
    stored insights) so big-picture questions are answered from real
    library-wide data instead of whatever transcript lines happen to
    contain the question's words."""
    from sqlalchemy import text as sql_text
    from ..topic_norm import group_topics
    from ..models import LibraryInsight

    import logging
    log = logging.getLogger("obtv.ai")
    lines: list[str] = []
    try:
        total_assets, total_secs = (
            await db.execute(
                select(func.count(MediaAsset.id), func.coalesce(func.sum(MediaAsset.duration_seconds), 0))
            )
        ).one()
        lines.append(
            f"Total assets in the library: {total_assets}. (\"Assets\", \"videos\", "
            f"\"files\", and \"clips\" all refer to these {total_assets} items — "
            f"{float(total_secs) / 3600:.1f} hours of footage in total.)"
        )
    except Exception:
        log.exception("library overview: totals failed")

    try:
        raw_topic_rows = (
            await db.execute(
                sql_text("""
                    SELECT topic, COUNT(DISTINCT id) AS n
                    FROM media_assets, jsonb_array_elements_text(topics) AS topic
                    WHERE topics IS NOT NULL
                    GROUP BY topic
                """)
            )
        ).all()
        grouped = group_topics((t, int(n)) for t, n in raw_topic_rows)
        if grouped:
            lines.append("Top topics across the library (topic — number of videos): " + "; ".join(
                f"{g['topic']} — {g['asset_count']}" for g in grouped[:20]
            ))
    except Exception:
        log.exception("library overview: topics failed")

    try:
        top_people = (
            await db.execute(
                select(
                    Person.display_name,
                    func.count(func.distinct(PersonAppearance.media_id)).label("assets"),
                    func.coalesce(func.sum(PersonAppearance.speaking_seconds), 0).label("secs"),
                )
                .join(PersonAppearance, PersonAppearance.person_id == Person.id)
                .group_by(Person.id)
                .order_by(func.count(func.distinct(PersonAppearance.media_id)).desc())
                .limit(12)
            )
        ).all()
        if top_people:
            lines.append("Most-seen people (name — videos, speaking time): " + "; ".join(
                f"{name} — {assets} videos, {float(secs) / 60:.0f} min" for name, assets, secs in top_people
            ))
    except Exception:
        log.exception("library overview: people failed")

    try:
        stored = (
            await db.execute(select(LibraryInsight).where(LibraryInsight.id == 1))
        ).scalar_one_or_none()
        if stored:
            if getattr(stored, "headline", None):
                lines.append(f"Library insights headline: {stored.headline}")
            for i in (stored.insights or [])[:6]:
                if isinstance(i, dict) and i.get("title"):
                    detail = (i.get("detail") or "")[:200]
                    lines.append(f"Insight: {i['title']} — {detail}")
    except Exception:
        log.exception("library overview: stored insights failed")
    return "\n".join(lines)


async def _run_qa(
    question: str,
    context_segments: list,
    db: AsyncSession,
    single_asset: bool = False,
    history: list[dict] | None = None,
    visual_lines: list[str] | None = None,
    overview: str | None = None,
) -> tuple[str, list[AICitationOut]]:
    """Run local LLM QA over retrieved context segments.

    single_asset: the chat is scoped to one video, so context labels and the
    prompt reference timecodes only — repeating the filename in every line is
    noise when the user is already on that asset's page.
    """
    citations: list[AICitationOut] = []
    context_parts: list[str] = []

    # Resolve diarization labels to identified person names so the LLM can
    # attribute first-person statements ("my wife and I...") to the speaker.
    speaker_names = await _speaker_names(db, {asset.id for _, asset in context_segments})

    for seg, asset in context_segments:
        tc = f"{int(seg.start_time // 60):02d}:{int(seg.start_time % 60):02d}"
        name = speaker_names.get((asset.id, seg.speaker)) if seg.speaker else None
        spoken = f"{name}: {seg.text}" if name else seg.text
        if single_asset:
            context_parts.append(f"[{tc}] {spoken}")
        else:
            context_parts.append(f"[{asset.filename} @ {tc}] {spoken}")
        citations.append(AICitationOut(
            media_id=asset.id,
            filename=asset.filename,
            start_time=seg.start_time,
            end_time=seg.end_time,
            snippet=seg.text[:200],
        ))

    if not context_parts and not visual_lines and not overview:
        if history:
            # Follow-up with no new retrievable context (e.g. "summarize what we
            # discussed") — let the LLM answer from the conversation itself.
            try:
                from ..services.llm import generate_response
                answer = await generate_response(
                    question, history=history, max_new_tokens=1500
                )
                return _strip_markdown(answer), []
            except Exception:
                pass
        return "No indexed media content found that matches your question. Make sure videos have been processed and indexed.", []

    context_text = "\n".join(context_parts[:12]) or "(none found)"
    visual_text = ""
    if visual_lines:
        visual_text = (
            "\n\nVISUAL SCENE MATCHES (keyframe analysis — footage that LOOKS "
            "like the query even when nobody talks about it; each segment merges "
            "matching shots within ~30s, so segment counts closely estimate "
            "distinct occurrences):\n" + "\n".join(visual_lines[:12])
        )
    if single_asset:
        prompt = (
            f"Transcript excerpts from a single video (format: [timecode] speaker: text):\n{context_text}"
            f"{visual_text}\n\n"
            f"Question: {question}\n\n"
            f"Answer the question using these excerpts as evidence. Statements are "
            f"first-person: when a line is labeled with a speaker's name, facts they "
            f"state about themselves (\"my wife and I have six children\") are facts "
            f"about that speaker. Quote or paraphrase the relevant lines and mention "
            f"their timecodes (e.g. 50:39). Never mention any filename — refer to the "
            f"content as \"this video\". Synthesize and interpret: if the excerpts "
            f"only imply an answer, give your best analytical reading and label it as "
            f"interpretation. Only say the excerpts don't answer the question if "
            f"nothing here is relevant. Transcripts only cover what is SAID — "
            f"for questions about what is SHOWN (performances, locations, "
            f"visuals), trust the visual scene matches and count their "
            f"segments. Do not invent quotes or timecodes."
        )
    else:
        overview_text = (
            f"LIBRARY OVERVIEW (authoritative aggregate data computed across the "
            f"entire library — for big-picture questions about main topics, themes, "
            f"key people, or what the library contains, base your answer on THIS "
            f"data first; transcript excerpts below are only supporting evidence. "
            f"When the question asks for counts or totals — how many videos, "
            f"assets, hours, people — answer directly from this overview. Numbers "
            f"that speakers happen to SAY in transcripts are things people said "
            f"on camera, NOT statistics about this library; never present them "
            f"as the library's totals):\n"
            f"{overview}\n\n"
        ) if overview else ""
        prompt = (
            f"{overview_text}"
            f"Transcript excerpts (format: [filename @ timecode] speaker: text):\n{context_text}"
            f"{visual_text}\n\n"
            f"Question: {question}\n\n"
            f"Answer the question using these excerpts as evidence. Statements are "
            f"first-person: when a line is labeled with a speaker's name, facts they "
            f"state about themselves are facts about that speaker. Quote or paraphrase "
            f"the relevant lines and mention their filenames and timecodes. "
            f"Synthesize and interpret: look for themes and patterns across excerpts "
            f"and different videos, and if the excerpts only imply an answer, give "
            f"your best analytical reading and label it as interpretation. Only say "
            f"the excerpts don't answer the question if nothing here is relevant. "
            f"Transcripts only cover what is SAID — for questions about what is "
            f"SHOWN (performances, locations, visuals), trust the visual scene "
            f"matches and count their segments. "
            f"Do not invent quotes or timecodes."
        )

    try:
        from ..services.llm import generate_response
        system = None
        if overview and not single_asset:
            system = (
                "You are a sharp, analytical media librarian for a video archive. "
                "The prompt contains a LIBRARY OVERVIEW block with authoritative, "
                "machine-computed statistics about the whole library (video counts, "
                "hours, topics, people). Any question about library totals, main "
                "topics, or key people MUST be answered from that block — those "
                "numbers are ground truth. Transcript excerpts are only quotes of "
                "what people said on camera; never treat numbers spoken in them as "
                "library statistics. For questions about specific spoken content, "
                "quote the excerpts with filenames and timecodes. Be direct and "
                "specific; make clear when something is interpretation. Start with "
                "the substance itself — no boilerplate openings. Plain text only, "
                "no markdown."
            )
        from ..services.web_search import generate_with_web
        answer = await generate_with_web(
            generate_response, prompt, history=history, max_new_tokens=1500,
            system=system, user_text=question,
        )
        answer = _strip_markdown(answer)
    except Exception as e:
        transcript_summary = "\n".join(
            (
                f"- {int(seg.start_time // 60):02d}:{int(seg.start_time % 60):02d}: {seg.text[:120]}"
                if single_asset
                else f"- {asset.filename} @ {seg.start_time:.0f}s: {seg.text[:120]}"
            )
            for seg, asset in context_segments[:3]
        )
        answer = (
            f"The AI model is currently unavailable, so here are the raw transcript "
            f"passages most related to your question:\n\n"
            f"{transcript_summary}\n\n"
            f"(Error: {e})"
        )

    # Sources must support the answer. In library-wide chats, retrieval always
    # fetches *something*, but aggregate answers (counts, topics, people) come
    # from the overview — attaching unrelated clips as "sources" is noise.
    # Keep only citations whose file the answer actually references.
    if not single_asset:
        referenced = [c for c in citations if c.filename in answer]
        citations = referenced

    return answer, citations[:5]


# ── Project creation from chat ───────────────────────────────────────────────
# "Combine these into a project / make a scary story" must DO it, not describe
# it: pick clips from the retrieved evidence, create the project with its
# media pool, and save the selection as draft-cut revision 1.

_PROJECT_INTENT_RE = re.compile(
    r"\b(make|create|build|combine|turn|put|assemble|stitch|cut)\b"
    r".{0,80}\b(project|cut|montage|story|reel|edit|video|compilation)\b",
    re.IGNORECASE | re.DOTALL,
)

_CREATE_SYSTEM = (
    "You are a video editor building a project from a media library. You are "
    "given numbered candidate clips (transcript moments and visual scene "
    "matches) with real timecodes. Decide whether the user is asking you to "
    "CREATE a project/cut, and if so select and order clips that tell the "
    "story they asked for.\n"
    "Rules:\n"
    "- Only use the numbered candidates. Never invent files or timecodes.\n"
    "- start/end must stay inside the candidate's window; prefer 3-30s clips "
    "(trim long windows to the strongest stretch).\n"
    "- Order clips for narrative arc, not by source file.\n"
    "- 'answer' is your reply to the user: one short paragraph describing the "
    "project you built (no markdown).\n"
    "Return ONLY a JSON object:\n"
    '{"create": true|false, "name": "<project name, <=60 chars>", '
    '"description": "<1-2 sentences>", '
    '"clips": [{"i": <candidate number>, "start": <sec>, "end": <sec>}], '
    '"answer": "<reply>"}\n'
    'If the user is NOT asking you to build something, return {"create": false}.'
)


async def _maybe_create_project(
    db: AsyncSession, question: str, retrieval_question: str,
    context_segments: list, history: list,
) -> tuple[str, str, str] | None:
    """If the question asks to build a project, create it (pool + draft cut v1)
    and return (answer, project_id, project_name). None = not an action turn."""
    from .project_chat import _visual_segments, _extract_json, _save_revision, _sanitize_clips
    from ..services.llm import generate_response

    # Candidates: transcript moments + visual scene segments, numbered.
    candidates: list[dict] = []
    for seg, asset in context_segments:
        candidates.append({
            "media_id": seg.media_id, "filename": asset.filename,
            "start": float(seg.start_time), "end": float(seg.end_time),
            "note": f'says: "{(seg.text or "")[:140]}"',
            "thumb": asset.thumbnail_url,
        })
    try:
        for _q, mid, fname, segs in await _visual_segments([retrieval_question], None, db):
            for a, b in segs[:8]:
                candidates.append({
                    "media_id": mid, "filename": fname,
                    "start": float(a), "end": float(b),
                    "note": f'looks like "{retrieval_question[:80]}"',
                    "thumb": None,
                })
    except Exception:
        pass  # transcript candidates alone can still build the cut
    candidates = candidates[:40]
    if not candidates:
        return None

    lines = [
        f"{i + 1}. [{c['filename']}] {c['start']:.1f}-{c['end']:.1f}s — {c['note']}"
        for i, c in enumerate(candidates)
    ]
    reply = await generate_response(
        f"User request: {question}\n\nCandidate clips:\n" + "\n".join(lines),
        history=history, system=_CREATE_SYSTEM, max_new_tokens=1200,
    )
    data = _extract_json(reply)
    if not isinstance(data, dict) or not data.get("create"):
        return None

    raw_clips = data.get("clips") or []
    thumbs = {c["media_id"]: c["thumb"] for c in candidates if c.get("thumb")}
    clips: list[dict] = []
    for item in raw_clips[:30]:
        try:
            idx = int(item["i"])
        except (KeyError, ValueError, TypeError):
            continue
        if not 1 <= idx <= len(candidates):
            continue  # reject 0/negative/out-of-range — never wrap around
        cand = candidates[idx - 1]
        # Clamp the model's trim into the candidate's real window.
        try:
            start = max(cand["start"], float(item.get("start", cand["start"])))
            end = min(cand["end"], float(item.get("end", cand["end"])))
        except (ValueError, TypeError):
            start, end = cand["start"], cand["end"]
        if end - start < 0.5:
            start, end = cand["start"], cand["end"]
        clips.append({
            "media_id": cand["media_id"], "filename": cand["filename"],
            "start_time": round(start, 2), "end_time": round(end, 2),
            "snippet": cand["note"][:200],
            "thumbnail_url": thumbs.get(cand["media_id"]),
            "locked": False,
        })
    clips = _sanitize_clips(clips)
    if not clips:
        return None

    name = (str(data.get("name") or "").strip() or question[:60])[:60]
    description = str(data.get("description") or "").strip()[:500] or None
    media_ids: list[str] = []
    for c in clips:
        if c["media_id"] not in media_ids:
            media_ids.append(c["media_id"])

    project = Project(
        id=str(uuid.uuid4()), name=name, description=description,
        media_ids=media_ids, media_ranges={},
    )
    db.add(project)
    await db.flush()
    await _save_revision(db, project.id, clips, summary=f"Created from AI chat: {name}", source="assistant")

    answer = str(data.get("answer") or "").strip() or f"Created the project '{name}'."
    answer += (
        f"\n\nProject '{name}' is ready: {len(clips)} clips from "
        f"{len(media_ids)} assets in the media pool, saved as draft cut v1."
    )
    return answer, project.id, name


@router.post("/ask", response_model=AIAnswerOut)
async def ask_ai(body: AIQuestion, db: AsyncSession = Depends(get_db)):
    conv_id = body.conversation_id
    if not conv_id:
        conv = AIConversation(
            id=str(uuid.uuid4()),
            title=body.question[:80],
            created_at=datetime.utcnow(),
        )
        db.add(conv)
        await db.flush()
        conv_id = conv.id
    else:
        conv_result = await db.execute(select(AIConversation).where(AIConversation.id == conv_id))
        conv = conv_result.scalar_one_or_none()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

    # Load conversation history BEFORE inserting the new user message so the
    # history reflects prior turns only.
    history = await _conversation_history(db, conv_id) if body.conversation_id else []

    user_msg = AIMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        role="user",
        content=body.question,
        created_at=datetime.utcnow(),
    )
    db.add(user_msg)

    # Follow-ups like "dive deeper" or "what about her?" are useless as
    # retrieval queries — rewrite them into standalone questions first.
    retrieval_question = await _standalone_question(body.question, history)

    # Hybrid retrieval: vector search finds semantically similar segments, but
    # misses first-person answers (the question names a person, the answer says
    # "my wife and I..."). Keyword search catches exact words like "children".
    # Run both and merge, deduping by segment id.
    context_segments: list = []
    seen_ids: set[str] = set()

    try:
        from ..services.embedding import get_text_embedding
        from ..services.qdrant_client import search_vectors

        q_vec = await get_text_embedding(retrieval_question)
        hits = await search_vectors(
            collection="transcripts",
            vector=q_vec,
            limit=8,
            media_id=body.media_id,
        )
        for hit in hits:
            seg_id = hit.payload.get("segment_id")
            if not seg_id or seg_id in seen_ids:
                continue
            row = (await db.execute(
                select(TranscriptSegment, MediaAsset)
                .join(MediaAsset, TranscriptSegment.media_id == MediaAsset.id)
                .where(TranscriptSegment.id == seg_id)
            )).first()
            if row:
                context_segments.append(row)
                seen_ids.add(seg_id)
    except Exception:
        pass  # vector search unavailable — keyword results below still apply

    try:
        for row in await _keyword_segments(db, retrieval_question, body.media_id):
            seg = row[0]
            if seg.id not in seen_ids:
                context_segments.append(row)
                seen_ids.add(seg.id)
    except Exception:
        pass

    context_segments = context_segments[:12]

    visual_lines: list[str] = []
    try:
        from .project_chat import _visual_research
        visual_lines = await _visual_research(
            [retrieval_question],
            [body.media_id] if body.media_id else None,
            db,
        )
    except Exception:
        pass  # visual retrieval unavailable — transcript answer still works

    overview = None if body.media_id else await _library_overview(db)

    # "How many assets mention/talk about X?" cannot be answered from a
    # dozen retrieved snippets — count over the whole database instead and
    # hand the model exact figures.
    if overview is not None:
        try:
            kw_lines = []
            for kw in _question_keywords(retrieval_question)[:4]:
                n = (
                    await db.execute(
                        select(func.count(func.distinct(TranscriptSegment.media_id)))
                        .where(TranscriptSegment.text.ilike(f"%{kw}%"))
                    )
                ).scalar_one()
                if n:
                    kw_lines.append(f'Assets whose transcripts mention "{kw}": {n}')
                n_appear = (
                    await db.execute(
                        select(func.count(func.distinct(PersonAppearance.media_id)))
                        .join(Person, Person.id == PersonAppearance.person_id)
                        .where(Person.display_name.ilike(f"%{kw}%"))
                    )
                ).scalar_one()
                if n_appear:
                    kw_lines.append(f'Assets where an identified person named like "{kw}" appears on screen or speaks: {n_appear}')
            if kw_lines:
                overview += (
                    "\nExact database counts (distinct assets, whole library — "
                    "use THESE for any \"how many assets mention/talk about X\" "
                    "question, not the number of excerpts below):\n"
                    + "\n".join(kw_lines)
                )
        except Exception:
            pass

    # Action turn: "combine these into a project / make a story" creates the
    # project + draft cut instead of just describing one.
    project_id = project_name = None
    answer_text = None
    citations: list = []
    if _PROJECT_INTENT_RE.search(body.question):
        # Savepoint: a failure mid-creation must not leave a half-created
        # project/revision that the message commit below would persist.
        try:
            async with db.begin_nested():
                created = await _maybe_create_project(
                    db, body.question, retrieval_question, context_segments, history,
                )
            if created:
                answer_text, project_id, project_name = created
        except Exception as e:
            import logging
            logging.getLogger("ai").warning("project creation from chat failed: %s", e, exc_info=True)
            # fall through to a normal answer

    if answer_text is None:
        answer_text, citations = await _run_qa(
            body.question, context_segments, db,
            single_asset=bool(body.media_id), history=history,
            visual_lines=visual_lines, overview=overview,
        )

    assistant_msg = AIMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        role="assistant",
        content=answer_text,
        citations=[c.model_dump() for c in citations],
        project_id=project_id,
        project_name=project_name,
        created_at=datetime.utcnow(),
    )
    db.add(assistant_msg)
    await db.commit()

    return AIAnswerOut(
        answer=answer_text,
        conversation_id=conv_id,
        citations=citations,
        project_id=project_id,
        project_name=project_name,
    )


@router.get("/conversations/{id}/messages", response_model=list[AIMessageOut])
async def get_conversation_messages(id: str, db: AsyncSession = Depends(get_db)):
    conv_result = await db.execute(select(AIConversation).where(AIConversation.id == id))
    if not conv_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Conversation not found")
    result = await db.execute(
        select(AIMessage)
        .where(AIMessage.conversation_id == id)
        .order_by(AIMessage.created_at)
    )
    return [AIMessageOut.model_validate(m) for m in result.scalars().all()]


@router.delete("/conversations/{id}", status_code=204)
async def delete_conversation(id: str, db: AsyncSession = Depends(get_db)):
    conv_result = await db.execute(select(AIConversation).where(AIConversation.id == id))
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.execute(delete(AIMessage).where(AIMessage.conversation_id == id))
    await db.delete(conv)
    await db.commit()


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(
            AIConversation,
            func.count(AIMessage.id).label("message_count"),
        )
        .outerjoin(AIMessage, AIConversation.id == AIMessage.conversation_id)
        .group_by(AIConversation.id)
        .order_by(desc(AIConversation.created_at))
        .limit(50)
    )
    out = []
    for conv, count in result.all():
        out.append(ConversationOut(
            id=conv.id,
            title=conv.title,
            created_at=conv.created_at,
            message_count=count,
        ))
    return out
