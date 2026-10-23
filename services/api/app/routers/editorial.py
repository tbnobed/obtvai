"""Shared editorial organization, with private personal desks and collections."""
from datetime import datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, or_, and_, extract, false, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import current_user
from ..database import get_db
from ..models import EditorialRecord, MediaAsset, Project, User

router = APIRouter(prefix="/editorial", tags=["editorial"])


class Rules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str | None = Field(None, max_length=200)
    air_year: int | None = Field(None, ge=1900, le=2200)
    status: str | None = Field(None, max_length=50)
    media_type: Literal["all", "hide_images", "images"] | None = None
    topic: str | None = Field(None, max_length=200)


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    media_id: str = Field(min_length=1, max_length=100)
    start: float | None = Field(None, ge=0, allow_inf_nan=False)
    end: float | None = Field(None, gt=0, allow_inf_nan=False)
    note: str = Field("", max_length=2000)

    @model_validator(mode="after")
    def valid_range(self):
        if (self.start is None) != (self.end is None):
            raise ValueError("Both start and end are required for a timed selection")
        if self.start is not None and self.end <= self.start:
            raise ValueError("End must be later than start")
        return self


class Edit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)
    rules: Rules | None = None
    media_ids: list[str] | None = Field(None, max_length=20000)
    workspace_id: str | None = None
    kind: Literal["manual", "smart"] | None = None
    visibility: Literal["personal", "team"] | None = None
    items: list[Item] | None = Field(None, max_length=2000)


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str | None = None
    workspace_ids: list[str] | None = Field(None, max_length=200)
    favorite_media_ids: list[str] | None = Field(None, max_length=2000)
    saved_project_ids: list[str] | None = Field(None, max_length=2000)


class Recent(BaseModel):
    media_id: str = Field(min_length=1, max_length=100)


def empty_me():
    return dict(workspace_id=None, workspace_ids=[], favorite_media_ids=[],
                saved_project_ids=[], recent_media_ids=[])


async def seed(db):
    first = (await db.execute(insert(EditorialRecord).values(
        id="editorial:initialized", kind="system", owner_id=None, data={}
    ).on_conflict_do_nothing(index_elements=["id"]).returning(EditorialRecord.id))).scalar_one_or_none()
    if first is None:
        return
    for id, name in (("praise", "Praise"), ("stakelbeck", "Stakelbeck")):
        await db.execute(insert(EditorialRecord).values(
            id=id, kind="workspace", owner_id=None,
            data=dict(name=name, description="Shared editorial workspace",
                      rules={"text": name}, media_ids=[]),
        ).on_conflict_do_nothing(index_elements=["id"]))


def visible(row, user):
    return row.kind != "collection" or row.data.get("visibility") == "team" or row.owner_id == user.id


def out(row):
    return {**row.data, "id": row.id, "created_by": row.owner_id}


async def load(db, id, kind, user, lock=False):
    q = select(EditorialRecord).where(EditorialRecord.id == id, EditorialRecord.kind == kind)
    if lock:
        q = q.with_for_update()
    row = (await db.execute(q)).scalar_one_or_none()
    if row is None or not visible(row, user):
        raise HTTPException(404, "Editorial item not found")
    return row


def writable(user):
    if user.role == "viewer":
        raise HTTPException(403, "Viewer accounts cannot edit shared organization")


async def validate_ids(db, ids, model):
    if not ids:
        return
    found = set((await db.execute(select(model.id).where(model.id.in_(ids)))).scalars())
    if set(ids) - found:
        raise HTTPException(422, "One or more referenced assets or projects no longer exist")


async def me_row(db, user):
    id = "desk:" + user.id
    await db.execute(insert(EditorialRecord).values(
        id=id, kind="desk", owner_id=user.id, data=empty_me()
    ).on_conflict_do_nothing(index_elements=["id"]))
    return (await db.execute(select(EditorialRecord).where(EditorialRecord.id == id).with_for_update())).scalar_one()


