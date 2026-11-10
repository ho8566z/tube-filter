"""Internal channels.list item, independent of persistence and network."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.time_utils import to_utc


@dataclass(frozen=True)
class ChannelInfo:
    channel_id: str = ""
    title: str = ""
    thumbnail_url: str | None = None
    country: str | None = None
    published_at: datetime | None = None
    subscriber_count: int | None = None
    hidden_subscriber: bool = False
    video_count: int | None = None
    view_count: int | None = None
    uploads_playlist_id: str | None = None

    @property
    def public_subscriber_count(self) -> int | None:
        return None if self.hidden_subscriber else self.subscriber_count

    @classmethod
    def from_youtube(cls, item: Mapping[str, Any]) -> "ChannelInfo":
        snippet = item.get("snippet") or {}
        stats = item.get("statistics") or {}
        details = item.get("contentDetails") or {}
        hidden = stats.get("hiddenSubscriberCount") is True
        published = snippet.get("publishedAt")

        def count(key):
            value = stats.get(key)
            return int(value) if value is not None else None

        return cls(
            channel_id=item.get("id", ""),
            title=snippet.get("title") or "",
            thumbnail_url=(snippet.get("thumbnails") or {})
            .get("default", {})
            .get("url"),
            country=snippet.get("country") or None,
            published_at=to_utc(datetime.fromisoformat(published))
            if published
            else None,
            subscriber_count=None if hidden else count("subscriberCount"),
            hidden_subscriber=hidden,
            video_count=count("videoCount"),
            view_count=count("viewCount"),
            uploads_playlist_id=(details.get("relatedPlaylists") or {}).get("uploads"),
        )
