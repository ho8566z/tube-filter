from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.main import app
from app.models import QuotaUsage
from app.quota.clock import next_reset, pt_date
from app.quota.guard import QuotaGuard
from app.quota.log import record_call
from app.quota.status import used_units
from app.time_utils import format_kst
from app.youtube.adapter import get_youtube
from tests.fakes.fake_youtube import FakeYouTubeAdapter

NOW = datetime(2026, 11, 10, 8, tzinfo=UTC)


@pytest.mark.parametrize(
    ("instant", "expected_date", "reset"),
    [
        ("2026-11-10T07:59:59+00:00", "2026-11-09", "2026-11-10T17:00:00+09:00"),
        ("2026-11-10T08:00:00+00:00", "2026-11-10", "2026-11-11T17:00:00+09:00"),
        ("2026-07-01T06:59:59+00:00", "2026-06-30", "2026-07-01T16:00:00+09:00"),
        ("2026-07-01T07:00:00+00:00", "2026-07-01", "2026-07-02T16:00:00+09:00"),
        ("2026-03-08T08:00:00+00:00", "2026-03-08", "2026-03-09T16:00:00+09:00"),
        ("2026-11-01T07:00:00+00:00", "2026-11-01", "2026-11-02T17:00:00+09:00"),
    ],
)
def test_pt_dates_and_dst_reset(instant, expected_date, reset):
    now = datetime.fromisoformat(instant)
    assert pt_date(now) == date.fromisoformat(expected_date)
    assert format_kst(next_reset(now)) == reset


def test_records_each_endpoint_with_correct_units(factory):
    fake = FakeYouTubeAdapter(QuotaGuard(factory, 9000), clock=lambda: NOW)
    for endpoint in (
        "search.list",
        "videos.list",
        "channels.list",
        "playlistItems.list",
        "videoCategories.list",
    ):
        fake.request(endpoint, {}, search_id="a" * 32)
    with factory() as db:
        rows = db.scalars(select(QuotaUsage).order_by(QuotaUsage.id)).all()
        assert [row.units for row in rows] == [100, 1, 1, 1, 1]
        assert {row.usage_date for row in rows} == {date(2026, 11, 10)}
        assert {row.called_at for row in rows} == {NOW}
        assert {row.search_id for row in rows} == {"a" * 32}
        assert used_units(db, NOW) == 104
        assert used_units(db, datetime(2026, 11, 11, 8, tzinfo=UTC)) == 0


@pytest.mark.parametrize(("limit", "allowed"), [(99, False), (100, True), (101, True)])
def test_guard_boundary(factory, limit, allowed):
    fake = FakeYouTubeAdapter(QuotaGuard(factory, limit), clock=lambda: NOW)
    if allowed:
        fake.request("search.list", {})
    else:
        with pytest.raises(DomainError) as exc:
            fake.request("search.list", {})
        assert exc.value.code == "QUOTA_BLOCKED"
        assert exc.value.status_code == 503
    assert len(fake.calls) == int(allowed)
    with factory() as db:
        assert used_units(db, NOW) == 100 * int(allowed)
    if limit == 100:
        with pytest.raises(DomainError):
            fake.request("videos.list", {})
        assert len(fake.calls) == 1


def test_guard_aggregates_existing_rows_and_rolls_over(factory):
    with factory() as db:
        record_call(db, "search.list", NOW)
    now = NOW
    fake = FakeYouTubeAdapter(QuotaGuard(factory, 100), clock=lambda: now)
    with pytest.raises(DomainError):
        fake.request("videos.list", {})
    now = datetime(2026, 11, 11, 8, tzinfo=UTC)
    fake.request("search.list", {})
    assert len(fake.calls) == 1


def test_accounting_failure_warns_and_still_calls(caplog):
    def broken_factory():
        raise OperationalError("sensitive SQL", {}, Exception("private details"))

    fake = FakeYouTubeAdapter(QuotaGuard(broken_factory, 9000), clock=lambda: NOW)
    assert len(fake.request("search.list", {})["items"]) == 30
    assert "quota accounting failed" in caplog.text
    assert "sensitive" not in caplog.text
    assert "private" not in caplog.text


def test_failed_commit_warns_and_still_calls(factory, monkeypatch, caplog):
    def broken_commit(_db):
        raise OperationalError("private SQL", {}, Exception("private detail"))

    monkeypatch.setattr(Session, "commit", broken_commit)
    fake = FakeYouTubeAdapter(QuotaGuard(factory, 9000), clock=lambda: NOW)
    assert len(fake.request("search.list", {})["items"]) == 30
    assert "quota accounting failed" in caplog.text
    assert "private" not in caplog.text
    with factory() as db:
        assert used_units(db, NOW) == 0


def test_simultaneous_requests_cannot_both_spend_last_units(factory):
    guard = QuotaGuard(factory, 100)

    def attempt(_index):
        fake = FakeYouTubeAdapter(guard, clock=lambda: NOW)
        try:
            fake.request("search.list", {})
        except DomainError as exc:
            return exc.code
        return "allowed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(results) == ["QUOTA_BLOCKED", "allowed"]
    with factory() as db:
        assert used_units(db, NOW) == 100


@pytest.mark.parametrize("calls", [0, 1, 101])
def test_public_quota_api(factory, monkeypatch, tmp_path, calls):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("QUOTA_DAILY_LIMIT", "10000")
    monkeypatch.setenv("QUOTA_SOFT_LIMIT", "9000")
    monkeypatch.setattr("app.quota.status.utc_now", lambda: NOW)
    with factory() as db:
        for _ in range(calls):
            record_call(db, "search.list", NOW)
    with TestClient(app) as client:
        app.state.session_factory = factory
        response = client.get("/api/v1/quota")
    assert response.status_code == 200
    assert response.json() == {
        "usedUnits": calls * 100,
        "limitUnits": 10000,
        "softLimitUnits": 9000,
        "remainingUnits": max(0, 10000 - calls * 100),
        "resetAt": "2026-11-11T17:00:00+09:00",
    }


def test_adapter_dependency_can_be_replaced(factory):
    from fastapi import FastAPI

    fake = FakeYouTubeAdapter(QuotaGuard(factory, 9000), clock=lambda: NOW)
    test_app = FastAPI()

    @test_app.get("/example")
    def example(youtube=Depends(get_youtube)):
        return youtube.request("search.list", {})

    test_app.dependency_overrides[get_youtube] = lambda: fake
    with TestClient(test_app) as client:
        assert len(client.get("/example").json()["items"]) == 30
