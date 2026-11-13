"""FNC-S-004: parallel detail batches; DB mapping stays on caller thread."""

import asyncio
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.cache.entity_cache import EntityCache
from app.errors import DomainError
from app.models import VideoCache
from app.search.video_info import VideoInfo
from app.youtube.adapter import YouTubeAdapter


def video_info(row: VideoCache) -> VideoInfo:
    return VideoInfo(
        video_id=row.video_id,
        channel_id=row.channel_id,
        title=row.title,
        description=row.description or "",
        published_at=row.published_at,
        duration_sec=row.duration_sec,
        view_count=row.view_count,
        like_count=row.like_count,
        comment_count=row.comment_count,
        tags=tuple(json.loads(row.tags or "[]")),
        category_id=str(row.category_id) if row.category_id is not None else None,
        default_language=row.default_language,
        made_for_kids=row.made_for_kids,
        region_allowed=tuple(json.loads(row.region_allowed))
        if row.region_allowed is not None
        else None,
        region_blocked=tuple(json.loads(row.region_blocked))
        if row.region_blocked is not None
        else None,
    )


def cache_video(item: Mapping[str, Any]) -> VideoCache:
    video = VideoInfo.from_youtube(item)
    snippet = item.get("snippet") or {}

    def encoded(value: Any) -> str | None:
        return json.dumps(value, ensure_ascii=False) if value is not None else None

    return VideoCache(
        video_id=video.video_id,
        channel_id=video.channel_id,
        title=video.title,
        description=video.description,
        published_at=video.published_at,
        thumbnail_url=(snippet.get("thumbnails") or {})
        .get("medium", (snippet.get("thumbnails") or {}).get("default", {}))
        .get("url"),
        duration_sec=video.duration_sec,
        tags=encoded(video.tags),
        category_id=int(video.category_id) if video.category_id is not None else None,
        default_language=video.default_audio_language or video.default_language,
        definition=(item.get("contentDetails") or {}).get("definition"),
        made_for_kids=video.made_for_kids,
        region_allowed=encoded(video.region_allowed),
        region_blocked=encoded(video.region_blocked),
        view_count=video.view_count,
        like_count=video.like_count,
        comment_count=video.comment_count,
    )


@dataclass
class VideoLookup:
    videos: list
    rows: dict
    deleted_ids: list
    failed_ids: list
    warnings: list


async def fetch_details(
    db: Session,
    adapter: YouTubeAdapter,
    cache: EntityCache,
    video_ids: Iterable[str],
    *,
    search_id: str | None = None,
    cache_only: bool = False,
) -> VideoLookup:
    ids = list(dict.fromkeys(video_ids))
    rows = cache.get_videos(db, ids)
    missing = [key for key in ids if key not in rows]
    failed, deleted, warnings = [], [], []

    async def fetch(batch: list[str]) -> dict[str, Any] | DomainError:
        try:
            return await asyncio.to_thread(
                adapter.request,
                "videos.list",
                {
                    "part": "snippet,contentDetails,statistics,status",
                    "id": ",".join(batch),
                },
                search_id=search_id,
            )
        except DomainError as exc:
            return exc

    batches = [missing[i : i + 50] for i in range(0, len(missing), 50)]
    payloads = (
        [] if cache_only else await asyncio.gather(*(fetch(batch) for batch in batches))
    )
    for batch, payload in zip(batches, payloads):
        if isinstance(payload, DomainError):
            failed.extend(batch)
            warnings.append("PARTIAL_FAILURE")
            # Preserve cached statistics when quota prevents their refresh.
            if payload.code == "QUOTA_BLOCKED":
                warnings.append("STALE_STATS")
                for key in batch:
                    row = db.get(VideoCache, key)
                    if (
                        row is not None
                        and row.fetched_at > cache.clock() - cache.max_age
                    ):
                        rows[key] = row
            continue
        returned = set()
        saved = []
        for item in payload.get("items", []):
            if item.get("id") not in batch:
                continue
            row = cache_video(item)
            saved.append(row)
            rows[row.video_id] = row
            returned.add(row.video_id)
            if row.duration_sec is None:
                warnings.append("PARTIAL_FAILURE")
        absent = [key for key in batch if key not in returned]
        deleted.extend(absent)
        if absent:
            db.execute(delete(VideoCache).where(VideoCache.video_id.in_(absent)))
        cache.save_videos(db, saved)
    if cache_only:
        for key in missing:
            row = db.get(VideoCache, key)
            if row is not None and row.fetched_at > cache.clock() - cache.max_age:
                rows[key] = row
        if missing:
            warnings.append("STALE_STATS")
    return VideoLookup(
        [video_info(rows[key]) for key in ids if key in rows],
        rows,
        deleted,
        failed,
        list(dict.fromkeys(warnings)),
    )
