"""FNC-S-006 standalone channel lookup service; caller owns the transaction."""

from collections.abc import Sequence
from dataclasses import dataclass, fields

from sqlalchemy.orm import Session

from app.cache.entity_cache import EntityCache
from app.errors import DomainError
from app.models import ChannelCache
from app.search.channel_info import ChannelInfo
from app.youtube.adapter import YouTubeAdapter


@dataclass(frozen=True)
class ChannelLookup:
    channels: tuple[ChannelInfo, ...]
    unavailable_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def fetch_channels(
    db: Session,
    adapter: YouTubeAdapter,
    cache: EntityCache,
    channel_ids: Sequence[str],
    *,
    search_id: str | None = None,
) -> ChannelLookup:
    ids = list(dict.fromkeys(channel_ids))
    hits = cache.get_channels(db, ids)
    names = [field.name for field in fields(ChannelInfo)]
    found = {
        key: ChannelInfo(**{name: getattr(row, name) for name in names})
        for key, row in hits.items()
    }
    missing = [key for key in ids if key not in found]
    for start in range(0, len(missing), 50):
        batch = missing[start : start + 50]
        try:
            payload = adapter.request(
                "channels.list",
                {"part": "snippet,statistics,contentDetails", "id": ",".join(batch)},
                search_id=search_id,
            )
        except DomainError:
            continue
        rows = []
        for item in payload.get("items", []):
            if item.get("id") not in batch:
                continue
            channel = ChannelInfo.from_youtube(item)
            found[channel.channel_id] = channel
            rows.append(
                ChannelCache(**{name: getattr(channel, name) for name in names})
            )
        cache.save_channels(db, rows)
    unavailable = tuple(key for key in ids if key not in found)
    return ChannelLookup(
        tuple(found[key] for key in ids if key in found),
        unavailable,
        ("PARTIAL_FAILURE",) if unavailable else (),
    )
