"""FNC-S-006 standalone channel lookup service; caller owns the transaction."""

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, fields
from typing import Any

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
    allow_stale: bool = False,
) -> ChannelLookup:
    ids = list(dict.fromkeys(channel_ids))
    hits = cache.get_channels(db, ids)
    names = [field.name for field in fields(ChannelInfo)]
    found = {
        key: ChannelInfo(**{name: getattr(row, name) for name in names})
        for key, row in hits.items()
    }
    missing = [key for key in ids if key not in found]
    batches = [missing[start : start + 50] for start in range(0, len(missing), 50)]

    def fetch(batch: list[str]) -> dict[str, Any] | DomainError:
        try:
            return adapter.request(
                "channels.list",
                {"part": "snippet,statistics,contentDetails", "id": ",".join(batch)},
                search_id=search_id,
            )
        except DomainError as exc:
            return exc

    # Only adapter calls run in workers; the caller's Session stays on this thread.
    with ThreadPoolExecutor(max_workers=5) as pool:
        payloads = list(pool.map(fetch, batches))
    warnings = []
    for batch, payload in zip(batches, payloads):
        if isinstance(payload, DomainError):
            if allow_stale:
                if payload.code != "QUOTA_BLOCKED":
                    raise payload
                for key in batch:
                    row = db.get(ChannelCache, key)
                    if row and row.fetched_at > cache.clock() - cache.max_age:
                        found[key] = ChannelInfo(**{n: getattr(row, n) for n in names})
                if any(key not in found for key in batch):
                    raise payload
                warnings.append("STALE_STATS")
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
        tuple(warnings + (["PARTIAL_FAILURE"] if unavailable else [])),
    )