@router.get("/state")
async def state(db: AsyncSession = Depends(get_db), user: User = Depends(current_user)):
    await seed(db)
    records = (await db.execute(select(EditorialRecord).where(EditorialRecord.kind.in_(["workspace", "collection"])))).scalars().all()
    me = await me_row(db, user)
    result = dict(workspaces=[out(r) for r in records if r.kind == "workspace"],
                  collections=[out(r) for r in records if r.kind == "collection" and visible(r, user)],
                  me={**empty_me(), **me.data})
    await db.commit()
    return result


@router.get("/me")
async def get_me(db: AsyncSession = Depends(get_db), user: User = Depends(current_user)):
    row = await me_row(db, user)
    result = {**empty_me(), **row.data}
    await db.commit()
    return result


@router.patch("/me")
async def patch_me(body: Preferences, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)):
    data = body.model_dump(exclude_unset=True)
    for key in ("workspace_ids", "favorite_media_ids", "saved_project_ids"):
        if key in data and data[key] is None:
            raise HTTPException(422, f"{key} must be an array")
    for id in ([data["workspace_id"]] if data.get("workspace_id") else []) + data.get("workspace_ids", []):
        await load(db, id, "workspace", user)
    await validate_ids(db, data.get("favorite_media_ids", []), MediaAsset)
    await validate_ids(db, data.get("saved_project_ids", []), Project)
    row = await me_row(db, user)
    row.data = {**empty_me(), **row.data, **data}
    await db.commit()
    return row.data


@router.post("/recent", status_code=204)
async def recent(body: Recent, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)):
    await validate_ids(db, [body.media_id], MediaAsset)
    row = await me_row(db, user)
    ids = [body.media_id] + [id for id in row.data.get("recent_media_ids", []) if id != body.media_id]
    row.data = {**empty_me(), **row.data, "recent_media_ids": ids[:30]}
    await db.commit()
    return Response(status_code=204)


async def save_record(kind, body, db, user, id=None):
    writable(user)
    row = await load(db, id, kind, user, lock=True) if id else None
    patch = body.model_dump(exclude_unset=True)
    allowed = {"name", "description", "rules", "media_ids"} if kind == "workspace" else {
        "name", "description", "rules", "workspace_id", "kind", "visibility", "items"}
    if patch.keys() - allowed:
        raise HTTPException(422, "Unsupported fields for this item")
    defaults = dict(name="", description="", rules={})
    if kind == "workspace":
        defaults.update(media_ids=[])
    else:
        defaults.update(workspace_id=None, kind="manual", visibility="personal", items=[])
    data = {**defaults, **(row.data if row else {}), **patch}
    if not (data.get("name") or "").strip():
        raise HTTPException(422, "Name is required")
    data["name"] = data["name"].strip()
    for key in allowed - {"workspace_id"}:
        if data.get(key) is None:
            raise HTTPException(422, f"{key} cannot be null")
    if kind == "workspace":
        data["media_ids"] = list(dict.fromkeys(data["media_ids"]))
        await validate_ids(db, data["media_ids"], MediaAsset)
    else:
        if data.get("workspace_id"):
            await load(db, data["workspace_id"], "workspace", user)
        data["items"] = [Item(**i).model_dump() for i in data["items"]]
        if len({i["id"] for i in data["items"]}) != len(data["items"]):
            raise HTTPException(422, "Duplicate selection IDs")
        await validate_ids(db, [i["media_id"] for i in data["items"]], MediaAsset)
        # Privacy cannot be changed by a collaborator on somebody else's collection.
        if row and data["visibility"] != row.data["visibility"] and row.owner_id != user.id:
            raise HTTPException(403, "Only the creator can change collection visibility")
        timed = [i for i in data["items"] if i["end"] is not None]
        if timed:
            durations = dict((await db.execute(select(MediaAsset.id, MediaAsset.duration_seconds).where(
                MediaAsset.id.in_([i["media_id"] for i in timed])))).all())
            if any(durations[i["media_id"]] is not None and i["end"] > durations[i["media_id"]] for i in timed):
                raise HTTPException(422, "Selection extends beyond the asset duration")
    if row:
        row.data = data
    else:
        row = EditorialRecord(id=str(uuid4()), kind=kind, owner_id=user.id, data=data)
        db.add(row)
    await db.commit()
    return out(row)


@router.post("/workspaces")
async def create_workspace(body: Edit, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)):
    return await save_record("workspace", body, db, user)


