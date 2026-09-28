"""Citations in library Q&A must identify existing evidence, not retrieved noise."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.routers import ai
from app.schemas import AICitationOut


def asset(id="asset-1", filename="Faith.mp4", synopsis="Faith in the community", topics=None):
    return SimpleNamespace(id=id, filename=filename, synopsis=synopsis, topics=topics or ["Faith"])


class CitationTests(unittest.IsolatedAsyncioTestCase):
    async def test_structured_lookup_uses_database_assets_and_literal_filter(self):
        db = AsyncMock()
        db.execute.return_value = Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[asset()]))))
        self.assertEqual([a.id for a in await ai._structured_assets(db, "Show me videos about faith?")], ["asset-1"])
        statement = db.execute.call_args.args[0]
        compiled = statement.compile()
        self.assertIn("media_assets.synopsis", str(compiled))
        self.assertIn("media_assets.topics", str(compiled))
        self.assertIn("%faith%", compiled.params.values())
        db.execute.reset_mock()
        self.assertEqual(await ai._structured_assets(db, "How many videos about faith?"), [])
        self.assertEqual(await ai._structured_assets(db, "Find videos about faith and 2025"), [])
        db.execute.assert_not_awaited()

    async def test_metadata_answer_cites_named_asset_without_transcript(self):
        db = AsyncMock()
        fake = asset()
        with patch.object(ai, "_speaker_names", AsyncMock(return_value={})), \
             patch("app.services.web_search.generate_with_web",
                   AsyncMock(return_value="Faith.mp4 is about the community.")):
            answer, citations = await ai._run_qa(
                "Find videos about faith", [], db, asset_matches=[fake],
            )
        self.assertIn(fake.filename, answer)
        self.assertEqual([(c.media_id, c.start_time, c.end_time) for c in citations],
                         [("asset-1", 0, 0)])

    async def test_aggregate_answer_does_not_cite_unrelated_evidence(self):
        db = AsyncMock()
        seg = SimpleNamespace(start_time=5, end_time=9, text="faith", speaker=None)
        with patch.object(ai, "_speaker_names", AsyncMock(return_value={})), \
             patch("app.services.web_search.generate_with_web",
                   AsyncMock(return_value="There are 20 assets in the library.")):
            _, citations = await ai._run_qa(
                "How many assets?", [(seg, asset())], db, overview="Total assets: 20",
            )
        self.assertEqual(citations, [])

    async def test_visual_evidence_cites_existing_scene_window(self):
        db = AsyncMock()
        scene = AICitationOut(
            media_id="scene-asset", filename="Concert.mp4",
            start_time=30, end_time=45, snippet="Visual scene match: concert",
        )
        with patch.object(ai, "_speaker_names", AsyncMock(return_value={})), \
             patch("app.services.web_search.generate_with_web",
                   AsyncMock(return_value="Concert.mp4 shows a performance.")):
            _, citations = await ai._run_qa(
                "Find the concert", [], db,
                visual_lines=["- [Concert.mp4] performance at 0:30-0:45"],
                visual_citations=[scene],
            )
        self.assertEqual(citations, [scene])

    def test_reference_filter_deduplicates_assets(self):
        citations = [AICitationOut(media_id="1", filename="One.mp4",
                                   start_time=i, end_time=i + 1) for i in (2, 4)]
        self.assertEqual(ai._referenced_citations("One.mp4 appears", citations), citations[:1])
        self.assertEqual(ai._referenced_citations("Overall themes are broad.", citations), [])

    def test_reference_filter_does_not_confuse_overlapping_names(self):
        short = AICitationOut(media_id="short", filename="Clip.mp4",
                              start_time=1, end_time=2)
        long = AICitationOut(media_id="long", filename="LongClip.mp4",
                             start_time=3, end_time=4)
        dashed = AICitationOut(media_id="dash", filename="Other-Clip.mp4",
                               start_time=5, end_time=6)
        self.assertEqual(
            ai._referenced_citations('See "LongClip.mp4" and (Other-Clip.mp4).',
                                     [short, long, dashed]),
            [long, dashed],
        )
        self.assertEqual(
            ai._referenced_citations("Look at /archive/Clip.mp4", [short]),
            [short],
        )