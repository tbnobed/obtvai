"""Focused contract tests for the schema v2 channel-analysis boundary."""

from datetime import datetime, timedelta
import asyncio
import json
import unittest

try:
    from app.routers.socials import (
        _history_payload,
        _N8NHTTPStatusError,
        _request_n8n_analysis,
        _parse_n8n_analysis,
    )
except ModuleNotFoundError:  # The API image installs FastAPI; local smoke tests may not.
    _history_payload = None
    _N8NHTTPStatusError = None
    _request_n8n_analysis = None
    _parse_n8n_analysis = None


def _ready_payload():
    return {
        "schemaVersion": 2,
        "status": "ready",
        "metrics": {
            "subscriber_count": 12000,
            "total_views": 980000,
            "total_videos": 42,
            "sample_size": 18,
            "avg_views": 54321.5,
            "median_views": 41200,
            "avg_likes": None,
            "avg_comments": 321.0,
            "engagement_rate": 1.8,
            "uploads_last_30d": 4,
            "uploads_per_week": 1.0,
            "recent_median_views": None,
            "previous_median_views": None,
            "performance_change_percent": -12.5,
            "subscriber_change": -30,
            "subscriber_change_percent": -0.25,
            "history_days": 88,
            "observed_at": "2026-05-02T12:00:00Z",
            "sample_oldest_at": "2026-02-01T12:00:00Z",
            "sample_newest_at": "2026-05-01T12:00:00Z",
        },
        "dataWarnings": ["Likes are unavailable for part of the sample."],
        "aiInsights": {
            "summary": "18 sampled uploads averaged 54,321.5 views.",
            "recommendations": ["Compare the next sample with this baseline."],
        },
        "topVideos": [
            {
                "id": "video-1",
                "title": "A measured result",
                "views": 120000,
                "likes": None,
                "comments": 42,
                "published_at": "2026-05-01T12:00:00Z",
                "thumbnail_url": "https://i.ytimg.com/vi/video-1/mqdefault.jpg",
            }
        ],
    }


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.content = json.dumps(body).encode("utf-8")
        self._body = body

    def json(self):
        return self._body


class _FakeHttpClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


@unittest.skipIf(_parse_n8n_analysis is None, "API dependencies are unavailable")
class SocialAnalysisV2ContractTests(unittest.TestCase):
    def test_full_v2_response_preserves_nulls_and_valid_negative_changes(self):
        parsed = _parse_n8n_analysis(_ready_payload())

        self.assertEqual(parsed["analysis_version"], 2)
        self.assertIsNone(parsed["analysis_metrics"]["avg_likes"])
        self.assertEqual(parsed["analysis_metrics"]["performance_change_percent"], -12.5)
        self.assertEqual(parsed["analysis_metrics"]["subscriber_change"], -30)
        self.assertEqual(parsed["top_videos"][0]["id"], "video-1")
        self.assertIsNone(parsed["top_videos"][0]["likes"])

    def test_empty_json_is_an_explicit_error(self):
        with self.assertRaisesRegex(ValueError, "empty JSON"):
            _parse_n8n_analysis({})

    def test_v2_error_is_not_a_ready_default(self):
        parsed = _parse_n8n_analysis(
            {
                "schemaVersion": 2,
                "status": "error",
                "error": {"code": "rate_limited", "message": "YouTube quota exhausted"},
            }
        )

        self.assertEqual(parsed["_status"], "error")
        self.assertEqual(parsed["analysis_version"], 2)
        self.assertIn("rate_limited", parsed["error"])
        self.assertNotIn("analysis_metrics", parsed)

    def test_non2xx_structured_v2_error_is_preserved_by_http_runner(self):
        body = {
            "schemaVersion": 2,
            "status": "error",
            "error": {
                "code": "youtube_rate_limited",
                "message": "YouTube Data API quota was exhausted",
            },
        }
        client = _FakeHttpClient(_FakeResponse(429, body))

        parsed = asyncio.run(_request_n8n_analysis(client, "youtube-channel", None))

        self.assertEqual(parsed["_status"], "error")
        self.assertEqual(parsed["analysis_version"], 2)
        self.assertIn("youtube_rate_limited", parsed["error"])
        self.assertEqual(client.calls[0][1]["json"], {
            "channelId": "youtube-channel",
            "history": None,
        })

    def test_non2xx_without_valid_error_envelope_falls_back_to_sanitized_http_error(self):
        client = _FakeHttpClient(_FakeResponse(429, {"message": "not schema v2"}))

        with self.assertRaises(_N8NHTTPStatusError) as raised:
            asyncio.run(_request_n8n_analysis(client, "youtube-channel", None))

        self.assertEqual(raised.exception.status_code, 429)

    def test_ready_requires_a_non_null_numeric_observation(self):
        zero_payload = _ready_payload()
        zero_payload["metrics"] = {"subscriber_count": 0}
        self.assertEqual(
            _parse_n8n_analysis(zero_payload)["analysis_metrics"]["subscriber_count"],
            0,
        )
        for metrics in (
            {key: None for key in _ready_payload()["metrics"]},
            {"observed_at": "2026-05-02T12:00:00Z"},
            {"sample_oldest_at": None, "sample_newest_at": None},
        ):
            with self.subTest(metrics=metrics):
                payload = _ready_payload()
                payload["metrics"] = metrics
                with self.assertRaisesRegex(ValueError, "substantive metrics"):
                    _parse_n8n_analysis(payload)


    def test_invalid_metric_shapes_are_rejected(self):
        for field, value in (
            ("subscriber_count", -1),
            ("total_views", float("nan")),
            ("avg_views", float("inf")),
        ):
            with self.subTest(field=field):
                payload = _ready_payload()
                payload["metrics"][field] = value

                with self.assertRaises(ValueError):
                    _parse_n8n_analysis(payload)


    def test_history_is_dated_bounded_and_null_when_absent(self):
        self.assertIsNone(_history_payload([]))
        base = datetime(2026, 1, 1, 12, 0, 0)
        snapshots = [
            type(
                "Snapshot",
                (),
                {
                    "fetched_at": base + timedelta(days=index),
                    "followers": index,
                    "total_views": index * 10,
                },
            )()
            for index in range(100)
        ]

        history = _history_payload(snapshots)

        self.assertIsNotNone(history)
        self.assertEqual(len(history), 90)
        self.assertEqual(
            history[0],
            {
                "recorded_at": "2026-01-11T12:00:00Z",
                "followers": 10,
                "total_views": 100,
            },
        )
        self.assertEqual(history[-1]["recorded_at"], "2026-04-10T12:00:00Z")
        self.assertEqual(set(history[-1]), {"recorded_at", "followers", "total_views"})


if __name__ == "__main__":
    unittest.main()