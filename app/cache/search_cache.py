"""Cache final video IDs and search metadata for normalized conditions."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import SearchCache
from app.time_utils import to_utc, utc_now


def conditions_json(conditions: dict) -> str:
    """Serialize already-normalized keyword + all filters, sorting nested keys."""
    return json.dumps(
        conditions,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def condition_hash(conditions: dict) -> str:
    return hashlib.sha256(conditions_json(conditions).encode("utf-8")).hexdigest()


class SearchResultCache:
    """Caller owns the session and transaction. Expiry is exclusive."""

    def __init__(
        self, settings: Settings, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self.ttl = timedelta(hours=settings.cache_search_ttl_hours)
        self.clock = clock

    def get(self, db: Session, conditions: dict) -> SearchCache | None:
        return db.scalar(
            select(SearchCache)
            .where(
                SearchCache.cond_hash == condition_hash(conditions),
                SearchCache.expires_at > to_utc(self.clock()),
            )
            .order_by(SearchCache.created_at.desc(), SearchCache.id.desc())
            .limit(1)
        )

    def save(
        self,
        db: Session,
        conditions: dict,
        video_ids: list[str],
        funnel: dict,
        *,
        warnings: list | None = None,
        quota_spent: int = 0,
        search_id: str | None = None,
    ) -> SearchCache:
        now = to_utc(self.clock())
        row = SearchCache(
            id=search_id or uuid4().hex,
            cond_hash=condition_hash(conditions),
            conditions=conditions_json(conditions),
            video_ids=json.dumps(video_ids, ensure_ascii=False),
            funnel=json.dumps(funnel, ensure_ascii=False),
            warnings=json.dumps(warnings, ensure_ascii=False)
            if warnings is not None
            else None,
            quota_spent=quota_spent,
            created_at=now,
            expires_at=now + self.ttl,
        )
        db.add(row)
        db.flush()
        return row
