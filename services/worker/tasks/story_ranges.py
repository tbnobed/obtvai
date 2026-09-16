"""Pure helpers for constraining StoryJob candidates to editorial windows."""

import math


def normalise_clip_ranges(raw_ranges):
    """Return valid campaign windows grouped by media id.

    Story jobs created before Campaign Builder have no ranges and retain the
    historical unrestricted behavior. Campaign jobs carry a snapshot of their
    selected windows, so candidate mining and final clip snapping cannot
    escape those windows.
    """

    result = {}
    for raw in raw_ranges or []:
        if not isinstance(raw, dict):
            continue
        media_id = str(raw.get("media_id") or "")
        try:
            start = float(raw.get("start_time"))
            end = float(raw.get("end_time"))
        except (TypeError, ValueError):
            continue
        if media_id and math.isfinite(start) and math.isfinite(end) and 0 <= start < end:
            result.setdefault(media_id, []).append((start, end))
    return result


def constrain_candidate(candidate, ranges_by_media):
    """Clip a candidate to selected windows, dropping out-of-window spans."""

    windows = ranges_by_media.get(str(candidate.get("media_id") or ""))
    if not windows:
        return [candidate]
    constrained = []
    for lo, hi in windows:
        start = max(float(candidate["start"]), lo)
        end = min(float(candidate["end"]), hi)
        if end - start < 1.0:
            continue
        item = dict(candidate)
        item["start"] = round(start, 1)
        item["end"] = round(end, 1)
        constrained.append(item)
    return constrained