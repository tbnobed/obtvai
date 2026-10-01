"""Dedicated service isolation, auth, and DB lifetime regression tests."""
import asyncio
import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

SOURCE = Path(__file__).parents[1] / "app" / "playback_main.py"

IMPORTS_BEFORE_SERVICE = set(sys.modules)
try:
    from app import playback_main as service
    IMPORTED_BY_SERVICE = set(sys.modules) - IMPORTS_BEFORE_SERVICE
    from app import auth
    from fastapi.testclient import TestClient
    from starlette.requests import Request
except ModuleNotFoundError:
    service = None


class SourceIsolationTests(unittest.TestCase):
    def test_no_heavy_router_or_main_imports_and_no_ddl(self):
        tree = ast.parse(SOURCE.read_text())
        imports = [
            node.module for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        self.assertNotIn("main", imports)
        self.assertFalse(any("routers" in name or "services" in name for name in imports))
        self.assertNotIn("create_all", SOURCE.read_text())
        self.assertNotIn("warmup", [
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        ])


@unittest.skipIf(service is None, "Full API runtime dependencies unavailable")
class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def request(self, headers=()):
        return Request({
            "type": "http", "method": "GET", "path": "/api/media/asset/playback",
            "headers": headers, "query_string": b"",
        })

    def fake_db(self, row):
        state = {"closed": False}

        class Session:
            async def __aenter__(self):
                state["closed"] = False
                return self

            async def __aexit__(self, *_):
                state["closed"] = True

            async def execute(self, query):
                # Verify this is a scalar column projection, not an ORM object.
                self.query = query
                return SimpleNamespace(first=lambda: row)

        return Session, state

    async def test_snapshot_immutable_and_closes_session(self):
        session, state = self.fake_db(("asset", "/curator/render_video.mp4", None, 13.0))
        with patch.object(service, "AsyncSessionLocal", session):
            snapshot = await service.media_snapshot("asset")
        self.assertTrue(state["closed"])
        self.assertEqual(snapshot.duration_seconds, 13.0)
        with self.assertRaises(FrozenInstanceError):
            snapshot.proxy_path = "changed"

    async def test_not_found_also_closes(self):
        session, state = self.fake_db(None)
        with patch.object(service, "AsyncSessionLocal", session):
            with self.assertRaises(service.HTTPException) as raised:
                await service.media_snapshot("missing")
        self.assertEqual(raised.exception.status_code, 404)
        self.assertTrue(state["closed"])

    async def test_db_closed_before_probe_playlist_and_segment_response(self):
        session, state = self.fake_db(("asset", "/curator/render_video.mp4", None, 13.0))

        async def describe(asset, request):
            self.assertTrue(state["closed"])
            self.assertIsInstance(asset, service.MediaSnapshot)
            return Path(asset.proxy_path), 13.0, True, False, ["audio"]

        async def segment_response(asset, number, request):
            self.assertTrue(state["closed"])
            self.assertIsInstance(asset, service.MediaSnapshot)
            return service.Response(b"ts", media_type="video/mp2t")

        with (
            patch.object(service, "AsyncSessionLocal", session),
            patch.object(service.playback, "archive_asset", return_value=True),
            patch.object(service.playback, "source", return_value=Path("/curator/render_video.mp4")),
            patch.object(service.playback, "describe", new=describe),
            patch.object(service.playback, "segment_response", new=segment_response),
        ):
            metadata = await service.playback_info("asset", self.request())
            self.assertIn(b'"hasAudio":true', metadata.body)
            playlist = await service.archive_playlist("asset", self.request())
            self.assertIn(b"segments/2.ts", playlist.body)
            segment = await service.archive_segment("asset", 1, self.request())
            self.assertEqual(segment.body, b"ts")

    async def test_legacy_stream_stays_on_main_api(self):
        snapshot = service.MediaSnapshot("asset", "/artifacts/proxies/asset.mp4", None, 10)
        with (
            patch.object(service, "media_snapshot", new=AsyncMock(return_value=snapshot)),
            patch.object(service.playback, "archive_asset", return_value=False),
            patch.object(service.playback, "describe", new=AsyncMock()) as describe,
        ):
            response = await service.playback_info("asset", self.request())
            self.assertIn(b'"url":"/api/media/asset/stream"', response.body)
            describe.assert_not_awaited()
            with self.assertRaises(service.HTTPException) as raised:
                await service.archive_playlist("asset", self.request())
            self.assertEqual(raised.exception.status_code, 404)

    async def test_ranges_and_negative_segment_fail_before_db(self):
        for number, headers in [(0, [(b"range", b"bytes=0-1")]), (-1, [])]:
            with patch.object(service, "media_snapshot", new=AsyncMock()) as snapshot:
                with self.assertRaises(service.HTTPException) as raised:
                    await service.archive_segment("asset", number, self.request(headers))
                self.assertEqual(raised.exception.status_code, 416)
                snapshot.assert_not_awaited()

    async def test_bounds_fail_explicitly(self):
        for value in ["0", "65", "not-an-int"]:
            with patch.dict("os.environ", {"PLAYBACK_ENCODE_JOBS": value}):
                with self.assertRaises(RuntimeError):
                    async with service.lifespan(service.app):
                        pass

    async def test_entrypoint_has_only_exact_routes(self):
        self.assertEqual(
            {route.path for route in service.app.routes},
            {"/api/healthz", "/api/media/{id}/playback",
             "/api/media/{id}/hls.m3u8", "/api/media/{id}/segments/{number}.ts"},
        )
        self.assertNotIn("app.main", IMPORTED_BY_SERVICE)
        self.assertNotIn("torch", IMPORTED_BY_SERVICE)


@unittest.skipIf(service is None, "Full API runtime dependencies unavailable")
class AuthTests(unittest.TestCase):
    def test_health_and_unauthenticated_requests(self):
        with TestClient(service.app) as client:
            self.assertEqual(client.get("/api/healthz").status_code, 200)
            for path in ["/api/media/asset/playback", "/api/media/asset/hls.m3u8",
                         "/api/media/asset/segments/0.ts"]:
                self.assertEqual(client.get(path).status_code, 401)

    def test_viewer_bearer_and_cookie_use_existing_middleware(self):
        snapshot = service.MediaSnapshot("asset", None, "/media/source.mp4", 12)
        with (
            patch.object(auth, "_resolve_user", new=AsyncMock(return_value=SimpleNamespace(role="viewer"))),
            patch.object(service, "media_snapshot", new=AsyncMock(return_value=snapshot)),
            patch.object(service.playback, "archive_asset", return_value=False),
            TestClient(service.app) as client,
        ):
            self.assertEqual(client.get("/api/media/asset/playback",
                                        headers={"Authorization": "Bearer test-only-token"}).status_code, 200)
            client.cookies.set("obtv_session", "test-only-cookie")
            self.assertEqual(client.get("/api/media/asset/playback").status_code, 200)
            self.assertEqual(client.post("/api/media/asset/playback").status_code, 403)
            self.assertEqual(client.get("/api/media/asset/stream").status_code, 404)


if __name__ == "__main__":
    unittest.main()