import re
import uuid
import calendar
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, delete, or_, cast, String
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
    from ..services.archive_memory import literal_pattern
    q = select(TranscriptSegment, MediaAsset).join(
        MediaAsset, TranscriptSegment.media_id == MediaAsset.id
    ).where(or_(*[TranscriptSegment.text.ilike(literal_pattern(kw), escape="\\") for kw in keywords]))
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
        {"role": m.role, "content": (m.content or "")[:1500],
         "searched": m.citations is not None if m.role == "assistant" else None}
        for m in reversed(rows)
    ]


_SCOPE_FACTS = (
    "I search the indexed assets in this archive, not the entire Curator catalog. "
    "Library UI filters and folders do not constrain my searches; selecting a single "
    "asset (media_id) does. An original-air-date request filters stored Curator original "
    "air date metadata only, excludes assets with unknown dates, and does not search "
    "spoken dates or guarantee coverage of the full Curator catalog."
)
_ROUTE_CLARIFICATION = (
    "Do you want me to search the archive, refine your previous search, or explain "
    "the scope of my previous answer? Please specify what you want to find."
)
_CONVERSATION_FAILURE = (
    "I couldn't formulate a reliable reply right now. No new archive search was performed; "
    "please try asking again."
)
_EXPLICIT_SEARCH = re.compile(
    r"^\s*(?:find|search(?: for)?|show(?: me)?|list|locate|"
    r"look for|give me|which (?:videos?|clips?|assets?|files?|recordings?))\b", re.I,
)
_FOLLOWUP_PREFIX = re.compile(
    r"^\s*(?:only|just|instead|what about|and|those|these|within|restrict|limit|narrow)\b", re.I,
)
_SCOPE_QUERY = re.compile(
    r"\b(?:search(?:ing)?|look(?:ing)?|cover(?:ing)?|include|scope|access|"
    r"see|use|limitations?|capabilit(?:y|ies))\b.{0,90}"
    r"\b(?:entire|whole|all|library|catalog|folders?|filters?|archives?|assets?)\b|"
    r"\b(?:entire|whole)\s+(?:library|catalog|archive)\b", re.I,
)


def _last_search_question(history: list[dict]) -> str | None:
    """Ignore conversational interruptions; null citations mark non-search turns."""
    for index in range(len(history) - 1, 0, -1):
        if (history[index]["role"] == "assistant" and history[index].get("searched")
                and history[index - 1]["role"] == "user"):
            question = history[index - 1]["content"]
            if _air_date_intent(question):
                return question
            # A refinement's user text ("only September") is not standalone.
            # Recover its *executed* month/year from the grounded metadata answer,
            # not from a guessed model rewrite or the current calendar year.
            answer = history[index]["content"]
            period = re.match(
                r"\d+ asset\(s\) with an original air date from "
                r"((?:19|20)\d{2})-(\d{2})-01 through "
                r"((?:19|20)\d{2})-(\d{2})-(\d{2})\.",
                answer,
            )
            if period:
                start_year, start_month, end_year, end_month, end_day = map(int, period.groups())
                if (start_year, start_month) == (end_year, end_month) and (
                    end_day == calendar.monthrange(start_year, start_month)[1]
                ):
                    month = calendar.month_name[start_month]
                    return f"Show all media aired in {month} {start_year}"
            return question
    return None


def _date_refinement(question: str, prior: str | None) -> str | None:
    """Reconstruct a metadata request rather than sending a month to semantic retrieval."""
    if not prior or not _air_date_intent(prior):
        return None
    month = re.search(rf"\b({_MONTH_PATTERN})\b", question, re.I)
    if not month:
        return None
    # Don't silently drop additional filters or infer a year from today's date.
    if not re.fullmatch(
        rf"\s*(?:(?:only|just|instead|what about|and|in|during|for|show me|the)\s+)*"
        rf"(?:{_MONTH_PATTERN})(?:\s+(?:of\s+)?\d{{4}})?\s*[?.!]?\s*",
        question, re.I,
    ):
        return None
    year = re.search(r"\b(?:19|20)\d{2}\b", question)
    if not year:
        previous = _air_date_range(prior)
        if previous is None or previous[0].year != (previous[1] - timedelta(days=1)).year:
            return None
        year = re.search(r"\b(?:19|20)\d{2}\b", str(previous[0].year))
    query = f"Show all media aired in {month.group(1)} {year.group()}"
    return query if _air_date_range(query) else None


