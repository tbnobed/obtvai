from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from app.commands.import_curator_workbook import (
    CuratorClient,
    ImportFailure,
    TERMINAL_STATUSES,
    asset_guid,
    choose_exact_asset,
    first_path,
    map_hires_path,
    read_workbook,
    resolve_web_proxy_path,
)


def _write_test_workbook(path: Path) -> None:
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
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData><row r=\"1\">{cells}</row><row r=\"2\">{values}</row></sheetData>"
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


class CuratorResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guid = "5be52a09-e43f-4a48-b41b-5c33b95ee53a"
        self.asset = {
            "href": f"https://curator.example/api/v1/assets/{self.guid}",
            "TBN_MediaId": {"values": ["HD-P010322"]},
            "WebProxyPath": {
                "values": [r"\\server\IPV\Proxies\WebProxy\2026\08\HD-P010322"]
            },
        }

    def test_selects_exact_asset_and_paths(self) -> None:
        chosen = choose_exact_asset(
            [self.asset],
            "HD-P010322",
            ("TBN_MediaId",),
        )
        self.assertIs(chosen, self.asset)
        self.assertEqual(asset_guid(chosen), self.guid)
        self.assertIn("WebProxy", first_path(chosen, ("WebProxyPath",)))

    def test_rejects_ambiguous_match(self) -> None:
        with self.assertRaises(ImportFailure):
            choose_exact_asset(
                [self.asset, dict(self.asset)],
                "HD-P010322",
                ("TBN_MediaId",),
            )

    def test_rejects_media_id_embedded_in_name(self) -> None:
        near_match = {
            "TBN_MediaId": {"values": ["Archive HD-P010322 revised"]},
        }
        with self.assertRaises(ImportFailure):
            choose_exact_asset(
                [near_match],
                "HD-P010322",
                ("TBN_MediaId",),
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

            def get(self, _url, *, params, headers):
                self.offsets.append(dict(params)["offset"])
                return self.responses.pop(0)

        near_match = {
            "TBN_MediaId": {"values": ["HD-P010322-revised"]},
        }
        exact_match = {
            "Id": {"values": [self.guid]},
            "TBN_MediaId": {"values": ["HD-P010322"]},
            "WebProxyPath": {
                "values": [r"\\server\IPV\Proxies\WebProxy\HD-P010322"]
            },
        }
        client = object.__new__(CuratorClient)
        client.base_url = "https://curator.example/"
        client.query_field = "TBN_MediaId"
        client.id_fields = ("TBN_MediaId",)
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


if __name__ == "__main__":
    unittest.main()