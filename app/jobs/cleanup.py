"""Cache retention and daily 03:00 KST scheduling without extra packages."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import (
    ChannelCache,
    QuotaUsage,
    SearchCache,
    VideoCache,
    VideoCategoryCache,
)
from app.time_utils import to_kst, to_utc, utc_now

logger = logging.getLogger(__name__)


def cleanup(db: Session, settings: Settings, now: datetime) -> dict[str, int]:
    """Delete at the boundary (age >= limit), committing all tables together."""
    now = to_utc(now)
    cutoff = now - timedelta(days=settings.cache_max_days)
    targets = (
        (SearchCache, SearchCache.expires_at <= now),
        (VideoCache, VideoCache.fetched_at <= cutoff),
        (ChannelCache, ChannelCache.fetched_at <= cutoff),
        (VideoCategoryCache, VideoCategoryCache.fetched_at <= cutoff),
        (QuotaUsage, QuotaUsage.called_at <= now - timedelta(days=90)),
    )
    counts = {}
    try:
        for model, condition in targets:
            result = db.execute(delete(model).where(condition))
            counts[model.__tablename__] = result.rowcount
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    logger.info("cache cleanup deleted rows: %s", counts)
    return counts


def next_cleanup_at(now: datetime) -> datetime:
    """Return the next strictly future 03:00 KST, expressed in UTC."""
    local = to_kst(now)
    target = local.replace(hour=3, minute=0, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    return to_utc(target)


def run_cleanup(factory: sessionmaker, settings: Settings, now: datetime) -> None:
    try:
        with factory() as db:
            cleanup(db, settings, now)
    except SQLAlchemyError:
        # A failed run must not kill the daily task or expose SQL/connection details.
        logger.warning(
            "cache cleanup failed; check database migrations and availability"
        )


async def schedule_cleanup(
    factory: sessionmaker,
    settings: Settings,
    *,
    clock: Callable[[], datetime] = utc_now,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Startup cleanup is run by lifespan; this task handles daily runs only."""
    while True:
        now = to_utc(clock())
        target = next_cleanup_at(now)
        # Recheck after early wakeups; never run before the scheduled time.
        while now < target:
            await sleep((target - now).total_seconds())
            now = to_utc(clock())
        worker = asyncio.create_task(
            asyncio.to_thread(run_cleanup, factory, settings, now)
        )
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            # Finish an in-flight transaction before lifespan disposes the engine.
            await worker
            raise
