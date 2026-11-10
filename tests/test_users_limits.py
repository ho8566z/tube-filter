import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.errors import DomainError, register_error_handlers
from app.limits.limiter import Limiter
from app.models import AppUser, FavoriteVideo, FilterPreset, SearchHistory
from app.quota.guard import QuotaGuard
from app.search.conditions import normalize
from app.search.service import SearchService
from app.search.service import router as search_router
from app.time_utils import utc_now
from app.users.auth import SecurityMiddleware
from app.users.auth import router as auth_router
from app.users.service import router as users_router
from app.youtube.adapter import get_youtube
from tests.fakes.fake_youtube import FakeYouTubeAdapter

NOW = datetime(2026, 11, 10, 14, 59, 59, tzinfo=UTC)
PASSWORD = "abcd1234"


@pytest.fixture
def context(factory):
    settings = Settings(_env_file=None, youtube_api_key="test", session_secret="x" * 32)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(search_router)
    app.add_middleware(SecurityMiddleware)
    app.state.settings = settings
    app.state.session_factory = factory
    time = [utc_now()]
    app.state.clock = lambda: time[0]
    limiter = Limiter(settings, app.state.clock)
    app.state.limiter = limiter
    fake = FakeYouTubeAdapter(QuotaGuard(factory, 9000), clock=app.state.clock)
    app.dependency_overrides[get_youtube] = lambda: fake
    with TestClient(app) as client:
        yield client, app, time, fake


def csrf(client):
    token = client.get("/api/v1/auth/csrf").json()["csrfToken"]
    client.headers["X-CSRF-Token"] = token
    return token


def signup(client, login_id="Tube01", **changes):
    csrf(client)
    return client.post(
        "/api/v1/auth/signup",
        json={
            "loginId": login_id,
            "password": PASSWORD,
            "passwordConfirm": PASSWORD,
            "agreePrivacy": True,
            **changes,
        },
    )


def login(client, login_id="TUBE01", password=PASSWORD):
    csrf(client)
    response = client.post(
        "/api/v1/auth/login", json={"loginId": login_id, "password": password}
    )
    if response.is_success:
        csrf(client)
    return response


def test_signup_normalization_hash_no_auto_login(context, factory, caplog):
    client, _, _, _ = context
    assert client.get("/api/v1/auth/check-id", params={"loginId": "TUBE01"}).json() == {
        "available": True
    }
    result = signup(client)
    assert result.status_code == 201
    assert result.json()["loginId"] == "tube01"
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/auth/check-id?loginId=Tube01").json() == {
        "available": False
    }
    assert signup(client, "tube01").status_code == 409
    with factory() as db:
        user = db.scalar(select(AppUser))
        assert len(user.password) == 60 and user.password.startswith("$2")
        assert PASSWORD not in user.password
    assert PASSWORD not in result.text and PASSWORD not in caplog.text


@pytest.mark.parametrize("login_id", ["abc", "a" * 21, "1abc", "ab_c", "한글아이디"])
def test_invalid_login_id(context, login_id):
    client, _, _, _ = context
    assert (
        client.get("/api/v1/auth/check-id", params={"loginId": login_id}).json()["code"]
        == "INVALID_LOGIN_ID"
    )
    assert signup(client, login_id).status_code == 400


@pytest.mark.parametrize(
    "changes",
    [
        {"password": "abc1234"},
        {"password": "a" * 65 + "1"},
        {"password": "abcdefgh"},
        {"password": "12345678"},
        {"passwordConfirm": "different1"},
        {"agreePrivacy": False},
        {"agreePrivacy": "true"},
        {"password": "a1" + "한" * 30},
        {"password": 12345678},
    ],
)
def test_signup_validation_no_secret_echo(context, changes, caplog):
    client, _, _, _ = context
    result = signup(client, **changes)
    assert result.status_code == 400
    assert result.json()["fieldErrors"]
    assert PASSWORD not in result.text and PASSWORD not in caplog.text


