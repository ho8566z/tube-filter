"""FNC-F-014 pure predicate and FNC-S-008 standalone parallel service."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.cache.entity_cache import EntityCache
from app.errors import DomainError
from app.search.channel_info import ChannelInfo
from app.search.filters_video import FilterResult, NumberRange, _result
from app.search.metrics import ChannelActivity
from app.time_utils import to_utc
from app.youtube.adapter import YouTubeAdapter


@dataclass(frozen=True)
class ActivityConditions:
    window_days: int = 30
    count: NumberRange = NumberRange()
    last_upload_within_days: int | None = None

    def __post_init__(self):
        if self.window_days not in (30, 60, 90) or (
            self.last_upload_within_days is not None
            and self.last_upload_within_days not in (30, 60, 90)
        ):
            raise ValueError("activity windows must be 30, 60, or 90 days")

    @property
    def active(self) -> bool:
        return self.count.active or self.last_upload_within_days is not None


def filter_activity(
    activity: ChannelActivity,
    conditions: ActivityConditions = ActivityConditions(),
    *,
    now: datetime,
) -> FilterResult:
    if not conditions.active:
        return _result("ACTIVITY", True)
    if activity.upload_dates is None:
        return _result("ACTIVITY", False, hidden=True)
    count = activity.count(conditions.window_days, now)
    passed = not conditions.count.active or conditions.count.contains(count)
    if conditions.last_upload_within_days is not None:
        last = activity.last_upload(now)
        passed = (
            passed
            and last is not None
            and (
                last >= to_utc(now) - timedelta(days=conditions.last_upload_within_days)
            )
        )
    return _result("ACTIVITY", passed)


@dataclass(frozen=True)
class ActivityLookup:
    activities: dict[str, ChannelActivity]
    results: dict[str, FilterResult]
    limited_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


async def fetch_activity(
    db: Session,
    adapter: YouTubeAdapter,
    cache: EntityCache,
    channels: Sequence[ChannelInfo],
    conditions: ActivityConditions = ActivityConditions(),
    *,
    now: datetime,
    search_id: str | None = None,
    include_video_ids: bool = False,
    cache_only: bool = False,
) -> ActivityLookup:
    """One request per uncached channel, no pagination. DB stays on caller thread.

    The adapter must support concurrent request calls (the production adapter
    uses independent HTTP clients and a locked quota guard).
    """
    if not conditions.active and not include_video_ids:
        return ActivityLookup({}, {})
    unique = list({c.channel_id: c for c in channels}.values())
    selected, limited = unique[:50], unique[50:]
    activities = cache.get_channel_activity(db, [c.channel_id for c in selected])
    if include_video_ids:
        activities = {k: v for k, v in activities.items() if v.video_ids is not None}

    async def fetch(channel):
        if not channel.uploads_playlist_id:
            return channel.channel_id, (
                ChannelActivity((), ()) if include_video_ids else ChannelActivity()
            )
        try:
            if cache_only:
                raise DomainError(
                    "QUOTA_BLOCKED", "캐시된 정보만 이용할 수 있습니다.", 503
                )
            payload = await asyncio.to_thread(
                adapter.request,
                "playlistItems.list",
                {
                    "part": "contentDetails",
                    "playlistId": channel.uploads_playlist_id,
                    "maxResults": 50,
                },
                search_id=search_id,
            )
            dates = tuple(
                to_utc(
                    datetime.fromisoformat(item["contentDetails"]["videoPublishedAt"])
                )
                for item in payload.get("items", [])[:50]
            )
            ids = tuple(
                item["contentDetails"]["videoId"]
                for item in payload.get("items", [])[:50]
                if item.get("contentDetails", {}).get("videoId")
            )
            return channel.channel_id, ChannelActivity(dates, ids)
        except DomainError as exc:
            return channel.channel_id, exc
        except (ValueError, KeyError, TypeError):
            return channel.channel_id, ChannelActivity()

    fetched = await asyncio.gather(
        *(fetch(c) for c in selected if c.channel_id not in activities)
    )
    warnings = []
    for key, activity in fetched:
        if isinstance(activity, DomainError):
            stale = cache.get_channel_activity(db, [key], stale=True).get(key)
            if include_video_ids and activity.code == "QUOTA_BLOCKED":
                activities[key] = stale or ChannelActivity()
                warnings.append("STALE_STATS")
                continue
            if include_video_ids:
                raise activity
            activity = ChannelActivity()
        activities[key] = activity
        if activity.upload_dates is not None:
            cache.save_channel_activity(db, key, activity)
    if any(a.upload_dates is None for a in activities.values()):
        warnings.append("PARTIAL_FAILURE")
    if limited:
        warnings.append("ACTIVITY_LIMIT")
    return ActivityLookup(
        activities,
        {
            key: filter_activity(value, conditions, now=now)
            for key, value in activities.items()
        },
        tuple(c.channel_id for c in limited),
        tuple(warnings),
    )
