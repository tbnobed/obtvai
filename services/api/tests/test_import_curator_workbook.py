from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.commands.import_curator_workbook import (
    CuratorClient,
    EXECUTION_CONFIRMATION,
    ImportFailure,
    TERMINAL_STATUSES,
    _read_state,
    _resolve_import_source,
    _validate_mode,
    asset_guid,
    build_parser,
    choose_exact_asset,
    first_path,
    map_hires_path,
    read_workbook,
    resolve_web_proxy_path,
    run_import,
)


def _write_test_workbook(path: Path, *, duplicate_media_id: bool = False) -> None:
    shared = [
        "Media ID",
        "Title",
        "TBN_LongSynopsis",
        "Host",
        "Guest",
        "HD-P010322",
        "Praise",
        "A synopsis",
        "Host Name",
        "Guest Name",
    ]
    cells = "".join(
        f'<c r="{column}1" t="s"><v>{index}</v></c>'
        for column, index in zip(("A", "B", "C", "D", "E"), range(5))
    )
    values = "".join(
        f'<c r="{column}2" t="s"><v>{index}</v></c>'
        for column, index in zip(("A", "B", "C", "D", "E"), range(5, 10))
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            + "".join(f"<si><t>{value}</t></si>" for value in shared)
            + "</sst>",
        )
        duplicate_row = f'<row r="3">{values}</row>' if duplicate_media_id else ""
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData><row r=\"1\">{cells}</row><row r=\"2\">{values}</row>{duplicate_row}</sheetData>"
            "</worksheet>",
        )


class WorkbookTests(unittest.TestCase):
    def test_reads_expected_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.xlsx"
            _write_test_workbook(path)
            rows = read_workbook(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].media_id, "HD-P010322")
        self.assertEqual(rows[0].display_title(), "HD-P010322 — Praise")
        self.assertEqual(rows[0].guest, "Guest Name")

    def test_rejects_duplicate_workbook_media_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.xlsx"
            _write_test_workbook(path, duplicate_media_id=True)
            with self.assertRaises(ImportFailure):
                read_workbook(path)


class CuratorResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guid = "5be52a09-e43f-4a48-b41b-5c33b95ee53a"
        self.asset = {
            "href": f"https://curator.example/api/v1/assets/{self.guid}",
            "TBN_MediaIDParent": {"values": ["HD-P010322"]},
            "WebProxyPath": {
                "values": [r"\\server\IPV\Proxies\WebProxy\2026\08\HD-P010322"]
            },
        }

    def test_selects_exact_asset_and_paths(self) -> None:
        chosen = choose_exact_asset(
            [self.asset],
            "HD-P010322",
            ("TBN_MediaIDParent",),
        )
        self.assertIs(chosen, self.asset)
        self.assertEqual(asset_guid(chosen), self.guid)
        self.assertIn("WebProxy", first_path(chosen, ("WebProxyPath",)))

    def test_rejects_ambiguous_match(self) -> None:
        with self.assertRaises(ImportFailure):
            choose_exact_asset(
                [self.asset, dict(self.asset)],
                "HD-P010322",
                ("TBN_MediaIDParent",),
            )

    def test_rejects_media_id_embedded_in_name(self) -> None:
        near_match = {
            "TBN_MediaIDParent": {"values": ["Archive HD-P010322 revised"]},
        }
        with self.assertRaises(ImportFailure):
            choose_exact_asset(
                [near_match],
                "HD-P010322",
                ("TBN_MediaIDParent",),
            )

    def test_dry_run_is_not_terminal(self) -> None:
        self.assertNotIn("dry-run-ready", TERMINAL_STATUSES)

    def test_search_checks_all_result_pages_before_exact_match(self) -> None:
        class Response:
            status_code = 200

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        class Http:
            def __init__(self, responses):
                self.responses = list(responses)
                self.offsets = []
                self.requests = []

            def get(self, _url, *, params, headers):
                self.offsets.append(dict(params)["offset"])
                self.requests.append(params)
                return self.responses.pop(0)

        near_match = {
            "TBN_MediaIDParent": {"values": ["HD-P010322-revised"]},
        }
        exact_match = {
            "Id": {"values": [self.guid]},
            "TBN_MediaIDParent": {"values": ["HD-P010322"]},
            "WebProxyPath": {
                "values": [r"\\server\IPV\Proxies\WebProxy\HD-P010322"]
            },
        }
        client = object.__new__(CuratorClient)
        client.base_url = "https://curator.example/"
        client.query_field = "TBN_MediaIDParent"
        client.id_fields = ("TBN_MediaIDParent",)
        client.web_proxy_fields = ("WebProxyPath",)
        client.hires_fields = ("HiResPath",)
        client._access_token = "test-token"
        client.http = Http(
            [
                Response({"size": 2, "value": [near_match]}),
                Response({"size": 2, "value": [exact_match]}),
            ]
        )
        chosen = client.search("HD-P010322")
        self.assertIs(chosen, exact_match)
        self.assertEqual(client.http.offsets, ["0", "1"])
        self.assertIn(
            ("queries", 'TBN_MediaIDParent:"HD-P010322"'),
            client.http.requests[0],
        )
        self.assertIn(("names", "TBN_MediaIDParent"), client.http.requests[0])

    def test_maps_hires_prefix_inside_mount(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "Shows" / "episode.mxf"
            target.parent.mkdir()
            target.touch()
            mapped = map_hires_path(
                r"\\server\HiRes\Shows\episode.mxf",
                r"\\server\HiRes",
                root,
            )
        self.assertEqual(mapped.name, "episode.mxf")

    def test_resolves_readable_web_proxy_video(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "2026" / "08" / "HD-P010322"
            folder.mkdir(parents=True)
            video = folder / "HD-P010322_video.mp4"
            video.write_bytes(b"video")
            mapped = resolve_web_proxy_path(
                r"\\server\IPV\Proxies\WebProxy\2026\08\HD-P010322",
                root,
            )
        self.assertEqual(mapped.name, "HD-P010322_video.mp4")

    def test_rejects_paths_outside_mounted_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            root.mkdir()
            with self.assertRaises(ImportFailure):
                resolve_web_proxy_path(
                    r"\\server\IPV\Proxies\WebProxy\..\outside",
                    root,
                )
            with self.assertRaises(ImportFailure):
                map_hires_path(
                    r"\\server\HiRes\..\outside\episode.mxf",
                    r"\\server\HiRes",
                    root,
                )

    def test_unavailable_web_proxy_uses_safe_hires_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "Shows" / "episode.mxf"
            target.parent.mkdir()
            target.touch()
            with patch.dict(
                os.environ,
                {
                    "CURATOR_HIRES_UNC_PREFIX": r"\\server\HiRes",
                    "CURATOR_HIRES_MOUNT_ROOT": str(root),
                },
                clear=False,
            ):
                source_type, mapped, proxy_error = _resolve_import_source(
                    r"\\server\IPV\Proxies\WebProxy\missing\HD-P010322",
                    r"\\server\HiRes\Shows\episode.mxf",
                )
        self.assertEqual(source_type, "hires-fallback")
        self.assertEqual(mapped.name, "episode.mxf")
        self.assertIn("not available", proxy_error or "")

    def test_preflight_is_default_and_execution_requires_confirmation(self) -> None:
        args = build_parser().parse_args(["workbook.xlsx"])
        self.assertFalse(args.execute)
        self.assertFalse(args.dry_run)
        _validate_mode(args)

        args = build_parser().parse_args(["workbook.xlsx", "--execute"])
        with self.assertRaises(ImportFailure):
            _validate_mode(args)

        args = build_parser().parse_args([
            "workbook.xlsx",
            "--execute",
            "--confirm",
            EXECUTION_CONFIRMATION,
        ])
        _validate_mode(args)

        args = build_parser().parse_args([
            "workbook.xlsx",
            "--dry-run",
            "--execute",
            "--confirm",
            EXECUTION_CONFIRMATION,
        ])
        with self.assertRaises(ImportFailure):
            _validate_mode(args)

    def test_rejects_state_file_for_another_workbook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(
                '{"version": 1, "workbook": "other.xlsx", "items": {}}',
                encoding="utf-8",
            )
            with self.assertRaises(ImportFailure):
                _read_state(state_path, Path(directory) / "workbook.xlsx")


class ImportExecutionTests(unittest.TestCase):
    guid = "5be52a09-e43f-4a48-b41b-5c33b95ee53a"

    def _asset(self) -> dict:
        return {
            "Id": {"values": [self.guid]},
            "TBN_MediaIDParent": {"values": ["HD-P010322"]},
            "WebProxyPath": {
                "values": [r"\\server\IPV\Proxies\WebProxy\HD-P010322"]
            },
        }

    def _run_args(self, workbook: Path, state_path: Path, *extra: str):
        return build_parser().parse_args([
            str(workbook),
            "--state-file",
            str(state_path),
            *extra,
        ])

    def test_default_preflight_never_constructs_obtv_client(self) -> None:
        class FakeCurator:
            web_proxy_fields = ("WebProxyPath",)
            hires_fields = ("OriginalPath",)

            def search(self, _media_id):
                return self_asset

            def close(self):
                pass

        class ObtvMustNotRun:
            def __init__(self):
                raise AssertionError("OBTV client must not be created in preflight")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook = root / "workbook.xlsx"
            state_path = root / "state.json"
            proxy_folder = root / "HD-P010322"
            proxy_folder.mkdir()
            (proxy_folder / "HD-P010322_video.mp4").write_bytes(b"video")
            _write_test_workbook(workbook)
            self_asset = self._asset()
            with patch.dict(
                os.environ,
                {"CURATOR_PROXY_MOUNT_ROOT": str(root)},
                clear=False,
            ), patch(
                "app.commands.import_curator_workbook.CuratorClient",
                FakeCurator,
            ), patch(
                "app.commands.import_curator_workbook.ObtvClient",
                ObtvMustNotRun,
            ):
                exit_code = run_import(self._run_args(workbook, state_path))
            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(state["items"]["HD-P010322"]["status"], "dry-run-ready")
        self.assertEqual(state["items"]["HD-P010322"]["source_type"], "web-proxy")

    def test_confirmed_execution_is_idempotent_across_state_resumption(self) -> None:
        class FakeCurator:
            web_proxy_fields = ("WebProxyPath",)
            hires_fields = ("OriginalPath",)

            def search(self, _media_id):
                return self_asset

            def close(self):
                pass

        class FakeObtv:
            import_calls = 0

            def import_web_proxy(self, *_args):
                type(self).import_calls += 1
                return {
                    "status": "queued",
                    "media_id": "media-123",
                    "job_id": "job-123",
                    "retryable": False,
                    "error": None,
                }

            def import_hires(self, *_args):
                raise AssertionError("Expected WebProxy import")

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook = root / "workbook.xlsx"
            state_path = root / "state.json"
            proxy_folder = root / "HD-P010322"
            proxy_folder.mkdir()
            (proxy_folder / "HD-P010322_video.mp4").write_bytes(b"video")
            _write_test_workbook(workbook)
            self_asset = self._asset()
            args = self._run_args(
                workbook,
                state_path,
                "--execute",
                "--confirm",
                EXECUTION_CONFIRMATION,
            )
            with patch.dict(
                os.environ,
                {"CURATOR_PROXY_MOUNT_ROOT": str(root)},
                clear=False,
            ), patch(
                "app.commands.import_curator_workbook.CuratorClient",
                FakeCurator,
            ), patch(
                "app.commands.import_curator_workbook.ObtvClient",
                FakeObtv,
            ):
                self.assertEqual(run_import(args), 0)
                self.assertEqual(run_import(args), 0)

        self.assertEqual(FakeObtv.import_calls, 1)


if __name__ == "__main__":
    unittest.main()