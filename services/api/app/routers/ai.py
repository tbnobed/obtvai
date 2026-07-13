import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from ..database import get_db
from ..models import AIConversation, AIMessage, MediaAsset, TranscriptSegment
from ..schemas import AIQuestion, AIAnswerOut, AICitationOut, ConversationOut, AIMessageOut
from ..config import settings

router = APIRouter(prefix="/ai", tags=["ai"])


async def _run_qa(question: str, context_segments: list, db: AsyncSession) -> tuple[str, list[AICitationOut]]:
    """Run local LLM QA over retrieved context segments."""
    citations: list[AICitationOut] = []
    context_parts: list[str] = []

    for seg, asset in context_segments:
        tc = f"{int(seg.start_time // 60):02d}:{int(seg.start_time % 60):02d}"
        context_parts.append(
            f"[{asset.filename} @ {tc}] {seg.text}"
        )
        citations.append(AICitationOut(
            media_id=asset.id,
            filename=asset.filename,
            start_time=seg.start_time,
            end_time=seg.end_time,
            snippet=seg.text[:200],
        ))

    if not context_parts:
        return "No indexed media content found that matches your question. Make sure videos have been processed and indexed.", []

    context_text = "\n".join(context_parts[:10])
    prompt = (
        f"Transcript excerpts (format: [filename @ timecode] text):\n{context_text}\n\n"
        f"Question: {question}\n\n"
        f"Answer the question using only these excerpts. Quote or paraphrase the "
        f"relevant lines and mention their timecodes. If the excerpts do not answer "
        f"the question, say so directly instead of guessing."
    )

    try:
        from ..services.llm import generate_response
        answer = await generate_response(prompt)
    except Exception as e:
        transcript_summary = "\n".join(
            f"- {asset.filename} @ {seg.start_time:.0f}s: {seg.text[:120]}"
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

    context_segments: list = []
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
            row = (await db.execute(
                select(TranscriptSegment, MediaAsset)
                .join(MediaAsset, TranscriptSegment.media_id == MediaAsset.id)
                .where(TranscriptSegment.id == seg_id)
            )).first()
            if row:
                context_segments.append(row)
    except Exception:
        # Keyword fallback when vector search is unavailable: match on the
        # meaningful words of the question, not stopwords like "does"/"this".
        from sqlalchemy import or_
        stopwords = {
            "a", "an", "the", "is", "are", "was", "were", "do", "does", "did",
            "this", "that", "these", "those", "in", "on", "at", "of", "to",
            "about", "any", "some", "what", "who", "when", "where", "why",
            "how", "it", "its", "and", "or", "not", "sense", "mention",
            "mentions", "talk", "talks", "say", "says", "said", "video",
        }
        words = [
            w.strip("?,.!\"'") for w in body.question.lower().split()
        ]
        keywords = [w for w in words if len(w) > 2 and w not in stopwords][:6]
        if keywords:
            q = select(TranscriptSegment, MediaAsset).join(
                MediaAsset, TranscriptSegment.media_id == MediaAsset.id
            ).where(or_(*[TranscriptSegment.text.ilike(f"%{kw}%") for kw in keywords]))
            if body.media_id:
                q = q.where(TranscriptSegment.media_id == body.media_id)
            rows = (await db.execute(q.limit(8))).all()
            context_segments = list(rows)

    answer_text, citations = await _run_qa(body.question, context_segments, db)

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