@pytest.mark.parametrize(
    "login_id,password", [("Abc1", "abc12345"), ("a" * 20, "a" * 63 + "1")]
)
def test_valid_input_boundaries(context, login_id, password):
    client, _, _, _ = context
    assert (
        signup(
            client, login_id, password=password, passwordConfirm=password
        ).status_code
        == 201
    )
    assert login(client, login_id, password).status_code == 200


def test_login_cookie_csrf_logout_and_permissions(context, factory):
    client, _, time, _ = context
    assert signup(client).status_code == 201
    wrong = login(client, password="wrong123").json()
    absent = login(client, login_id="absent1").json()
    assert wrong == absent and wrong["code"] == "LOGIN_FAILED"
    result = login(client)
    assert result.json() == {"loginId": "tube01"}
    cookie = result.headers["set-cookie"].lower()
    assert all(
        item in cookie
        for item in ["tf_session=", "httponly", "samesite=lax", "max-age=86400"]
    )
    assert "secure" not in cookie
    assert PASSWORD not in cookie
    me = client.get("/api/v1/me")
    assert me.status_code == 200 and me.json()["createdAt"].endswith("+09:00")
    with factory() as db:
        assert db.scalar(select(AppUser)).last_login_at == time[0]
    client.headers.pop("X-CSRF-Token")
    assert client.patch("/api/v1/me/password", json={}).status_code == 403
    csrf(client)
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert not client.cookies.get("TF_SESSION")
    assert client.post("/api/v1/auth/logout").status_code == 204
    for path in [
        "/api/v1/me",
        "/api/v1/presets",
        "/api/v1/favorites/x",
        "/api/v1/history",
    ]:
        assert client.get(path).json()["code"] == "UNAUTHORIZED"
    assert client.patch("/api/v1/me/password", json={}).status_code == 401
    assert client.request("DELETE", "/api/v1/me", json={}).status_code == 401


def test_csrf_required_for_public_mutations_and_secure_cookie(context):
    client, app, _, _ = context
    assert client.post("/api/v1/auth/signup", json={}).status_code == 403
    csrf(client)
    client.headers["X-CSRF-Token"] = "bad"
    assert client.post("/api/v1/auth/login", json={}).status_code == 403
    with TestClient(app, base_url="https://testserver") as https:
        assert "secure" in https.get("/api/v1/auth/csrf").headers["set-cookie"].lower()


def test_session_rolling_expiry_and_tampering(context):
    client, _, time, _ = context
    signup(client)
    login(client)
    time[0] += timedelta(hours=24) - timedelta(seconds=1)
    assert client.get("/api/v1/me").status_code == 200
    time[0] += timedelta(hours=24) - timedelta(seconds=1)
    assert client.get("/api/v1/me").status_code == 200
    time[0] += timedelta(hours=24)
    assert client.get("/api/v1/me").status_code == 401
    time[0] = utc_now()
    login(client)
    cookie = client.cookies.get("TF_SESSION")
    client.cookies.clear()
    client.cookies.set("TF_SESSION", cookie + "tampered")
    assert client.get("/api/v1/me").status_code == 401


def test_password_change(context):
    client, _, _, _ = context
    signup(client)
    login(client)
    body = {
        "currentPassword": "wrong123",
        "newPassword": "newpass1",
        "newPasswordConfirm": "newpass1",
    }
    assert (
        client.patch("/api/v1/me/password", json=body).json()["code"]
        == "WRONG_PASSWORD"
    )
    body["currentPassword"] = PASSWORD
    for new, confirm in [
        (PASSWORD, PASSWORD),
        ("weak", "weak"),
        ("newpass1", "other123"),
    ]:
        body.update(newPassword=new, newPasswordConfirm=confirm)
        assert client.patch("/api/v1/me/password", json=body).status_code == 400
    body.update(newPassword="newpass1", newPasswordConfirm="newpass1")
    assert client.patch("/api/v1/me/password", json=body).status_code == 204
    assert login(client, password=PASSWORD).status_code == 401
    assert login(client, password="newpass1").status_code == 200


