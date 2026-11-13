"""SCR-000/001/002/010/011: HTML only; actions use the existing JSON APIs."""

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db
from app.users.auth import current_user

APP_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=APP_DIR / "templates")
router = APIRouter()


@router.get("/", response_class=HTMLResponse)
@router.get("/login", response_class=HTMLResponse)
@router.get("/signup", response_class=HTMLResponse)
@router.get("/privacy", response_class=HTMLResponse)
@router.get("/terms", response_class=HTMLResponse)
@router.get("/presets", response_class=HTMLResponse)
@router.get("/favorites", response_class=HTMLResponse)
@router.get("/history", response_class=HTMLResponse)
@router.get("/me", response_class=HTMLResponse)
@router.get("/channels/{channel_id}", response_class=HTMLResponse)
def page(request: Request, db: Session = Depends(get_db)) -> Response:
    user = current_user(request, db)
    if (
        request.url.path in {"/presets", "/favorites", "/history", "/me"}
        and user is None
    ):
        return RedirectResponse("/login", status_code=303)
    if request.url.path == "/login" and user is not None:
        return RedirectResponse("/", status_code=303)
    token = request.session.setdefault("csrf", secrets.token_urlsafe(32))
    name = request.url.path.strip("/") or "home"
    if "channel_id" in request.path_params:
        name = "channel"
    return templates.TemplateResponse(
        request=request,
        name=f"{name}.html",
        context={
            "user": user,
            "csrf_token": token,
            "channel_id": request.path_params.get("channel_id"),
        },
        headers={"Cache-Control": "no-store"},
    )
