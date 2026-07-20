from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import (
    COOKIE_NAME,
    create_session,
    current_user,
    delete_session,
    delete_user_sessions,
    hash_password,
    new_session_token,
    set_session_cookie,
    verify_password,
)
from ..database import get_db
from ..models import User, UserSession
from ..schemas import LoginIn, PasswordChangeIn, SessionUserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _session_user(u: User) -> SessionUserOut:
    return SessionUserOut(id=u.id, username=u.username, display_name=u.display_name, role=u.role)


@router.post("/login", response_model=SessionUserOut)
async def login(body: LoginIn, response: Response, db: AsyncSession = Depends(get_db)):
    username = body.username.strip().lower()
    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    # Verify against a constant dummy hash when the user is unknown so the
    # response time does not reveal which usernames exist.
    dummy = "$2b$12$C6UzMDM.H6dfI/f/IKcEeO7ZBpTd/O0iBLW6dB2Sy0YO5FeSNr8B2"
    ok = verify_password(body.password, user.password_hash if user else dummy)
    if not user or not ok or user.disabled:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = new_session_token()
    await create_session(db, user.id, token)
    await db.commit()
    set_session_cookie(response, token)
    return _session_user(user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        await delete_session(db, token)
        await db.commit()
    set_session_cookie(response, None)


@router.get("/me", response_model=SessionUserOut)
async def me(request: Request):
    return _session_user(current_user(request))


@router.post("/password", status_code=204)
async def change_password(body: PasswordChangeIn, request: Request, db: AsyncSession = Depends(get_db)):
    user = current_user(request)
    db_user = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
    if not verify_password(body.current_password, db_user.password_hash):
        raise HTTPException(status_code=401, detail="Current password incorrect")
    db_user.password_hash = hash_password(body.new_password)
    # Keep this session, kill any others.
    await delete_user_sessions(db, db_user.id, keep_token=request.cookies.get(COOKIE_NAME))
    await db.commit()
