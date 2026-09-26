"""No model downloads or external services; optional PostgreSQL integration below."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.services import archive_memory as memory
from app.commands.archive_memory_schema import trigger_statements, STATEMENTS


def mock_session():
    db = AsyncMock()
    db.begin_nested = Mock(side_effect=lambda: AsyncMock())
    return db


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    def test_no_summary_is_not_invented(self):
        asset = SimpleNamespace(filename="unknown.mp4", synopsis=None, topics=None)
        self.assertEqual(memory.summary_text(asset), "")
        asset.synopsis = "An interview about local schools."
        first = memory.fingerprint(memory.summary_text(asset))
        asset.synopsis = "Corrected interview description."
        self.assertNotEqual(first, memory.fingerprint(memory.summary_text(asset)))

    def test_model_identity_isolated_even_with_same_dimensions(self):
        with patch.object(memory.settings, "embeddings_model", "encoder-one"):
            first = memory.collection_name()
        with patch.object(memory.settings, "embeddings_model", "encoder-two"):
            self.assertNotEqual(first, memory.collection_name())

    def test_literal_counts_and_ambiguous_semantic_counts(self):
        self.assertEqual(memory.mention_term('How many videos mention "Mary Jane"?'), "Mary Jane")
        self.assertEqual(memory.mention_term("How many assets mention 'faith'?"), "faith")
        self.assertIsNone(memory.mention_term("How many videos are about faith?"))
        self.assertEqual(memory.literal_pattern("50%_off"), "%50\\%\\_off%")
        for question in (
            "How many videos mention faith or hope?",
            'How many videos mention "faith" or "hope"?',
            'How many videos mention "faith" in 2025?',
            'How many videos mention "faith" with Mary?',
            "How many videos mention faith by Mary?",
            'How many videos mention "faith" AND speaker="Mary"?',
        ):
            self.assertIsNone(memory.mention_term(question), question)

    async def test_cache_hit_avoids_builder(self):
        db = mock_session()
        db.execute.return_value = Mock(first=Mock(return_value=("known overview",)))
        build = AsyncMock(return_value="expensive")
        with patch.object(memory, "installed", AsyncMock(return_value=True)), \
             patch.object(memory, "version", AsyncMock(return_value="media:1")):
            self.assertEqual(await memory.cached(db, "overview", "shared", build), "known overview")
        build.assert_not_awaited()

    async def test_concurrent_delete_or_edit_does_not_cache_old_snapshot(self):
        db = mock_session()
        db.execute.return_value = Mock(first=Mock(return_value=None))
        build = AsyncMock(return_value="old summary")
        with patch.object(memory, "installed", AsyncMock(return_value=True)), \
             patch.object(memory, "version", AsyncMock(side_effect=["media:1", "media:2"])), \
             patch.object(memory, "store_cache", AsyncMock()) as store:
            self.assertEqual(await memory.cached(db, "overview", "shared", build), "old summary")
            store.assert_not_awaited()

    async def test_distinct_scopes_have_distinct_cache_keys(self):
        db = mock_session()
        db.execute.return_value = Mock(first=Mock(return_value=None))
        with patch.object(memory, "installed", AsyncMock(return_value=True)), \
             patch.object(memory, "version", AsyncMock(return_value="media:1")), \
             patch.object(memory, "store_cache", AsyncMock()) as store:
            await memory.cached(db, "mentions:faith", "media:a", AsyncMock(return_value=1))
            await memory.cached(db, "mentions:faith", "shared-library", AsyncMock(return_value=100))
            self.assertNotEqual(store.await_args_list[0].args[0], store.await_args_list[1].args[0])

    async def test_deleted_and_stale_summary_points_cannot_supply_evidence(self):
        from app.services import qdrant_client
        db = AsyncMock()
        db.execute.return_value = Mock(scalars=Mock(return_value=[]))
        hit = SimpleNamespace(payload={"media_id": "deleted", "fingerprint": "old"})
        with patch.object(qdrant_client, "search_vectors", AsyncMock(return_value=[hit])) as search:
            self.assertEqual(await memory.hierarchical_segments(db, [0.1]), [])
            self.assertEqual(search.await_count, 1)  # no global fallback with empty allowed IDs

    async def test_optional_cache_read_failure_uses_builder(self):
        db = mock_session()
        with patch.object(memory, "installed", AsyncMock(side_effect=RuntimeError("read denied"))), \
             patch.object(memory, "store_cache", AsyncMock()) as store:
            self.assertEqual(await memory.cached(db, "overview", "shared", AsyncMock(return_value="truth")), "truth")
            store.assert_not_awaited()
            db.rollback.assert_not_awaited()

    async def test_optional_cache_write_failure_returns_result(self):
        db = mock_session()
        db.execute.return_value = Mock(first=Mock(return_value=None))
        with patch.object(memory, "installed", AsyncMock(return_value=True)), \
             patch.object(memory, "version", AsyncMock(return_value="media:1")), \
             patch.object(memory, "store_cache", AsyncMock(side_effect=TimeoutError("locked"))):
            self.assertEqual(await memory.cached(db, "overview", "shared", AsyncMock(return_value="truth")), "truth")
            db.rollback.assert_not_awaited()

    async def test_builder_error_is_not_swallowed(self):
        with patch.object(memory, "installed", AsyncMock(return_value=False)):
            with self.assertRaisesRegex(RuntimeError, "query failed"):
                await memory.cached(mock_session(), "overview", "shared",
                                    AsyncMock(side_effect=RuntimeError("query failed")))

    async def test_no_summary_hits_preserves_direct_retrieval_contract(self):
        from app.services import qdrant_client
        with patch.object(qdrant_client, "search_vectors", AsyncMock(return_value=[])):
            self.assertEqual(await memory.hierarchical_segments(AsyncMock(), [0.1]), [])

    def test_migration_is_manual_and_transactional(self):
        from app.commands.archive_memory import INDEXES
        sql = "\n".join(STATEMENTS + trigger_statements())
        self.assertIn("AFTER INSERT OR DELETE OR TRUNCATE", sql)
        self.assertIn("FOR EACH STATEMENT", sql)
        self.assertIn("UPDATE OF filename,synopsis,topics", sql)
        self.assertNotIn("UPDATE OF embedding_id", sql)
        self.assertIn("ON CONFLICT(media_id)", sql)
        self.assertEqual(len(INDEXES), 2)


if __name__ == "__main__":
    unittest.main()