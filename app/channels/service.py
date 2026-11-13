"""FNC-C-001: reuse channel, upload activity, and video lookup services."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.channels.pattern import upload_pattern
from app.errors import DomainError
from app.models import VideoCache
from app.search.activity import fetch_activity
from app.search.channels import fetch_channels
from app.search.details import fetch_details
from app.search.service import SearchService, get_service, render_items
from app.time_utils import format_kst

router = APIRouter(prefix="/api/v1/channels")


async def channel_detail(service: SearchService, channel_id: str) -> dict[str, Any]:
    db, cache, adapter = service.db, service.cache, service.adapter
    lookup = fetch_channels(db, adapter, cache, [channel_id], allow_stale=True)
    db.commit()
    if not lookup.channels:
        raise DomainError("CHANNEL_NOT_FOUND", "채널을 찾을 수 없습니다.", 404)
    channel = lookup.channels[0]
    activity = await fetch_activity(
        db,
        adapter,
        cache,
        [channel],
        now=service.clock(),
        include_video_ids=True,
        cache_only="STALE_STATS" in lookup.warnings,
    )
    db.commit()
    uploads = activity.activities[channel_id]
    ids = uploads.video_ids
    cache_only = "STALE_STATS" in (*lookup.warnings, *activity.warnings)
    if ids is None and cache_only:
        # Older activity caches have dates only. Still show available video caches
        # when quota prevents retrieving the uploads playlist.
        ids = list(
            db.scalars(
                select(VideoCache.video_id)
                .where(
                    VideoCache.channel_id == channel_id,
                    VideoCache.fetched_at > service.clock() - cache.max_age,
                )
                .order_by(VideoCache.published_at.desc(), VideoCache.video_id)
                .limit(50)
            )
        )
    details = await fetch_details(
        db,
        adapter,
        cache,
        (ids or ())[:50],
        cache_only=cache_only,
    )
    db.commit()
    return {
        "channel": {
            "id": channel.channel_id,
            "title": channel.title,
            "subscribers": channel.public_subscriber_count,
            "videoCount": channel.video_count,
            "country": channel.country,
            "createdAt": format_kst(channel.published_at)
            if channel.published_at
            else None,
        },
        "recentVideos": render_items(
            details.videos,
            details.rows,
            {channel_id: channel},
            service.clock(),
            activity.activities,
        ),
        "pattern": upload_pattern(
            uploads.upload_dates
            if uploads.upload_dates is not None
            else [video.published_at for video in details.videos]
        ),
        "warnings": list(
            dict.fromkeys([*lookup.warnings, *activity.warnings, *details.warnings])
        ),
    }


@router.get("/{channel_id}")
def get_channel(
    channel_id: str, service: SearchService = Depends(get_service)
) -> dict[str, Any]:
    return asyncio.run(channel_detail(service, channel_id))
