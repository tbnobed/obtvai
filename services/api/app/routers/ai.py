import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from ..database import get_db
from ..models import (
    AIConversation, AIMessage, MediaAsset, TranscriptSegment,
    Person, PersonAppearance,
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


async def _run_qa(
    question: str,
    context_segments: list,
    db: AsyncSession,
    single_asset: bool = False,
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

    if not context_parts:
        return "No indexed media content found that matches your question. Make sure videos have been processed and indexed.", []

    context_text = "\n".join(context_parts[:12])
    if single_asset:
        prompt = (
            f"Transcript excerpts from a single video (format: [timecode] speaker: text):\n{context_text}\n\n"
            f"Question: {question}\n\n"
            f"Answer the question using only these excerpts. Statements are first-person: "
            f"when a line is labeled with a speaker's name, facts they state about "
            f"themselves (\"my wife and I have six children\") are facts about that "
            f"speaker. Quote or paraphrase the relevant lines and mention their "
            f"timecodes (e.g. 50:39). Never mention any filename — refer to the "
            f"content as \"this video\". If the excerpts do not answer the question, "
            f"say so directly instead of guessing."
        )
    else:
        prompt = (
            f"Transcript excerpts (format: [filename @ timecode] speaker: text):\n{context_text}\n\n"
            f"Question: {question}\n\n"
            f"Answer the question using only these excerpts. Statements are first-person: "
            f"when a line is labeled with a speaker's name, facts they state about "
            f"themselves are facts about that speaker. Quote or paraphrase the "
            f"relevant lines and mention their timecodes. If the excerpts do not answer "
            f"the question, say so directly instead of guessing."
        )

    try:
        from ..services.llm import generate_response
        answer = await generate_response(prompt)
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

    return answer, citations[:5]


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

    user_msg = AIMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        role="user",
        content=body.question,
        created_at=datetime.utcnow(),
    )
    db.add(user_msg)

    # Hybrid retrieval: vector search finds semantically similar segments, but
    # misses first-person answers (the question names a person, the answer says
    # "my wife and I..."). Keyword search catches exact words like "children".
    # Run both and merge, deduping by segment id.
    context_segments: list = []
    seen_ids: set[str] = set()

    try:
        from ..services.embedding import get_text_embedding
        from ..services.qdrant_client import search_vectors

        q_vec = await get_text_embedding(body.question)
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
        for row in await _keyword_segments(db, body.question, body.media_id):
            seg = row[0]
            if seg.id not in seen_ids:
                context_segments.append(row)
                seen_ids.add(seg.id)
    except Exception:
        pass

    context_segments = context_segments[:12]

    answer_text, citations = await _run_qa(
        body.question, context_segments, db, single_asset=bool(body.media_id)
    )

    assistant_msg = AIMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        role="assistant",
        content=answer_text,
        citations=[c.model_dump() for c in citations],
        created_at=datetime.utcnow(),
    )
    db.add(assistant_msg)
    await db.commit()

    return AIAnswerOut(
        answer=answer_text,
        conversation_id=conv_id,
        citations=citations,
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