def test_signed_cookie_max_age(context, monkeypatch):
    from itsdangerous import TimestampSigner

    client, _, _, _ = context
    signup(client)
    login(client)
    timestamp = TimestampSigner("unused").get_timestamp()
    monkeypatch.setattr(
        TimestampSigner, "get_timestamp", lambda self: timestamp + 86401
    )
    assert client.get("/api/v1/me").status_code == 401


def test_deleted_sqlite_id_reuse_rejects_old_cookie(context):
    client, _, _, _ = context
    old_id = signup(client).json()["id"]
    login(client)
    cookie = client.cookies.get("TF_SESSION")
    assert (
        client.request("DELETE", "/api/v1/me", json={"password": PASSWORD}).status_code
        == 204
    )
    assert signup(client).json()["id"] == old_id
    client.cookies.clear()
    client.cookies.set("TF_SESSION", cookie)
    assert client.get("/api/v1/me").status_code == 401


def test_limit_environment_overrides(monkeypatch):
    for name, value in (
        ("LIMIT_SEARCH_GUEST_PER_DAY", "1"),
        ("LIMIT_SEARCH_USER_PER_DAY", "2"),
        ("LIMIT_SEARCH_PER_MIN", "3"),
        ("LIMIT_OTHER_PER_MIN", "4"),
    ):
        monkeypatch.setenv(name, value)
    settings = Settings(_env_file=None, youtube_api_key="test", session_secret="x" * 32)
    limiter = Limiter(settings, clock=lambda: NOW)
    limiter.new_search("ip")
    assert_limit(lambda: limiter.new_search("ip"), "SEARCH_LIMIT")
    for _ in range(2):
        limiter.new_search("ip", 1)
    assert_limit(lambda: limiter.new_search("ip", 1), "SEARCH_LIMIT")
    for path, count in (("/api/v1/search", 3), ("/api/v1/auth/login", 4)):
        for _ in range(count):
            limiter.check_request("ip", path)
        assert_limit(lambda: limiter.check_request("ip", path), "TOO_MANY_REQUESTS")


def test_withdraw_cascades_and_old_cookie_cannot_revive(context, factory):
    client, _, _, _ = context
    user_id = signup(client).json()["id"]
    signup(client, "other01")
    login(client)
    cookie = client.cookies.get("TF_SESSION")
    with factory() as db:
        other = db.scalar(select(AppUser).where(AppUser.login_id == "other01"))
        for uid in (user_id, other.id):
            db.add_all(
                [
                    FilterPreset(user_id=uid, name="preset", conditions="{}"),
                    FavoriteVideo(user_id=uid, video_id="video000001"),
                    SearchHistory(user_id=uid, keyword="test", conditions="{}"),
                ]
            )
        db.commit()
    assert (
        client.request("DELETE", "/api/v1/me", json={"password": "wrong123"}).json()[
            "code"
        ]
        == "WRONG_PASSWORD"
    )
    assert (
        client.request("DELETE", "/api/v1/me", json={"password": PASSWORD}).status_code
        == 204
    )
    assert client.get("/api/v1/me").status_code == 401
    with factory() as db:
        for model in (FilterPreset, FavoriteVideo, SearchHistory):
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.user_id == user_id)
                )
                == 0
            )
            assert db.scalar(select(func.count()).select_from(model)) == 1
        assert db.get(AppUser, user_id) is None
    assert signup(client).status_code == 201
    client.cookies.clear()
    client.cookies.set("TF_SESSION", cookie)
    assert client.get("/api/v1/me").status_code == 401


def assert_limit(callback, code):
    with pytest.raises(DomainError) as error:
        callback()
    assert error.value.code == code and error.value.status_code == 429


