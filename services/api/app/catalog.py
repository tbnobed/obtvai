"""Bounded Curator discovery. No scheduler or discovery runs at API startup."""
from __future__ import annotations

import re
import os
from datetime import date, datetime
from urllib.parse import urljoin

from .commands.import_curator_workbook import CuratorClient, ImportFailure, _field_values

ASSET_TYPES = ("Media", "Audio", "Image")
CUTOFF = date(2023, 1, 1)
PAGE_SIZE = 199


def cutoff() -> date:
    value = os.getenv("CURATOR_CATALOG_CUTOFF", CUTOFF.isoformat())
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ImportFailure("CURATOR_CATALOG_CUTOFF must be an ISO YYYY-MM-DD date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ImportFailure("CURATOR_CATALOG_CUTOFF is not a valid date") from None


def exact_id(asset: dict) -> str:
    # Curator Id metadata is authoritative, never name/path/fuzzy matching.
    values = list(dict.fromkeys(_field_values(asset, ("Id",))))
    if len(values) != 1:
        raise ImportFailure("Missing or ambiguous Curator Id")
    return values[0]


def eligibility(asset: dict) -> tuple[str, str | None]:
    minimum = cutoff()  # Invalid policy fails closed, even for malformed assets.
    values = list(dict.fromkeys(_field_values(asset, ("IngestCompleteDate",))))
    if len(values) != 1:
        return "review", "Missing or ambiguous IngestCompleteDate"
    value = values[0]
    # Do not guess culture-specific dates, epoch units, mtime, or air dates.
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?", value):
        return "review", "Invalid IngestCompleteDate; expected ISO date or timestamp"
    try:
        day = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return "review", "Invalid IngestCompleteDate"
    return ("eligible", None) if day >= minimum else ("excluded", None)


class CatalogClient(CuratorClient):
    def page(self, asset_type: str, offset: int, *, dated: bool) -> list[dict]:
        if asset_type not in ASSET_TYPES or offset < 0:
            raise ImportFailure("Invalid catalog cursor")
        if not self._access_token:
            self._authenticate()
        params = [
            ("assetTypes", asset_type), ("recursive", "true"),
            ("offset", str(offset)), ("limit", str(PAGE_SIZE)),
        ]
        # First sweep uses the verified existence query. The unfiltered second
        # sweep is essential: existence queries cannot report missing dates.
        if dated:
            params.append(("queries", "IngestCompleteDate:*"))
        # FolderPath is optional import metadata, not a defined Gateway field:
        # requesting it makes the live server reject the entire page with 500.
        for name in ("Id", "Name", "IngestCompleteDate", "WebProxyPath"):
            params.append(("names", name))
        for attempt in range(2):
            response = self.http.get(
                urljoin(self.base_url, "api/v1/assets"), params=params,
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
            if response.status_code != 401 or attempt:
                break
            self._authenticate()
        if response.status_code >= 400:
            raise ImportFailure(f"Curator catalog HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ImportFailure("Curator catalog returned invalid JSON") from exc
        page = payload.get("value") if isinstance(payload, dict) else None
        if not isinstance(page, list) or len(page) > PAGE_SIZE or any(not isinstance(x, dict) for x in page):
            raise ImportFailure("Curator catalog returned an invalid page")
        total = payload.get("size")
        if not isinstance(total, int) or total < 0:
            raise ImportFailure("Curator catalog response has no valid size")
        if not page and offset < total:
            raise ImportFailure("Curator returned an empty page before reported total")
        return page


def next_cursor(cursor: dict, count: int, *, head_refresh: bool = False) -> dict:
    """Round-robin types; each retains its own full/presence sweep checkpoint."""
    result = dict(cursor)
    lanes = {k: dict(v) for k, v in cursor.get("lanes", {}).items()}
    index = cursor["type_index"]
    lane = lanes.get(str(index), {
        "offset": cursor["offset"], "dated": cursor["dated"],
        "generation": cursor["generation"],
    })
    if head_refresh:
        pass  # Bounded fresh-arrival lookback must not reset historical progress.
    elif count:
        lane["offset"] += count
    else:
        lane["offset"] = 0
        if lane["dated"]:
            lane["dated"] = False
        else:
            lane["dated"] = True
            lane["generation"] += 1
    lanes[str(index)] = lane
    index = (index + 1) % len(ASSET_TYPES)
    next_lane = lanes.get(str(index), {"offset": 0, "dated": True, "generation": 0})
    result.update(next_lane, type_index=index, lanes=lanes,
                  discovery_turn=cursor.get("discovery_turn", 0) + 1)
    return result


INITIAL_CURSOR = {"offset": 0, "type_index": 0, "dated": True, "generation": 0}