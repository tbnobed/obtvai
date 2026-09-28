"""Search scope regressions; SQL compilation exercises every shared filter."""
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.dialects import postgresql

from app.catalog_models import CatalogAsset  # pre-load before patch.dict(sys.modules)
from app.routers.search import _search_asset_scope, _fallback_text_search, semantic_search
from app.schemas import SearchQuery


class Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self


class Database:
    def __init__(self, asset=None, segment=None, scene=None, person=None):
        self.asset = asset
        self.segment = segment
        self.scene = scene
        self.person = person
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        sql = str(statement)
        table = sql.split("FROM ", 1)[1].split()[0] if "FROM " in sql else ""
        if table == "people":
            return Rows([self.person] if self.person else [])
        if table == "person_appearances":
            return Rows([(SimpleNamespace(first_spoken_at=2.0, speaking_seconds=4.0), self.asset)] if self.asset else [])
        if table == "transcript_segments":
            return Rows([(self.segment, self.asset)] if self.segment else [])
        if table == "scenes":
            return Rows([(self.scene, self.asset)] if self.scene and "JOIN media_assets" in sql else [])
        if table == "media_assets" and self.asset:
            return Rows([self.asset])
        return Rows()

    def add(self, row):
        pass

    async def commit(self):
        pass


def sql_and_params(statement):
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


