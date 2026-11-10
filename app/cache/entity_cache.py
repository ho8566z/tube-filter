"""Fresh entity reads and replacement writes; fetching belongs to stage 6."""

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ChannelCache, VideoCache
from app.time_utils import to_utc, utc_now


class EntityCache:
    """Return fresh hits only; caller fetches misses and commits writes."""

    def __init__(self, settings: Settings, clock: Callable[[], datetime] = utc_now):
        self.ttl = timedelta(hours=settings.cache_stats_ttl_hours)
        self.max_age = timedelta(days=settings.cache_max_days)
        self.clock = clock

    def _get(self, db: Session, model, key, ids: Sequence[str]) -> dict:
        if not ids:
            return {}
        now = to_utc(self.clock())
        rows = db.scalars(
            select(model).where(
                key.in_(ids),
                model.fetched_at > now - min(self.ttl, self.max_age),
            )
        )
        return {getattr(row, key.key): row for row in rows}

    def get_videos(
        self, db: Session, video_ids: Sequence[str]
    ) -> dict[str, VideoCache]:
        return self._get(db, VideoCache, VideoCache.video_id, video_ids)

    def get_channels(
        self, db: Session, channel_ids: Sequence[str]
    ) -> dict[str, ChannelCache]:
        return self._get(db, ChannelCache, ChannelCache.channel_id, channel_ids)

    def _save(self, db: Session, rows: Sequence) -> None:
        now = to_utc(self.clock())
        for row in rows:
            row.fetched_at = now
            db.merge(row)
        db.flush()

    def save_videos(self, db: Session, videos: Sequence[VideoCache]) -> None:
        """Accept complete mapped records, with optional absent values set to None."""
        self._save(db, videos)

    def save_channels(self, db: Session, channels: Sequence[ChannelCache]) -> None:
        self._save(db, channels)
