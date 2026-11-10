import asyncio
import json
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.favorites.service import router as favorites_router
from app.history.service import record_search
from app.history.service import router as history_router
from app.models import FavoriteVideo, FilterPreset, SearchHistory, VideoCache
from app.presets.service import router as presets_router
from app.search.conditions import normalize
from app.search.service import SearchService
from tests.fakes.fake_youtube import VIDEOS
from tests.test_users_limits import context, csrf, login, signup  # noqa: F401


@pytest.fixture
def personal(context):  # noqa: F811 - reuse the stage 7 session fixture
    client, app, time, fake = context
    for router in (presets_router, favorites_router, history_router):
        app.include_router(router)
    return client, app, time, fake


@pytest.fixture
def member(personal):
    client, app, time, fake = personal
    uid = signup(client).json()["id"]
    assert login(client).status_code == 200
    return client, app, time, fake, uid


def preset(client, name="preset", conditions=None):
    return client.post(
        "/api/v1/presets", json={"name": name, "conditions": conditions or {}}
    )


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/presets"),
        ("GET", "/presets/1"),
        ("POST", "/presets"),
        ("PUT", "/presets/1"),
        ("DELETE", "/presets/1"),
        ("GET", "/favorites"),
        ("PUT", "/favorites/v0000000001"),
        ("DELETE", "/favorites/v0000000001"),
        ("GET", "/history"),
        ("DELETE", "/history/1"),
        ("DELETE", "/history/all"),
    ],
)
def test_guest_401_before_csrf(personal, method, path):
    client, _, _, fake = personal
    result = client.request(method, "/api/v1" + path)
    assert result.status_code == 401
    assert result.json()["code"] == "UNAUTHORIZED"
    assert fake.calls == []


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/presets"),
        ("PUT", "/presets/1"),
        ("DELETE", "/presets/1"),
        ("PUT", "/favorites/v0000000001"),
        ("DELETE", "/favorites/v0000000001"),
        ("DELETE", "/history/all"),
    ],
)
def test_personal_mutations_reuse_csrf(member, method, path):
    client, _, _, _, _ = member
    client.headers.pop("X-CSRF-Token")
    assert client.request(method, "/api/v1" + path).status_code == 403


def test_presets_crud_normalization_keyword_exclusion(member, factory):
    client, _, time, fake, uid = member
    result = preset(
        client,
        " z ",
        {
            "keyword": "discard",
            "video": {"durationSec": {"min": "1:00"}},
        },
    )
    assert result.status_code == 201
    pid = result.json()["id"]
    saved = client.get(f"/api/v1/presets/{pid}").json()
    assert saved["name"] == "z" and "keyword" not in saved["conditions"]
    assert saved["conditions"]["video"]["durationSec"] == {"min": 60}
    assert preset(client, "a").status_code == 201
    listing = client.get("/api/v1/presets").json()
    assert [row["name"] for row in listing] == ["a", "z"]
    assert listing[0]["createdAt"].endswith("+09:00")
    assert preset(client, "z").json()["code"] == "DUPLICATE_PRESET_NAME"
    time[0] += timedelta(seconds=1)
    path = f"/api/v1/presets/{pid}"
    assert client.put(path, json={"name": "a", "conditions": {}}).status_code == 409
    assert client.get(path).json()["name"] == "z"
    response = client.put(path, json={"name": "b", "conditions": {"pages": 5}})
    assert response.status_code == 200 and response.json()["conditions"]["pages"] == 5
    with factory() as db:
        row = db.get(FilterPreset, pid)
        assert row.user_id == uid and row.updated_at == time[0]
        assert "keyword" not in json.loads(row.conditions)
    assert client.delete(path).status_code == 204
    assert client.delete(path).json()["code"] == "PRESET_NOT_FOUND"
    assert fake.calls == []  # Loading conditions never executes a search.


@pytest.mark.parametrize(
    "name,valid",
    [("", False), ("   ", False), ("a", True), ("한" * 30, True), ("a" * 31, False)],
)
def test_preset_name_length(member, name, valid):
    client, _, _, _, _ = member
    assert preset(client, name).status_code == (201 if valid else 400)


