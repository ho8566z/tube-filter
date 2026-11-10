"""FNC-S-002: cache-aware maximum cost, with no upstream I/O."""

from app.quota.status import used_units


def estimate(db, conditions, search_cache, settings, now):
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
