"""Session auth: opaque HttpOnly cookie -> sessions table, enforced by ASGI
middleware on every /api request (router dependencies would miss the
StaticFiles thumbnail mount).

Roles: admin (everything), user (everything except user management),
viewer (read-only + explicitly allowlisted read-style POSTs like semantic
search and AI Q&A).

The watcher authenticates with X-Internal-Token (INTERNAL_API_TOKEN env)
instead of a cookie.
"""
import hashlib
import secrets
from datetime import datetime, timedelta

import bcrypt
from fastapi import HTTPException, Request
from sqlalchemy import delete, select

from .config import settings
from .database import AsyncSessionLocal
from .models import User, UserSession

COOKIE_NAME = "obtv_session"
SESSION_TTL = timedelta(days=30)
LAST_SEEN_THROTTLE = timedelta(minutes=5)

ROLES = ("admin", "user", "viewer")

# No auth at all.
PUBLIC_PATHS = {"/api/auth/login", "/api/healthz"}

# Read-style POSTs a viewer may use (exact match unless noted).
VIEWER_POST_ALLOWLIST = {
    "/api/search",
    "/api/search/script-match",
    "/api/ai/ask",
    "/api/socials/insights",
    "/api/auth/logout",
    "/api/auth/password",
}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


async def create_session(db, user_id: str, token: str) -> None:
    now = datetime.utcnow()
    db.add(UserSession(
        token_hash=_token_hash(token),
        user_id=user_id,
        created_at=now,
        expires_at=now + SESSION_TTL,
        last_seen=now,
    ))
    # Opportunistic prune of expired sessions.
    await db.execute(delete(UserSession).where(UserSession.expires_at < now))


async def delete_session(db, token: str) -> None:
    await db.execute(delete(UserSession).where(UserSession.token_hash == _token_hash(token)))


async def delete_user_sessions(db, user_id: str, keep_token: str | None = None) -> None:
    q = delete(UserSession).where(UserSession.user_id == user_id)
    if keep_token:
        q = q.where(UserSession.token_hash != _token_hash(keep_token))
    await db.execute(q)


def set_session_cookie(response, token: str | None) -> None:
    if token:
        response.set_cookie(
            COOKIE_NAME, token,
            max_age=int(SESSION_TTL.total_seconds()),
            httponly=True, samesite="lax", path="/",
            # NOT Secure: production nginx serves plain HTTP on the LAN.
        )
    else:
        response.delete_cookie(COOKIE_NAME, path="/")


async def _resolve_user(token: str):
    """Return the (user, session) for a valid, unexpired session else None."""
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(User, UserSession)
            .join(UserSession, UserSession.user_id == User.id)
            .where(UserSession.token_hash == _token_hash(token))
        )).first()
        if not row:
            return None
        user, session = row
        if session.expires_at < now or user.disabled:
            return None
        if now - (session.last_seen or session.created_at) > LAST_SEEN_THROTTLE:
            session.last_seen = now
            await db.commit()
        return user


def _viewer_may(method: str, path: str) -> bool:
    if method in ("GET", "HEAD", "OPTIONS"):
        return True
    if method == "POST":
        if path in VIEWER_POST_ALLOWLIST:
            return True
        if path == "/api/ai/conversations" or path.startswith("/api/ai/conversations/"):
            return True
    return False


async def auth_middleware(request: Request, call_next):
    path = request.url.path.rstrip("/") or "/"
    if not path.startswith("/api") or path in PUBLIC_PATHS or request.method == "OPTIONS":
        return await call_next(request)

    # Internal services (watcher) authenticate with a shared token.
    internal = request.headers.get("x-internal-token")
    if internal and settings.internal_api_token and secrets.compare_digest(internal, settings.internal_api_token):
        request.state.user = None
        return await call_next(request)

    from fastapi.responses import JSONResponse

    token = request.cookies.get(COOKIE_NAME)
    user = await _resolve_user(token) if token else None
    if user is None:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    request.state.user = user

    if path == "/api/users" or path.startswith("/api/users/"):
        if user.role != "admin":
            return JSONResponse({"detail": "Admin only"}, status_code=403)
    elif user.role == "viewer" and not _viewer_may(request.method, path):
        return JSONResponse(
            {"detail": "View-only account — ask an admin for edit access"},
            status_code=403,
        )

    return await call_next(request)


def current_user(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if user is None:
        # Internal-token calls have no user; user-facing routers below never
        # run for them in practice (watcher only posts /media), but guard anyway.
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(request: Request) -> User:
    user = current_user(request)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user
