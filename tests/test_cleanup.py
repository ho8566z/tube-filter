import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.jobs.cleanup import cleanup, next_cleanup_at, run_cleanup, schedule_cleanup
from app.main import lifespan
from app.models import (
    ChannelCache,
    QuotaUsage,
    SearchCache,
    VideoCache,
    VideoCategoryCache,
)
from app.time_utils import KST

NOW = datetime(2026, 11, 10, 8, tzinfo=UTC)


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        youtube_api_key="test",
        session_secret="x" * 32,
        cache_max_days=28,
    )


def test_cleanup_all_retention_boundaries(factory, settings, caplog):
    with factory() as db:
        for days in (27, 28, 29):
            fetched = NOW - timedelta(days=days)
            db.add(
                VideoCache(
                    video_id=str(days),
                    channel_id="channel",
                    title="video",
                    published_at=NOW,
                    fetched_at=fetched,
                )
            )
            db.add(
                ChannelCache(channel_id=str(days), title="channel", fetched_at=fetched)
            )
            db.add(
                VideoCategoryCache(
                    region_code="KR",
                    category_id=days,
                    title="category",
                    fetched_at=fetched,
                )
            )
        for seconds in (-1, 0, 1):
            db.add(
                SearchCache(
                    id=str(seconds),
                    cond_hash="a" * 64,
                    conditions="{}",
                    video_ids="[]",
                    funnel="{}",
                    expires_at=NOW + timedelta(seconds=seconds),
                )
            )
            db.add(
                QuotaUsage(
                    usage_date=date(2026, 8, 12),
                    endpoint="videos.list",
                    units=1,
                    called_at=NOW - timedelta(days=90) + timedelta(seconds=seconds),
                )
            )
        db.commit()
        with caplog.at_level(logging.INFO):
            counts = cleanup(db, settings, NOW.astimezone(KST))
        assert counts == {
            "search_cache": 2,
            "video_cache": 2,
            "channel_cache": 2,
            "video_category_cache": 2,
            "quota_usage": 2,
        }
    with factory() as db:
        assert db.scalars(select(VideoCache.video_id)).all() == ["27"]
        assert db.scalars(select(ChannelCache.channel_id)).all() == ["27"]
        assert db.scalars(select(VideoCategoryCache.category_id)).all() == [27]
        assert db.scalars(select(SearchCache.id)).all() == ["1"]
        assert db.scalar(select(QuotaUsage)).called_at == (
            NOW - timedelta(days=90) + timedelta(seconds=1)
        )
        assert cleanup(db, settings, NOW) == dict.fromkeys(counts, 0)
    for table in counts:
        assert table in caplog.text
    assert "deleted rows" in caplog.text


def test_cleanup_respects_configured_max_days(factory, settings):
    settings.cache_max_days = 2
    with factory() as db:
        db.add(
            ChannelCache(
                channel_id="expired", title="c", fetched_at=NOW - timedelta(days=2)
            )
        )
        db.commit()
        assert cleanup(db, settings, NOW)["channel_cache"] == 1


def test_failed_cleanup_rolls_back_all_deletions(factory, settings, monkeypatch):
    with factory() as db:
        db.add(
            ChannelCache(
                channel_id="expired", title="c", fetched_at=NOW - timedelta(days=29)
            )
        )
        db.commit()
        original_execute = db.execute

        def fail_on_quota(statement, *args, **kwargs):
            if statement.table.name == "quota_usage":
                raise OperationalError("private SQL", {}, Exception("private"))
            return original_execute(statement, *args, **kwargs)

        monkeypatch.setattr(db, "execute", fail_on_quota)
        with pytest.raises(OperationalError):
            cleanup(db, settings, NOW)
    with factory() as db:
        assert db.get(ChannelCache, "expired") is not None


@pytest.mark.parametrize(
    "instant, expected",
    [
        ("2026-11-10T02:59:59+09:00", "2026-11-10T03:00:00+09:00"),
        ("2026-11-10T03:00:00+09:00", "2026-11-11T03:00:00+09:00"),
        ("2026-11-10T03:00:01+09:00", "2026-11-11T03:00:00+09:00"),
        ("2026-12-31T18:00:00+00:00", "2027-01-02T03:00:00+09:00"),
    ],
)
def test_next_kst_schedule(instant, expected):
    assert next_cleanup_at(datetime.fromisoformat(instant)) == datetime.fromisoformat(
        expected
    )


def test_scheduler_repeats_recovers_and_cancels(factory, settings, monkeypatch, caplog):
    async def scenario():
        now = datetime(2026, 11, 10, 2, 59, tzinfo=KST)
        sleeps = []
        calls = []
        original_cleanup = cleanup

        def flaky_cleanup(db, config, instant):
            calls.append(instant)
            if len(calls) == 1:
                raise OperationalError("private SQL", {}, Exception("private"))
            return original_cleanup(db, config, instant)

        async def sleep(seconds):
            nonlocal now
            sleeps.append(seconds)
            if len(sleeps) == 4:
                raise asyncio.CancelledError
            # First wakeup is early, so it must sleep again before cleaning.
            now += timedelta(seconds=seconds / 2 if len(sleeps) == 1 else seconds)

        monkeypatch.setattr("app.jobs.cleanup.cleanup", flaky_cleanup)
        with pytest.raises(asyncio.CancelledError):
            await schedule_cleanup(factory, settings, clock=lambda: now, sleep=sleep)
        assert sleeps == [60, 30, 86400, 86400]
        assert calls == [
            datetime(2026, 11, 10, 3, tzinfo=KST),
            datetime(2026, 11, 11, 3, tzinfo=KST),
        ]

    asyncio.run(scenario())
    assert "cache cleanup failed" in caplog.text
    assert "private" not in caplog.text


def test_missing_database_warns_without_exposing_sql(settings, caplog):
    def broken_factory():
        raise OperationalError("private SQL", {}, Exception("private"))

    run_cleanup(broken_factory, settings, NOW)
    assert "cache cleanup failed" in caplog.text
    assert "private" not in caplog.text


def test_cancel_waits_for_inflight_cleanup(factory, settings, monkeypatch):
    async def scenario():
        now = datetime(2026, 11, 10, 2, 59, tzinfo=KST)
        entered = asyncio.Event()
        release = Event()
        finished = Event()
        loop = asyncio.get_running_loop()

        def slow_cleanup(*args):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(timeout=5)
            finished.set()

        async def sleep(seconds):
            nonlocal now
            now += timedelta(seconds=seconds)

        monkeypatch.setattr("app.jobs.cleanup.run_cleanup", slow_cleanup)
        task = asyncio.create_task(
            schedule_cleanup(factory, settings, clock=lambda: now, sleep=sleep)
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert finished.is_set()

    asyncio.run(scenario())


def test_lifespan_runs_once_starts_and_stops_task(factory, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    calls = []
    stopped = []
    tasks = []

    def startup_cleanup(*args):
        calls.append(args)

    async def scheduled(*args):
        tasks.append(asyncio.current_task())
        try:
            await asyncio.Event().wait()
        finally:
            stopped.append(True)

    monkeypatch.setattr("app.main.run_cleanup", startup_cleanup)
    monkeypatch.setattr("app.main.schedule_cleanup", scheduled)
    test_app = FastAPI(lifespan=lifespan)
    with TestClient(test_app):
        assert len(calls) == 1
        assert calls[0][0] is test_app.state.session_factory
        assert len(tasks) == 1
    assert stopped == [True]
    assert tasks[0].done()
