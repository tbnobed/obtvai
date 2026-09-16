"""Pure Campaign Builder execution-state rules.

Keeping the persisted lock/idempotency decisions independent from FastAPI and
SQLAlchemy makes the duplicate-dispatch and ambiguous-publish behavior
executable in dependency-light unit tests.
"""


def selected_media_ids(clips: list[dict]) -> list[str]:
    return list(dict.fromkeys(str(clip["media_id"]) for clip in clips))


def selected_media_ranges(clips: list[dict]) -> dict[str, dict[str, float]]:
    """Project-compatible envelopes while preserving each campaign snapshot."""

    ranges: dict[str, dict[str, float]] = {}
    for clip in clips:
        media_id = str(clip["media_id"])
        start, end = float(clip["start_time"]), float(clip["end_time"])
        current = ranges.get(media_id)
        if current is None:
            ranges[media_id] = {"in": start, "out": end}
        else:
            current["in"] = min(current["in"], start)
            current["out"] = max(current["out"], end)
    return ranges


def merge_media_ranges(
    existing: dict | None, selected: dict[str, dict[str, float]]
) -> dict[str, dict[str, float]]:
    """Add selected envelopes without narrowing an existing project range."""

    merged = {
        str(media_id): {"in": float(window["in"]), "out": float(window["out"])}
        for media_id, window in (existing or {}).items()
        if isinstance(window, dict) and "in" in window and "out" in window
    }
    for media_id, window in selected.items():
        current = merged.get(media_id)
        if current is None:
            merged[media_id] = dict(window)
            continue
        current["in"] = min(current["in"], float(window["in"]))
        current["out"] = max(current["out"], float(window["out"]))
    return merged


def execution_conflict(
    status: str,
    dispatch_state: str,
    retry: bool,
) -> str | None:
    """Return a stable conflict message, or ``None`` when dispatch is allowed."""

    if status in {"ready", "draft_ready"}:
        return "Deliverable has already completed"
    if status == "dispatch_unknown":
        return (
            "Dispatch outcome is unknown; this deliverable is not safely "
            "retryable. Inspect the referenced job before taking action."
        )
    # A referenced source job reporting failed/cancelled/removed is the only
    # safe retry case for an ambiguous dispatch.  The route derives `failed`
    # from that authoritative source status before reaching this rule.
    if status == "failed":
        if not retry:
            return "Deliverable failed; set retry=true to dispatch it again"
        return None
    if dispatch_state in {"publishing", "ambiguous"}:
        return (
            "Dispatch outcome is unknown; this deliverable is not safely "
            "retryable. Inspect the referenced job before taking action."
        )
    if status in {"queued", "running"}:
        return "Deliverable is already queued or running"
    if retry and status != "failed":
        return "Only failed deliverables can be retried"
    return None