def _prior_explanation_intent(question: str, history: list[dict]) -> bool:
    """Short, referential questions about an existing answer are not media queries."""
    if not any(m["role"] == "assistant" for m in history):
        return False
    words = re.findall(r"\b[\w']+\b", question.lower())
    if len(words) > 16 or not words:
        return False
    if re.search(r"\b(?:find|search|clips?|videos?|where|which|who|what happened|"
                 r"people|characters?|he|she|they|speaker|interview)\b", question, re.I):
        return False
    if not re.match(
        r"^\s*(?:why|how(?: come)?|(?:can|could|would) you (?:explain|clarify)|"
        r"explain|what (?:does|do|made))\b", question, re.I,
    ):
        return False
    return bool(re.search(
        r"\b(?:only|few|many|that|this|those|your|you|earlier|previous|"
        r"number|count|results?|matches?|citations?|answers?|excluded|included)\b",
        question, re.I,
    ) or re.search(r"\b\d+\b", question))


async def _route_turn(question: str, history: list[dict]) -> tuple[str, str]:
    """Closed-set LLM intent router. Invalid/failed decisions never become retrieval queries."""
    prior = _last_search_question(history)
    explicit_target_search = (
        _EXPLICIT_SEARCH.search(question)
        and re.search(r"\b(?:for|about|featuring|containing|mentioning|with)\s+\S+", question, re.I)
    )
    if _SCOPE_QUERY.search(question) and not _PROJECT_INTENT_RE.search(question) and not explicit_target_search:
        return "conversation", "scope"
    # An elliptical month is never a standalone scene search. Recover its year
    # from the last date result, even when conversation intervened.
    if _FOLLOWUP_PREFIX.search(question) and re.search(rf"\b(?:{_MONTH_PATTERN})\b", question, re.I):
        date_query = _date_refinement(question, prior)
        return ("date", date_query) if date_query else ("clarify", "")
    if _prior_explanation_intent(question, history):
        return "conversation", "prior"
    # Explicit standalone requests keep their existing search/project/date behavior.
    if _PROJECT_INTENT_RE.search(question) or (
        _EXPLICIT_SEARCH.search(question) and not _FOLLOWUP_PREFIX.search(question)
        and (explicit_target_search or not re.search(
            r"\b(?:scope|entire library|whole library|all library|searching|previous answer)\b",
            question, re.I,
        ))
    ):
        return "search", question
    from ..services.llm import generate_response
    transcript = "\n".join(
        f"{m['role']} ({'search' if m.get('searched') else 'conversation'}): {m['content'][:400]}"
        for m in history[-8:]
    )
    try:
        reply = await generate_response(
            f"History:\n{transcript}\nPrevious search request: {prior or 'none'}\n"
            f"Latest message: {question}\n"
            'Return JSON ONLY: {"intent":"conversation|refinement|search|clarify",'
            '"topic":"scope|prior|other","query":"standalone archive search request or empty"}',
            system=(
                "Classify the user's latest turn. Conversation includes questions about "
                "search scope, capabilities, limitations and clarification of previous answers; "
                "it NEVER searches. Refinement changes the prior search criteria (even across "
                "conversational interruptions). Search is a genuinely new archive request. "
                "Examples: after an answer with 12 results, 'why only twelve?', "
                "'how come so few?', 'why did you show just 12?', and 'how was that "
                "count decided?' are conversation/prior, not clarify or search. "
                "'Why did the speaker say that?' asks about media content and is "
                "search, not an explanation of the assistant's result count. "
                "If uncertain, classify clarify. For refinement/search give a fully specified "
                "standalone query. Do not invent dates or filters. topic is scope for questions "
                "about archive coverage, library filters, date coverage or capabilities, "
                "prior for explanations of an earlier answer, other otherwise."
            ),
            max_new_tokens=160,
        )
        from .project_chat import _extract_json
        data = _extract_json(reply)
        if not isinstance(data, dict):
            return "clarify", ""
        intent, topic, query = data.get("intent"), data.get("topic"), data.get("query")
        if intent == "conversation" and topic in {"scope", "prior", "other"}:
            return "conversation", topic
        if intent == "refinement" and prior:
            date_query = _date_refinement(question, prior)
            if date_query:
                return "date", date_query
            if isinstance(query, str) and 5 < len(query) < 400 and not (
                _air_date_intent(prior) or _air_date_intent(query)
            ):
                return "search", query
        if intent == "search" and isinstance(query, str) and 5 < len(query) < 400:
            return "search", query
    except Exception:
        pass
    return "clarify", ""


