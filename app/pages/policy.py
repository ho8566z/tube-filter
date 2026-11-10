"""SCR-000/001/002/010/011: HTML only; actions use the existing JSON APIs."""

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, Request
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
def page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if request.url.path == "/login" and user is not None:
        return RedirectResponse("/", status_code=303)
    token = request.session.setdefault("csrf", secrets.token_urlsafe(32))
    name = request.url.path.strip("/") or "home"
    return templates.TemplateResponse(
        request=request,
        name=f"{name}.html",
        context={"user": user, "csrf_token": token},
        headers={"Cache-Control": "no-store"},
    )
