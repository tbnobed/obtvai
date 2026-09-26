"""Opt-in REAL trigger/cache invalidation tests on a disposable PostgreSQL DB.

ARCHIVE_MEMORY_TEST_DATABASE_URL must name a database ending in _archive_memory_test.
Never point this at production: tables are created and dropped by these tests.
"""
import os
import unittest
from urllib.parse import urlparse
from unittest.mock import patch

URL = os.getenv("ARCHIVE_MEMORY_TEST_DATABASE_URL")


@unittest.skipUnless(URL, "requires an explicit disposable PostgreSQL database")
class PostgresMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import asyncpg
        self.assertTrue(urlparse(URL).path.endswith("_archive_memory_test"),
                        "refusing to run destructive tests outside disposable test DB")
        self.db = await asyncpg.connect(URL)
        await self.db.execute("""
          CREATE TABLE media_assets(id text PRIMARY KEY,filename text,synopsis text,
                                    topics jsonb,duration_seconds float);
          CREATE TABLE transcript_segments(id text PRIMARY KEY,media_id text,text text);
          CREATE TABLE people(id text PRIMARY KEY,display_name text);
          CREATE TABLE person_appearances(person_id text,media_id text,speaking_seconds float);
          CREATE TABLE library_insights(headline text,insights jsonb);
          CREATE TABLE archive_memory_conversation_test(id text PRIMARY KEY);
        """)
        from app.commands.archive_memory_schema import STATEMENTS, trigger_statements
        async with self.db.transaction():
            for sql in STATEMENTS + trigger_statements():
                await self.db.execute(sql)

    async def asyncTearDown(self):
        await self.db.execute("""
          DROP TABLE IF EXISTS media_assets,transcript_segments,people,person_appearances,library_insights,
                     archive_memory_cache,archive_memory_dirty,archive_memory_versions,
                     archive_memory_conversation_test CASCADE;
          DROP FUNCTION archive_memory_invalidate(),archive_memory_enqueue();
          DROP SEQUENCE archive_memory_revision_seq;
        """)
        await self.db.close()

    async def test_invalidation_is_transactional_and_outbox_survives_delete(self):
        await self.db.execute("INSERT INTO media_assets(id,filename) VALUES('a','A')")
        before = await self.db.fetchval(
            "SELECT revision FROM archive_memory_versions WHERE name='media_assets'")
        tx = self.db.transaction()
        await tx.start()
        await self.db.execute("UPDATE media_assets SET synopsis='not committed' WHERE id='a'")
        await tx.rollback()
        self.assertEqual(before, await self.db.fetchval(
            "SELECT revision FROM archive_memory_versions WHERE name='media_assets'"))
        await self.db.execute("DELETE FROM media_assets WHERE id='a'")
        self.assertGreater(await self.db.fetchval(
            "SELECT revision FROM archive_memory_versions WHERE name='media_assets'"), before)
        self.assertEqual(1, await self.db.fetchval("SELECT count(*) FROM archive_memory_dirty"))

    async def test_literal_filter_counts_all_rows_before_limiting_evidence(self):
        await self.db.execute("""
          INSERT INTO media_assets(id,filename) VALUES('a','A'),('b','B'),('c','C');
          INSERT INTO transcript_segments VALUES
            ('a1','a','Faith'),('a2','a','faith'),('b1','b','faith'),('c1','c','other')
        """)
        count = await self.db.fetchval(
            "SELECT count(DISTINCT media_id) FROM transcript_segments WHERE text ILIKE '%faith%'")
        self.assertEqual(count, 2)
        rows = await self.db.fetch(
            "SELECT id FROM transcript_segments WHERE text ILIKE '%faith%' LIMIT 1")
        self.assertEqual(len(rows), 1)

    async def test_normalized_topic_aliases_count_one_asset_not_two(self):
        from app.services.archive_memory import TOPIC_COUNTS_SQL
        await self.db.execute("""
          INSERT INTO media_assets(id,filename,topics)
          VALUES('a','A','["Faith-Life","faith_life"]'),('b','B','["Faith Life"]')
        """)
        result = await self.db.fetch(TOPIC_COUNTS_SQL)
        self.assertEqual([(r["topic"], r["n"]) for r in result], [("faith life", 2)])

    async def test_edit_during_indexing_retains_new_outbox_revision(self):
        await self.db.execute("INSERT INTO media_assets(id,filename) VALUES('a','A')")
        revision = await self.db.fetchval(
            "SELECT revision FROM archive_memory_dirty WHERE media_id='a'")
        await self.db.execute("UPDATE media_assets SET synopsis='new analysis' WHERE id='a'")
        await self.db.execute(
            "DELETE FROM archive_memory_dirty WHERE media_id='a' AND revision=$1", revision)
        self.assertEqual(1, await self.db.fetchval("SELECT count(*) FROM archive_memory_dirty"))

    async def test_concurrent_trigram_index_ddl_is_valid(self):
        from app.commands.archive_memory import INDEXES
        for name, definition in INDEXES.items():
            await self.db.execute(f"CREATE INDEX CONCURRENTLY {name} {definition}")
            self.assertTrue(await self.db.fetchval(
                "SELECT indisvalid FROM pg_index WHERE indexrelid=$1::regclass", name))

    def session_factory(self):
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        url = URL.replace("postgresql://", "postgresql+asyncpg://", 1).replace(
            "postgres://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(url)
        return engine, async_sessionmaker(engine, expire_on_commit=False)

    async def test_real_cache_read_error_preserves_conversation_transaction(self):
        from sqlalchemy import text
        from app.services.archive_memory import cached
        await self.db.execute("DROP TABLE archive_memory_cache")
        engine, factory = self.session_factory()
        try:
            async with factory() as db:
                await db.execute(text("INSERT INTO archive_memory_conversation_test VALUES('read')"))

                async def builder():
                    return (await db.execute(text("SELECT 42"))).scalar_one()

                self.assertEqual(await cached(db, "test", "shared", builder), 42)
                await db.commit()
            self.assertEqual(await self.db.fetchval(
                "SELECT count(*) FROM archive_memory_conversation_test WHERE id='read'"), 1)
        finally:
            await engine.dispose()

    async def test_real_cache_write_lock_timeout_preserves_answer_and_transaction(self):
        import json
        from sqlalchemy import text
        from app import database
        from app.services.archive_memory import cached, fingerprint, SCHEMA_VERSION
        key = fingerprint(json.dumps([SCHEMA_VERSION, "test", "shared"], ensure_ascii=False))
        await self.db.execute(
            "INSERT INTO archive_memory_cache VALUES($1,'old','0',CURRENT_TIMESTAMP)", key)
        lock = self.db.transaction()
        await lock.start()
        await self.db.execute("UPDATE archive_memory_cache SET value='1' WHERE key=$1", key)
        engine, factory = self.session_factory()
        try:
            with patch.object(database, "AsyncSessionLocal", factory):
                async with factory() as db:
                    await db.execute(text("INSERT INTO archive_memory_conversation_test VALUES('write')"))

                    async def builder():
                        return (await db.execute(text("SELECT 43"))).scalar_one()

                    self.assertEqual(await cached(db, "test", "shared", builder), 43)
                    await db.commit()
            self.assertEqual(await self.db.fetchval(
                "SELECT count(*) FROM archive_memory_conversation_test WHERE id='write'"), 1)
        finally:
            await lock.rollback()
            await engine.dispose()

    async def test_unicode_count_cache_does_not_merge_postgres_distinct_terms(self):
        from app import database
        from app.services.archive_memory import exact_mentions
        await self.db.execute("""
          INSERT INTO media_assets(id,filename) VALUES('a','A'),('b','B'),('c','C');
          INSERT INTO transcript_segments VALUES
            ('a1','a','Straße'),('b1','b','STRASSE'),('c1','c','STRASSE');
        """)
        engine, factory = self.session_factory()
        try:
            with patch.object(database, "AsyncSessionLocal", factory):
                async with factory() as db:
                    for term in ("Straße", "STRASSE", "Straße", "STRASSE"):
                        expected = await self.db.fetchval(
                            "SELECT count(DISTINCT media_id) FROM transcript_segments WHERE text ILIKE $1",
                            "%" + term + "%")
                        self.assertEqual(await exact_mentions(db, term, None), expected)
                self.assertEqual(await self.db.fetchval("SELECT count(*) FROM archive_memory_cache"), 2)
        finally:
            await engine.dispose()