"""Unit tests for Re-Air Report CSV serialization and external publishing."""
import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _load_media_report_module():
    app_module = types.ModuleType("app")
    app_module.__path__ = []
    db_module = types.ModuleType("db")
    db_module.get_db = lambda: None
    db_module.get_session = lambda: None

    tasks_module = types.ModuleType("tasks")
    tasks_module.__path__ = []
    base_module = types.ModuleType("tasks.base")

    class FakeCelery:
        def task(self, *args, **kwargs):
            return lambda function: function

    base_module.celery_app = FakeCelery()
    app_module.celery_app = base_module.celery_app
    base_module.update_job = lambda *args, **kwargs: None
    base_module.append_log = lambda *args, **kwargs: None
    base_module.is_cancelled = lambda *args, **kwargs: False

    saved_modules = {
        name: sys.modules.get(name)
        for name in ("app", "db", "tasks", "tasks.base")
    }
    sys.modules.update({
        "app": app_module,
        "db": db_module,
        "tasks": tasks_module,
        "tasks.base": base_module,
    })
    try:
        path = Path(__file__).parents[1] / "tasks" / "media_report.py"
        spec = importlib.util.spec_from_file_location("media_report_under_test", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in saved_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


media_report = _load_media_report_module()

try:
    import httpx  # type: ignore
except ModuleNotFoundError:
    httpx = types.ModuleType("httpx")

    class HTTPError(Exception):
        pass

    class ConnectError(HTTPError):
        pass

    httpx.HTTPError = HTTPError
    httpx.ConnectError = ConnectError
    httpx.post = lambda *args, **kwargs: None
    sys.modules["httpx"] = httpx


class FakeResponse:
    def __init__(self, status_code=201, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class MediaReportCsvTests(unittest.TestCase):
    def test_csv_has_bom_all_columns_and_partial_rows(self):
        rows = [{
            "clip_id": "PROXY-17",
            "curator_original_air_date": "2026-08-01T12:00:00Z",
            "curator_last_air_date": "2026-08-29",
            "host": "A Host",
            "guests": "Guest One, Guest Two",
            "short_synopsis": 'A quoted, "short" synopsis',
            "long_synopsis": "Transcript-backed details.",
            "date_mentions": "00:01:02 — August 5",
            "date_sensitive": "Partial report: transcript unavailable",
        }]

        content = media_report._render_report_csv(rows)

        self.assertTrue(content.startswith("\ufeffClipID,Air Dates,Host,Guests"))
        self.assertIn("Original: 2026-08-01 | Last: 2026-08-29", content)
        self.assertIn('"A quoted, ""short"" synopsis"', content)
        self.assertIn("Partial report: transcript unavailable", content)
        self.assertEqual(content.count("\n"), 2)


class MediaReportPublishTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "REPORT_INGEST_API_KEY": "super-secret-test-token",
            "REPORT_INGEST_URL": "https://example.test/api/reports/ingest",
        }
        self.success_payload = {
            "id": 42,
            "name": "reair-report-20260830-120000.csv",
            "clipCount": 2,
            "uploadedAt": "2026-08-30T19:00:00Z",
        }

    @patch("httpx.post")
    def test_posts_exact_csv_once_with_bearer_header(self, post):
        post.return_value = FakeResponse(payload=self.success_payload)
        content = media_report._render_report_csv([
            {
                "clip_id": "one",
                "short_synopsis": "Full transcript result",
                "long_synopsis": "Detailed transcript result",
            },
            {
                "clip_id": "two",
                "short_synopsis": "Partial report",
                "date_sensitive": "Transcript unavailable",
            },
        ])

        with patch.dict(os.environ, self.env, clear=False):
            result = media_report._post_report(self.success_payload["name"], content)

        post.assert_called_once_with(
            self.env["REPORT_INGEST_URL"],
            headers={"Authorization": f"Bearer {self.env['REPORT_INGEST_API_KEY']}"},
            json={"name": self.success_payload["name"], "content": content},
            timeout=30.0,
        )
        self.assertEqual(content.count(","), 7 * 3)
        self.assertIn("Transcript unavailable", content)
        self.assertEqual(result["id"], "42")
        self.assertEqual(result["clip_count"], 2)

    @patch("httpx.post")
    def test_rejected_response_is_not_retried_and_redacts_token(self, post):
        post.return_value = FakeResponse(
            status_code=401,
            text=f"Rejected bearer {self.env['REPORT_INGEST_API_KEY']}",
        )

        with patch.dict(os.environ, self.env, clear=False):
            with self.assertRaisesRegex(RuntimeError, r"HTTP 401") as raised:
                media_report._post_report("report.csv", "content")

        post.assert_called_once()
        self.assertNotIn(self.env["REPORT_INGEST_API_KEY"], str(raised.exception))
        self.assertIn("[REDACTED]", str(raised.exception))

    @patch("httpx.post")
    def test_network_failure_is_not_retried(self, post):
        import httpx

        post.side_effect = httpx.ConnectError("connection refused")
        with patch.dict(os.environ, self.env, clear=False):
            with self.assertRaisesRegex(RuntimeError, "request failed"):
                media_report._post_report("report.csv", "content")
        post.assert_called_once()

    @patch("httpx.post")
    def test_invalid_success_response_is_rejected(self, post):
        post.return_value = FakeResponse(payload={"id": "missing-fields"})
        with patch.dict(os.environ, self.env, clear=False):
            with self.assertRaisesRegex(RuntimeError, "response omitted"):
                media_report._post_report("report.csv", "content")

    @patch("httpx.post")
    def test_missing_secret_fails_before_request(self, post):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "REPORT_INGEST_API_KEY"):
                media_report._post_report("report.csv", "content")
        post.assert_not_called()

    def test_cancelled_report_does_not_post_at_publish_boundary(self):
        sqlalchemy = types.ModuleType("sqlalchemy")
        sqlalchemy.text = lambda statement: statement

        class CancelledResult:
            @staticmethod
            def scalar_one_or_none():
                return "cancelled"

        class CancelledDb:
            status = "cancelled"

            @staticmethod
            def execute(statement, params):
                return CancelledResult()

        db = CancelledDb()
        with patch.dict(sys.modules, {"sqlalchemy": sqlalchemy}):
            with patch.object(media_report, "_post_report") as post:
                result = media_report._post_report_if_running(
                    db,
                    "report-id",
                    "report.csv",
                    "csv content",
                )

        self.assertIsNone(result)
        self.assertEqual(db.status, "cancelled")
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()