async def _conversation_answer(question: str, history: list[dict], media_id: str | None) -> str:
    """Reply using the dialog and documented behavior only; never consult the archive."""
    from ..services.llm import generate_response

    scope = "This turn is restricted to the selected asset (media_id)." if media_id else (
        "There is no selected-asset (media_id) restriction on this turn."
    )
    try:
        answer = await generate_response(
            question,
            history=history,
            system=(
                "You are answering a conversational follow-up, NOT searching. Respond "
                "naturally and briefly to the latest message, including acknowledgments. "
                "Explain a previous answer when asked, using only conversation history "
                "and the following authoritative facts; don't just repeat the prior answer. "
                f"Archive scope facts: {_SCOPE_FACTS} {scope} "
                "Citations in earlier answers are evidence shown to the user; they are "
                "not necessarily an exhaustive count of all matches. Do not claim to know "
                "why an exact count of results was shown unless history explicitly gives "
                "the reason. If the history does not support an explanation, say what is "
                "unknown and what can be inferred from the known scope/limits. "
                "Never invent media, result counts, dates, unshown searches, actions or "
                "system access. Do not claim that you just searched or changed anything. "
                "If asked to search, ask for a separate search request."
            ),
            max_new_tokens=220,
        )
        answer = _strip_markdown(answer).strip()
        return answer[:1500] if answer else _CONVERSATION_FAILURE
    except Exception:
        return _CONVERSATION_FAILURE


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
    from ..services.archive_memory import overview
    return await overview(db, lambda: _build_library_overview(db))


_ASSET_LOOKUP_RE = re.compile(
    r"^\s*(?:find|show(?: me)?|list|which|what)\s+"
    r"(?:the |some |all )?(?:videos?|assets?|clips?|files?|recordings?)"
    r"\s+(?:about|on|of|with|featuring|related to)\s+(.+?)\s*[?.!]?\s*$",
    re.I,
)


async def _structured_assets(db: AsyncSession, question: str) -> list[MediaAsset]:
    """Find real assets from library metadata for explicit asset-list requests.

    An asset need not have a transcript to be discoverable. Do not mistake a
    question about totals or a compound filter for an exhaustive catalog query.
    """
    match = _ASSET_LOOKUP_RE.fullmatch(question)
    if not match:
        return []
    term = match.group(1).strip().rstrip("?.!").strip().strip("\"'")
    if not 3 <= len(term) <= 120 or re.search(r"\b(?:and|or|before|after|between)\b", term, re.I):
        return []
    from ..services.archive_memory import literal_pattern
    pattern = literal_pattern(term)
    rows = await db.execute(
        select(MediaAsset).where(or_(
            MediaAsset.filename.ilike(pattern, escape="\\"),
            MediaAsset.synopsis.ilike(pattern, escape="\\"),
            cast(MediaAsset.topics, String).ilike(pattern, escape="\\"),
        )).order_by(MediaAsset.filename, MediaAsset.id).limit(12)
    )
    return list(rows.scalars().all())


def _asset_citation(asset: MediaAsset) -> AICitationOut:
    # Metadata identifies the asset, not a spoken passage or particular scene.
    return AICitationOut(
        media_id=asset.id, filename=asset.filename, start_time=0, end_time=0,
        snippet=(asset.synopsis or ", ".join(
            t for t in (asset.topics or []) if isinstance(t, str)
        ) or asset.filename)[:200],
    )