@router.patch("/workspaces/{id}")
async def edit_workspace(id: str, body: Edit, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)):
    return await save_record("workspace", body, db, user, id)


@router.post("/collections")
async def create_collection(body: Edit, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)):
    return await save_record("collection", body, db, user)


@router.patch("/collections/{id}")
async def edit_collection(id: str, body: Edit, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)):
    return await save_record("collection", body, db, user, id)


@router.delete("/collections/{id}", status_code=204)
async def delete_collection(id: str, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)):
    writable(user)
    row = await load(db, id, "collection", user, lock=True)
    if row.owner_id != user.id and user.role != "admin":
        raise HTTPException(403, "Only the creator or an administrator can delete this collection")
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)


@router.delete("/workspaces/{id}", status_code=204)
async def delete_workspace(id: str, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)):
    writable(user)
    row = await load(db, id, "workspace", user, lock=True)
    if row.owner_id != user.id and user.role != "admin":
        raise HTTPException(403, "Only the creator or an administrator can delete this workspace")
    # Preserve collections and their selections when their workspace is removed.
    others = (await db.execute(select(EditorialRecord).where(
        EditorialRecord.kind.in_(["collection", "desk"])).with_for_update())).scalars()
    for r in others:
        d = dict(r.data)
        if d.get("workspace_id") == id:
            d["workspace_id"] = None
        if "workspace_ids" in d:
            d["workspace_ids"] = [x for x in d["workspace_ids"] if x != id]
        r.data = d
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)


def rule_condition(rules, empty_matches=False):
    clauses = []
    if (value := (rules.get("text") or "").strip()):
        # Literal substring, not SQL wildcard input.
        needle = "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        clauses.append(or_(*[c.ilike(needle, escape="\\") for c in (
            MediaAsset.filename, MediaAsset.original_path, MediaAsset.curator_folder_path)]))
    if rules.get("air_year"):
        clauses.append(extract("year", MediaAsset.curator_original_air_date) == rules["air_year"])
    if rules.get("status"):
        clauses.append(MediaAsset.status == rules["status"])
    if rules.get("topic"):
        clauses.append(MediaAsset.topics.contains([rules["topic"]]))
    if rules.get("media_type") in ("images", "hide_images"):
        from ..media_filter import image_asset_condition
        from ..catalog_models import CatalogAsset
        condition = image_asset_condition(MediaAsset, CatalogAsset)
        clauses.append(condition if rules["media_type"] == "images" else ~condition)
    return and_(*clauses) if clauses else (MediaAsset.id.is_not(None) if empty_matches else false())


async def resolve_scope(db, user, workspace_id=None, collection_id=None):
    """Explicit selections override team auto-rules; empty is never global."""
    workspace = await load(db, workspace_id, "workspace", user) if workspace_id else None
    collection = await load(db, collection_id, "collection", user) if collection_id else None
    if collection and collection.data.get("workspace_id"):
        if workspace and collection.data["workspace_id"] != workspace.id:
            raise HTTPException(422, "Collection belongs to a different workspace")
        workspace = await load(db, collection.data["workspace_id"], "workspace", user)
    if not workspace and not collection:
        return None, []
    if collection and collection.data["kind"] == "manual":
        items = collection.data["items"]
        ids = list(dict.fromkeys(i["media_id"] for i in items))
        found = list((await db.execute(select(MediaAsset.id).where(MediaAsset.id.in_(ids)))).scalars()) if ids else []
        return found, [i for i in items if i["media_id"] in set(found)]
    q = select(MediaAsset.id)
    if workspace:
        d = workspace.data
        q = q.where(or_(MediaAsset.id.in_(d.get("media_ids", [])), rule_condition(d.get("rules", {}))))
    if collection:
        q = q.where(rule_condition(collection.data["rules"], empty_matches=True))
    return list((await db.execute(q)).scalars()), []


@router.get("/scope")
async def scope(workspace_id: str | None = None, collection_id: str | None = None,
                db: AsyncSession = Depends(get_db), user: User = Depends(current_user)):
    ids, items = await resolve_scope(db, user, workspace_id, collection_id)
    return {"media_ids": ids, "items": items}
