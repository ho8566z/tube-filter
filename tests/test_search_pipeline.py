import asyncio
import json
import threading
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db import get_db
from app.errors import DomainError, register_error_handlers
from app.limits.limiter import Limiter
from app.meta.service import metadata
from app.meta.service import router as meta_router
from app.models import SearchCache, VideoCache, VideoCategoryCache
from app.quota.estimate import estimate
from app.quota.guard import QuotaGuard
from app.quota.status import used_units
from app.search.candidates import fetch_candidates, search_params
from app.search.conditions import normalize
from app.search.details import fetch_details
from app.search.paging import paginate
from app.search.service import SearchService, get_service, router
from app.users.auth import SecurityMiddleware
from app.users.auth import router as auth_router
from app.youtube.adapter import get_youtube
from tests.fakes.fake_youtube import CHANNELS, VIDEOS, FakeYouTubeAdapter

NOW = datetime(2026, 11, 10, 8, tzinfo=UTC)


@pytest.fixture
def setup(factory):
    settings = Settings(_env_file=None, youtube_api_key="test", session_secret="x" * 32)
    fake = FakeYouTubeAdapter(QuotaGuard(factory, 9000), clock=lambda: NOW)
    return settings, fake


def execute(service, body, **kwargs):
    return asyncio.run(
        service.execute(
            normalize({"keyword": "x", **body}, now=service.clock()), **kwargs
        )
    )


def test_pipeline_funnel_cache_quota_paging_and_guest_hook(factory, setup):
    settings, fake = setup
    hooks = []
    with factory() as db:
        service = SearchService(db, fake, settings, clock=lambda: NOW)
        body = {
            "video": {"views": {"min": 1000}},
            "channel": {
                "subscribers": {"max": 500},
                "activity": {"countMin": 3, "lastUploadWithinDays": 30},
            },
        }
        result = execute(service, body, on_new_search=lambda: hooks.append("new"))
        funnel = result["funnel"]
        assert [
            funnel[key]
            for key in (
                "candidates",
                "afterVideoFilters",
                "afterChannelFilters",
                "afterActivityFilters",
                "final",
            )
        ] == [30, 20, 12, 12, 12]
        assert funnel["drops"]["VIEWS"] == 10
        assert funnel["drops"]["SUBSCRIBERS"] == 8
        assert sum(funnel["drops"].values()) == 30 - 12
        assert (
            result["quota"]["spent"] == 108
        )  # search + details + channels + six uploads
        assert result["page"]["totalElements"] == 12
        assert result["page"]["size"] == 20
        assert result["page"]["items"][0]["publishedAt"].endswith("+09:00")
        assert "likeRatePct" in result["page"]["items"][0]["calc"]
        calls = len(fake.calls)
        again = execute(service, body, on_new_search=lambda: hooks.append("bad"))
        assert again["cached"] and again["searchId"] == result["searchId"]
        assert again["quota"]["spent"] == 0
        assert len(fake.calls) == calls and hooks == ["new"]
        assert again["funnel"] == result["funnel"]
        assert again["page"] == result["page"]
        assert json.loads(db.get(SearchCache, result["searchId"]).video_ids)
        page = asyncio.run(
            service.results(
                result["searchId"], sort="views", order="desc", size=10, page=1
            )
        )
        assert [item["stats"]["views"] for item in page["items"]] == [1100, 1000]
        assert page["totalPages"] == 2
        assert len(fake.calls) == calls


@pytest.mark.parametrize(
    "body,endpoint",
    [
        ({"video": {"views": {"min": 10000}}}, "channels.list"),
        (
            {"channel": {"subscribers": {"min": 10000}, "activity": {"countMin": 1}}},
            "playlistItems.list",
        ),
    ],
)
def test_early_exit_skips_later_calls(factory, setup, body, endpoint):
    settings, fake = setup
    with factory() as db:
        result = execute(SearchService(db, fake, settings, clock=lambda: NOW), body)
        assert result["page"]["items"] == []
        assert not any(call[0] == endpoint for call in fake.calls)
        assert sum(result["funnel"]["drops"].values()) == 30


