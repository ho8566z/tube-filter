from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from app.errors import DomainError
from app.models import QuotaUsage
from app.quota.guard import QuotaGuard
from app.quota.status import used_units
from app.youtube.adapter import HttpYouTubeAdapter
from tests.fakes.fake_youtube import CHANNELS, VIDEOS, FakeYouTubeAdapter

NOW = datetime(2026, 11, 10, 8, tzinfo=UTC)


@pytest.mark.parametrize(
    "endpoint", ["captions.list", "videos.insert", "https://x", "videos"]
)
def test_disallowed_endpoint_never_calls_or_records(factory, endpoint):
    fake = FakeYouTubeAdapter(QuotaGuard(factory, 9000), clock=lambda: NOW)
    with pytest.raises(ValueError):
        fake.request(endpoint, {})
    assert fake.calls == []
    with factory() as db:
        assert used_units(db, NOW) == 0


@pytest.mark.parametrize(
    "result",
    [
        httpx.ConnectError("private-key"),
        httpx.ReadTimeout("private-key"),
        httpx.Response(500, json={"error": {"message": "private-key"}}),
        httpx.Response(403, json={"error": {"errors": [{"reason": "forbidden"}]}}),
        httpx.Response(200, content="bad json private-key"),
        httpx.Response(200, json=[]),
    ],
)
def test_failed_attempts_stay_recorded(factory, result):
    fake = FakeYouTubeAdapter(QuotaGuard(factory, 9000), clock=lambda: NOW)
    fake.responses.append(result)
    with pytest.raises(DomainError) as exc:
        fake.request("search.list", {})
    assert exc.value.code == "UPSTREAM_ERROR"
    assert exc.value.status_code == 502
    assert "private-key" not in str(exc.value)
    with factory() as db:
        db.rollback()  # failure of caller work cannot undo the accounting
        assert used_units(db, NOW) == 100
        assert db.scalar(select(QuotaUsage)).search_id is None


def test_quota_exceeded_blocks_shared_guard_until_next_pt_day(factory):
    now = NOW
    guard = QuotaGuard(factory, 9000)
    fake = FakeYouTubeAdapter(guard, clock=lambda: now)
    fake.responses.append(
        httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}})
    )
    with pytest.raises(DomainError) as exc:
        fake.request("search.list", {})
    assert exc.value.code == "QUOTA_BLOCKED"
    assert exc.value.status_code == 503
    other = FakeYouTubeAdapter(guard, clock=lambda: now)
    with pytest.raises(DomainError):
        other.request("videos.list", {})
    assert other.calls == []
    with factory() as db:
        assert used_units(db, now) == 100
    now = datetime(2026, 11, 11, 8, tzinfo=UTC)
    other.request("videos.list", {})
    assert len(other.calls) == 1


def test_fake_fixed_data_is_independent_of_returned_mutations(factory):
    fake = FakeYouTubeAdapter(QuotaGuard(factory, 9000), clock=lambda: NOW)
    assert len(VIDEOS) == 30
    assert len(CHANNELS) == 10
    params = {"id": VIDEOS[0]["id"]}
    result = fake.request("videos.list", params)
    result["items"][0]["snippet"]["title"] = "changed"
    assert (
        fake.request("videos.list", params)["items"][0]["snippet"]["title"] == "Video 0"
    )


def test_http_transport_uses_only_official_url_and_environment_key(
    factory, monkeypatch
):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"items": []})

    real_client = httpx.Client
    monkeypatch.setattr(
        "app.youtube.adapter.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    adapter = HttpYouTubeAdapter(
        "test-key", QuotaGuard(factory, 9000), clock=lambda: NOW
    )
    for endpoint in (
        "search.list",
        "videos.list",
        "channels.list",
        "playlistItems.list",
        "videoCategories.list",
    ):
        adapter.request(endpoint, {"part": "snippet", "key": "wrong"})
    assert len(seen) == 5
    for request in seen:
        assert request.method == "GET"
        assert request.url.host == "www.googleapis.com"
        assert request.url.path.startswith("/youtube/v3/")
        assert request.url.params["key"] == "test-key"
