import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.cache.entity_cache import EntityCache
from app.cache.search_cache import SearchResultCache, condition_hash
from app.config import Settings
from app.models import ChannelCache, VideoCache
from app.time_utils import KST

NOW = datetime(2026, 11, 10, 8, tzinfo=UTC)


@pytest.fixture
def cache_settings():
    return Settings(
        _env_file=None,
        youtube_api_key="test",
        session_secret="x" * 32,
        cache_search_ttl_hours=6,
        cache_stats_ttl_hours=24,
        cache_max_days=28,
    )


def video(video_id="video", **kwargs):
    return VideoCache(
        video_id=video_id,
        channel_id="channel",
        title="영상",
        published_at=NOW,
        **kwargs,
    )


def channel(channel_id="channel", **kwargs):
    return ChannelCache(channel_id=channel_id, title="채널", **kwargs)


def test_hash_sorts_all_keys_and_includes_keyword_and_every_filter():
    first = {"keyword": "검색", "video": {"views": {"max": 10, "min": 1}}}
    second = {"video": {"views": {"min": 1, "max": 10}}, "keyword": "검색"}
    expected = hashlib.sha256(
        json.dumps(
            first, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    assert condition_hash(first) == condition_hash(second) == expected
    assert condition_hash(first | {"keyword": "다른 검색"}) != expected
    assert condition_hash(first | {"channel": {"countries": ["KR"]}}) != expected
    assert condition_hash({"tags": ["a", "b"]}) != condition_hash({"tags": ["b", "a"]})
    with pytest.raises(ValueError):
        condition_hash({"invalid": float("nan")})


@pytest.mark.parametrize("seconds, hit", [(-1, True), (0, False), (1, False)])
def test_search_six_hour_boundary(factory, cache_settings, seconds, hit):
    now = NOW
    cache = SearchResultCache(cache_settings, clock=lambda: now)
    conditions = {"keyword": "검색", "video": {"views": {"min": 1}}}
    with factory() as db:
        assert cache.get(db, conditions) is None
        saved = cache.save(
            db,
            conditions,
            ["b", "a"],
            {"final": 2},
            warnings=["PARTIAL_FAILURE"],
            quota_spent=101,
        )
        db.commit()
        search_id = saved.id
    with factory() as db:
        row = cache.get(db, conditions)
        assert row.id == search_id and len(search_id) == 32
        assert json.loads(row.conditions) == conditions
        assert json.loads(row.video_ids) == ["b", "a"]
        assert json.loads(row.funnel) == {"final": 2}
        assert json.loads(row.warnings) == ["PARTIAL_FAILURE"]
        assert row.quota_spent == 101
        assert row.expires_at == NOW + timedelta(hours=6)
        assert cache.get(db, conditions | {"keyword": "다름"}) is None
        now = (NOW + timedelta(hours=6, seconds=seconds)).astimezone(KST)
        assert (cache.get(db, conditions) is not None) is hit


def test_search_latest_and_empty_result_and_transaction(factory, cache_settings):
    now = NOW
    cache = SearchResultCache(cache_settings, clock=lambda: now)
    with factory() as db:
        cache.save(db, {"keyword": "q"}, ["old"], {})
        now += timedelta(seconds=1)
        row = cache.save(db, {"keyword": "q"}, [], {"final": 0})
        assert cache.get(db, {"keyword": "q"}).id == row.id
        assert row.video_ids == "[]"
        db.rollback()
        assert cache.get(db, {"keyword": "q"}) is None


@pytest.mark.parametrize("seconds, hit", [(-1, True), (0, False), (1, False)])
def test_entities_twenty_four_hour_boundary(factory, cache_settings, seconds, hit):
    now = NOW
    cache = EntityCache(cache_settings, clock=lambda: now)
    with factory() as db:
        cache.save_videos(db, [video(view_count=0, like_count=None)])
        cache.save_channels(
            db, [channel(hidden_subscriber=True, subscriber_count=None)]
        )
        db.commit()
    with factory() as db:
        assert cache.get_videos(db, ["video"])["video"].view_count == 0
        assert cache.get_channels(db, ["channel"])["channel"].subscriber_count is None
        now += timedelta(hours=24, seconds=seconds)
        assert bool(cache.get_videos(db, ["video", "missing"])) is hit
        assert bool(cache.get_channels(db, ["channel", "missing"])) is hit
        assert cache.get_videos(db, []) == cache.get_channels(db, []) == {}


def test_refresh_replaces_stats_and_timestamp(factory, cache_settings):
    now = NOW
    cache = EntityCache(cache_settings, clock=lambda: now)
    with factory() as db:
        cache.save_videos(db, [video(view_count=10, like_count=3)])
        cache.save_channels(db, [channel(subscriber_count=10)])
        db.commit()
    now += timedelta(days=2)
    with factory() as db:
        assert cache.get_videos(db, ["video"]) == {}
        cache.save_videos(db, [video(view_count=20, like_count=None)])
        cache.save_channels(
            db, [channel(subscriber_count=None, hidden_subscriber=True)]
        )
        db.commit()
    with factory() as db:
        refreshed = cache.get_videos(db, ["video"])["video"]
        assert (refreshed.view_count, refreshed.like_count) == (20, None)
        assert refreshed.fetched_at == now
        refreshed_channel = cache.get_channels(db, ["channel"])["channel"]
        assert refreshed_channel.subscriber_count is None
        assert refreshed_channel.hidden_subscriber
        assert refreshed_channel.fetched_at == now


def test_ttls_read_environment(factory, monkeypatch):
    monkeypatch.setenv("CACHE_SEARCH_TTL_HOURS", "2")
    monkeypatch.setenv("CACHE_STATS_TTL_HOURS", "3")
    monkeypatch.setenv("CACHE_MAX_DAYS", "1")
    settings = Settings(_env_file=None, youtube_api_key="test", session_secret="x" * 32)
    search = SearchResultCache(settings, clock=lambda: NOW)
    entities = EntityCache(settings, clock=lambda: NOW)
    with factory() as db:
        row = search.save(db, {}, [], {})
        assert row.expires_at == NOW + timedelta(hours=2)
        db.add(video(fetched_at=NOW - timedelta(hours=3)))
        db.flush()
        assert entities.get_videos(db, ["video"]) == {}
        # The retention limit still wins if the configured freshness exceeds it.
        settings.cache_stats_ttl_hours = 100
        db.add(video("old", fetched_at=NOW - timedelta(days=1)))
        db.flush()
        assert EntityCache(settings, clock=lambda: NOW).get_videos(db, ["old"]) == {}