def test_daily_guest_user_boundaries_kst_and_identity(context):
    _, app, time, _ = context
    limiter = app.state.limiter
    time[0] = NOW
    for _ in range(5):
        limiter.new_search("ip1")
    assert_limit(lambda: limiter.new_search("ip1"), "SEARCH_LIMIT")
    limiter.new_search("ip2")
    for n in range(20):
        limiter.new_search(f"ip{n}", 1)
    assert_limit(lambda: limiter.new_search("another-ip", 1), "SEARCH_LIMIT")
    limiter.new_search("ip1", 2)
    time[0] += timedelta(seconds=1)  # UTC 15:00 == KST midnight
    limiter.new_search("ip1")
    limiter.new_search("ip1", 1)
    assert set(limiter.daily.values()) == {1}


def test_sliding_minute_boundary_categories_and_ip(context):
    _, app, time, _ = context
    limiter = app.state.limiter
    time[0] = NOW
    for _ in range(10):
        limiter.check_request("ip1", "/api/v1/search")
    assert_limit(
        lambda: limiter.check_request("ip1", "/api/v1/search/estimate"),
        "TOO_MANY_REQUESTS",
    )
    limiter.check_request("ip2", "/api/v1/search")
    for _ in range(60):
        limiter.check_request("ip1", "/api/v1/me")
    assert_limit(
        lambda: limiter.check_request("ip1", "/api/v1/me"), "TOO_MANY_REQUESTS"
    )
    time[0] += timedelta(seconds=60) - timedelta(microseconds=1)
    assert_limit(
        lambda: limiter.check_request("ip1", "/api/v1/search"), "TOO_MANY_REQUESTS"
    )
    time[0] += timedelta(microseconds=1)
    limiter.check_request("ip1", "/api/v1/search")
    limiter.check_request("ip1", "/api/v1/me")


def test_concurrent_daily_limit_is_atomic(context):
    _, app, _, _ = context

    def attempt(_):
        try:
            app.state.limiter.new_search("same-ip")
            return True
        except DomainError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(20))) == 5


def test_search_hook_cache_exemption_user_identity_and_request_limit(context):
    client, app, _, fake = context
    app.state.settings.limit_search_guest_per_day = 1
    csrf(client)
    first = client.post("/api/v1/search", json={"keyword": "first"})
    assert first.status_code == 200
    calls = len(fake.calls)
    assert client.post("/api/v1/search", json={"keyword": "first"}).json()["cached"]
    assert len(fake.calls) == calls
    assert (
        client.post("/api/v1/search", json={"keyword": "second"}).json()["code"]
        == "SEARCH_LIMIT"
    )
    assert len(fake.calls) == calls
    uid = signup(client).json()["id"]
    login(client)
    assert client.post("/api/v1/search", json={"keyword": "second"}).status_code == 200
    assert app.state.limiter.daily[("user", uid)] == 1
    assert client.post("/api/v1/search", json={"keyword": "first"}).json()["cached"]
    assert app.state.limiter.daily[("user", uid)] == 1
    for _ in range(5):
        client.post("/api/v1/search/estimate", json={"keyword": "first"})
    result = client.post("/api/v1/search", json={"keyword": "first"})
    assert result.status_code == 429 and result.json()["code"] == "TOO_MANY_REQUESTS"


def test_cache_tables_survive_withdraw(context, factory):
    client, app, _, fake = context
    with factory() as db:
        service = SearchService(db, fake, app.state.settings)
        asyncio.run(service.execute(normalize({"keyword": "test"})))
    from app.models import ChannelCache, SearchCache, VideoCache

    with factory() as db:
        before = [
            db.scalar(select(func.count()).select_from(m))
            for m in (SearchCache, VideoCache, ChannelCache)
        ]
    signup(client)
    login(client)
    assert (
        client.request("DELETE", "/api/v1/me", json={"password": PASSWORD}).status_code
        == 204
    )
    with factory() as db:
        after = [
            db.scalar(select(func.count()).select_from(m))
            for m in (SearchCache, VideoCache, ChannelCache)
        ]
    assert before == after and all(before)
