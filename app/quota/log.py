"""Persist attempted calls separately from the caller's transaction."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import QuotaUsage
from app.quota.clock import pt_date

# The only quota cost table. Keys also define the allowed adapter endpoints.
ENDPOINT_COSTS = {
    "search.list": 100,
    "videos.list": 1,
    "channels.list": 1,
    "playlistItems.list": 1,
    "videoCategories.list": 1,
}


def record_call(
    db: Session, endpoint: str, now: datetime, search_id: str | None = None
) -> None:
    db.add(
        QuotaUsage(
            usage_date=pt_date(now),
            endpoint=endpoint,
            units=ENDPOINT_COSTS[endpoint],
            called_at=now,
            search_id=search_id,
        )
    )
    db.commit()