def test_zero_candidates_and_hidden_drop(factory, setup):
    settings, fake = setup
    with factory() as db:
        service = SearchService(db, fake, settings, clock=lambda: NOW)
        fake.responses = [httpx.Response(200, json={"items": []})]
        result = execute(service, {})
        assert len(fake.calls) == 1 and result["funnel"]["final"] == 0
        result = execute(
            service, {"keyword": "hidden", "video": {"comments": {"min": 0}}}
        )
        assert result["funnel"]["hiddenValues"] == 30
        assert result["funnel"]["filterDrops"] == {"COMMENTS": 30}


def test_estimate_without_upstream_calls(factory, setup):
    settings, fake = setup
    with factory() as db:
        service = SearchService(db, fake, settings, clock=lambda: NOW)
        c = normalize({"keyword": "x"})
        assert (
            estimate(db, c, service.search_cache, settings, NOW)["estimatedUnits"]
            == 204
        )
        active = normalize({"keyword": "x", "channel": {"activity": {"countMin": 0}}})
        assert (
            estimate(db, active, service.search_cache, settings, NOW)["estimatedUnits"]
            == 254
        )
        assert fake.calls == []
        execute(service, {})
        calls = len(fake.calls)
        result = estimate(db, c, service.search_cache, settings, NOW)
        assert result["estimatedUnits"] == 0 and result["cached"]
        assert result["estimatedSearchesLeft"] is None
        assert len(fake.calls) == calls


def test_soft_limit_cache_still_works_and_new_search_rejected(factory, setup):
    settings, fake = setup
    with factory() as db:
        service = SearchService(db, fake, settings, clock=lambda: NOW)
        first = execute(service, {})
        fake.guard.soft_limit = first["quota"]["usedToday"]
        calls = len(fake.calls)
        cached = execute(service, {})
        assert cached["quota"]["spent"] == 0
        with pytest.raises(DomainError, match="한도") as exc:
            execute(service, {"keyword": "new"})
        assert exc.value.code == "QUOTA_BLOCKED"
        assert len(fake.calls) == calls


def test_soft_limit_reached_between_stages_keeps_video_results(factory, setup):
    settings, fake = setup
    fake.guard.soft_limit = 101
    with factory() as db:
        service = SearchService(db, fake, settings, clock=lambda: NOW)
        result = execute(service, {})
        assert result["quota"]["spent"] == 101
        assert result["page"]["totalElements"] == 30
        assert [endpoint for endpoint, _ in fake.calls] == [
            "search.list",
            "videos.list",
        ]
        assert result["warnings"] == ["PARTIAL_FAILURE"]
        assert execute(service, {})["quota"]["spent"] == 0


def test_partial_search_page_failure_retains_cached_candidates(factory, setup):
    settings, fake = setup
    with factory() as db:
        service = SearchService(db, fake, settings, clock=lambda: NOW)
        execute(service, {})  # seed entity caches
        fake.responses = [
            httpx.Response(
                200,
                json={
                    "items": [{"id": {"videoId": VIDEOS[0]["id"]}}],
                    "nextPageToken": "next",
                },
            ),
            httpx.Response(500, json={"error": {}}),
        ]
        result = execute(service, {"keyword": "partial"})
        assert result["page"]["totalElements"] == 1
        assert result["warnings"] == ["PARTIAL_FAILURE"]
        assert result["quota"]["spent"] == 200


def test_quota_exceeded_mid_search_preserves_cached_result(factory, setup):
    settings, fake = setup
    with factory() as db:
        service = SearchService(db, fake, settings, clock=lambda: NOW)
        execute(service, {})
        fake.responses = [
            httpx.Response(
                200,
                json={
                    "items": [{"id": {"videoId": VIDEOS[0]["id"]}}],
                    "nextPageToken": "next",
                },
            ),
            httpx.Response(
                403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}}
            ),
        ]
        result = execute(service, {"keyword": "partial"})
        assert result["page"]["totalElements"] == 1
        assert result["warnings"] == ["PARTIAL_FAILURE"]
        calls = len(fake.calls)
        with pytest.raises(DomainError):
            execute(service, {"keyword": "blocked"})
        assert len(fake.calls) == calls