_MONTH_NAMES = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
_MONTH_PATTERN = "|".join(_MONTH_NAMES)
_TEMPORAL_VALUE = (
    rf"(?:{_MONTH_PATTERN})\b|\d{{4}}(?:-\d{{2}}(?:-\d{{2}})?)?\b|"
    r"today\b|yesterday\b|recently\b|lately\b|"
    r"(?:this|last|next)\s+(?:week|month|year)\b"
)
_METADATA_DATE_FIELD = re.compile(
    r"\b(?:original air date|air date|broadcast date|last air date|"
    r"created|aired|broadcast|upload(?:ed)?|ingest(?:ed|ion)?|recorded)\b", re.I,
)
_MEDIA_NOUN = re.compile(r"\b(?:media|assets?|videos?|clips?|files?|recordings?|everything|anything|programs?|shows?|episodes?)\b", re.I)
_TEMPORAL_FILTER = re.compile(
    rf"\b(?:in|on|during|from|between|before|after)\s+(?:{_TEMPORAL_VALUE})",
    re.I,
)
_DATE_PERIOD = re.compile(
    rf"(?:({_MONTH_PATTERN})\s+(?:of\s+)?(\d{{4}})|(\d{{4}})-(\d{{2}})-(\d{{2}})|(\d{{4}}))",
    re.I,
)
_DATE_PREFIX_WORDS = {
    "all", "the", "of", "media", "asset", "assets", "video", "videos",
    "clip", "clips", "file", "files", "recording", "recordings",
    "that", "which", "were", "was", "are", "have", "had", "with", "an",
    "a", "original", "air", "date", "created", "aired", "broadcast",
    "everything", "anything", "program", "programs", "show", "shows",
    "episode", "episodes",
}


def _air_date_intent(question: str) -> bool:
    """Route archive metadata dates, not spoken mentions or people named May."""
    if not (_MEDIA_NOUN.search(question) or re.search(r"\bwhat\s+(?:aired|was broadcast)\b", question, re.I)):
        return False
    if _air_date_range(question) is not None:
        return True
    if re.search(r"\b(?:where they|that (?:discuss|mention|say|talk)|"
                 r"(?:discuss|mention|say|talk)\s+about)\b", question, re.I):
        return False
    # Unsupported date filters (including relative dates and compound metadata
    # conditions) must ask for clarification rather than searching video scenes.
    if _TEMPORAL_FILTER.search(question):
        return True
    return bool(_METADATA_DATE_FIELD.search(question) and (
        re.search(
            r"\b(?:\d{4}|today|yesterday|recently|lately|"
            r"(?:this|last|next)\s+(?:week|month|year))\b", question, re.I,
        )
        or re.search(rf"\b(?:aired|broadcast)\s+(?:{_MONTH_PATTERN})\b", question, re.I)
    ))


def _date_period(value: str) -> tuple[datetime, datetime] | None:
    match = _DATE_PERIOD.fullmatch(value.strip())
    if not match:
        return None
    try:
        if match.group(1):
            year, month = int(match.group(2)), _MONTH_NAMES[match.group(1).lower()]
            start = datetime(year, month, 1)
            end = datetime(year + (month == 12), month % 12 + 1, 1)
        elif match.group(3):
            start = datetime(int(match.group(3)), int(match.group(4)), int(match.group(5)))
            end = start + timedelta(days=1)
        else:
            start = datetime(int(match.group(6)), 1, 1)
            end = datetime(start.year + 1, 1, 1)
    except (ValueError, OverflowError):
        return None
    return start, end


def _air_date_range(question: str) -> tuple[datetime, datetime, str] | None:
    """Only accept a complete, unqualified asset request; never ignore extra filters."""
    match = re.fullmatch(
        r"\s*(.*?)\s+(in|on|during|from|between)\s+(.+?)\s*[?.!]?\s*",
        question, re.I,
    )
    if match:
        prefix, connector, dates = match.groups()
    else:
        # "which videos aired July 2025" is also a common date formulation.
        bare = re.fullmatch(
            r"\s*(.*?\b(?:aired|broadcast))\s+(.+?)\s*[?.!]?\s*",
            question, re.I,
        )
        if not bare:
            return None
        prefix, dates = bare.groups()
        connector = "in"
    command = re.fullmatch(
        r"(?:show(?: me)?|find|list|give me|which|what|how many|count)\s+(.+)",
        prefix, re.I,
    )
    if not command:
        return None
    words = command.group(1).lower().split()
    if not (_MEDIA_NOUN.search(command.group(1)) or
            re.fullmatch(r"what\s+(?:aired|was broadcast)", prefix, re.I)):
        return None
    if any(w not in _DATE_PREFIX_WORDS for w in words):
        return None
    if re.search(r"\b(?:upload(?:ed)?|ingest(?:ed|ion)?|recorded|last air date)\b", question, re.I):
        return None
    # A bare "created" refers to the Curator original air date, not the
    # archive ingest timestamp or file modification time.
    if connector.lower() in {"from", "between"} and re.search(
        r"\s+(?:to|through|and)\s+", dates, re.I,
    ):
        parts = re.fullmatch(r"(.+?)\s+(?:to|through|and)\s+(.+)", dates, re.I)
        if not parts:
            return None
        first, last = _date_period(parts.group(1)), _date_period(parts.group(2))
        if first is None or last is None or first[0] > last[0]:
            return None
        start, end = first[0], last[1]
    else:
        if connector.lower() == "between":
            return None
        period = _date_period(dates)
        if period is None:
            return None
        start, end = period
    return start, end, f"{start.date().isoformat()} through {(end - timedelta(days=1)).date().isoformat()}"


