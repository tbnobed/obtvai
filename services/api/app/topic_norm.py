"""Topic normalization — mirror of artifacts/api-server/src/lib/topics.ts and
services/worker/topic_norm.py (keep all copies in sync).

"Abraham_Accords", "abraham accords", "Abraham-Accords" all collapse to one key.
"""

import re

SMALL_WORDS = {"a", "an", "and", "at", "for", "in", "of", "on", "or", "the", "to", "vs"}

# Words that must keep a fixed casing in labels.
PROPER_CASING = {
    "ai": "AI",
    "gpu": "GPU",
    "gpus": "GPUs",
    "llm": "LLM",
    "llms": "LLMs",
    "tv": "TV",
    "qa": "Q&A",
    "q3": "Q3",
    "us": "US",
    "uk": "UK",
    "eu": "EU",
    "un": "UN",
    "nato": "NATO",
    "covid": "COVID",
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "aws": "AWS",
}

# Full normalized keys whose label isn't derivable word-by-word.
SPECIAL_LABELS = {
    "b roll": "B-roll",
}

_SEPARATORS_RE = re.compile(r"[_\-]+")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_topic_key(raw: str) -> str:
    """Canonical filter key: lowercase, _/- become spaces, whitespace collapsed."""
    s = _SEPARATORS_RE.sub(" ", (raw or "").lower())
    return _WHITESPACE_RE.sub(" ", s).strip()


def topic_label(key: str) -> str:
    """Human-readable label for a normalized key: title case with proper-noun casing."""
    if key in SPECIAL_LABELS:
        return SPECIAL_LABELS[key]
    words = key.split(" ")
    out = []
    for i, w in enumerate(words):
        if w in PROPER_CASING:
            out.append(PROPER_CASING[w])
        elif i > 0 and w in SMALL_WORDS:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def group_topics(raw_counts) -> list[dict]:
    """Group raw topic strings (with per-topic counts) by normalized key, summing counts.

    Accepts an iterable of (raw_topic, count) pairs; returns a list of
    {"key", "topic", "asset_count"} dicts sorted by count desc, then key.
    """
    grouped: dict[str, int] = {}
    for raw, count in raw_counts:
        key = normalize_topic_key(raw)
        if not key:
            continue
        grouped[key] = grouped.get(key, 0) + int(count)
    return [
        {"key": key, "topic": topic_label(key), "asset_count": n}
        for key, n in sorted(grouped.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