@pytest.mark.parametrize(
    "conditions,code",
    [
        ({"video": {"views": {"min": 2, "max": 1}}}, "INVALID_RANGE"),
        ({"video": {"durationSec": {"max": 43201}}}, "INVALID_DURATION"),
        (
            {"video": {"tags": {"include": [str(i) for i in range(31)]}}},
            "TOO_MANY_TAGS",
        ),
        ({"pages": 6}, "VALIDATION_ERROR"),
        ({"extra": 1}, "VALIDATION_ERROR"),
    ],
)
def test_preset_filters_validated_on_create_and_update(member, conditions, code):
    client, _, _, _, _ = member
    pid = preset(client).json()["id"]
    body = {"name": "changed", "conditions": conditions}
    for method, path in [("POST", "/presets"), ("PUT", f"/presets/{pid}")]:
        response = client.request(method, "/api/v1" + path, json=body)
        assert response.status_code == 400 and response.json()["code"] == code
    assert client.get(f"/api/v1/presets/{pid}").json()["name"] == "preset"


def test_preset_30_limit_update_and_member_scope(member, factory):
    client, _, time, _, uid = member
    with factory() as db:
        db.add_all(
            [
                FilterPreset(user_id=uid, name=f"p{i}", conditions="{}")
                for i in range(29)
            ]
        )
        db.commit()
    result = preset(client, "thirtieth")
    assert result.status_code == 201
    pid = result.json()["id"]
    assert preset(client, "over").json()["code"] == "PRESET_LIMIT"
    assert (
        client.put(
            f"/api/v1/presets/{pid}", json={"name": "renamed", "conditions": {}}
        ).status_code
        == 200
    )
    signup(client, "other01")
    login(client, "other01")
    assert client.get("/api/v1/presets").json() == []
    assert preset(client, "renamed").status_code == 201
    for method in ("GET", "PUT", "DELETE"):
        result = client.request(
            method, f"/api/v1/presets/{pid}", json={"name": "stolen", "conditions": {}}
        )
        assert result.status_code == 404 and result.json()["code"] == "PRESET_NOT_FOUND"
    with factory() as db:
        assert db.get(FilterPreset, pid).name == "renamed"


@pytest.mark.parametrize(
    "video_id", ["a" * 10, "a" * 12, "한" * 11, "a" * 10 + "!", "a" * 10 + " "]
)
def test_invalid_favorite_id(member, video_id):
    client, _, _, _, _ = member
    for method in ("PUT", "DELETE"):
        result = client.request(method, f"/api/v1/favorites/{video_id}")
        assert result.status_code == 400
        assert result.json()["code"] == "INVALID_VIDEO_ID"


def test_favorite_200_limit_idempotence_and_isolation(member, factory):
    client, _, time, fake, uid = member
    with factory() as db:
        db.add_all(
            [FavoriteVideo(user_id=uid, video_id=f"v{i:010d}") for i in range(199)]
        )
        db.commit()
    path = "/api/v1/favorites/A_-01234567"
    assert client.put(path).status_code == 204
    assert client.put(path).status_code == 204
    result = client.put("/api/v1/favorites/new00000001")
    assert result.status_code == 400 and result.json()["code"] == "FAVORITE_LIMIT"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(FavoriteVideo)) == 200
        assert db.scalar(select(func.count()).select_from(VideoCache)) == 0
    signup(client, "other01")
    login(client, "other01")
    assert client.get("/api/v1/favorites").json()["totalElements"] == 0
    assert client.delete(path).status_code == 204
    with factory() as db:
        assert db.get(FavoriteVideo, (uid, "A_-01234567")) is not None
    assert client.put(path).status_code == 204  # Same ID belongs to each member.
    assert client.delete(path).status_code == 204
    assert client.delete(path).status_code == 204
    assert fake.calls == []


def test_favorite_details_ttl_deleted_paging_and_calc(member, factory):
    client, _, time, fake, uid = member
    assert client.put("/api/v1/favorites/v0000000001").status_code == 204
    result = client.get("/api/v1/favorites").json()
    item = result["items"][0]
    assert item["available"] and item["stats"]["views"] == 100
    assert item["calc"]["label"] == "계산값 · YouTube 제공 지표 아님"
    assert [call[0] for call in fake.calls] == ["videos.list"]
    # Keep login active while advancing to either side of the cache boundary.
    time[0] += timedelta(hours=24) - timedelta(microseconds=1)
    assert client.get("/api/v1/favorites").json()["items"][0]["available"]
    assert len(fake.calls) == 1
    time[0] += timedelta(microseconds=1)
    fake.responses.append(httpx.Response(200, json={"items": []}))
    result = client.get("/api/v1/favorites").json()
    assert result["items"] == [
        {
            "videoId": "v0000000001",
            "available": False,
            "title": "더 이상 볼 수 없는 영상",
        }
    ]
    with factory() as db:
        assert db.get(VideoCache, "v0000000001") is None
        assert db.get(FavoriteVideo, (uid, "v0000000001")) is not None
    calls = len(fake.calls)
    for page in (1, 10**30):
        result = client.get(f"/api/v1/favorites?page={page}&size=10").json()
        assert result["items"] == [] and result["totalElements"] == 1
    assert len(fake.calls) == calls


