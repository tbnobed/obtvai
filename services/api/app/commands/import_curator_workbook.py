"""Resumable Curator workbook importer.

Run this command inside the API container so it can read the same read-only
Curator and hi-res mounts as the API:

    python -m app.commands.import_curator_workbook /imports/library.xlsx

The command never runs during normal application startup.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

try:
    import httpx
except ModuleNotFoundError:  # Parser/unit-test use outside the API image.
    httpx = None  # type: ignore[assignment]


HTTP_ERRORS = (httpx.HTTPError,) if httpx is not None else ()


DEFAULT_WEB_PROXY_FIELDS = (
    "WebProxyPath",
    "Web Proxy Path",
    "ProxyPath",
)
DEFAULT_HIRES_FIELDS = (
    "HiResPath",
    "Hi Res Path",
    "FilePath",
)
TERMINAL_STATUSES = {"queued", "existing", "imported"}
UUID_RE = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
)


class ImportFailure(RuntimeError):
    """A safe, operator-facing import error."""


IMPORT_ERRORS = (ImportFailure, OSError) + HTTP_ERRORS


@dataclass(frozen=True)
class WorkbookRow:
    media_id: str
    title: str
    long_synopsis: str
    host: str
    guest: str
    row_number: int

    def report_metadata(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "title": self.title,
            "long_synopsis": self.long_synopsis,
            "host": self.host,
            "guest": self.guest,
        }

    def display_title(self) -> str:
        title = self.title.strip()
        if not title or title.casefold() == self.media_id.casefold():
            return self.media_id
        return f"{self.media_id} — {title}"


def _csv_env(name: str, defaults: Iterable[str]) -> tuple[str, ...]:
    raw = os.environ.get(name, "")
    values = tuple(part.strip() for part in raw.split(",") if part.strip())
    return values or tuple(defaults)


def _normalise_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _cell_column(reference: str) -> int:
    letters = "".join(ch for ch in reference if ch.isalpha())
    value = 0
    for letter in letters.upper():
        value = value * 26 + ord(letter) - ord("A") + 1
    return value - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(node.text or "" for node in item.iter() if node.tag.endswith("}t"))
            for item in root if item.tag.endswith("}si")]


def _first_sheet_path(archive: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    first_sheet = next(
        (node for node in workbook.iter() if node.tag.endswith("}sheet")),
        None,
    )
    if first_sheet is None:
        raise ImportFailure("The workbook has no worksheets")
    relationship_id = next(
        (value for key, value in first_sheet.attrib.items()
         if key.endswith("}id") or key == "r:id"),
        None,
    )
    if not relationship_id:
        raise ImportFailure("The first worksheet has no relationship id")

    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    target = next(
        (
            node.attrib.get("Target")
            for node in rels
            if node.attrib.get("Id") == relationship_id
        ),
        None,
    )
    if not target:
        raise ImportFailure("The first worksheet relationship is missing")
    target_path = PurePosixPath(target.lstrip("/"))
    if target_path.parts and target_path.parts[0] == "xl":
        return str(target_path)
    return str(PurePosixPath("xl") / target_path)


def _sheet_rows(archive: zipfile.ZipFile, sheet_path: str) -> list[list[str]]:
    shared = _shared_strings(archive)
    root = ET.fromstring(archive.read(sheet_path))
    output: list[list[str]] = []
    for row in (node for node in root.iter() if node.tag.endswith("}row")):
        values: dict[int, str] = {}
        for cell in (node for node in row if node.tag.endswith("}c")):
            reference = cell.attrib.get("r", "")
            column = _cell_column(reference)
            cell_type = cell.attrib.get("t")
            if cell_type == "inlineStr":
                value = "".join(
                    node.text or "" for node in cell.iter()
                    if node.tag.endswith("}t")
                )
            else:
                value_node = next(
                    (node for node in cell if node.tag.endswith("}v")),
                    None,
                )
                value = value_node.text if value_node is not None and value_node.text else ""
                if cell_type == "s" and value:
                    try:
                        value = shared[int(value)]
                    except (ValueError, IndexError):
                        raise ImportFailure(
                            f"Invalid shared-string index in cell {reference}"
                        )
            values[column] = value.strip()
        if values:
            width = max(values) + 1
            output.append([values.get(index, "") for index in range(width)])
    return output


def read_workbook(path: Path) -> list[WorkbookRow]:
    if not path.is_file():
        raise ImportFailure(f"Workbook not found: {path}")
    if path.suffix.casefold() != ".xlsx":
        raise ImportFailure("Only .xlsx workbooks are supported")
    try:
        with zipfile.ZipFile(path) as archive:
            rows = _sheet_rows(archive, _first_sheet_path(archive))
    except (zipfile.BadZipFile, ET.ParseError, KeyError) as exc:
        raise ImportFailure(f"Could not read workbook: {exc}") from exc
    if not rows:
        raise ImportFailure("The first worksheet is empty")

    headers = {_normalise_key(value): index for index, value in enumerate(rows[0])}
    required = {
        "mediaid": "Media ID",
        "title": "Title",
        "tbnlongsynopsis": "TBN_LongSynopsis",
        "host": "Host",
        "guest": "Guest",
    }
    missing = [label for key, label in required.items() if key not in headers]
    if missing:
        raise ImportFailure(f"Missing required columns: {', '.join(missing)}")

    def value(row: list[str], key: str) -> str:
        index = headers[key]
        return row[index].strip() if index < len(row) else ""

    output: list[WorkbookRow] = []
    seen: dict[str, int] = {}
    for row_number, row in enumerate(rows[1:], start=2):
        media_id = value(row, "mediaid")
        if not media_id:
            continue
        dedupe_key = media_id.casefold()
        if dedupe_key in seen:
            raise ImportFailure(
                f"Duplicate Media ID {media_id!r} on rows "
                f"{seen[dedupe_key]} and {row_number}"
            )
        seen[dedupe_key] = row_number
        output.append(
            WorkbookRow(
                media_id=media_id,
                title=value(row, "title"),
                long_synopsis=value(row, "tbnlongsynopsis"),
                host=value(row, "host"),
                guest=value(row, "guest"),
                row_number=row_number,
            )
        )
    if not output:
        raise ImportFailure("The workbook contains no populated Media IDs")
    return output


def _flatten_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        output: list[str] = []
        for item in value:
            output.extend(_flatten_values(item))
        return output
    if isinstance(value, dict):
        for key in ("values", "value"):
            if key in value:
                return _flatten_values(value[key])
    return []


def _asset_fields(asset: dict[str, Any]) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    sources = [asset]
    metadata = asset.get("metadata")
    if isinstance(metadata, dict):
        sources.append(metadata)
    for source in sources:
        for key, value in source.items():
            values = [item.strip() for item in _flatten_values(value) if item.strip()]
            if values:
                fields.setdefault(_normalise_key(key), []).extend(values)
    return fields


def _field_values(
    asset: dict[str, Any],
    field_names: Iterable[str],
) -> list[str]:
    fields = _asset_fields(asset)
    output: list[str] = []
    for name in field_names:
        output.extend(fields.get(_normalise_key(name), []))
    return output


def _media_id_matches(candidate: str, media_id: str) -> bool:
    return candidate.strip().casefold() == media_id.strip().casefold()


def choose_exact_asset(
    assets: list[dict[str, Any]],
    media_id: str,
    id_fields: Iterable[str],
) -> dict[str, Any]:
    matches = [
        asset for asset in assets
        if any(
            _media_id_matches(value, media_id)
            for value in _field_values(asset, id_fields)
        )
    ]
    if not matches:
        raise ImportFailure(
            f"Curator returned {len(assets)} result(s), but none contained "
            f"an exact Media ID match for {media_id}"
        )
    if len(matches) > 1:
        raise ImportFailure(
            f"Curator returned {len(matches)} exact matches for {media_id}; "
            "refusing an ambiguous import"
        )
    return matches[0]


def asset_guid(asset: dict[str, Any]) -> str:
    candidates = _field_values(asset, ("Id", "AssetId", "Asset ID"))
    candidates.extend(_flatten_values(asset.get("href")))
    for candidate in candidates:
        match = UUID_RE.search(candidate)
        if not match:
            continue
        value = match.group(0)
        try:
            return str(uuid.UUID(value))
        except ValueError:
            continue
    raise ImportFailure("The matched Curator asset did not include a GUID")


def first_path(asset: dict[str, Any], field_names: Iterable[str]) -> str | None:
    for value in _field_values(asset, field_names):
        if value.strip():
            return value.strip()
    return None


def map_hires_path(
    source_path: str,
    external_prefix: str,
    mount_root: Path,
) -> Path:
    normalised = source_path.strip().replace("\\", "/")
    prefix = external_prefix.strip().replace("\\", "/").rstrip("/")
    if normalised.startswith("/media/") or normalised == "/media":
        relative = normalised.removeprefix("/media").lstrip("/")
    elif prefix and normalised.casefold().startswith(prefix.casefold() + "/"):
        relative = normalised[len(prefix):].lstrip("/")
    else:
        raise ImportFailure(
            "HiResPath cannot be mapped. Set CURATOR_HIRES_UNC_PREFIX to the "
            "external path mounted at /media."
        )
    if any(part in ("", ".", "..") for part in PurePosixPath(relative).parts):
        raise ImportFailure("HiResPath contains an invalid path segment")
    root = mount_root.resolve()
    candidate = (root / Path(*PurePosixPath(relative).parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ImportFailure("HiResPath resolves outside the /media mount") from exc
    if not candidate.is_file():
        raise ImportFailure(f"Mapped HiRes file is not available: {candidate}")
    return candidate


class CuratorClient:
    def __init__(self) -> None:
        if httpx is None:
            raise ImportFailure(
                "The httpx package is required to contact Curator; run this "
                "command inside the OBTV API container"
            )
        self.base_url = os.environ.get(
            "CURATOR_API_BASE_URL",
            "https://curator.tbn.tv/CuratorGateway",
        ).rstrip("/") + "/"
        self.client_id = os.environ.get("CURATOR_CLIENT_ID", "")
        self.client_secret = os.environ.get("CURATOR_CLIENT_SECRET", "")
        # The supplied Curator Postman collection omits scope for the
        # client-credentials grant. Some Curator deployments return HTTP 500
        # when it is included, so only send it when an operator opts in.
        self.scope = os.environ.get("CURATOR_OAUTH_SCOPE", "").strip()
        self.query_field = os.environ.get("CURATOR_MEDIA_ID_QUERY_FIELD", "").strip()
        if not self.query_field:
            raise ImportFailure(
                "CURATOR_MEDIA_ID_QUERY_FIELD must name Curator's canonical, "
                "unique Media ID metadata field"
            )
        self.id_fields = (self.query_field,)
        self.web_proxy_fields = _csv_env(
            "CURATOR_WEB_PROXY_FIELDS",
            DEFAULT_WEB_PROXY_FIELDS,
        )
        self.hires_fields = _csv_env("CURATOR_HIRES_FIELDS", DEFAULT_HIRES_FIELDS)
        self.http = httpx.Client(timeout=httpx.Timeout(45.0, connect=15.0))
        self._access_token = ""

    def close(self) -> None:
        self.http.close()

    def _authenticate(self) -> None:
        if not self.client_id or not self.client_secret:
            raise ImportFailure(
                "CURATOR_CLIENT_ID and CURATOR_CLIENT_SECRET must be set"
            )
        token_data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }
        if self.scope:
            token_data["scope"] = self.scope
        response = self.http.post(
            urljoin(self.base_url, "connect/token"),
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code >= 400:
            raise ImportFailure(
                f"Curator authentication failed with HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ImportFailure("Curator authentication returned invalid JSON") from exc
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise ImportFailure("Curator authentication returned no access token")
        self._access_token = token

    def search(self, media_id: str) -> dict[str, Any]:
        if not self._access_token:
            self._authenticate()
        query = f'{self.query_field}:"{media_id}"'
        requested_names = tuple(dict.fromkeys(
            (*self.id_fields, *self.web_proxy_fields, *self.hires_fields)
        ))
        assets: list[dict[str, Any]] = []
        offset = 0
        total: int | None = None
        page_size = 199
        while total is None or offset < total:
            params: list[tuple[str, str]] = [
                ("queries", query),
                ("recursive", "true"),
                ("offset", str(offset)),
                ("limit", str(page_size)),
            ]
            params.extend(("names", name) for name in requested_names)
            response = self.http.get(
                urljoin(self.base_url, "api/v1/assets"),
                params=params,
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
            if response.status_code == 401:
                self._access_token = ""
                self._authenticate()
                response = self.http.get(
                    urljoin(self.base_url, "api/v1/assets"),
                    params=params,
                    headers={"Authorization": f"Bearer {self._access_token}"},
                )
            if response.status_code >= 400:
                raise ImportFailure(
                    f"Curator search failed with HTTP {response.status_code}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise ImportFailure("Curator search returned invalid JSON") from exc
            values = payload.get("value") if isinstance(payload, dict) else None
            if not isinstance(values, list):
                raise ImportFailure(
                    "Curator search response did not contain a value list"
                )
            page = [item for item in values if isinstance(item, dict)]
            assets.extend(page)
            reported_total = payload.get("size")
            if not isinstance(reported_total, int) or reported_total < 0:
                raise ImportFailure(
                    "Curator search response did not contain a valid collection size"
                )
            total = reported_total
            if not page:
                break
            offset += len(values)
        return choose_exact_asset(assets, media_id, self.id_fields)


class ObtvClient:
    def __init__(self) -> None:
        if httpx is None:
            raise ImportFailure(
                "The httpx package is required to contact OBTV; run this "
                "command inside the OBTV API container"
            )
        self.base_url = os.environ.get(
            "OBTV_API_URL",
            "http://127.0.0.1:8000/api",
        ).rstrip("/") + "/"
        self.internal_token = os.environ.get("INTERNAL_API_TOKEN", "")
        self.http = httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0))

    def close(self) -> None:
        self.http.close()

    def _headers(self) -> dict[str, str]:
        if not self.internal_token:
            raise ImportFailure("INTERNAL_API_TOKEN must be set")
        return {"X-Internal-Token": self.internal_token}

    def import_web_proxy(
        self,
        row: WorkbookRow,
        curator_guid: str,
        web_proxy_path: str,
        manifest_name: str,
    ) -> dict[str, Any]:
        response = self.http.post(
            urljoin(self.base_url, "media/curator-import"),
            headers=self._headers(),
            json={
                "manifest_name": manifest_name,
                "assets": [
                    {
                        "asset_id": curator_guid,
                        "name": row.display_title(),
                        "web_proxy_path": web_proxy_path,
                        "folder_path": f"Spreadsheet Imports/{row.title or 'Untitled'}",
                        "requested_by": "curator-workbook-import",
                    }
                ],
            },
        )
        if response.status_code >= 400:
            raise ImportFailure(
                f"OBTV Curator import failed with HTTP {response.status_code}"
            )
        try:
            payload = response.json()
            item = payload["items"][0]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ImportFailure("OBTV Curator import returned an invalid response") from exc
        return {
            "status": str(item.get("status") or "failed"),
            "media_id": item.get("media_id"),
            "job_id": item.get("job_id"),
            "retryable": bool(item.get("retryable")),
            "error": item.get("error"),
        }

    def import_hires(self, row: WorkbookRow, file_path: Path) -> dict[str, Any]:
        response = self.http.post(
            urljoin(self.base_url, "media"),
            headers=self._headers(),
            json={"file_path": str(file_path), "title": row.display_title()},
        )
        if response.status_code >= 400:
            raise ImportFailure(
                f"OBTV HiRes import failed with HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ImportFailure("OBTV HiRes import returned invalid JSON") from exc
        return {
            "status": "imported",
            "media_id": payload.get("id"),
            "job_id": None,
            "retryable": False,
            "error": None,
        }


def _read_state(path: Path, workbook: Path) -> dict[str, Any]:
    if path.exists():
        try:
            state = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise ImportFailure(f"Could not read state file {path}: {exc}") from exc
        if not isinstance(state, dict) or not isinstance(state.get("items"), dict):
            raise ImportFailure(f"State file has an invalid structure: {path}")
        return state
    return {
        "version": 1,
        "workbook": workbook.name,
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
        "items": {},
    }


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = int(time.time())
    payload = json.dumps(state, indent=2, sort_keys=True) + "\n"
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            handle.write(payload)
            temp_path = Path(handle.name)
        temp_path.replace(path)
    except OSError as exc:
        raise ImportFailure(f"Could not write state file {path}: {exc}") from exc


def _safe_error(exc: Exception) -> str:
    message = str(exc).replace(
        os.environ.get("CURATOR_CLIENT_SECRET", "") or "\0",
        "<redacted>",
    )
    return message[:1000]


def run_import(args: argparse.Namespace) -> int:
    workbook = args.workbook.resolve()
    rows = read_workbook(workbook)
    if args.media_id:
        requested = {value.casefold() for value in args.media_id}
        rows = [row for row in rows if row.media_id.casefold() in requested]
        missing = requested - {row.media_id.casefold() for row in rows}
        if missing:
            raise ImportFailure(
                f"Requested Media ID(s) not found in workbook: {', '.join(sorted(missing))}"
            )
    if args.limit is not None:
        rows = rows[:args.limit]

    state_path = (
        args.state_file.resolve()
        if args.state_file
        else Path("/uploads/import-reports") / f"{workbook.stem}.json"
    )
    state = _read_state(state_path, workbook)
    curator = CuratorClient()
    obtv = ObtvClient()
    manifest_name = f"curator-api-{workbook.stem}"
    summary: dict[str, int] = {}
    try:
        for index, row in enumerate(rows, start=1):
            previous = state["items"].get(row.media_id, {})
            if (
                not args.retry_all
                and previous.get("status") in TERMINAL_STATUSES
            ):
                status = f"skipped-{previous['status']}"
                summary[status] = summary.get(status, 0) + 1
                print(f"[{index}/{len(rows)}] {row.media_id}: {status}", flush=True)
                continue

            item_state: dict[str, Any] = {
                **row.report_metadata(),
                "status": "running",
                "attempted_at": int(time.time()),
            }
            state["items"][row.media_id] = item_state
            _write_state(state_path, state)

            try:
                asset = curator.search(row.media_id)
                guid = asset_guid(asset)
                web_proxy = first_path(asset, curator.web_proxy_fields)
                hires = first_path(asset, curator.hires_fields)
                item_state["curator_asset_id"] = guid
                item_state["web_proxy_path"] = web_proxy
                item_state["hires_path"] = hires

                if web_proxy:
                    item_state["source_type"] = "web-proxy"
                    if args.dry_run:
                        result = {
                            "status": "dry-run-ready",
                            "media_id": None,
                            "job_id": None,
                            "retryable": False,
                            "error": None,
                        }
                    else:
                        result = obtv.import_web_proxy(
                            row,
                            guid,
                            web_proxy,
                            manifest_name,
                        )
                elif hires:
                    item_state["source_type"] = "hires"
                    mapped = map_hires_path(
                        hires,
                        os.environ.get("CURATOR_HIRES_UNC_PREFIX", ""),
                        Path(os.environ.get("CURATOR_HIRES_MOUNT_ROOT", "/media")),
                    )
                    item_state["mapped_hires_path"] = str(mapped)
                    if args.dry_run:
                        result = {
                            "status": "dry-run-ready",
                            "media_id": None,
                            "job_id": None,
                            "retryable": False,
                            "error": None,
                        }
                    else:
                        result = obtv.import_hires(row, mapped)
                else:
                    raise ImportFailure(
                        "The matched Curator asset returned neither a WebProxyPath "
                        "nor a HiResPath"
                    )
                item_state.update(result)
            except IMPORT_ERRORS as exc:
                item_state.update(
                    {
                        "status": "failed",
                        "retryable": True,
                        "error": _safe_error(exc),
                    }
                )
            _write_state(state_path, state)
            status = item_state["status"]
            summary[status] = summary.get(status, 0) + 1
            print(f"[{index}/{len(rows)}] {row.media_id}: {status}", flush=True)
    finally:
        curator.close()
        obtv.close()

    print(f"State file: {state_path}")
    print("Summary: " + ", ".join(f"{key}={value}" for key, value in sorted(summary.items())))
    failed = summary.get("failed", 0)
    return 2 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve workbook Media IDs through Curator and ingest them into OBTV.",
    )
    parser.add_argument("workbook", type=Path, help="Path to the .xlsx workbook")
    parser.add_argument(
        "--state-file",
        type=Path,
        help="Checkpoint/report path (default: /uploads/import-reports/<workbook>.json)",
    )
    parser.add_argument(
        "--media-id",
        action="append",
        help="Import only this Media ID; repeat for multiple IDs",
    )
    parser.add_argument("--limit", type=int, help="Process at most this many rows")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and validate paths without queueing OBTV ingestion",
    )
    parser.add_argument(
        "--retry-all",
        action="store_true",
        help="Retry rows already recorded as queued, existing, imported, or dry-run-ready",
    )
    return parser


def main() -> None:
    try:
        exit_code = run_import(build_parser().parse_args())
    except ImportFailure as exc:
        print(f"Import error: {_safe_error(exc)}", file=sys.stderr)
        raise SystemExit(2) from None
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()