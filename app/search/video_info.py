"""Immutable filter input mapped from one videos.list item, without I/O."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.time_utils import to_utc

_DURATION = re.compile(
    r"P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?"
)


def parse_duration(value: str | None) -> int | None:
    """Parse day/hour/minute/second ISO durations; unknown formats remain missing."""
    if value is None:
        return None
    match = _DURATION.fullmatch(value)
    if (
        match is None
        or not any(part is not None for part in match.groups())
        or value.endswith("T")
    ):
        return None
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


@dataclass(frozen=True)
class VideoInfo:
    video_id: str = ""
    channel_id: str = ""
    duration_sec: int | None = None
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    tags: tuple[str, ...] = ()
    title: str = ""
    description: str = ""
    category_id: str | None = None
    default_audio_language: str | None = None
    default_language: str | None = None
    made_for_kids: bool | None = None
    # None means absent; an explicitly empty allowed list allows no countries.
    region_allowed: tuple[str, ...] | None = None
    region_blocked: tuple[str, ...] | None = None
    published_at: datetime | None = None
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_youtube(cls, item: Mapping[str, Any]) -> "VideoInfo":
        """Map the adapter's raw item; preserve absent statistics as None.

        Duration warnings are local messages for the caller to surface later,
        not an addition to the public API warning codes.
        """
        snippet = item.get("snippet") or {}
        details = item.get("contentDetails") or {}
        statistics = item.get("statistics") or {}
        status = item.get("status") or {}
        restriction = details.get("regionRestriction") or {}
        duration = parse_duration(details.get("duration"))
        published = snippet.get("publishedAt")

        def count(key: str) -> int | None:
            value = statistics.get(key)
            return int(value) if value is not None else None

        def regions(key: str) -> tuple[str, ...] | None:
            value = restriction.get(key)
            return tuple(value) if value is not None else None

        return cls(
            video_id=item.get("id", ""),
            channel_id=snippet.get("channelId", ""),
            duration_sec=duration,
            view_count=count("viewCount"),
            like_count=count("likeCount"),
            comment_count=count("commentCount"),
            tags=tuple(snippet.get("tags") or ()),
            title=snippet.get("title") or "",
            description=snippet.get("description") or "",
            category_id=snippet.get("categoryId"),
            default_audio_language=snippet.get("defaultAudioLanguage"),
            default_language=snippet.get("defaultLanguage"),
            made_for_kids=status.get("madeForKids"),
            region_allowed=regions("allowed"),
            region_blocked=regions("blocked"),
            published_at=to_utc(datetime.fromisoformat(published))
            if published
            else None,
            warnings=("영상 길이를 해석할 수 없습니다.",) if duration is None else (),
        )