class LibrarySearchTests(unittest.IsolatedAsyncioTestCase):
    def test_filters_match_media_list_and_empty_pool(self):
        body = SearchQuery(query="news", media_ids=[], media_type="images",
                           status="ready", folder="root", person="person-1", topic="Local_AI-Infrastructure")
        from app.models import MediaAsset
        from sqlalchemy import select
        sql, params = sql_and_params(select(MediaAsset).where(*_search_asset_scope(body)))
        self.assertIn("media_assets.id IN", sql)
        self.assertEqual(params["id_1"], [])
        self.assertIn("media_assets.status =", sql)
        self.assertIn("media_assets.folder_id IS NULL", sql)
        self.assertIn("person_appearances.person_id =", sql)
        self.assertIn("jsonb_array_elements_text(media_assets.topics)", sql)
        self.assertEqual(params["topic_key"], "local ai infrastructure")
        self.assertIn("catalog_assets", sql)
        for folder, expected in [("folder-1", "media_assets.folder_id ="), ("root", "media_assets.folder_id IS NULL")]:
            sql, _ = sql_and_params(select(MediaAsset).where(*_search_asset_scope(SearchQuery(query="x", folder=folder))))
            self.assertIn(expected, sql)
        sql, _ = sql_and_params(select(MediaAsset).where(*_search_asset_scope(SearchQuery(query="x", media_type="hide_images"))))
        self.assertIn("NOT", sql)

    async def test_empty_ids_short_circuits_every_branch(self):
        for search_type in ("combined", "filename", "person", "transcript", "visual"):
            db = Database()
            response = await semantic_search(SearchQuery(query="news", search_type=search_type, media_ids=[]), db)
            self.assertEqual(response.results, [])
            self.assertFalse(db.statements)

    async def test_filename_scope_and_limit(self):
        asset = SimpleNamespace(id="a", filename="news.mov", original_path="/archive/news.mov", thumbnail_url=None)
        for search_type in ("filename", "combined"):
            db = Database(asset)
            if search_type == "combined":
                embedding = types.ModuleType("app.services.embedding")
                embedding.get_text_embedding = AsyncMock(return_value=[1.0])
                embedding.get_clip_text_embedding = AsyncMock()
                vectors = types.ModuleType("app.services.qdrant_client")
                vectors.search_vectors = AsyncMock(return_value=[])
                with patch.dict(sys.modules, {"app.services.embedding": embedding, "app.services.qdrant_client": vectors}):
                    response = await semantic_search(SearchQuery(query="news", search_type=search_type, limit=1, folder="root"), db)
            else:
                response = await semantic_search(SearchQuery(query="news", search_type=search_type, limit=1, folder="root"), db)
            self.assertEqual(len(response.results), 1)
            self.assertEqual(response.results[0].match_type, "filename")
            asset_sql = next(sql_and_params(s)[0] for s in db.statements if "FROM media_assets" in str(s))
            self.assertIn("folder_id IS NULL", asset_sql)
            self.assertIn("LIMIT", asset_sql)

    async def test_fallback_sql_applies_all_scope(self):
        db = Database()
        await _fallback_text_search(SearchQuery(
            query="news", media_id="a", media_ids=["a"], media_type="hide_images",
            status="ready", folder="root", person="p", topic="climate", limit=2,
        ), db)
        sql, params = sql_and_params(db.statements[0])
        for expected in ("media_assets.id =", "media_assets.id IN", "media_assets.status =",
                         "media_assets.folder_id IS NULL", "person_appearances.person_id",
                         "jsonb_array_elements_text", "catalog_assets", "LIMIT"):
            self.assertIn(expected, sql)
        self.assertEqual(params["param_1"], 2)

    async def test_combined_filename_and_vector_transcript_scope(self):
        asset = SimpleNamespace(id="a", filename="news.mov", original_path=None, thumbnail_url=None)
        seg = SimpleNamespace(id="seg", start_time=4, end_time=7, text="news broadcast")
        db = Database(asset, seg)
        embedding = types.ModuleType("app.services.embedding")
        embedding.get_text_embedding = AsyncMock(return_value=[1.0])
        embedding.get_clip_text_embedding = AsyncMock(return_value=[1.0])
        vectors = types.ModuleType("app.services.qdrant_client")
        async def hits(collection, **kwargs):
            if collection == "transcripts":
                return [SimpleNamespace(payload={"segment_id": "seg"}, score=0.8)]
            return []
        vectors.search_vectors = AsyncMock(side_effect=hits)
        with patch.dict(sys.modules, {"app.services.embedding": embedding, "app.services.qdrant_client": vectors}):
            response = await semantic_search(SearchQuery(query="news", folder="root", limit=2, media_ids=["a"]), db)
        self.assertEqual({r.match_type for r in response.results}, {"filename", "transcript"})
        self.assertEqual(next(r.start_time for r in response.results if r.match_type == "transcript"), 4)
        for stmt in db.statements:
            if "FROM transcript_segments" in str(stmt):
                sql, _ = sql_and_params(stmt)
                self.assertIn("folder_id IS NULL", sql)
                self.assertIn("media_assets.id IN", sql)
        self.assertEqual(vectors.search_vectors.call_args_list[0].kwargs["media_ids"], ["a"])

    async def test_exact_and_person_paths_use_scope(self):
        asset = SimpleNamespace(id="a", filename="news.mov", original_path=None, thumbnail_url=None)
        seg = SimpleNamespace(id="seg", start_time=8, end_time=9, text="breaking news")
        db = Database(asset, seg, person=SimpleNamespace(id="p", display_name="Alice"))
        result = await semantic_search(SearchQuery(query="Alice", search_type="person", status="ready", folder="root"), db)
        self.assertEqual(result.results[0].match_type, "person")
        self.assertEqual(result.results[0].start_time, 2)
        sql = next(sql_and_params(s)[0] for s in db.statements if "FROM person_appearances" in str(s))
        self.assertIn("media_assets.status =", sql)
        self.assertIn("folder_id IS NULL", sql)
        db = Database(asset, seg)
        embedding = types.ModuleType("app.services.embedding")
        embedding.get_text_embedding = AsyncMock(return_value=[1.0])
        embedding.get_clip_text_embedding = AsyncMock(return_value=[1.0])
        vectors = types.ModuleType("app.services.qdrant_client")
        vectors.search_vectors = AsyncMock(return_value=[])
        with patch.dict(sys.modules, {"app.services.embedding": embedding, "app.services.qdrant_client": vectors}):
            result = await semantic_search(SearchQuery(query='"breaking news"', search_type="transcript", status="ready"), db)
        self.assertEqual(result.results[0].match_type, "transcript")
        sql = next(sql_and_params(s)[0] for s in db.statements if "FROM transcript_segments" in str(s))
        self.assertIn("media_assets.status =", sql)
        self.assertIn("transcript_segments.text", sql)

    async def test_exact_phrase_survives_unavailable_embedding_with_filters(self):
        asset = SimpleNamespace(id="a", filename="report.mov", original_path=None, thumbnail_url=None)
        seg = SimpleNamespace(id="seg", start_time=11, end_time=14, text="the 100%_result is here")
        db = Database(asset, seg)
        embedding = types.ModuleType("app.services.embedding")
        embedding.get_text_embedding = AsyncMock(side_effect=RuntimeError("embedding unavailable"))
        embedding.get_clip_text_embedding = AsyncMock(side_effect=RuntimeError("embedding unavailable"))
        vectors = types.ModuleType("app.services.qdrant_client")
        vectors.search_vectors = AsyncMock(return_value=[])
        body = SearchQuery(query='"100%_result"', search_type="transcript",
                           media_id="a", media_ids=["a"], status="ready",
                           folder="root", person="p", topic="science",
                           media_type="hide_images", limit=1)
        with patch.dict(sys.modules, {"app.services.embedding": embedding, "app.services.qdrant_client": vectors}):
            result = await semantic_search(body, db)
        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0].start_time, 11)
        embedding.get_text_embedding.assert_not_awaited()
        stmt = next(s for s in db.statements if "FROM transcript_segments" in str(s))
        sql, params = sql_and_params(stmt)
        for expected in ("media_assets.id =", "media_assets.id IN", "media_assets.status =",
                         "folder_id IS NULL", "person_appearances.person_id",
                         "jsonb_array_elements_text", "catalog_assets", "LIMIT"):
            self.assertIn(expected, sql)
        self.assertIn("%100\\%\\_result%", params.values())
        self.assertIn("ESCAPE", sql)

    async def test_quoted_fallback_strips_quotes_and_escapes_wildcards(self):
        asset = SimpleNamespace(id="a", filename="report.mov", original_path=None, thumbnail_url=None)
        seg = SimpleNamespace(id="seg", start_time=2, end_time=3, text="the 100%_result")
        db = Database(asset, seg)
        result = await _fallback_text_search(SearchQuery(query='"100%_result"', folder="root"), db)
        self.assertEqual(result[0].start_time, 2)
        sql, params = sql_and_params(db.statements[0])
        self.assertIn("folder_id IS NULL", sql)
        self.assertIn("%100\\%\\_result%", params.values())
        self.assertNotIn('%"100', params.values())

    async def test_filename_search_finds_path_token_without_slash_and_escapes_wildcards(self):
        asset = SimpleNamespace(id="a", filename="clip.mov",
                                original_path="/archive/2025/100%_final/clip.mov", thumbnail_url=None)
        db = Database(asset)
        result = await semantic_search(SearchQuery(query="2025", search_type="filename",
                                                  folder="root", limit=1), db)
        self.assertEqual(result.results[0].match_type, "filename")
        self.assertEqual(result.results[0].snippet, asset.original_path)
        sql, params = sql_and_params(db.statements[0])
        self.assertIn("media_assets.original_path ILIKE", sql)
        self.assertIn("media_assets.filename ILIKE", sql)
        self.assertIn("%2025%", params.values())
        db = Database(asset)
        await semantic_search(SearchQuery(query="100%_final", search_type="filename"), db)
        _, params = sql_and_params(db.statements[0])
        self.assertIn("%100\\%\\_final%", params.values())

    async def test_visual_vector_hydration_is_scoped(self):
        asset = SimpleNamespace(id="a", filename="news.mov", original_path=None, thumbnail_url=None)
        scene = SimpleNamespace(id="scene", start_time=4, end_time=12,
                                thumbnail_url=None, description="news desk")
        db = Database(asset, scene=scene)
        embedding = types.ModuleType("app.services.embedding")
        embedding.get_text_embedding = AsyncMock(return_value=[1.0])
        embedding.get_clip_text_embedding = AsyncMock(return_value=[1.0])
        vectors = types.ModuleType("app.services.qdrant_client")
        vectors.search_vectors = AsyncMock(return_value=[
            SimpleNamespace(payload={"scene_id": "scene", "frame_time": 8}, score=0.35)
        ])
        with patch.dict(sys.modules, {"app.services.embedding": embedding, "app.services.qdrant_client": vectors}):
            response = await semantic_search(SearchQuery(query="news", search_type="visual", folder="root",
                                                        media_type="hide_images", limit=1), db)
        self.assertEqual(response.results[0].match_type, "visual")
        self.assertEqual(response.results[0].start_time, 6)
        sql = next(sql_and_params(s)[0] for s in db.statements if "FROM scenes" in str(s))
        self.assertIn("folder_id IS NULL", sql)
        self.assertIn("catalog_assets", sql)
        self.assertEqual(len(response.results), 1)

    async def test_vector_failure_fallback_preserves_filename(self):
        asset = SimpleNamespace(id="a", filename="news.mov", original_path=None, thumbnail_url=None)
        seg = SimpleNamespace(id="seg", start_time=3, end_time=5, text="news")
        db = Database(asset, seg)
        embedding = types.ModuleType("app.services.embedding")
        embedding.get_text_embedding = AsyncMock(side_effect=RuntimeError("offline"))
        embedding.get_clip_text_embedding = AsyncMock()
        vectors = types.ModuleType("app.services.qdrant_client")
        vectors.search_vectors = AsyncMock(return_value=[])
        with patch.dict(sys.modules, {"app.services.embedding": embedding, "app.services.qdrant_client": vectors}), \
                patch("logging.getLogger"):
            response = await semantic_search(SearchQuery(query="news", search_type="combined",
                                                        status="ready", limit=2), db)
        self.assertEqual({r.match_type for r in response.results}, {"filename", "transcript"})
        sql = next(sql_and_params(s)[0] for s in db.statements if "FROM transcript_segments" in str(s))
        self.assertIn("media_assets.status =", sql)


if __name__ == "__main__":
    unittest.main()