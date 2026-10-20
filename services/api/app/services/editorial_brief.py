"""Resolve user instructions separately from assistant claims and search results."""
import json
import re


def reviewed_window(rows, anchor: float, maximum: float = 240.0, budget: int = 2400):
    """Only extend through complete transcript cues supplied to the selector."""
    kept, used = [], 0
    for start, end, text in rows:
        if not text or end <= anchor:
            continue
        if end > anchor + maximum or used + len(text) + 1 > budget:
            break
        if kept and start - kept[-1][1] > 10:
            break
        kept.append((float(start), float(end), text))
        used += len(text) + 1
    if not kept:
        return None
    return kept[0][0], kept[-1][1], " ".join(r[2] for r in kept)


def parse_brief(raw: str, source: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    brief = json.loads(raw)
    if not isinstance(brief, dict) or not isinstance(brief.get("objective"), str):
        raise ValueError("Editorial brief was not resolved; no cut was changed")
    year = brief.get("air_year")
    if year is not None and (
        type(year) is not int or not 1900 <= year <= 2100 or str(year) not in source
    ):
        raise ValueError("Unsubstantiated original-air-date constraint")
    # A model's null is not permission to drop an explicit user requirement.
    stated_years = list(re.finditer(
        r"\bair(?:ed|ing|s)?\b[^\n.!?]{0,60}?\b(19\d{2}|20\d{2}|2100)\b",
        source, re.I,
    ))
    if stated_years:
        latest = stated_years[-1]
        cleared = re.search(
            r"\b(?:any|all)\s+(?:air\s+)?years?\b|"
            r"\b(?:remove|drop|ignore)\s+(?:the\s+)?(?:air[- ]?date|year)\s+(?:filter|restriction|constraint)",
            source[latest.end():], re.I,
        )
        if not cleared:
            brief["air_year"] = int(latest.group(1))
    normalized = lambda s: re.sub(r"\W+", "", s).casefold()
    for key in ("excluded_people", "excluded_sources"):
        terms = brief.get(key, [])
        if not isinstance(terms, list):
            raise ValueError("Invalid editorial exclusions")
        for term in terms:
            if not isinstance(term, str) or len(normalized(term)) < 3 or normalized(term) not in normalized(source):
                raise ValueError("Unsubstantiated editorial exclusion")
    searches = brief.get("searches")
    if not isinstance(searches, list) or not searches or any(not isinstance(q, str) or not q.strip() for q in searches):
        raise ValueError("No content search could be resolved from the brief")
    seconds = brief.get("target_seconds")
    if seconds is not None and (type(seconds) not in (int, float) or not 0 < seconds <= 86400):
        raise ValueError("Invalid editorial runtime")
    sources = list(brief.get("excluded_sources", []))
    for match in re.finditer(r"\bclip\s+([A-Z0-9][A-Z0-9_-]{3,})\b[^\n]*(?:remove|exclude)", source, re.I):
        code = match.group(1)
        later = source[match.end():]
        if not re.search(r"\b(?:include|restore|allow)\s+(?:clip\s+)?" + re.escape(code), later, re.I):
            if code not in sources:
                sources.append(code)
    brief["excluded_sources"] = sources
    people = list(brief.get("excluded_people", []))
    for match in re.finditer(
        r"\bremove\s+anything\s+that\s+has\s+(.+?)\s+in\s+it\b|"
        r"\bclip\s+[A-Z0-9_-]+\s+is\s+of\s+(.+?)\s+speaking\b", source, re.I,
    ):
        person = (match.group(1) or match.group(2)).strip()
        if len(person) <= 80 and person not in people and not re.search(
            r"\b(?:include|restore|allow)\s+" + re.escape(person), source[match.end():], re.I
        ):
            people.append(person)
    brief["excluded_people"] = people
    return brief


async def resolve_brief(messages: list[str], generate) -> dict:
    source = "\n".join(messages)
    if len(source) > 64000:
        raise ValueError("This editorial conversation needs a shorter consolidated brief before editing")
    raw = await generate(
        source,
        system=(
            "Resolve the user's current editorial brief from USER messages in chronological order. "
            "Later explicit changes supersede earlier constraints; complaints and confirmations retain them. "
            "Return ONLY JSON: {\"objective\":string,\"searches\":[1-3 content-topic queries],"
            "\"air_year\":integer or null,\"excluded_people\":[names],\"excluded_sources\":[source codes],"
            "\"target_seconds\":number or null,\"edit_requested\":boolean,\"rebuild\":boolean}. "
            "Air year means ORIGINAL AIR DATE, never a spoken year or visual similarity. "
            "An exclusion complaint about an identified source must retain BOTH the person and source code. "
            "Queries describe subject matter, never 'cut', 'parameters', verification, or the complaint. "
            "Never invent specific themes such as AI, politics, climate or space when the user only asks for "
            "the most prominent topics. Keep that objective broad; a later planner sees the actual media pool. "
            "For best-of-year topics, search substantive news/interview/highlight topics, not the year number. "
            "A request to produce the previously requested cut, or correct ignored requirements, is "
            "edit_requested=true and rebuild=true. Rebuild=false for ordinary incremental additions. "
            "For general questions, edit_requested=false. Do not invent constraints or exclusions."
        ),
        max_new_tokens=700,
    )
    return parse_brief(raw, source)
