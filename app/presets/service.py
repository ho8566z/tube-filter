"""FNC-P-001–003: owner-scoped, normalized filter presets."""

import json

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import DomainError
from app.models import FilterPreset
from app.search.conditions import invalid, normalize
from app.time_utils import format_kst
from app.users.auth import current_user

router = APIRouter(prefix="/api/v1/presets")


class PresetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    conditions: dict


def owned(db, user_id, preset_id):
    if not 1 <= preset_id <= 2**63 - 1:
        invalid("id")
    row = db.scalar(
        select(FilterPreset).where(
            FilterPreset.id == preset_id, FilterPreset.user_id == user_id
        )
    )
    if row is None:
        raise DomainError("PRESET_NOT_FOUND", "프리셋을 찾을 수 없습니다.", 404)
    return row


def detail(row):
    return {"id": row.id, "name": row.name, "conditions": json.loads(row.conditions)}


def values(body, now):
    name = body.name.strip()
    if not 1 <= len(name) <= 30:
        invalid("name")
    # Presets contain filters only. Supply a validation keyword, then discard it.
    data = normalize({**body.conditions, "keyword": "preset"}, now=now).data
    data.pop("keyword")
    return name, json.dumps(data, ensure_ascii=False)


def save(db, row):
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "DUPLICATE_PRESET_NAME", "같은 이름의 프리셋이 있습니다.", 409
        ) from None


@router.get("")
def list_presets(request: Request, db: Session = Depends(get_db)):
    uid = current_user(request, db).id
    rows = db.scalars(
        select(FilterPreset)
        .where(FilterPreset.user_id == uid)
        .order_by(FilterPreset.name, FilterPreset.id)
    )
    return [
        {"id": row.id, "name": row.name, "createdAt": format_kst(row.created_at)}
        for row in rows
    ]


@router.get("/{preset_id}")
def get_preset(preset_id: int, request: Request, db: Session = Depends(get_db)):
    return detail(owned(db, current_user(request, db).id, preset_id))


@router.post("", status_code=201)
def create_preset(body: PresetBody, request: Request, db: Session = Depends(get_db)):
    uid = current_user(request, db).id
    now = request.app.state.clock()
    name, conditions = values(body, now)
    count = db.scalar(
        select(func.count())
        .select_from(FilterPreset)
        .where(FilterPreset.user_id == uid)
    )
    if count >= 30:
        raise DomainError("PRESET_LIMIT", "프리셋은 최대 30개까지 저장할 수 있습니다.")
    row = FilterPreset(
        user_id=uid, name=name, conditions=conditions, created_at=now, updated_at=now
    )
    save(db, row)
    return {"id": row.id, "name": row.name}


@router.put("/{preset_id}")
def update_preset(
    preset_id: int, body: PresetBody, request: Request, db: Session = Depends(get_db)
):
    row = owned(db, current_user(request, db).id, preset_id)
    now = request.app.state.clock()
    row.name, row.conditions = values(body, now)
    row.updated_at = now
    save(db, row)
    return detail(row)


@router.delete("/{preset_id}", status_code=204)
def delete_preset(preset_id: int, request: Request, db: Session = Depends(get_db)):
    db.delete(owned(db, current_user(request, db).id, preset_id))
    db.commit()
    return Response(status_code=204)
