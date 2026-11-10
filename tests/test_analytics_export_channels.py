import asyncio
import csv
import io
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analysis.heatmap import heatmap
from app.analysis.scatter import scatter
from app.analysis.service import router as analysis_router
from app.analysis.summary import summarize
from app.cache.entity_cache import EntityCache
from app.channels.pattern import upload_pattern
from app.channels.service import channel_detail
from app.channels.service import router as channels_router
from app.config import Settings
from app.errors import DomainError, register_error_handlers
from app.export.csv import export_csv, safe_cell
from app.export.csv import router as export_router
from app.limits.limiter import Limiter
from app.models import ChannelCache, SearchCache, VideoCache
from app.quota.guard import QuotaGuard
from app.search.channels import fetch_channels
from app.search.conditions import normalize
from app.search.metrics import CALCULATED_LABEL
from app.search.service import SearchService
from app.users.auth import SecurityMiddleware
from app.youtube.adapter import get_youtube
from tests.fakes.fake_youtube import CHANNELS, FakeYouTubeAdapter

NOW = datetime(2026, 11, 10, 8, tzinfo=UTC)


@pytest.fixture
def setup(factory):
    settings = Settings(_env_file=None, youtube_api_key="test", session_secret="x" * 32)
    return settings, FakeYouTubeAdapter(QuotaGuard(factory, 9000), clock=lambda: NOW)


def item(views=0, subscribers=0, like=None, ratio=None):
    return {
        "videoId": "id",
        "title": "한글,제목\n다음 줄",
        "channelTitle": "채널",
        "publishedAt": "2026-11-10T17:00:00+09:00",
        "durationSec": 0,
        "stats": {"views": views, "likes": None, "comments": None},
        "channel": {"subscribers": subscribers},
        "calc": {"likeRatePct": like, "viewsPerSubPct": ratio},
    }


def test_summary_empty_null_odd_even_zero_and_rounding():
    empty = summarize([])
    assert empty["count"] == 0
    assert empty["views"] == {"avg": None, "median": None, "max": None}
    assert empty["label"] == CALCULATED_LABEL
    values = [item(v, like=v, ratio=v) for v in [None, 0, 1, 2]]
    result = summarize(values)
    assert result["count"] == 4
    assert result["views"] == {"avg": 1, "median": 1, "max": 2}
    result = summarize([item(0), item(1)])
    assert result["views"]["median"] == 0.5
    assert summarize([item(1), item(0), item(0)])["views"]["avg"] == 0.33


def test_scatter_nulls_zero_and_limit():
    assert scatter([]) == []
    assert scatter([item(None), item(subscribers=None)]) == []
    assert scatter([item()])[0]["subscribers"] == 0
    assert scatter([item()])[0]["views"] == 0
    assert len(scatter([item()] * 501)) == 500


def test_kst_week_month_year_hour_boundaries_and_pattern_limit():
    dates = [
        datetime(2026, 11, 8, 14, 59, 59, tzinfo=UTC),  # Sunday 23:59
        datetime(2026, 11, 8, 15, tzinfo=UTC),  # Monday 00:00
        datetime(2026, 12, 31, 15, tzinfo=UTC),  # January 1
    ]
    result = heatmap(dates + [None])
    assert len(result["matrix"]) == 7
    assert all(len(row) == 24 for row in result["matrix"])
    assert result["matrix"][6][23] == 1
    assert result["matrix"][0][0] == 1
    assert result["max"] == 1
    assert heatmap([])["max"] == 0
    assert upload_pattern(dates)["monthly"] == [
        {"month": "2026-11", "count": 2},
        {"month": "2027-01", "count": 1},
    ]
    assert upload_pattern([])["monthly"] == []
    assert upload_pattern(dates[:1] * 51)["monthly"][0]["count"] == 50


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t=", "\r@", "  +"])
def test_csv_formula_injection_all_text_columns(prefix):
    row = item()
    for key in ("videoId", "title", "channelTitle"):
        row[key] = prefix + 'SUM(1,2)\n"quoted"'
    data = export_csv([row], NOW)
    assert data.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    assert rows[2][:3] == [
        "'" + row[key] for key in ("videoId", "title", "channelTitle")
    ]
    assert CALCULATED_LABEL in rows[0][0]
    assert "YouTube Data API v3" in rows[0][0] and "+09:00" in rows[0][0]
    assert "계산값" in rows[1][-1] and "계산값" in rows[1][-2]
    assert rows[2][4:6] == ["0", "0"]
    assert rows[2][6:8] == ["", ""]
    assert safe_cell(None) is None


