import asyncio
import threading
from datetime import UTC, datetime, timedelta

import pytest

from app.cache.entity_cache import EntityCache
from app.config import Settings
from app.errors import DomainError
from app.models import ChannelCache
from app.search.activity import ActivityConditions, fetch_activity
from app.search.channel_info import ChannelInfo
from app.search.channels import fetch_channels
from app.search.filters_video import NumberRange

NOW = datetime(2026, 11, 10, tzinfo=UTC)


class MockAdapter:
    """In-memory adapter; the barrier proves two requests overlap."""

    def __init__(self, barrier=None):
        self.calls = []
        self.fail = set()
        self.omit = set()
        self.barrier = barrier

    def request(self, endpoint, params, *, search_id=None):
        self.calls.append((endpoint, params, search_id))
        if endpoint == "channels.list":
            ids = params["id"].split(",")
            if ids[0] in self.fail:
                raise DomainError("UPSTREAM_ERROR", "실패", 502)
            return {
                "items": [
                    {
                        "id": key,
                        "snippet": {"title": key},
                        "statistics": {"subscriberCount": "0"},
                        "contentDetails": {"relatedPlaylists": {"uploads": key}},
                    }
                    for key in ids
                    if key not in self.omit
                ]
            }
        if self.barrier:
            self.barrier.wait(timeout=5)
        if params["playlistId"] in self.fail:
            raise DomainError("UPSTREAM_ERROR", "실패", 502)
        return {
            "items": [{"contentDetails": {"videoPublishedAt": NOW.isoformat()}}],
            "nextPageToken": "must-not-follow",
        }


@pytest.fixture
def cache():
    return EntityCache(
        Settings(_env_file=None, youtube_api_key="test", session_secret="x" * 32),
        clock=lambda: NOW,
    )


def seed(db, cache, count=2):
    cache.save_channels(
        db,
        [
            ChannelCache(channel_id=str(i), title=str(i), uploads_playlist_id=str(i))
            for i in range(count)
        ],
    )
    return [
        ChannelInfo(channel_id=str(i), uploads_playlist_id=str(i)) for i in range(count)
    ]


def test_channels_batch_dedup_cache_partial_and_order(factory, cache):
    adapter = MockAdapter()
    adapter.omit = {"missing"}
    ids = [str(i) for i in range(101)]
    with factory() as db:
        result = fetch_channels(
            db, adapter, cache, ids + ["0", "missing"], search_id="s"
        )
        assert [c.channel_id for c in result.channels] == ids
        assert result.unavailable_ids == ("missing",)
        assert result.warnings == ("PARTIAL_FAILURE",)
        assert [len(call[1]["id"].split(",")) for call in adapter.calls] == [50, 50, 2]
        assert all(
            call[1]["part"] == "snippet,statistics,contentDetails" and call[2] == "s"
            for call in adapter.calls
        )
        adapter.calls.clear()
        assert len(fetch_channels(db, adapter, cache, ids).channels) == 101
        assert adapter.calls == []
        assert fetch_channels(db, adapter, cache, []).channels == ()


def test_channel_batch_failure_does_not_discard_success(factory, cache):
    adapter = MockAdapter()
    adapter.fail = {"0"}
    with factory() as db:
        result = fetch_channels(db, adapter, cache, [str(i) for i in range(51)])
        assert [c.channel_id for c in result.channels] == ["50"]
        assert len(result.unavailable_ids) == 50