@pytest.mark.parametrize("query", ["page=-1", "page=x", "size=0", "size=51", "size=1"])
def test_favorite_paging_validation(member, query):
    client, _, _, _, _ = member
    assert client.get("/api/v1/favorites?" + query).status_code == 400


def test_favorite_order_only_fetch_page_and_50_id_batches(member, factory):
    client, _, time, fake, uid = member
    with factory() as db:
        db.add_all(
            [
                FavoriteVideo(
                    user_id=uid,
                    video_id=f"v{i:010d}",
                    created_at=time[0] + timedelta(seconds=i),
                )
                for i in range(51)
            ]
        )
        db.commit()
    result = client.get("/api/v1/favorites?size=50").json()
    assert result["totalElements"] == 51 and result["totalPages"] == 2
    assert [item["videoId"] for item in result["items"]] == [
        f"v{i:010d}" for i in range(50, 0, -1)
    ]
    assert len(fake.calls) == 1 and len(fake.calls[0][1]["id"].split(",")) == 50
    result = client.get("/api/v1/favorites?size=50&page=1").json()
    assert result["items"][0]["videoId"] == "v0000000000"
    assert len(fake.calls) == 2


def test_quota_blocked_uses_cached_info_without_claiming_deletion(member, factory):
    client, _, time, fake, uid = member
    client.put("/api/v1/favorites/v0000000001")
    client.get("/api/v1/favorites")
    time[0] += timedelta(hours=23)
    client.get("/api/v1/me")
    time[0] += timedelta(hours=1)
    client.put("/api/v1/favorites/v0000000002")
    fake.guard.block(time[0])
    result = client.get("/api/v1/favorites").json()
    items = {item["videoId"]: item for item in result["items"]}
    assert items["v0000000001"]["available"] is True
    assert items["v0000000002"] == {"videoId": "v0000000002", "available": False}
    assert "STALE_STATS" in result["warnings"]
    assert len(fake.calls) == 1
    with factory() as db:
        assert db.get(FavoriteVideo, (uid, "v0000000002")) is not None
    # A cache record at the 28-day retention boundary cannot be displayed.
    with factory() as db:
        db.get(VideoCache, "v0000000001").fetched_at = time[0] - timedelta(days=28)
        db.commit()
    result = client.get("/api/v1/favorites").json()
    assert all(not item["available"] for item in result["items"])


def test_history_search_hook_guest_member_cache_and_failed_search(member, factory):
    client, _, _, fake, uid = member
    client.post("/api/v1/auth/logout")
    csrf(client)
    assert client.post("/api/v1/search", json={"keyword": "guest"}).status_code == 200
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(SearchHistory)) == 0
    login(client)
    assert client.post("/api/v1/search", json={"keyword": "guest"}).json()["cached"]
    assert (
        client.post("/api/v1/search", json={"keyword": "한" * 100}).status_code == 200
    )
    assert client.post("/api/v1/search", json={"keyword": "x" * 101}).status_code == 400
    history = client.get("/api/v1/history").json()
    assert len(history) == 2 and history[0]["keyword"] == "한" * 100
    assert history[0]["resultCount"] == 30
    assert history[0]["searchedAt"].endswith("+09:00")
    assert history[1]["conditions"] == normalize({"keyword": "guest"}).data
    with factory() as db:
        for row in db.scalars(select(SearchHistory)):
            assert row.user_id == uid
            assert "videoId" not in row.conditions
    calls = len(fake.calls)
    client.get("/api/v1/history")
    assert len(fake.calls) == calls