def test_candidate_mapping_pages_and_dedup(factory, setup):
    _, fake = setup
    c = normalize(
        {
            "keyword": "x",
            "pages": 5,
            "order": "date",
            "published": {"after": "2026-10-01", "before": "2026-11-01"},
            "video": {
                "hd": True,
                "caption": True,
                "cc": True,
                "embeddable": True,
                "regionCode": "US",
                "relevanceLanguage": "en",
                "categoryIds": {"include": [27]},
            },
        }
    )
    params = search_params(c)
    assert params == {
        "part": "id",
        "type": "video",
        "maxResults": 50,
        "safeSearch": "moderate",
        "q": "x",
        "order": "date",
        "publishedAfter": "2026-09-30T15:00:00+00:00",
        "publishedBefore": "2026-10-31T15:00:00+00:00",
        "videoDefinition": "high",
        "videoCaption": "closedCaption",
        "videoLicense": "creativeCommon",
        "videoEmbeddable": "true",
        "regionCode": "US",
        "relevanceLanguage": "en",
        "videoCategoryId": "27",
    }
    payload = {"items": [{"id": {"videoId": "one"}}], "nextPageToken": "next"}
    fake.responses = [httpx.Response(200, json=payload) for _ in range(5)]
    ids, warnings = asyncio.run(fetch_candidates(fake, c, search_id="s"))
    assert ids == ["one"] and warnings == [] and len(fake.calls) == 5
    assert fake.calls[1][1]["pageToken"] == "next"
    c = normalize({"keyword": "x", "video": {"categoryIds": {"include": [10, 27]}}})
    assert "videoCategoryId" not in search_params(c)


class HundredAdapter(FakeYouTubeAdapter):
    """Barrier requires two detail and two channel batches to overlap."""

    def __init__(self, guard):
        super().__init__(guard, clock=lambda: NOW)
        self.barrier = threading.Barrier(2)
        self.videos, self.channels = [], []
        for i in range(100):
            video, channel = deepcopy(VIDEOS[i % 30]), deepcopy(CHANNELS[i % 10])
            channel["id"] = f"UC{i:022d}"
            video["id"] = f"v{i:010d}"
            video["snippet"]["channelId"] = channel["id"]
            self.videos.append(video)
            self.channels.append(channel)

    def _send(self, endpoint, params):
        self.calls.append((endpoint, deepcopy(params)))
        if endpoint == "playlistItems.list":
            return httpx.Response(
                200,
                json={
                    "items": [{"contentDetails": {"videoPublishedAt": NOW.isoformat()}}]
                },
            )
        if endpoint == "search.list":
            start = 50 if params.get("pageToken") else 0
            payload = {
                "items": [
                    {"id": {"videoId": v["id"]}}
                    for v in self.videos[start : start + 50]
                ]
            }
            if start == 0:
                payload["nextPageToken"] = "next"
            return httpx.Response(200, json=payload)
        self.barrier.wait(timeout=5)
        data = self.videos if endpoint == "videos.list" else self.channels
        return httpx.Response(
            200,
            json={
                "items": [
                    item for item in data if item["id"] in params["id"].split(",")
                ]
            },
        )


def test_hundred_candidates_parallel_video_and_channel_batches(factory, setup):
    settings, _ = setup
    fake = HundredAdapter(QuotaGuard(factory, 9000))
    with factory() as db:
        result = execute(SearchService(db, fake, settings, clock=lambda: NOW), {})
        assert result["funnel"]["final"] == 100
        assert result["quota"]["spent"] == 204
        assert result["page"]["totalPages"] == 5
        assert len(fake.calls) == 6
        assert all(
            len(p["id"].split(",")) == 50
            for endpoint, p in fake.calls
            if endpoint != "search.list"
        )


