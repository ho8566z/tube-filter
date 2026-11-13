"""FNC-U-001/002/005/006: account validation and persistence."""

import re
from typing import Never

import bcrypt
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, SecretStr, StrictBool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import DomainError
from app.models import AppUser
from app.time_utils import format_kst, utc_now

router = APIRouter(prefix="/api/v1")


class Signup(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    loginId: str
    password: SecretStr
    passwordConfirm: SecretStr
    agreePrivacy: StrictBool


class PasswordChange(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    currentPassword: SecretStr
    newPassword: SecretStr
    newPasswordConfirm: SecretStr


class PasswordBody(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    password: SecretStr


def invalid(field, message) -> Never:
    raise DomainError(
        "VALIDATION_ERROR",
        "입력값을 확인해 주세요.",
        field_errors=[{"field": field, "message": message}],
    )


def normalize_login_id(value):
    value = value.lower()
    if not re.fullmatch(r"[a-z][a-z0-9]{3,19}", value):
        raise DomainError(
            "INVALID_LOGIN_ID",
            "아이디는 영문으로 시작하는 영문·숫자 4~20자입니다.",
            field_errors=[
                {"field": "loginId", "message": "아이디 형식을 확인해 주세요."}
            ],
        )
    return value


def validate_password(password, confirm, field="password") -> None:
    if (
        not 8 <= len(password) <= 64
        or not re.search(r"[a-zA-Z]", password)
        or not re.search(r"[0-9]", password)
        or len(password.encode("utf-8")) > 72
    ):
        invalid(
            field, "영문과 숫자를 포함한 8~64자(UTF-8 72바이트 이하)를 입력해 주세요."
        )
    if password != confirm:
        invalid(field + "Confirm", "비밀번호가 일치하지 않습니다.")


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def password_matches(password, encoded):
    raw = password.encode("utf-8")
    if len(raw) > 72:
        return False
    return bcrypt.checkpw(raw, encoded.encode("ascii"))


def check_password(password, user) -> None:
    if not password_matches(password, user.password):
        raise DomainError("WRONG_PASSWORD", "현재 비밀번호가 올바르지 않습니다.")


def require_user(request: Request, db: Session = Depends(get_db)):
    # Shared dependency is also available to the later personal-data routes.
    from app.users.auth import current_user

    user = current_user(request, db)
    if user is None:
        raise DomainError("UNAUTHORIZED", "로그인이 필요합니다.", 401)
    return user


@router.get("/auth/check-id")
def check_id(loginId: str, db: Session = Depends(get_db)):
    login_id = normalize_login_id(loginId)
    return {
        "available": db.scalar(select(AppUser.id).where(AppUser.login_id == login_id))
        is None
    }


@router.post("/auth/signup", status_code=201)
def signup(body: Signup, db: Session = Depends(get_db)):
    login_id = normalize_login_id(body.loginId)
    password = body.password.get_secret_value()
    validate_password(password, body.passwordConfirm.get_secret_value())
    if not body.agreePrivacy:
        invalid("agreePrivacy", "개인정보처리방침에 동의해 주세요.")
    if db.scalar(select(AppUser.id).where(AppUser.login_id == login_id)) is not None:
        raise DomainError("DUPLICATE_LOGIN_ID", "이미 사용 중인 아이디입니다.", 409)
    user = AppUser(
        login_id=login_id, password=hash_password(password), created_at=utc_now()
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "DUPLICATE_LOGIN_ID", "이미 사용 중인 아이디입니다.", 409
        ) from None
    return {"id": user.id, "loginId": user.login_id}


@router.get("/me")
def me(user: AppUser = Depends(require_user)):
    return {
        "id": user.id,
        "loginId": user.login_id,
        "createdAt": format_kst(user.created_at),
    }


@router.patch("/me/password", status_code=204)
def change_password(
    body: PasswordChange,
    user: AppUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    current = body.currentPassword.get_secret_value()
    check_password(current, user)
    new = body.newPassword.get_secret_value()
    validate_password(new, body.newPasswordConfirm.get_secret_value(), "newPassword")
    if new == current:
        invalid("newPassword", "새 비밀번호는 현재 비밀번호와 달라야 합니다.")
    user.password = hash_password(new)
    db.commit()
    return Response(status_code=204)


@router.delete("/me", status_code=204)
def withdraw(
    body: PasswordBody,
    request: Request,
    user: AppUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    check_password(body.password.get_secret_value(), user)
    # The three personal tables already have ON DELETE CASCADE FKs.
    db.delete(user)
    db.commit()
    request.session.clear()
    return Response(status_code=204)