def test_history_50_retention_ties_and_owner_deletion(member, factory):
    client, _, time, fake, uid = member
    signup(client, "other01")
    login(client, "other01")
    other = client.get("/api/v1/me").json()["id"]
    with factory() as db:
        record_search(db, other, {"keyword": "other"}, 0, time[0])
        for i in range(51):
            record_search(db, uid, {"keyword": str(i)}, i, time[0])
        assert db.scalar(select(func.count()).select_from(SearchHistory)) == 51
        foreign_id = db.scalar(
            select(SearchHistory.id).where(SearchHistory.user_id == uid)
        )
    assert client.delete(f"/api/v1/history/{foreign_id}").status_code == 404
    assert client.delete("/api/v1/history/all").status_code == 204
    assert client.get("/api/v1/history").json() == []
    login(client)
    rows = client.get("/api/v1/history").json()
    assert len(rows) == 50
    assert [row["keyword"] for row in rows] == [str(i) for i in range(50, 0, -1)]
    assert client.delete(f"/api/v1/history/{rows[0]['id']}").status_code == 204
    assert client.delete(f"/api/v1/history/{rows[0]['id']}").status_code == 404
    assert client.delete("/api/v1/history/all").status_code == 204
    assert client.delete("/api/v1/history/all").status_code == 204
    assert client.get("/api/v1/history").json() == []
    assert fake.calls == []


def test_history_failure_does_not_fail_new_or_cached_search(member, factory, caplog):
    _, app, time, fake, uid = member
    with factory() as db:
        service = SearchService(db, fake, app.state.settings, clock=app.state.clock)
        conditions = normalize({"keyword": "private keyword"})
        for cached in (False, True):
            original = db.flush

            def fail_history(*args, **kwargs):
                if any(isinstance(row, SearchHistory) for row in db.new):
                    raise SQLAlchemyError("private keyword")
                return original(*args, **kwargs)

            with patch.object(db, "flush", side_effect=fail_history):
                result = asyncio.run(service.execute(conditions, user_id=uid))
            assert result["cached"] == cached and result["page"]["totalElements"] == 30
        assert db.scalar(select(func.count()).select_from(SearchHistory)) == 0
    assert "검색 기록 저장에 실패" in caplog.text
    assert "private keyword" not in caplog.text


def test_favorites_share_search_cache_and_refresh_updated_stats(member):
    client, _, time, fake, _ = member
    assert client.post("/api/v1/search", json={"keyword": "shared"}).status_code == 200
    client.put("/api/v1/favorites/v0000000001")
    calls = len(fake.calls)
    result = client.get("/api/v1/favorites").json()["items"][0]
    assert result["stats"]["views"] == 100
    assert result["channelTitle"] == "Channel 1"
    assert len(fake.calls) == calls
    time[0] += timedelta(hours=23)
    client.get("/api/v1/me")
    time[0] += timedelta(hours=1)
    updated = deepcopy(VIDEOS[1])
    updated["statistics"]["viewCount"] = "999"
    fake.responses.append(httpx.Response(200, json={"items": [updated]}))
    result = client.get("/api/v1/favorites").json()["items"][0]
    assert result["stats"]["views"] == 999
    assert len(fake.calls) == calls + 1
    assert fake.calls[-1][0] == "videos.list"


@pytest.mark.parametrize("preset_id", [0, -1, 2**63, 10**30])
def test_preset_id_validation(member, preset_id):
    client, _, _, _, _ = member
    assert client.get(f"/api/v1/presets/{preset_id}").status_code == 400


def test_history_retention_50_then_51_and_zero_results(member, factory):
    client, app, time, fake, uid = member
    with factory() as db:
        for i in range(50):
            record_search(db, uid, {"keyword": str(i)}, 0, time[0])
        first = db.scalar(select(SearchHistory.id).order_by(SearchHistory.id))
        assert db.scalar(select(func.count()).select_from(SearchHistory)) == 50
        record_search(db, uid, {"keyword": "fifty-first"}, 0, time[0])
        assert db.get(SearchHistory, first) is None
        assert db.scalar(select(func.count()).select_from(SearchHistory)) == 50
    # Successful early termination with no candidates also records a search.
    fake.responses.append(httpx.Response(200, json={"items": []}))
    result = client.post("/api/v1/search", json={"keyword": "empty"})
    assert result.status_code == 200 and result.json()["page"]["totalElements"] == 0
    rows = client.get("/api/v1/history").json()
    assert len(rows) == 50 and rows[0]["keyword"] == "empty"
    assert rows[0]["resultCount"] == 0
