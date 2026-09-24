"""Dependency-light policy/transport tests; no production connections or ingest."""
import unittest
from unittest.mock import Mock

from app.catalog import (
    ASSET_TYPES, CUTOFF, INITIAL_CURSOR, CatalogClient, eligibility,
    exact_id, next_cursor,
)
from app.commands.import_curator_workbook import ImportFailure
from app.commands.curator_catalog import parser


def asset(identifier="id-1", day="2023-01-01"):
    return {"metadata": {"Id": [identifier], "IngestCompleteDate": [day]}}


class CatalogTests(unittest.TestCase):
    def test_cutoff_inclusive(self):
        self.assertEqual(eligibility(asset(day="2023-01-01"))[0], "eligible")
        self.assertEqual(eligibility(asset(day="2022-12-31T23:59:59Z"))[0], "excluded")
        self.assertEqual(eligibility(asset(day="2023-01-01T00:00:00Z"))[0], "eligible")
        self.assertEqual(eligibility(asset(day="2024-02-29T12:30:00.001+01:00"))[0], "eligible")

    def test_missing_invalid_ambiguous_dates_review_not_substituted(self):
        cases = [
            {}, {"ProductionDate": "2024-01-01"}, {"IngestCompleteDate": "01/01/2023"},
            {"IngestCompleteDate": "2023-02-29"}, {"IngestCompleteDate": "2023-01-01evil"},
            {"IngestCompleteDate": ["2023-01-01", "2022-01-01"]},
            {"IngestCompleteDate": None}, {"IngestCompleteDate": "2023-13-01"},
            {"IngestCompleteDate": "2023-01-01T25:00:00"},
        ]
        for case in cases:
            with self.subTest(case=case):
                status, error = eligibility(case)
                self.assertEqual(status, "review")
                self.assertTrue(error)

    def test_exact_id_not_name_or_href(self):
        self.assertEqual(exact_id(asset("Exact-Id")), "Exact-Id")
        for item in ({"Name": "Exact-Id"}, {"href": "/assets/Exact-Id"},
                     {"Id": ["one", "two"]}, {"Id": ""}):
            with self.assertRaises(ImportFailure):
                exact_id(item)

    def test_duplicates_and_resume_use_same_exact_identity(self):
        # Page shifts/re-delivery cannot produce a second primary key. Persisted
        # rows in production use this exact identity as the table primary key.
        persisted = {exact_id(a): a for a in [asset("a"), asset("a"), asset("b")]}
        cursor = next_cursor(INITIAL_CURSOR, 3)
        restored = dict(cursor)
        for row in [asset("b"), asset("c")]:
            persisted[exact_id(row)] = row
        self.assertEqual(set(persisted), {"a", "b", "c"})
        self.assertEqual(restored["offset"], 3)
        self.assertEqual(INITIAL_CURSOR["offset"], 0)

    def test_reconciliation_restarts_zero_and_scans_missing_dates(self):
        cursor = dict(INITIAL_CURSOR)
        for _ in ASSET_TYPES:
            cursor = next_cursor(cursor, 0)
        self.assertFalse(cursor["dated"])
        self.assertEqual(cursor["generation"], 0)
        for _ in ASSET_TYPES:
            cursor = next_cursor(cursor, 0)
        self.assertTrue(cursor["dated"])
        self.assertEqual(cursor["generation"], 1)
        self.assertEqual(cursor["offset"], 0)

    def client(self, payload, status=200):
        client = object.__new__(CatalogClient)
        client._access_token = "test-token"
        client.base_url = "https://example.invalid/CuratorGateway/"
        response = Mock(status_code=status)
        response.json.return_value = payload
        client.http = Mock()
        client.http.get.return_value = response
        return client

    def test_verified_query_and_type_and_limit_only(self):
        client = self.client({"value": [asset()], "size": 1})
        client.page("Audio", 199, dated=True)
        params = client.http.get.call_args.kwargs["params"]
        self.assertIn(("limit", "199"), params)
        self.assertIn(("assetTypes", "Audio"), params)
        self.assertIn(("offset", "199"), params)
        self.assertEqual([v for k, v in params if k == "queries"], ["IngestCompleteDate:*"])
        client.page("Image", 0, dated=False)
        self.assertFalse(any(k == "queries" for k, v in client.http.get.call_args.kwargs["params"]))

    def test_transport_schema_and_false_empty_failures_do_not_advance(self):
        cursor = dict(INITIAL_CURSOR)
        cases = [
            ({"value": [], "size": 50}, 200),
            ({"value": [], "size": 0}, 503),
            ({"value": "bad", "size": 0}, 200),
            ({"value": [asset()]}, 200),
            ({"value": [asset()] * 200, "size": 200}, 200),
        ]
        for payload, code in cases:
            with self.subTest(code=code, payload_type=type(payload)):
                with self.assertRaises(ImportFailure):
                    self.client(payload, code).page("Media", cursor["offset"], dated=True)
                self.assertEqual(cursor, INITIAL_CURSOR)

    def test_unsupported_type_rejected(self):
        client = self.client({"value": [], "size": 0})
        with self.assertRaises(ImportFailure):
            client.page("Document", 0, dated=True)
        client.http.get.assert_not_called()

    def test_command_default_dry_run_no_recurring(self):
        args = parser().parse_args([])
        self.assertFalse(args.apply)
        self.assertFalse(args.enable_recurring)
        self.assertEqual(args.max_assets, 10)
        self.assertEqual(args.max_pages, 1)


if __name__ == "__main__":
    unittest.main()