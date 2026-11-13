"""FNC-S-002: cache-aware maximum cost, with no upstream I/O."""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.cache.search_cache import SearchResultCache
from app.config import Settings
from app.quota.status import used_units
from app.search.conditions import SearchConditions


def estimate(
    db: Session,
    conditions: SearchConditions,
    search_cache: SearchResultCache,
    settings: Settings,
    now: datetime,
) -> dict[str, Any]:
    cached = search_cache.get(db, conditions.data) is not None
    cost = (
        0
        if cached
        else 102 * conditions.data["pages"] + (50 if conditions.activity.active else 0)
    )
    remaining = max(0, settings.quota_daily_limit - used_units(db, now))
    return {
        "estimatedUnits": cost,
        "cached": cached,
        "remainingUnits": remaining,
        "estimatedSearchesLeft": remaining // cost if cost else None,
    }