async def _air_date_answer(db: AsyncSession, question: str, media_id: str | None):
    period = _air_date_range(question)
    if period is None:
        return (
            "Please specify an original air date range (for example, 'show me all media "
            "created in July 2025' or 'show me all media aired between 2025-07-01 "
            "and 2025-07-31'). Archive upload/ingest dates and file modification "
            "dates are different fields and are not searched by this request.",
            None,
        )
    start, end, label = period
    query = select(MediaAsset).where(
        MediaAsset.curator_original_air_date >= start,
        MediaAsset.curator_original_air_date < end,
    )
    if media_id:
        query = query.where(MediaAsset.id == media_id)
    assets = (await db.execute(query.order_by(MediaAsset.curator_original_air_date, MediaAsset.filename, MediaAsset.id))).scalars().all()
    citations = [
        AICitationOut(
            media_id=asset.id, filename=asset.filename,
            start_time=0, end_time=0,
            snippet=f"Original air date (Curator metadata): {asset.curator_original_air_date.date().isoformat()}; asset-level metadata, not a video moment",
        )
        for asset in assets
    ]
    answer = (
        f"{len(assets)} asset(s) with an original air date from {label}. "
        "Assets without an original air date are excluded."
    )
    if assets:
        answer += "\n" + "\n".join(
            f"- {asset.filename} — {asset.curator_original_air_date.date().isoformat()}"
            for asset in assets
        )
    return answer, citations


def _referenced_citations(answer: str, candidates: list[AICitationOut]) -> list[AICitationOut]:
    """Only attach evidence actually named in the answer, deduplicated by asset."""
    seen: set[str] = set()
    result = []
    for citation in candidates:
        # Substring matching can attribute "Clip.mp4" when the answer only
        # names "LongClip.mp4". Treat punctuation used in filenames as part of
        # a filename, while allowing quotes, parentheses and prose boundaries.
        reference = re.search(
            r"(?<![\w.\-])" + re.escape(citation.filename) + r"(?![\w.\-])",
            answer,
        )
        if reference and citation.media_id not in seen:
            result.append(citation)
            seen.add(citation.media_id)
    return result[:5]


async def _build_library_overview(db: AsyncSession) -> str:
    """Compact aggregate snapshot of the whole library (topics, people,
    stored insights) so big-picture questions are answered from real
    library-wide data instead of whatever transcript lines happen to
    contain the question's words."""
    from sqlalchemy import text as sql_text
    from ..topic_norm import group_topics
    from ..models import LibraryInsight
    from ..services.archive_memory import TOPIC_COUNTS_SQL

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
        raise

    try:
        raw_topic_rows = (
            await db.execute(
                sql_text(TOPIC_COUNTS_SQL)
            )
        ).all()
        grouped = group_topics((t, int(n)) for t, n in raw_topic_rows)
        if grouped:
            lines.append("Top topics across the library (topic — number of videos): " + "; ".join(
                f"{g['topic']} — {g['asset_count']}" for g in grouped[:20]
            ))
    except Exception:
        log.exception("library overview: topics failed")
        raise

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
        raise

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
        raise
    return "\n".join(lines)


