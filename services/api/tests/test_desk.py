"""Bounded production desk queries and atomic mutations; no live DB."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, AsyncMock, patch
from sqlalchemy.dialects import postgresql
from app.routers import editorial as e
from app.auth import _viewer_may


class DeskTests(unittest.IsolatedAsyncioTestCase):
    async def test_queries_page_in_sql_and_never_select_collection_contents(self):
        result = Mock()
        result.scalar_one.return_value = 600
        result.mappings.return_value.all.return_value = []
        db = NS(execute=AsyncMock(return_value=result))
        await e.desk_items("collections", q="100%_test", workspace_id=None, air_year=None,
                          topic=None, visibility="all", sort="recent", offset=50, limit=25, db=db, user=NS(id="u"))
        statements = [call.args[0].compile(dialect=postgresql.dialect()) for call in db.execute.call_args_list]
        sql = str(statements[-1])
        self.assertIn("LIMIT", sql)
        self.assertIn("OFFSET", sql)
        self.assertIn("owner_id", sql)
        self.assertNotIn("editorial_records.data,", sql)
        self.assertIn("%100\\%\\_test%", statements[-1].params.values())
        self.assertIn(25, statements[-1].params.values())
        self.assertIn(50, statements[-1].params.values())

    async def test_favorite_query_orders_saved_ids_and_uses_air_date(self):
        desk=Mock()
        desk.scalar_one_or_none.return_value={"favorite_media_ids":["older","newer"]}
        count=Mock();count.scalar_one.return_value=1
        page=Mock();page.mappings.return_value.all.return_value=[{"id":"newer","title":"New"}]
        db=NS(execute=AsyncMock(side_effect=[desk,count,page]))
        value=await e.desk_items("favorites", q="", workspace_id=None, air_year=2026,
                               topic=None, visibility="all", sort="recent", offset=0, limit=12,db=db,user=NS(id="u"))
        self.assertEqual(value["total"],1)
        compiled=db.execute.call_args_list[-1].args[0].compile(dialect=postgresql.dialect())
        self.assertIn("curator_original_air_date",str(compiled))
        self.assertIn("CASE",str(compiled))
        self.assertIn(12,compiled.params.values())

    async def test_empty_saved_list_never_expands_to_all_assets(self):
        result=Mock();result.scalar_one_or_none.return_value={}
        db=NS(execute=AsyncMock(return_value=result))
        result=await e.desk_items("favorites",q="",workspace_id=None,air_year=None,topic=None,
                                  visibility="all",sort="recent",offset=0,limit=50,db=db,user=NS(id="u"))
        self.assertEqual(result["items"],[])
        db.execute.assert_awaited_once()

    async def test_bulk_remove_preserves_unrelated_favorites(self):
        row=NS(data={"favorite_media_ids":["a","b","c"]})
        db=NS(commit=AsyncMock())
        with patch.object(e,"me_row",AsyncMock(return_value=row)):
            result=await e.change_favorites(e.FavoriteChange(ids=["b"],operation="remove"),db,NS(id="u"))
        self.assertEqual(result["favorite_media_ids"],["a","c"])
        self.assertTrue(_viewer_may("POST","/api/editorial/favorites"))

    async def test_append_locks_deduplicates_and_keeps_timed_selections(self):
        row=NS(id="c",owner_id="u",data={"kind":"manual","items":[
            {"id":"whole","media_id":"a","start":None,"end":None},
            {"id":"timed","media_id":"b","start":1,"end":3}]})
        with patch.object(e,"load",AsyncMock(return_value=row)) as load, patch.object(e,"validate_ids",AsyncMock()):
            result=await e.append_assets("c",e.CollectionAssets(media_ids=["a","b","b"]),
                                         NS(commit=AsyncMock()),NS(id="u",role="user"))
        self.assertEqual(len(result["items"]),3)
        self.assertTrue(load.call_args.kwargs["lock"])


if __name__=="__main__":
    unittest.main()