def test_csv_empty_unicode_sort_and_1000_row_limit():
    assert (
        len(list(csv.reader(io.StringIO(export_csv([], NOW).decode("utf-8-sig"))))) == 2
    )
    values = [item(i) for i in range(1001)]
    data = list(
        csv.reader(
            io.StringIO(export_csv(values, NOW, sort="views").decode("utf-8-sig"))
        )
    )
    assert len(data) == 1002
    assert data[2][5] == "1000" and data[-1][5] == "1"
    assert data[2][1] == values[0]["title"]


def test_public_api_cache_only_full_results_and_expiry(factory, setup):
    settings, fake = setup
    with factory() as db:
        service = SearchService(db, fake, settings, clock=lambda: NOW)
        result = asyncio.run(service.execute(normalize({"keyword": "x"}, now=NOW)))
        search_id = result["searchId"]
        empty = service.search_cache.save(
            db, {"keyword": "empty"}, [], {}, search_id="empty"
        )
        db.commit()
        assert empty.id == "empty"
    fake.calls.clear()
    app = FastAPI()
    register_error_handlers(app)
    for router in (analysis_router, export_router, channels_router):
        app.include_router(router)
    app.add_middleware(SecurityMiddleware)
    app.state.settings = settings
    app.state.session_factory = factory
    app.state.clock = lambda: NOW
    app.state.limiter = Limiter(settings, clock=lambda: NOW)
    app.dependency_overrides[get_youtube] = lambda: fake
    with TestClient(app) as client:
        base = f"/api/v1/search/{search_id}"
        summary = client.get(base + "/summary").json()
        assert summary["count"] == 30  # all pages
        assert summary["label"] == CALCULATED_LABEL
        assert len(client.get(base + "/scatter").json()) == 30
        assert client.get(base + "/heatmap").json()["max"] == 30
        response = client.get(base + "/export.csv?sort=views&order=asc")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert response.headers["content-disposition"].startswith("attachment;")
        assert (
            len(list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")))))
            == 32
        )
        for query in ("sort=invalid", "order=invalid"):
            assert (
                client.get(base + "/export.csv?" + query).json()["code"]
                == "INVALID_SORT"
            )
        assert fake.calls == []
        for suffix in ("summary", "scatter", "heatmap", "export.csv"):
            assert client.get(f"/api/v1/search/empty/{suffix}").status_code == 200
            assert (
                client.get(f"/api/v1/search/missing/{suffix}").json()["code"]
                == "SEARCH_NOT_FOUND"
            )
        with factory() as db:
            db.get(SearchCache, search_id).expires_at = NOW
            db.commit()
        for suffix in ("summary", "scatter", "heatmap", "export.csv"):
            assert client.get(base + "/" + suffix).json()["code"] == "SEARCH_NOT_FOUND"
        assert client.get("/api/v1/channels/" + CHANNELS[0]["id"]).status_code == 200
        assert (
            client.get("/api/v1/channels/missing").json()["code"] == "CHANNEL_NOT_FOUND"
        )
        fake.guard.soft_limit = 0
        blocked = client.get("/api/v1/channels/uncached")
        assert blocked.status_code == 503 and blocked.json()["code"] == "QUOTA_BLOCKED"


def test_channel_warm_cache_missing_hidden_and_quota_fallback(factory, setup):
    settings, fake = setup
    key = CHANNELS[0]["id"]
    with factory() as db:
        service = SearchService(db, fake, settings, clock=lambda: NOW)
        detail = asyncio.run(channel_detail(service, key))
        assert detail["channel"]["subscribers"] == 0
        assert len(detail["recentVideos"]) == 3
        assert detail["pattern"]["monthly"] == [{"month": "2026-11", "count": 3}]
        assert [endpoint for endpoint, _ in fake.calls] == [
            "channels.list",
            "playlistItems.list",
            "videos.list",
        ]
        assert all(
            item["calc"]["label"] == CALCULATED_LABEL for item in detail["recentVideos"]
        )
        fake.calls.clear()
        assert asyncio.run(channel_detail(service, key)) == detail
        assert fake.calls == []
        with pytest.raises(DomainError) as exc:
            asyncio.run(channel_detail(service, "missing"))
        assert exc.value.code == "CHANNEL_NOT_FOUND"
        fake.calls.clear()
        row = db.get(ChannelCache, key)
        row.hidden_subscriber = True
        row.subscriber_count = 100
        row.fetched_at = NOW - timedelta(hours=24)
        row.recent_fetched_at = NOW - timedelta(hours=24)
        for video in db.query(VideoCache).all():
            video.fetched_at = NOW - timedelta(hours=24)
        db.commit()
        fake.guard.soft_limit = 0
        stale = asyncio.run(channel_detail(service, key))
        assert stale["channel"]["subscribers"] is None
        assert len(stale["recentVideos"]) == 3
        assert "STALE_STATS" in stale["warnings"]
        assert fake.calls == []
        with pytest.raises(DomainError) as exc:
            asyncio.run(channel_detail(service, "uncached"))
        assert exc.value.code == "QUOTA_BLOCKED"
        row.fetched_at = NOW - timedelta(days=28)
        db.commit()
        with pytest.raises(DomainError) as exc:
            asyncio.run(channel_detail(service, key))
        assert exc.value.code == "QUOTA_BLOCKED"


def test_legacy_activity_cache_upgrades_once_without_new_schema(factory, setup):
    settings, fake = setup
    with factory() as db:
        service = SearchService(db, fake, settings, clock=lambda: NOW)
        asyncio.run(channel_detail(service, CHANNELS[0]["id"]))
        row = db.get(ChannelCache, CHANNELS[0]["id"])
        row.recent_uploads = json.dumps([NOW.isoformat()])
        db.commit()
        fake.calls.clear()
        result = asyncio.run(channel_detail(service, row.channel_id))
        assert len(result["recentVideos"]) == 3
        assert [call[0] for call in fake.calls] == ["playlistItems.list"]
        cached = EntityCache(settings, lambda: NOW).get_channel_activity(
            db, [row.channel_id]
        )
        assert len(cached[row.channel_id].video_ids) == 3


def test_channel_limits_fifty_and_empty_uploads(factory, setup):
    settings, fake = setup

    class ManyUploads(FakeYouTubeAdapter):
        def _send(self, endpoint, params):
            response = super()._send(endpoint, params)
            if endpoint == "playlistItems.list":
                payload = response.json()
                payload["items"] = payload["items"] * 20
                response = type(response)(200, json=payload)
            return response

    fake = ManyUploads(fake.guard, clock=lambda: NOW)
    with factory() as db:
        service = SearchService(db, fake, settings, clock=lambda: NOW)
        result = asyncio.run(channel_detail(service, CHANNELS[0]["id"]))
        assert sum(row["count"] for row in result["pattern"]["monthly"]) == 50
        assert len(result["recentVideos"]) <= 50
        # Empty upload playlist is a successful cache hit on subsequent views.
        key = CHANNELS[1]["id"]
        fetch_channels(db, fake, service.cache, [key])
        db.commit()
        fake.responses = [httpx.Response(200, json={"items": []})]
        result = asyncio.run(channel_detail(service, key))
        assert result["recentVideos"] == [] and result["pattern"]["monthly"] == []
        fake.calls.clear()
        asyncio.run(channel_detail(service, key))
        assert fake.calls == []


def test_analytics_share_other_request_rate_limit(setup):
    settings, _ = setup
    limiter = Limiter(settings, clock=lambda: NOW)
    for _ in range(60):
        limiter.check_request("ip", "/api/v1/search/id/summary")
    with pytest.raises(DomainError) as exc:
        limiter.check_request("ip", "/api/v1/search/id/export.csv")
    assert exc.value.code == "TOO_MANY_REQUESTS"
    limiter.check_request("ip", "/api/v1/search")


def test_quota_blocked_channel_without_playlist_cache_shows_cached_videos(
    factory, setup
):
    settings, fake = setup
    with factory() as db:
        service = SearchService(db, fake, settings, clock=lambda: NOW)
        key = CHANNELS[0]["id"]
        asyncio.run(channel_detail(service, key))
        row = db.get(ChannelCache, key)
        row.recent_uploads = None
        row.recent_fetched_at = None
        db.commit()
        fake.guard.soft_limit = 0
        fake.calls.clear()
        result = asyncio.run(channel_detail(service, key))
        assert len(result["recentVideos"]) == 3
        assert result["pattern"]["monthly"] == [{"month": "2026-11", "count": 3}]
        assert "STALE_STATS" in result["warnings"]
        assert fake.calls == []
        # The 28-day storage boundary also applies to fallback video data.
        for video in db.query(VideoCache).all():
            video.fetched_at = NOW - timedelta(days=28)
        db.commit()
        result = asyncio.run(channel_detail(service, key))
        assert result["recentVideos"] == [] and result["pattern"]["monthly"] == []


def test_analysis_uses_stale_cache_without_api_and_excludes_max_age(factory, setup):
    settings, fake = setup
    with factory() as db:
        service = SearchService(db, fake, settings, clock=lambda: NOW)
        result = asyncio.run(service.execute(normalize({"keyword": "x"}, now=NOW)))
        for video in db.query(VideoCache).all():
            video.fetched_at = NOW - timedelta(hours=24)
        db.commit()
        fake.calls.clear()
        items, warnings = asyncio.run(service.all_results(result["searchId"]))
        assert len(items) == 30 and warnings == ["STALE_STATS"]
        assert fake.calls == []
        for video in db.query(VideoCache).all():
            video.fetched_at = NOW - timedelta(days=28)
        db.commit()
        items, warnings = asyncio.run(service.all_results(result["searchId"]))
        assert items == [] and fake.calls == []
