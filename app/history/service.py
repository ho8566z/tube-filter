"""FNC-P-006/007: the latest 50 searches, without video lists."""

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import DomainError
from app.models import SearchHistory
from app.time_utils import format_kst
from app.users.auth import current_user

router = APIRouter(prefix="/api/v1/history")
logger = logging.getLogger(__name__)


def record_search(
    db: Session,
    user_id: int | None,
    conditions: dict[str, Any],
    result_count: int,
    now: datetime,
) -> None:
    """Search has succeeded; a history failure must not replace its response."""
    if user_id is None:
        return
    try:
        db.add(
            SearchHistory(
                user_id=user_id,
                keyword=conditions["keyword"],
                conditions=json.dumps(conditions, ensure_ascii=False),
                result_count=result_count,
                searched_at=now,
            )
        )
        db.flush()
        old_ids = list(
            db.scalars(
                select(SearchHistory.id)
                .where(SearchHistory.user_id == user_id)
                .order_by(SearchHistory.searched_at.desc(), SearchHistory.id.desc())
                .offset(50)
            )
        )
        if old_ids:
            db.execute(
                delete(SearchHistory).where(
                    SearchHistory.user_id == user_id, SearchHistory.id.in_(old_ids)
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        # Do not log SQL parameters or the member's search conditions.
        logger.warning("검색 기록 저장에 실패했습니다.")


@router.get("")
def list_history(
    request: Request, db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(SearchHistory)
        .where(SearchHistory.user_id == current_user(request, db).id)
        .order_by(SearchHistory.searched_at.desc(), SearchHistory.id.desc())
        .limit(50)
    )
    return [
        {
            "id": row.id,
            "keyword": row.keyword,
            "conditions": json.loads(row.conditions),
            "resultCount": row.result_count,
            "searchedAt": format_kst(row.searched_at),
        }
        for row in rows
    ]


@router.delete("/{history_id}", status_code=204)
def delete_history(
    history_id: str, request: Request, db: Session = Depends(get_db)
) -> Response:
    uid = current_user(request, db).id
    query = delete(SearchHistory).where(SearchHistory.user_id == uid)
    if history_id != "all":
        if not history_id.isascii() or not history_id.isdecimal():
            raise DomainError("HISTORY_NOT_FOUND", "검색 기록을 찾을 수 없습니다.", 404)
        # Avoid accepting arbitrary-length integer strings as database IDs.
        if len(history_id) > 19 or int(history_id) > 2**63 - 1:
            raise DomainError("HISTORY_NOT_FOUND", "검색 기록을 찾을 수 없습니다.", 404)
        query = query.where(SearchHistory.id == int(history_id))
    result = db.execute(query)
    if history_id != "all" and not result.rowcount:
        raise DomainError("HISTORY_NOT_FOUND", "검색 기록을 찾을 수 없습니다.", 404)
    db.commit()
    return Response(status_code=204)
