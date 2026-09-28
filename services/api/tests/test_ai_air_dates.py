"""Date answers use Curator original air date only, with no retrieval fallback."""
import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

_old_url = os.environ.get("DATABASE_URL")
# Importing app.database constructs an engine, but does not connect. Override
# even a production .env; these tests execute exclusively on in-memory SQLite.
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@127.0.0.1:1/never_connect"

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.models import MediaAsset, AIConversation, AIMessage
from app.routers import ai
from app.schemas import AIQuestion

if _old_url is None:
    os.environ.pop("DATABASE_URL", None)
else:
    os.environ["DATABASE_URL"] = _old_url


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


class AsyncDbAdapter:
    """The route's awaited methods backed by SQLite; no aiosqlite required."""
    def __init__(self, session: Session):
        self.session = session

    def add(self, obj):
        self.session.add(obj)

    def add_all(self, objects):
        self.session.add_all(objects)

    async def flush(self):
        self.session.flush()

    async def commit(self):
        self.session.commit()

    async def execute(self, statement):
        return self.session.execute(statement)


class AirDateTests(unittest.IsolatedAsyncioTestCase):
    async def test_everything_aired_routes_to_metadata(self):
        questions = [
            "show me everything that aired in 2025",
            "show me anything aired in 2025",
            "list all programs aired in 2025",
            "show me shows that aired in 2025",
            "what aired in 2025",
            "what was broadcast in 2025",
        ]
        with self.session() as session:
            db = AsyncDbAdapter(session)
            db.add_all([MediaAsset(id="aired", filename="Aired.mp4",
                                  curator_original_air_date=datetime(2025, 6, 1))])
            await db.commit()
            for question in questions:
                with self.subTest(question=question):
                    self.assertTrue(ai._air_date_intent(question))
                    self.assertEqual(ai._air_date_range(question)[:2],
                                     (datetime(2025, 1, 1), datetime(2026, 1, 1)))
                    with patch.object(ai, "_standalone_question", AsyncMock(side_effect=AssertionError("Semantic retrieval must not run"))):
                        response = await ai.ask_ai(AIQuestion(question=question), db)
                    self.assertEqual([c.media_id for c in response.citations], ["aired"])
                    self.assertIn("original air date", response.answer)

    def test_month_year_and_year_rollover(self):
        self.assertEqual(
            ai._air_date_range("List all assets aired in July 2025")[:2],
            (datetime(2025, 7, 1), datetime(2025, 8, 1)),
        )
        self.assertEqual(
            ai._air_date_range("Show me videos with original air date in December of 2025")[:2],
            (datetime(2025, 12, 1), datetime(2026, 1, 1)),
        )
        self.assertIsNone(ai._air_date_range("Show me videos aired in July"))

    async def asyncSetUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        for table in (MediaAsset.__table__, AIConversation.__table__, AIMessage.__table__):
            table.create(self.engine)
        self.session = sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        self.engine.dispose()

    async def test_july_boundaries_missing_dates_all_matches_and_persistence(self):
        with self.session() as session:
            db = AsyncDbAdapter(session)
            assets = [
                MediaAsset(id=f"j{i}", filename=f"July-{i:02d}.mp4",
                           curator_original_air_date=datetime(2025, 7, 1 if i % 2 else 31, 23, 59))
                for i in range(17)
            ]
            assets += [
                MediaAsset(id="before", filename="Before.mp4", curator_original_air_date=datetime(2025, 6, 30, 23, 59, 59)),
                MediaAsset(id="after", filename="After.mp4", curator_original_air_date=datetime(2025, 8, 1)),
                MediaAsset(id="missing", filename="NoDate.mp4", created_at=datetime(2025, 7, 1),
                           recorded_at=datetime(2025, 7, 2)),
            ]
            db.add_all(assets)
            await db.commit()
            with patch.object(ai, "_standalone_question", AsyncMock(side_effect=AssertionError("LLM rewrite"))), \
                 patch.object(ai, "_run_qa", AsyncMock(side_effect=AssertionError("LLM QA"))), \
                 patch.object(ai, "_library_overview", AsyncMock(side_effect=AssertionError("overview"))), \
                 patch.object(ai, "_keyword_segments", AsyncMock(side_effect=AssertionError("transcripts"))), \
                 patch("app.services.embedding.get_text_embedding", AsyncMock(side_effect=AssertionError("embedding"))), \
                 patch("app.routers.project_chat._visual_segments", AsyncMock(side_effect=AssertionError("visual"))):
                response = await ai.ask_ai(AIQuestion(question="show me all media created in july of 2025"), db)
            self.assertEqual(len(response.citations), 17)
            self.assertEqual({c.media_id for c in response.citations}, {f"j{i}" for i in range(17)})
            self.assertIn("17 asset(s)", response.answer)
            self.assertIn("original air date", response.answer)
            self.assertNotIn("curator_original_air_date", response.answer)
            self.assertNotIn("Before.mp4", response.answer)
            self.assertNotIn("After.mp4", response.answer)
            self.assertNotIn("NoDate.mp4", response.answer)
            self.assertTrue(all("asset-level metadata" in c.snippet for c in response.citations))
            messages = (await db.execute(select(AIMessage).where(
                AIMessage.conversation_id == response.conversation_id
            ).order_by(AIMessage.created_at))).scalars().all()
            self.assertEqual([m.role for m in messages], ["user", "assistant"])
            self.assertEqual(messages[1].content, response.answer)
            self.assertEqual(len(messages[1].citations), 17)
            self.assertEqual(len((await ai.get_conversation_messages(response.conversation_id, db))[1].citations), 17)

    async def test_iso_exact_range_and_single_asset_scope(self):
        with self.session() as session:
            db = AsyncDbAdapter(session)
            db.add_all([
                MediaAsset(id="inside", filename="Inside.mp4", curator_original_air_date=datetime(2025, 7, 31, 14)),
                MediaAsset(id="outside", filename="Outside.mp4", curator_original_air_date=datetime(2025, 8, 1)),
            ])
            await db.commit()
            exact = await ai.ask_ai(AIQuestion(question="Find videos aired on 2025-07-31"), db)
            self.assertEqual([c.media_id for c in exact.citations], ["inside"])
            range_answer = await ai.ask_ai(AIQuestion(
                question="List all videos broadcast between 2025-07-01 and 2025-07-31",
                media_id="outside",
            ), db)
            self.assertEqual(range_answer.citations, [])
            self.assertIn("0 asset(s)", range_answer.answer)
            full = await ai.ask_ai(AIQuestion(
                question="List all videos broadcast between 2025-07-01 and 2025-08-01"
            ), db)
            self.assertEqual({c.media_id for c in full.citations}, {"inside", "outside"})

    async def test_ambiguous_and_ingest_dates_clarify_without_retrieval(self):
        with self.session() as session:
            db = AsyncDbAdapter(session)
            with patch.object(ai, "_standalone_question", AsyncMock(side_effect=AssertionError("rewrite"))), \
                 patch.object(ai, "_run_qa", AsyncMock(side_effect=AssertionError("QA"))), \
                 patch("app.services.embedding.get_text_embedding", AsyncMock(side_effect=AssertionError("embedding"))), \
                 patch("app.routers.project_chat._visual_segments", AsyncMock(side_effect=AssertionError("visual"))):
                for question in (
                    "show me all media created in July",
                    "show me all media uploaded in July 2025",
                    "show me all media ingested in 2025-07-01",
                    "show me all media about faith in July 2025",
                    "show me all media aired on 2025-02-30",
                    "show me all media created last week",
                    "show me all media from last month",
                ):
                    result = await ai.ask_ai(AIQuestion(question=question), db)
                    self.assertIn("Please specify", result.answer)
                    self.assertIsNone(result.citations)
                    stored = (await db.execute(select(AIMessage).where(
                        AIMessage.conversation_id == result.conversation_id,
                        AIMessage.role == "assistant",
                    ))).scalar_one()
                    self.assertEqual(stored.content, result.answer)

    async def test_non_metadata_questions_follow_normal_retrieval(self):
        with self.session() as session:
            db = AsyncDbAdapter(session)
            with patch.object(ai, "_run_qa", AsyncMock(return_value=("Normal search", []))) as qa, \
                 patch.object(ai, "_route_turn", AsyncMock(side_effect=lambda q, h: ("search", q))), \
                 patch.object(ai, "_keyword_segments", AsyncMock(return_value=[])), \
                 patch.object(ai, "_structured_assets", AsyncMock(return_value=[])), \
                 patch.object(ai, "_library_overview", AsyncMock(return_value="")), \
                 patch("app.services.embedding.get_text_embedding", AsyncMock(return_value=None)), \
                 patch("app.routers.project_chat._visual_segments", AsyncMock(return_value=[])):
                for question in (
                    "Who created the world?",
                    "What did May say?",
                    "show clips where they discuss July holidays",
                    "show clips where they discuss July 2025",
                    "show clips created by May",
                ):
                    self.assertFalse(ai._air_date_intent(question), question)
                    result = await ai.ask_ai(AIQuestion(question=question), db)
                    self.assertEqual(result.answer, "Normal search", question)
            self.assertEqual(qa.await_count, 5)

    async def test_scope_without_retrieval_and_date_refinement_after_interruption(self):
        with self.session() as session:
            db = AsyncDbAdapter(session)
            db.add_all([
                MediaAsset(id="july", filename="July.mp4",
                           curator_original_air_date=datetime(2025, 7, 5)),
                MediaAsset(id="sept", filename="September.mp4",
                           curator_original_air_date=datetime(2025, 9, 5)),
                MediaAsset(id="unknown", filename="Unknown.mp4"),
            ])
            await db.commit()
            original = await ai.ask_ai(AIQuestion(question="Show all media aired in July 2025"), db)
            with patch("app.services.llm.generate_response", AsyncMock(side_effect=[
                '{"intent":"conversation","topic":"scope","query":""}',
                '{"intent":"refinement","topic":"other","query":"show all media aired in September 2025"}',
            ])) as router, \
                patch("app.services.embedding.get_text_embedding", AsyncMock(side_effect=AssertionError("embedding"))), \
                patch("app.routers.project_chat._visual_segments", AsyncMock(side_effect=AssertionError("visual"))), \
                patch.object(ai, "_run_qa", AsyncMock(side_effect=AssertionError("retrieval QA"))), \
                patch.object(ai, "_standalone_question", AsyncMock(side_effect=AssertionError("rewrite"))):
                scope = await ai.ask_ai(AIQuestion(
                    question="Are you searching the entire library?", conversation_id=original.conversation_id,
                ), db)
                self.assertIsNone(scope.citations)
                self.assertIn("not the entire Curator catalog", scope.answer)
                self.assertIn("folders do not constrain", scope.answer)
                self.assertIn("excludes assets with unknown dates", scope.answer)
                previous = ai._last_search_question(await ai._conversation_history(db, original.conversation_id))
                self.assertEqual(previous, "Show all media aired in July 2025")
                self.assertEqual(ai._date_refinement("only September", previous),
                                 "Show all media aired in September 2025")
                refined = await ai.ask_ai(AIQuestion(
                    question="only September", conversation_id=original.conversation_id,
                ), db)
                self.assertEqual([c.media_id for c in refined.citations], ["sept"])
                self.assertIn("2025-09-01", refined.answer)
                october = await ai.ask_ai(AIQuestion(
                    question="only October", conversation_id=original.conversation_id,
                ), db)
                self.assertEqual(october.citations, [])
                self.assertIn("2025-10-01", october.answer)
                self.assertEqual(router.await_count, 0)
            stored = await ai.get_conversation_messages(original.conversation_id, db)
            self.assertEqual([m.citations for m in stored if m.role == "assistant"][1], None)
            self.assertEqual([c.media_id for c in stored[-3].citations], ["sept"])
            # An explicit new date search has a distinct empty result set.
            empty = await ai.ask_ai(AIQuestion(
                question="Find videos aired in November 2025", conversation_id=original.conversation_id,
            ), db)
            self.assertEqual(empty.citations, [])
            self.assertEqual((await ai.get_conversation_messages(original.conversation_id, db))[-1].citations, [])

    async def test_structured_router_handles_scope_paraphrase(self):
        with self.session() as session:
            db = AsyncDbAdapter(session)
            with patch("app.services.llm.generate_response", AsyncMock(return_value=
                 '{"intent":"conversation","topic":"scope","query":""}')) as route, \
                 patch("app.services.embedding.get_text_embedding", AsyncMock(side_effect=AssertionError("embedding"))), \
                 patch("app.routers.project_chat._visual_segments", AsyncMock(side_effect=AssertionError("visual"))):
                answer = await ai.ask_ai(AIQuestion(question="Does that include the full collection?"), db)
                self.assertIsNone(answer.citations)
                self.assertIn("not the entire Curator catalog", answer.answer)
                route.assert_awaited_once()
            self.assertEqual(
                await ai._route_turn("Search the entire library for cats", []),
                ("search", "Search the entire library for cats"),
            )

    async def test_router_failure_clarifies_without_searching_conversation(self):
        with self.session() as session:
            db = AsyncDbAdapter(session)
            with patch("app.services.llm.generate_response", AsyncMock(side_effect=RuntimeError("offline"))), \
                 patch("app.services.embedding.get_text_embedding", AsyncMock(side_effect=AssertionError("embedding"))), \
                 patch("app.routers.project_chat._visual_segments", AsyncMock(side_effect=AssertionError("visual"))), \
                 patch.object(ai, "_run_qa", AsyncMock(side_effect=AssertionError("QA"))):
                result = await ai.ask_ai(AIQuestion(question="Does that include the full collection?"), db)
                self.assertIsNone(result.citations)
                self.assertIn("Do you want me to search", result.answer)
                self.assertIsNone((await ai.get_conversation_messages(result.conversation_id, db))[-1].citations)

    async def test_general_conversation_replies_without_retrieval(self):
        with self.session() as session:
            db = AsyncDbAdapter(session)
            with patch("app.services.llm.generate_response", AsyncMock(side_effect=[
                '{"intent":"conversation","topic":"other","query":""}',
                "You're welcome!",
            ])) as llm, \
                 patch("app.services.embedding.get_text_embedding", AsyncMock(side_effect=AssertionError("embedding"))), \
                 patch("app.routers.project_chat._visual_segments", AsyncMock(side_effect=AssertionError("visual"))), \
                 patch.object(ai, "_run_qa", AsyncMock(side_effect=AssertionError("QA"))):
                result = await ai.ask_ai(AIQuestion(question="Thanks for clarifying!"), db)
                self.assertEqual(result.answer, "You're welcome!")
                self.assertIsNone(result.citations)
                self.assertEqual(llm.await_count, 2)
                self.assertIn("No new archive search", ai._CONVERSATION_FAILURE)
                self.assertIsNone((await ai.get_conversation_messages(result.conversation_id, db))[-1].citations)

    async def test_prior_answer_explanation_uses_history_and_grounded_facts(self):
        with self.session() as session:
            db = AsyncDbAdapter(session)
            db.add(MediaAsset(id="one", filename="One.mp4",
                              curator_original_air_date=datetime(2025, 7, 5)))
            await db.commit()
            original = await ai.ask_ai(AIQuestion(question="Show all media aired in July 2025"), db)
            with patch.object(ai, "_route_turn", AsyncMock(return_value=("conversation", "prior"))), \
                 patch("app.services.llm.generate_response", AsyncMock(return_value=
                     "The stored original-air-date filter returned one asset. "
                     "I can't determine from that count whether other assets lack date metadata.")) as llm, \
                 patch("app.services.embedding.get_text_embedding", AsyncMock(side_effect=AssertionError("embedding"))), \
                 patch("app.routers.project_chat._visual_segments", AsyncMock(side_effect=AssertionError("visual"))), \
                 patch.object(ai, "_run_qa", AsyncMock(side_effect=AssertionError("QA"))):
                explained = await ai.ask_ai(AIQuestion(
                    question="Why only 1?", conversation_id=original.conversation_id,
                ), db)
                self.assertIn("lack date metadata", explained.answer)
                self.assertIsNone(explained.citations)
                kwargs = llm.await_args.kwargs
                self.assertIn("unknown dates", kwargs["system"])
                self.assertIn("not necessarily an exhaustive count", kwargs["system"])
                self.assertTrue(any("1 asset(s)" in m["content"] for m in kwargs["history"]))
            with patch.object(ai, "_route_turn", AsyncMock(return_value=("conversation", "other"))), \
                 patch("app.services.llm.generate_response", AsyncMock(side_effect=RuntimeError("offline"))), \
                 patch("app.services.embedding.get_text_embedding", AsyncMock(side_effect=AssertionError("embedding"))):
                failed = await ai.ask_ai(AIQuestion(
                    question="Could you explain more?", conversation_id=original.conversation_id,
                ), db)
                self.assertEqual(failed.answer, ai._CONVERSATION_FAILURE)
                self.assertIsNone(failed.citations)

    async def test_referential_why_how_explanations_route_without_retrieval(self):
        history = [
            {"role": "user", "content": "Show all media aired in July 2025", "searched": None},
            {"role": "assistant", "content": "12 asset(s) with an original air date from 2025-07-01 through 2025-07-31.",
             "searched": True},
        ]
        for question in ("Why only twelve?", "How come so few results?",
                         "Why did you show just 12?", "How was that count decided?",
                         "Can you explain that number?"):
            with self.subTest(question=question), \
                 patch("app.services.llm.generate_response", AsyncMock(side_effect=AssertionError("router LLM"))):
                self.assertEqual(await ai._route_turn(question, history),
                                 ("conversation", "prior"))
        self.assertFalse(ai._prior_explanation_intent("Why did the speaker say that?", history))
        self.assertFalse(ai._prior_explanation_intent("Why only twelve?", []))


if __name__ == "__main__":
    unittest.main()