def test_activity_limit_pipeline_counts_excluded_videos(factory, setup):
    settings, _ = setup
    fake = HundredAdapter(QuotaGuard(factory, 9000))
    with factory() as db:
        result = execute(
            SearchService(db, fake, settings, clock=lambda: NOW),
            {"channel": {"activity": {"countMin": 1}}},
        )
        assert result["funnel"]["afterChannelFilters"] == 100
        assert result["funnel"]["final"] == 50
        assert result["funnel"]["drops"] == {"ACTIVITY": 50}
        assert result["warnings"] == ["ACTIVITY_LIMIT"]
        assert result["quota"]["spent"] == 254
        assert sum(endpoint == "playlistItems.list" for endpoint, _ in fake.calls) == 50
        assert json.loads(db.get(SearchCache, result["searchId"]).video_ids) == [
            v["id"] for v in fake.videos[:50]
        ]


def test_detail_partial_batch_failure_keeps_other_batch(factory, setup):
    settings, _ = setup

    class PartialAdapter:
        def request(self, endpoint, params, *, search_id=None):
            if params["id"].startswith("failed"):
                raise DomainError("UPSTREAM_ERROR", "일부 실패", 502)
            return {"items": [deepcopy(VIDEOS[0])]}

    with factory() as db:
        service = SearchService(db, PartialAdapter(), settings, clock=lambda: NOW)
        ids = [f"failed{i}" for i in range(50)] + [VIDEOS[0]["id"]]
        result = asyncio.run(fetch_details(db, service.adapter, service.cache, ids))
        assert [v.video_id for v in result.videos] == [VIDEOS[0]["id"]]
        assert result.failed_ids == ids[:50]
        assert result.deleted_ids == []
        assert result.warnings == ["PARTIAL_FAILURE"]


def test_channel_lookup_failure_only_excludes_when_conditions_enabled(factory, setup):
    settings, fake = setup

    class MissingChannelAdapter(FakeYouTubeAdapter):
        def _send(self, endpoint, params):
            if endpoint == "channels.list":
                self.calls.append((endpoint, deepcopy(params)))
                return httpx.Response(500, json={"error": {}})
            return super()._send(endpoint, params)

    fake = MissingChannelAdapter(fake.guard, clock=lambda: NOW)
    with factory() as db:
        service = SearchService(db, fake, settings, clock=lambda: NOW)
        result = execute(service, {})
        assert result["page"]["totalElements"] == 30
        assert result["warnings"] == ["PARTIAL_FAILURE"]
        result = execute(service, {"channel": {"countries": [None]}})
        assert result["funnel"]["final"] == 0
        assert result["funnel"]["drops"] == {"HIDDEN_VALUE": 30}
        assert result["funnel"]["filterDrops"] == {"CHANNEL_COUNTRY": 30}


def test_details_cache_deleted_missing_and_stale_stats(factory, setup):
    settings, fake = setup
    with factory() as db:
        service = SearchService(db, fake, settings, clock=lambda: NOW)
        result = execute(service, {})
        key = VIDEOS[0]["id"]
        row = db.get(VideoCache, key)
        row.fetched_at = NOW - timedelta(hours=24)
        db.commit()
        fake.responses = [httpx.Response(200, json={"items": []})]
        lookup = asyncio.run(fetch_details(db, fake, service.cache, [key]))
        assert lookup.deleted_ids == [key] and db.get(VideoCache, key) is None
        db.commit()
        page = asyncio.run(service.results(result["searchId"]))
        assert page["totalElements"] == 30  # fake restores the available video
        row = db.get(VideoCache, key)
        row.fetched_at = NOW - timedelta(hours=24)
        db.commit()
        fake.guard.soft_limit = 0
        page = asyncio.run(service.results(result["searchId"]))
        assert page["totalElements"] == 30 and "STALE_STATS" in page["warnings"]
        cached = execute(service, {})
        assert cached["quota"]["spent"] == 0 and "STALE_STATS" in cached["warnings"]
        stored = db.get(SearchCache, result["searchId"])
        stored.expires_at = NOW
        db.commit()
        with pytest.raises(DomainError) as exc:
            asyncio.run(service.results(result["searchId"]))
        assert exc.value.code == "SEARCH_NOT_FOUND"


