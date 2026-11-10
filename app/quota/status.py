"""FNC-Q-002: current PT day's usage and public status API."""

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import QuotaUsage
from app.quota.clock import next_reset, pt_date
from app.time_utils import format_kst, utc_now

router = APIRouter(prefix="/api/v1")


def used_units(db: Session, now: datetime) -> int:
    return db.scalar(
        select(func.coalesce(func.sum(QuotaUsage.units), 0)).where(
            QuotaUsage.usage_date == pt_date(now)
        )
    )


@router.get("/quota")
def quota_status(request: Request, db: Session = Depends(get_db)) -> dict:
    now = utc_now()
    settings = request.app.state.settings
    used = used_units(db, now)
    return {
        "usedUnits": used,
        "limitUnits": settings.quota_daily_limit,
        "softLimitUnits": settings.quota_soft_limit,
        "remainingUnits": max(0, settings.quota_daily_limit - used),
        "resetAt": format_kst(next_reset(now)),
    }
