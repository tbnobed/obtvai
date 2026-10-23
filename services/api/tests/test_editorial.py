"""Editorial organization safety tests; no network, GPU or live DB calls."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from app.routers import editorial as e
from app.auth import _viewer_may


def record(id="w", kind="workspace", owner="u", **data):
    defaults = {"name": "Test", "description": "", "rules": {}, "media_ids": []} if kind == "workspace" else {
        "name": "Test", "description": "", "rules": {}, "items": [],
        "visibility": "team", "kind": "manual", "workspace_id": None,
    }
    return NS(id=id, kind=kind, owner_id=owner, data={**defaults, **data})


def db_with_rows(rows):
    result = Mock()
    result.scalars.return_value = rows
    db = NS(execute=AsyncMock(return_value=result), commit=AsyncMock(), add=Mock(), delete=AsyncMock())
    return db


class ValidationTests(unittest.TestCase):
    def test_invalid_ranges(self):
        for start, end in [(0, None), (None, 5), (4, 4), (5, 2), (-1, 4), (0, float("inf")), (float("nan"), 4)]:
            with self.subTest(start=start, end=end), self.assertRaises(ValidationError):
                e.Item(id="i", media_id="a", start=start, end=end)

    def test_whole_asset_and_timed_selection(self):
        self.assertIsNone(e.Item(id="i", media_id="a").start)
        self.assertEqual(e.Item(id="i", media_id="a", start=0, end=2).end, 2)

    def test_original_air_date_not_ingest_date(self):
        sql = str(e.rule_condition({"air_year": 2026}).compile(dialect=postgresql.dialect()))
        self.assertIn("curator_original_air_date", sql)
        self.assertNotIn("created_at", sql)

    def test_text_escapes_sql_wildcards(self):
        params = e.rule_condition({"text": "100%_test"}).compile(dialect=postgresql.dialect()).params
        self.assertIn("%100\\%\\_test%", params.values())

    def test_empty_workspace_does_not_match_entire_library(self):
        self.assertEqual(str(e.rule_condition({})), "false")
        self.assertNotEqual(str(e.rule_condition({}, empty_matches=True)), "false")

    def test_personal_collection_never_visible_to_another_user(self):
        row = record(kind="collection", visibility="personal")
        self.assertTrue(e.visible(row, NS(id="u")))
        self.assertFalse(e.visible(row, NS(id="other")))

    def test_viewers_can_manage_desk_but_not_shared_records(self):
        self.assertTrue(_viewer_may("PATCH", "/api/editorial/me"))
        self.assertTrue(_viewer_may("POST", "/api/editorial/recent"))
        self.assertFalse(_viewer_may("POST", "/api/editorial/workspaces"))
        with self.assertRaises(HTTPException):
            e.writable(NS(role="viewer"))

    def test_unknown_rule_and_bad_year_are_rejected(self):
        for data in ({"air_year": 0}, {"air_year": 2026.5}, {"surprise": True}):
            with self.assertRaises(ValidationError):
                e.Rules(**data)


class ScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_library_is_null_not_empty(self):
        self.assertEqual(await e.resolve_scope(None, NS(id="u")), (None, []))

    async def test_empty_manual_collection_stays_empty(self):
        with patch.object(e, "load", AsyncMock(return_value=record(kind="collection"))):
            self.assertEqual(await e.resolve_scope(None, NS(id="u"), collection_id="c"), ([], []))

    async def test_explicit_manual_selection_can_cross_workspace_rules(self):
        item = dict(id="i", media_id="foreign", start=2, end=9, note="select")
        db = db_with_rows(["foreign"])
        rows = [record(rules={"text": "Praise"}), record(kind="collection", workspace_id="w", items=[item])]
        with patch.object(e, "load", AsyncMock(side_effect=rows + [rows[0]])):
            ids, items = await e.resolve_scope(db, NS(id="u"), "w", "c")
        self.assertEqual(ids, ["foreign"])
        self.assertEqual(items, [item])

    async def test_mismatched_workspace_rejected(self):
        with patch.object(e, "load", AsyncMock(side_effect=[
            record(), record(kind="collection", workspace_id="different")
        ])), self.assertRaises(HTTPException) as ctx:
            await e.resolve_scope(None, NS(id="u"), "w", "c")
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_deleted_manual_media_is_not_returned(self):
        item = dict(id="i", media_id="deleted", start=None, end=None, note="")
        with patch.object(e, "load", AsyncMock(return_value=record(kind="collection", items=[item]))):
            self.assertEqual(await e.resolve_scope(db_with_rows([]), NS(id="u"), collection_id="c"), ([], []))

    async def test_smart_collection_intersects_workspace(self):
        db = db_with_rows(["match"])
        smart = record(kind="collection", rules={"air_year": 2026})
        smart.data["kind"] = "smart"
        with patch.object(e, "load", AsyncMock(side_effect=[
            record(rules={"text": "Praise"}), smart
        ])):
            ids, _ = await e.resolve_scope(db, NS(id="u"), "w", "c")
        self.assertEqual(ids, ["match"])
        sql = str(db.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
        self.assertIn("AND", sql)
        self.assertIn("curator_original_air_date", sql)

    async def test_private_load_is_404_even_for_admin(self):
        db = db_with_rows([])
        db.execute.return_value.scalar_one_or_none.return_value = record(kind="collection", visibility="personal")
        with self.assertRaises(HTTPException) as ctx:
            await e.load(db, "c", "collection", NS(id="other", role="admin"))
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_server_derives_owner_and_rejects_injected_fields(self):
        with self.assertRaises(ValidationError):
            e.Edit(name="Name", created_by="other")
        db = db_with_rows([])
        with patch.object(e, "validate_ids", AsyncMock()):
            output = await e.save_record("workspace", e.Edit(name=" Name "), db, NS(id="u", role="user"))
        self.assertEqual(output["created_by"], "u")
        self.assertEqual(output["name"], "Name")
        db.commit.assert_awaited_once()

    async def test_null_required_data_rejected(self):
        for body in (e.Edit(name="Name", media_ids=None), e.Edit(name="Name", rules=None)):
            with self.assertRaises(HTTPException):
                await e.save_record("workspace", body, db_with_rows([]), NS(id="u", role="user"))

    async def test_whole_asset_item_defaults_survive_partial_body_dump(self):
        body = e.Edit(name="Selects", items=[e.Item(id="i", media_id="a")])
        with patch.object(e, "validate_ids", AsyncMock()):
            output = await e.save_record("collection", body, db_with_rows([]), NS(id="u", role="user"))
        self.assertEqual(output["items"], [dict(id="i", media_id="a", start=None, end=None, note="")])

    async def test_invalid_visibility_change_rejected(self):
        row = record(kind="collection", owner="other")
        with patch.object(e, "load", AsyncMock(return_value=row)), patch.object(e, "validate_ids", AsyncMock()):
            with self.assertRaises(HTTPException) as ctx:
                await e.save_record("collection", e.Edit(visibility="personal"), db_with_rows([]), NS(id="u", role="user"), "c")
            self.assertEqual(ctx.exception.status_code, 403)

    async def test_workspace_delete_preserves_collections_and_clears_default(self):
        col = record(kind="collection", workspace_id="w", items=[{"id":"i","media_id":"a"}])
        desk = NS(data={"workspace_id":"w","workspace_ids":["w","other"]})
        db = db_with_rows([col, desk])
        row = record()
        with patch.object(e, "load", AsyncMock(return_value=row)):
            await e.delete_workspace("w", db, NS(id="u", role="user"))
        self.assertIsNone(col.data["workspace_id"])
        self.assertEqual(col.data["items"][0]["media_id"], "a")
        self.assertIsNone(desk.data["workspace_id"])
        self.assertEqual(desk.data["workspace_ids"], ["other"])
        db.delete.assert_awaited_once_with(row)


if __name__ == "__main__":
    unittest.main()
