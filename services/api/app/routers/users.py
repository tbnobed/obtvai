from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import delete_user_sessions, hash_password, require_admin
from ..database import get_db
from ..models import User, UserSession
from ..schemas import UserCreateIn, UserOut, UserUpdateIn

router = APIRouter(prefix="/users", tags=["users"])


async def _last_seen_map(db: AsyncSession) -> dict[str, object]:
    rows = (await db.execute(
        select(UserSession.user_id, func.max(UserSession.last_seen)).group_by(UserSession.user_id)
    )).all()
    return {user_id: seen for user_id, seen in rows}


def _out(u: User, last_seen=None) -> UserOut:
    return UserOut(
        id=u.id, username=u.username, display_name=u.display_name,
        role=u.role, disabled=u.disabled, created_at=u.created_at, last_seen=last_seen,
    )


async def _active_admin_count(db: AsyncSession) -> int:
    return (await db.execute(
        select(func.count()).select_from(User).where(User.role == "admin", User.disabled == False)  # noqa: E712
    )).scalar_one()


@router.get("", response_model=list[UserOut])
async def list_users(request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    users = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    seen = await _last_seen_map(db)
    return [_out(u, seen.get(u.id)) for u in users]


@router.post("", response_model=UserOut, status_code=201)
async def create_user(body: UserCreateIn, request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    username = body.username.strip().lower()
    existing = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")
    user = User(
        username=username,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role=body.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _out(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: str, body: UserUpdateIn, request: Request, db: AsyncSession = Depends(get_db)):
    me = require_admin(request)
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    demoting = body.role is not None and body.role != "admin" and user.role == "admin"
    disabling = body.disabled is True and not user.disabled
    if (demoting or disabling) and user.role == "admin" and not user.disabled:
        if await _active_admin_count(db) <= 1:
            raise HTTPException(status_code=400, detail="Cannot demote or disable the last admin")
    if me.id == user.id and body.disabled is True:
        raise HTTPException(status_code=400, detail="Cannot disable your own account")

    if body.role is not None:
        user.role = body.role
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.disabled is not None:
        user.disabled = body.disabled
    if body.password is not None:
        user.password_hash = hash_password(body.password)
        await delete_user_sessions(db, user.id)
    if user.disabled:
        await delete_user_sessions(db, user.id)
    await db.commit()
    await db.refresh(user)
    seen = await _last_seen_map(db)
    return _out(user, seen.get(user.id))


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    me = require_admin(request)
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if me.id == user.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    if user.role == "admin" and not user.disabled and await _active_admin_count(db) <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last admin")
    await db.delete(user)
    await db.commit()