@pytest.mark.parametrize("seconds,hit", [(-1, True), (0, False), (1, False)])
def test_channel_and_activity_independent_ttl(factory, cache, seconds, hit):
    adapter = MockAdapter()
    with factory() as db:
        channels = seed(db, cache, 1)
        conditions = ActivityConditions(count=NumberRange(min=0))
        asyncio.run(fetch_activity(db, adapter, cache, channels, conditions, now=NOW))
        row = db.get(ChannelCache, "0")
        assert row.recent_fetched_at == NOW
        # Statistics refresh must preserve activity data without extending its TTL.
        later = NOW + timedelta(hours=24, seconds=seconds)
        cache.clock = lambda: later
        cache.save_channels(db, [ChannelCache(channel_id="0", title="new")])
        assert bool(cache.get_channel_activity(db, ["0"])) is hit
        before = len(adapter.calls)
        asyncio.run(fetch_activity(db, adapter, cache, channels, conditions, now=later))
        assert len(adapter.calls) - before == (0 if hit else 1)
        assert row.fetched_at == later
        # Updating activity must not refresh an old statistics timestamp.
        row.fetched_at = NOW - timedelta(days=2)
        cache.save_channel_activity(db, "0", cache.get_channel_activity(db, ["0"])["0"])
        assert cache.get_channels(db, ["0"]) == {}


def test_activity_parallel_single_call_and_cache(factory, cache):
    adapter = MockAdapter(threading.Barrier(2))
    with factory() as db:
        channels = seed(db, cache)
        conditions = ActivityConditions(
            count=NumberRange(1, 1), last_upload_within_days=30
        )
        result = asyncio.run(
            fetch_activity(
                db,
                adapter,
                cache,
                channels + channels,
                conditions,
                now=NOW,
                search_id="s",
            )
        )
        assert all(value.passed for value in result.results.values())
        assert len(adapter.calls) == 2
        assert all(
            call[0] == "playlistItems.list"
            and call[1]["maxResults"] == 50
            and call[1]["part"] == "contentDetails"
            and call[2] == "s"
            for call in adapter.calls
        )
        again = asyncio.run(
            fetch_activity(db, adapter, cache, channels, conditions, now=NOW)
        )
        assert again == result
        assert len(adapter.calls) == 2


def test_activity_skip_limit_failure_and_missing_playlist(factory, cache):
    adapter = MockAdapter()
    with factory() as db:
        channels = seed(db, cache, 52)
        disabled = asyncio.run(fetch_activity(db, adapter, cache, channels, now=NOW))
        assert disabled.results == {} and adapter.calls == []
        adapter.fail = {"0"}
        channels[1] = ChannelInfo(channel_id="1")
        result = asyncio.run(
            fetch_activity(
                db,
                adapter,
                cache,
                channels,
                ActivityConditions(count=NumberRange(min=0)),
                now=NOW,
            )
        )
        assert len(adapter.calls) == 49
        assert result.limited_ids == ("50", "51")
        assert result.warnings == ("PARTIAL_FAILURE", "ACTIVITY_LIMIT")
        assert not result.results["0"].passed and not result.results["1"].passed
        assert result.results["2"].passed
        assert db.get(ChannelCache, "0").recent_fetched_at is None
        assert db.get(ChannelCache, "2").recent_fetched_at == NOW


def test_activity_fifty_requests_preserves_first_occurrence_order(factory, cache):
    adapter = MockAdapter()
    with factory() as db:
        channels = seed(db, cache, 52)
        result = asyncio.run(
            fetch_activity(
                db,
                adapter,
                cache,
                channels + channels[:1],
                ActivityConditions(count=NumberRange(min=0)),
                now=NOW,
            )
        )
        assert len(adapter.calls) == 50
        assert result.limited_ids == ("50", "51")
        assert len(result.results) == 50


def test_successful_empty_playlist_is_cached(factory, cache):
    class EmptyAdapter:
        def __init__(self):
            self.calls = 0

        def request(self, endpoint, params, *, search_id=None):
            self.calls += 1
            return {"items": []}

    adapter = EmptyAdapter()
    with factory() as db:
        channels = seed(db, cache, 1)
        conditions = ActivityConditions(count=NumberRange(0, 0))
        for _ in range(2):
            result = asyncio.run(
                fetch_activity(
                    db,
                    adapter,
                    cache,
                    channels,
                    conditions,
                    now=NOW,
                )
            )
            assert result.results["0"].passed
            assert result.activities["0"].upload_dates == ()
        assert adapter.calls == 1
