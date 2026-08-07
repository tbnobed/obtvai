"""Web search tool for the chat agents, backed by the self-hosted SearXNG
metasearch service (already used by the trends worker).

The local LLM has no native tool-calling API, so the tool uses a marker
protocol: the model is told it may reply with nothing but

    WEB_SEARCH: <query>

lines (max 2). When the first response is such a tool call, the searches run
against SearXNG and the model is asked again with the results appended to the
prompt. One round only — the second answer is final.
"""
import logging
import os

import httpx

logger = logging.getLogger("obtv.websearch")

SEARXNG_URL = os.getenv("SEARXNG_URL", "")

_MAX_QUERIES = 2
_MAX_RESULTS = 5
_TIMEOUT_S = 8.0


async def search_web(query: str, max_results: int = _MAX_RESULTS) -> list[dict]:
    """Run one query against SearXNG; returns [{title, url, snippet}]."""
    if not SEARXNG_URL:
        return []
    url = SEARXNG_URL.rstrip("/") + "/search"
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        resp = await client.get(
            url, params={"q": query, "format": "json", "language": "en"}
        )
        resp.raise_for_status()
        data = resp.json()
    out = []
    for r in (data.get("results") or [])[:max_results]:
        out.append({
            "title": (r.get("title") or "").strip()[:150],
            "url": (r.get("url") or "").strip()[:300],
            "snippet": " ".join((r.get("content") or "").split())[:300],
        })
    return out


def _tool_system(system: str | None) -> str:
    tool = (
        "TOOL AVAILABLE — web search. Use it whenever live external information "
        "would improve the answer, not only when the context is empty. Search "
        "when the user asks about real-world events, dates, people, places, or "
        "organizations (upcoming or recent events, 'other events we should know "
        "about', background on someone or something mentioned in the footage), "
        "when your knowledge might be out of date, or ALWAYS when the user "
        "explicitly asks you to search the internet/web or look something up. "
        "To search, reply with NOTHING except one or two lines in exactly this "
        "form:\n"
        "WEB_SEARCH: <search query>\n"
        "You will immediately be re-asked with live results added, and can then "
        "combine them with the footage evidence. Skip the search only for "
        "questions answerable purely from the provided footage/transcripts "
        "(what was said or shown, timestamps, speakers)."
    )
    return f"{system}\n\n{tool}" if system else tool


def _parse_tool_call(text: str) -> list[str]:
    """Return search queries iff the response is purely WEB_SEARCH lines."""
    lines = [ln.strip() for ln in (text or "").strip().splitlines() if ln.strip()]
    if not lines or not all(ln.upper().startswith("WEB_SEARCH:") for ln in lines):
        return []
    queries = []
    for ln in lines:
        q = ln.split(":", 1)[1].strip().strip('"')
        if q:
            queries.append(q)
    return queries[:_MAX_QUERIES]


async def generate_with_web(
    generate_response,
    prompt: str,
    *,
    history: list[dict] | None = None,
    system: str | None = None,
    max_new_tokens: int = 512,
) -> str:
    """LLM call with an optional single round of web search.

    Drop-in replacement for generate_response(); falls back to a plain call
    when SEARXNG_URL is not configured.
    """
    if not SEARXNG_URL:
        return await generate_response(
            prompt, history=history, system=system, max_new_tokens=max_new_tokens
        )
    first = await generate_response(
        prompt, history=history, system=_tool_system(system),
        max_new_tokens=max_new_tokens,
    )
    queries = _parse_tool_call(first)
    if not queries:
        return first

    blocks: list[str] = []
    for q in queries:
        try:
            hits = await search_web(q)
        except Exception:
            logger.exception("web search failed for %r", q)
            hits = []
        if hits:
            blocks.append(f'Results for "{q}":\n' + "\n".join(
                f"- {h['title']} — {h['snippet']} (source: {h['url']})" for h in hits
            ))
        else:
            blocks.append(f'Results for "{q}": no results / search unavailable.')
    logger.info("web search used: %s", queries)
    web_block = (
        "\n\nWEB SEARCH RESULTS (fetched from the live internet just now — use "
        "them for external facts, mention the source site in plain text when you "
        "rely on one, and clearly separate web facts from what is in the "
        "footage):\n" + "\n\n".join(blocks)
    )
    return await generate_response(
        prompt + web_block, history=history, system=system,
        max_new_tokens=max_new_tokens,
    )