async def _run_qa(
    question: str,
    context_segments: list,
    db: AsyncSession,
    single_asset: bool = False,
    history: list[dict] | None = None,
    visual_lines: list[str] | None = None,
    overview: str | None = None,
    asset_matches: list[MediaAsset] | None = None,
    visual_citations: list[AICitationOut] | None = None,
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

    if asset_matches:
        context_parts = [
            f"[{asset.filename}] Library metadata: "
            f"{(asset.synopsis or '')[:300]} Topics: "
            f"{', '.join(t for t in (asset.topics or []) if isinstance(t, str))[:150]}"
            for asset in asset_matches
        ] + context_parts
        citations = [_asset_citation(asset) for asset in asset_matches] + citations
    citations.extend(visual_citations or [])

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
            f"Library evidence (transcripts use [filename @ timecode]; "
            f"metadata uses [filename] without a timecode):\n{context_text}"
            f"{visual_text}\n\n"
            f"Question: {question}\n\n"
            f"Answer the question using these excerpts as evidence. Statements are "
            f"first-person: when a line is labeled with a speaker's name, facts they "
            f"state about themselves are facts about that speaker. Quote or paraphrase "
            f"the relevant lines and mention their filenames and timecodes. "
            f"For metadata-only matches mention the filename, but do not invent a timecode. "
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
        citations = _referenced_citations(answer, citations)

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
) -> tuple[str, str, str, list[AICitationOut]] | None:
    """If the question asks to build a project, create it (pool + draft cut v1)
    and return (answer, project_id, project_name, selected assets). None = not an action turn."""
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
    selected = [
        AICitationOut(
            media_id=c["media_id"], filename=c["filename"],
            start_time=c["start_time"], end_time=c["end_time"],
            snippet=c["snippet"],
        ) for c in clips
    ]
    # The created project's own selected clips are the evidence, not other
    # candidates the planner considered.
    return answer, project.id, name, selected[:5]


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

    if _air_date_intent(body.question):
        answer_text, citations = await _air_date_answer(db, body.question, body.media_id)
        return await _save_ai_answer(db, conv_id, answer_text, citations)

    intent, routed_value = await _route_turn(body.question, history)
    if intent == "conversation":
        if routed_value == "scope":
            answer = _SCOPE_FACTS
            if body.media_id:
                answer += " This request is scoped to the selected asset."
        else:
            answer = await _conversation_answer(body.question, history, body.media_id)
        return await _save_ai_answer(db, conv_id, answer, None)
    if intent == "clarify":
        return await _save_ai_answer(db, conv_id, _ROUTE_CLARIFICATION, None)
    if intent == "date":
        answer_text, citations = await _air_date_answer(db, routed_value, body.media_id)
        return await _save_ai_answer(db, conv_id, answer_text, citations)

    # Follow-ups like "dive deeper" or "what about her?" are useless as
    # retrieval queries — rewrite them into standalone questions first.
    retrieval_question = routed_value if routed_value != body.question else await _standalone_question(body.question, history)
    from ..services.archive_memory import mention_term, exact_mentions
    # A conversational rewrite must never discard a qualifier and accidentally
    # turn a qualified question into an unqualified exact-count request.
    count_term = mention_term(body.question)
    exact_answer = None
    if count_term is not None:
        count = await exact_mentions(db, count_term, body.media_id)
        scope = "this asset" if body.media_id else "the library"
        exact_answer = (
            f'{count} distinct asset(s) in {scope} have an indexed transcript containing '
            f'"{count_term}" (case-insensitive literal text match). '
            "This counts matching transcript text, not every recording semantically "
            "about the topic; assets without transcripts are not included."
        )
    elif re.search(r"\bhow many\b|\bcount\b", body.question + "\n" + retrieval_question, re.I):
        exact_answer = (
            "I can't reliably calculate a count from that wording, and retrieved "
            "excerpts are not a complete census. The exact-count shortcut currently "
            'supports a single quoted transcript phrase, for example: How many assets mention "faith"? '
            "It does not support unquoted terms or additional date, person, Boolean, "
            "or semantic-topic conditions. Please specify one quoted literal without "
            "extra qualifiers, or use a separately scoped database report."
        )

    # Hybrid retrieval: vector search finds semantically similar segments, but
    # misses first-person answers (the question names a person, the answer says
    # "my wife and I..."). Keyword search catches exact words like "children".
    # Run both and merge, deduping by segment id.
    context_segments: list = []
    seen_ids: set[str] = set()
    q_vec = None

    try:
        from ..services.embedding import get_text_embedding
        from ..services.qdrant_client import search_vectors

        q_vec = await get_text_embedding(retrieval_question) if exact_answer is None else None
        hits = await search_vectors(
            collection="transcripts",
            vector=q_vec,
            limit=8,
            media_id=body.media_id,
        ) if q_vec is not None else []
        for hit in hits:
            seg_id = hit.payload.get("segment_id")
            if not seg_id or seg_id in seen_ids:
                continue
            query = (
                select(TranscriptSegment, MediaAsset)
                .join(MediaAsset, TranscriptSegment.media_id == MediaAsset.id)
                .where(TranscriptSegment.id == seg_id)
            )
            if body.media_id:
                query = query.where(MediaAsset.id == body.media_id)
            row = (await db.execute(query)).first()
            if row:
                context_segments.append(row)
                seen_ids.add(seg_id)
    except Exception:
        pass  # vector search unavailable — keyword results below still apply

    keyword_start = len(context_segments)
    try:
        keyword_rows = await _keyword_segments(db, retrieval_question, body.media_id) if exact_answer is None else []
        for row in keyword_rows:
            seg = row[0]
            if seg.id not in seen_ids:
                context_segments.append(row)
                seen_ids.add(seg.id)
    except Exception:
        pass

    routed = []
    if q_vec is not None:
        try:
            from ..services.archive_memory import hierarchical_segments
            routed = await hierarchical_segments(db, q_vec, body.media_id)
        except Exception:
            import logging
            logging.getLogger("obtv.ai").warning(
                "Asset summary retrieval unavailable; using transcript/keyword evidence",
                exc_info=True,
            )
    # Diversify sources without allowing routing to displace all direct matches.
    from itertools import zip_longest
    merged, merged_ids = [], set()
    for group in zip_longest(context_segments[:keyword_start],
                             context_segments[keyword_start:], routed):
        for row in group:
            if row is not None and row[0].id not in merged_ids:
                merged.append(row)
                merged_ids.add(row[0].id)
    context_segments = merged[:12]

    visual_lines: list[str] = []
    visual_citations: list[AICitationOut] = []
    try:
        from .project_chat import _visual_segments, _fmt_ts
        if exact_answer is None:
            visual_matches = await _visual_segments(
                [retrieval_question], [body.media_id] if body.media_id else None, db,
            )
            for query, mid, filename, spans in visual_matches:
                if len(visual_lines) >= 12:
                    break
                visual_lines.append(
                    f'- [{filename}] looks like "{query[:80]}": '
                    f'{len(spans)} distinct segment(s) at '
                    + ", ".join(f"{_fmt_ts(a)}-{_fmt_ts(b)}" for a, b in spans[:12])
                )
                for start, end in spans[:5]:
                    visual_citations.append(AICitationOut(
                        media_id=mid, filename=filename,
                        start_time=start, end_time=end,
                        snippet=f'Visual scene match: {query[:160]}',
                    ))
    except Exception:
        pass  # visual retrieval unavailable — transcript answer still works

    asset_matches = await _structured_assets(db, retrieval_question) if exact_answer is None and not body.media_id else []
    overview = None if body.media_id or exact_answer is not None else await _library_overview(db)

    # Action turn: "combine these into a project / make a story" creates the
    # project + draft cut instead of just describing one.
    project_id = project_name = None
    answer_text = exact_answer
    citations: list = []
    if exact_answer is None and _PROJECT_INTENT_RE.search(body.question):
        # Savepoint: a failure mid-creation must not leave a half-created
        # project/revision that the message commit below would persist.
        try:
            async with db.begin_nested():
                created = await _maybe_create_project(
                    db, body.question, retrieval_question, context_segments, history,
                )
            if created:
                answer_text, project_id, project_name, citations = created
        except Exception as e:
            import logging
            logging.getLogger("ai").warning("project creation from chat failed: %s", e, exc_info=True)
            # fall through to a normal answer

    if answer_text is None:
        answer_text, citations = await _run_qa(
            body.question, context_segments, db,
            single_asset=bool(body.media_id), history=history,
            visual_lines=visual_lines, overview=overview,
            asset_matches=asset_matches, visual_citations=visual_citations,
        )

    return await _save_ai_answer(db, conv_id, answer_text, citations, project_id, project_name)


async def _save_ai_answer(
    db: AsyncSession, conv_id: str, answer_text: str,
    citations: list[AICitationOut] | None, project_id: str | None = None,
    project_name: str | None = None,
) -> AIAnswerOut:
    assistant_msg = AIMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        role="assistant",
        content=answer_text,
        citations=[c.model_dump() for c in citations] if citations is not None else None,
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
