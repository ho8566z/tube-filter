"""FNC-U-003/004: signed-cookie identity and CSRF/session enforcement."""

import secrets

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.db import get_db
from app.errors import DomainError, domain_error_handler
from app.models import AppUser
from app.users.service import hash_password, password_matches

router = APIRouter(prefix="/api/v1/auth")
SESSION_SECONDS = 24 * 60 * 60
# Use the same bcrypt path for missing users, without storing any submitted value.
DUMMY_HASH = hash_password(secrets.token_hex(16))


class Login(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    loginId: str
    password: SecretStr


def current_user(request, db):
    identity = request.session.get("user")
    if not identity:
        return None
    user = db.get(AppUser, identity["id"])
    # Creation time prevents a deleted SQLite row ID from reviving an old cookie.
    if user is None or user.created_at.isoformat() != identity["createdAt"]:
        request.session.clear()
        return None
    return user


@router.get("/csrf")
def csrf(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    token = request.session.setdefault("csrf", secrets.token_urlsafe(32))
    return {"csrfToken": token}


@router.post("/login")
def login(body: Login, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(AppUser).where(AppUser.login_id == body.loginId.lower()))
    matches = password_matches(
        body.password.get_secret_value(), user.password if user else DUMMY_HASH
    )
    if user is None or not matches:
        raise DomainError(
            "LOGIN_FAILED", "아이디 또는 비밀번호가 올바르지 않습니다.", 401
        )
    user.last_login_at = request.app.state.clock()
    db.commit()
    request.session.clear()
    request.session.update(
        {
            "user": {"id": user.id, "createdAt": user.created_at.isoformat()},
            "csrf": secrets.token_urlsafe(32),
            "activeAt": request.app.state.clock().timestamp(),
        }
    )
    return {"loginId": user.login_id}


@router.post("/logout", status_code=204)
def logout(request: Request):
    request.session.clear()
    return Response(status_code=204)


class SecurityMiddleware:
    """Load settings after lifespan startup, then use Starlette's signed cookies."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        settings = scope["app"].state.settings
        sessions = SessionMiddleware(
            self.enforce,
            secret_key=settings.session_secret.get_secret_value(),
            session_cookie="TF_SESSION",
            max_age=SESSION_SECONDS,
            same_site="lax",
            https_only=scope["scheme"] == "https",
        )
        await sessions(scope, receive, send)

    async def enforce(self, scope, receive, send):
        request = Request(scope)
        now = request.app.state.clock()
        active = request.session.get("activeAt")
        if active is not None and now.timestamp() - active >= SESSION_SECONDS:
            request.session.clear()
        if request.session:
            request.session["activeAt"] = now.timestamp()
        path = request.url.path
        try:
            request.app.state.limiter.check_request(
                request.client.host if request.client else "unknown", path
            )
            private = any(
                path == prefix or path.startswith(prefix + "/")
                for prefix in (
                    "/api/v1/me",
                    "/api/v1/presets",
                    "/api/v1/favorites",
                    "/api/v1/history",
                )
            )
            if private:
                with request.app.state.session_factory() as db:
                    if current_user(request, db) is None:
                        raise DomainError("UNAUTHORIZED", "로그인이 필요합니다.", 401)
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                # Logout without a session is deliberately idempotent.
                empty_logout = path == "/api/v1/auth/logout" and not request.session
                expected = request.session.get("csrf")
                actual = request.headers.get("X-CSRF-Token", "")
                if not empty_logout and (
                    not expected
                    or not secrets.compare_digest(expected.encode(), actual.encode())
                ):
                    raise DomainError(
                        "FORBIDDEN", "CSRF 토큰이 올바르지 않습니다.", 403
                    )
        except DomainError as exc:
            response = await domain_error_handler(request, exc)
            return await response(scope, receive, send)
        await self.app(scope, receive, send)
