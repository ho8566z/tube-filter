"""Fresh entity reads and replacement writes; services fetch cache misses."""

import json
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ChannelCache, VideoCache
from app.search.metrics import ChannelActivity
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

    def get_channel_activity(
        self, db: Session, channel_ids: Sequence[str], *, stale: bool = False
    ) -> dict[str, ChannelActivity]:
        """Activity freshness is independent of channel statistics freshness."""
        if not channel_ids:
            return {}
        cutoff = to_utc(self.clock()) - (
            self.max_age if stale else min(self.ttl, self.max_age)
        )
        rows = db.scalars(
            select(ChannelCache).where(
                ChannelCache.channel_id.in_(channel_ids),
                ChannelCache.recent_fetched_at > cutoff,
                ChannelCache.recent_uploads.is_not(None),
            )
        )
        result = {}
        for row in rows:
            data = json.loads(row.recent_uploads)
            # Earlier caches contain only a list of dates.
            dates = data["dates"] if isinstance(data, dict) else data
            ids = data.get("videoIds") if isinstance(data, dict) else None
            result[row.channel_id] = ChannelActivity(
                tuple(to_utc(datetime.fromisoformat(value)) for value in dates),
                tuple(ids) if ids is not None else None,
            )
        return result

    def save_channel_activity(
        self, db: Session, channel_id: str, activity: ChannelActivity
    ) -> None:
        """Do not renew fetched_at: activity does not refresh channel statistics."""
        row = db.get(ChannelCache, channel_id)
        if row is None or activity.upload_dates is None:
            return
        dates = [to_utc(value).isoformat() for value in activity.upload_dates]
        row.recent_uploads = json.dumps(
            {"dates": dates, "videoIds": activity.video_ids}
            if activity.video_ids is not None
            else dates
        )
        row.recent_fetched_at = to_utc(self.clock())
        db.flush()