@pytest.mark.parametrize("order", ["asc", "desc"])
def test_null_last_ties_latest_first_page_edges(order):
    items = [
        {"videoId": "old", "publishedAt": "2026-01-01", "stats": {"views": 10}},
        {"videoId": "new", "publishedAt": "2026-01-02", "stats": {"views": 10}},
        {"videoId": "hidden", "publishedAt": "2026-01-03", "stats": {"views": None}},
    ]
    page = paginate(items, sort="views", order=order)
    assert [item["videoId"] for item in page["items"]] == ["new", "old", "hidden"]
    assert paginate(items, page=1)["items"] == []
    assert paginate([])["totalPages"] == 0


def test_metadata_seven_day_ttl_and_region_isolation(factory, setup):
    _, fake = setup
    with factory() as db:
        first = metadata(db, fake, now=NOW)
        assert first["categories"] == [{"id": 27, "title": "교육"}]
        assert first["limits"]["maxPages"] == 5
        metadata(db, fake, now=NOW + timedelta(days=7, microseconds=-1))
        assert len(fake.calls) == 1
        metadata(db, fake, now=NOW + timedelta(days=7))
        assert len(fake.calls) == 2
        metadata(db, fake, "US", now=NOW)
        assert len(fake.calls) == 3
        assert len(list(db.scalars(select(VideoCategoryCache)))) == 2
        fake.guard.soft_limit = 0
        stale = metadata(db, fake, now=NOW + timedelta(days=14))
        assert stale["categories"] == first["categories"]
        assert stale["warnings"] == ["STALE_STATS"]


def test_public_search_meta_api_and_validation(factory, setup):
    settings, fake = setup
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)
    app.include_router(meta_router)
    app.include_router(auth_router)
    app.add_middleware(SecurityMiddleware)
    app.state.session_factory = factory
    app.state.settings = settings
    app.state.clock = lambda: NOW
    app.state.limiter = Limiter(settings, clock=lambda: NOW)
    app.dependency_overrides[get_youtube] = lambda: fake

    def service(db=Depends(get_db)):
        return SearchService(db, fake, settings, clock=lambda: NOW)

    app.dependency_overrides[get_service] = service
    with TestClient(app) as client:
        token = client.get("/api/v1/auth/csrf").json()["csrfToken"]
        client.headers["X-CSRF-Token"] = token
        assert (
            client.post("/api/v1/search/estimate", json={"keyword": "x"}).json()[
                "estimatedUnits"
            ]
            == 204
        )
        result = client.post("/api/v1/search", json={"keyword": "x"})
        assert result.status_code == 200
        search_id = result.json()["searchId"]
        assert (
            client.get(
                f"/api/v1/search/{search_id}/results?sort=views&size=10&page=1"
            ).status_code
            == 200
        )
        assert (
            client.get(f"/api/v1/search/{search_id}/results?sort=bad").json()["code"]
            == "INVALID_SORT"
        )
        assert (
            client.get(f"/api/v1/search/{search_id}/results?size=30").status_code == 400
        )
        assert (
            client.get("/api/v1/search/missing/results").json()["code"]
            == "SEARCH_NOT_FOUND"
        )
        invalid = client.post(
            "/api/v1/search",
            json={"keyword": "x", "video": {"views": {"min": 2, "max": 1}}},
        )
        assert invalid.status_code == 400 and invalid.json()["code"] == "INVALID_RANGE"
        assert invalid.json()["fieldErrors"][0]["field"] == "video.views"
        assert client.get("/api/v1/meta").status_code == 200
        assert client.get("/api/v1/meta?regionCode=bad").status_code == 400
    with factory() as db:
        assert used_units(db, NOW) == 103
