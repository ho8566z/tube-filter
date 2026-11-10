from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.db import Base, create_db_engine, get_db
from app.errors import DomainError, register_error_handlers
from app.main import lifespan
from app.models import (
    AppUser,
    ChannelCache,
    FavoriteVideo,
    FilterPreset,
    QuotaUsage,
    SearchCache,
    SearchHistory,
    VideoCache,
    VideoCategoryCache,
)
from app.time_utils import KST, format_kst

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def migrated_db(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    url = f"sqlite:///{(tmp_path / 'nested' / 'test.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_db_engine(url)
    yield engine, config
    engine.dispose()


def test_migration_schema_and_round_trip(migrated_db):
    engine, config = migrated_db
    schema = inspect(engine)
    assert set(schema.get_table_names()) == {
        "alembic_version",
        "app_user",
        "filter_preset",
        "favorite_video",
        "search_history",
        "search_cache",
        "video_cache",
        "channel_cache",
        "video_category_cache",
        "quota_usage",
    }
    with engine.connect() as connection:
        assert (
            compare_metadata(MigrationContext.configure(connection), Base.metadata)
            == []
        )
    assert schema.get_pk_constraint("favorite_video")["constrained_columns"] == [
        "user_id",
        "video_id",
    ]
    assert schema.get_pk_constraint("video_category_cache")["constrained_columns"] == [
        "region_code",
        "category_id",
    ]
    assert schema.get_foreign_keys("video_cache") == []
    assert {
        tuple(index["column_names"]) for index in schema.get_indexes("search_cache")
    } == {("cond_hash", "expires_at"), ("expires_at",)}
    command.upgrade(config, "head")  # applying twice is safe
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    command.upgrade(config, "head")
    assert len(inspect(engine).get_table_names()) == 10


def test_defaults_utc_storage_and_nullable_values(migrated_db):
    engine, _ = migrated_db
    published = datetime(2026, 11, 11, 1, 0, tzinfo=KST)
    with Session(engine) as session:
        user = AppUser(login_id="tester", password="h" * 60)
        session.add(user)
        session.flush()
        session.add_all(
            [
                FilterPreset(
                    user_id=user.id, name="조건", conditions='{"views": null}'
                ),
                FavoriteVideo(user_id=user.id, video_id="abcdefghijk"),
                SearchHistory(user_id=user.id, keyword="검색", conditions="{}"),
                SearchCache(
                    id="a" * 32,
                    cond_hash="b" * 64,
                    conditions="{}",
                    video_ids="[]",
                    funnel="{}",
                    expires_at=published,
                ),
                VideoCache(
                    video_id="abcdefghijk",
                    channel_id="c" * 24,
                    title="영상",
                    published_at=published,
                    view_count=2**40,
                ),
                ChannelCache(channel_id="c" * 24, title="채널"),
                VideoCategoryCache(region_code="KR", category_id=10, title="음악"),
                QuotaUsage(
                    usage_date=date(2026, 11, 10), endpoint="videos.list", units=1
                ),
            ]
        )
        session.commit()
        session.expire_all()
        video = session.get(VideoCache, "abcdefghijk")
        assert video.published_at == datetime(2026, 11, 10, 16, tzinfo=UTC)
        assert format_kst(video.published_at) == "2026-11-11T01:00:00+09:00"
        assert video.like_count is None
        assert video.view_count == 2**40
        assert video.fetched_at.tzinfo == UTC
        assert session.get(AppUser, user.id).last_login_at is None
        assert session.scalar(select(ChannelCache)).hidden_subscriber is False
        assert session.scalar(select(VideoCategoryCache)).assignable is True
        assert session.scalar(select(SearchCache)).quota_spent == 0
        assert session.scalar(select(SearchCache)).warnings is None
        assert session.scalar(select(SearchHistory)).result_count == 0
        preset = session.scalar(select(FilterPreset))
        assert preset.conditions == '{"views": null}'
        assert preset.created_at.tzinfo == preset.updated_at.tzinfo == UTC
        quota = session.scalar(select(QuotaUsage))
        assert quota.usage_date == date(2026, 11, 10)
        assert quota.called_at.tzinfo == UTC
    with engine.connect() as connection:
        stored = connection.scalar(text("SELECT published_at FROM video_cache"))
        assert stored == "2026-11-10 16:00:00.000000"


def test_user_constraints_and_cascade(migrated_db):
    engine, _ = migrated_db
    with Session(engine) as session:
        user = AppUser(login_id="tester", password="h" * 60)
        session.add(user)
        session.commit()
        user_id = user.id
        session.add(AppUser(login_id="tester", password="x" * 60))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add_all(
            [
                FilterPreset(user_id=user_id, name="조건", conditions="{}"),
                FavoriteVideo(user_id=user_id, video_id="abcdefghijk"),
                SearchHistory(user_id=user_id, keyword="검색", conditions="{}"),
            ]
        )
        session.commit()
        session.add(FilterPreset(user_id=user_id, name="조건", conditions="{}"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.execute(delete(AppUser).where(AppUser.id == user_id))
        session.commit()
        for model in (FilterPreset, FavoriteVideo, SearchHistory):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        session.add(FavoriteVideo(user_id=user_id, video_id="abcdefghijk"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_memory_database_is_shared_across_connections():
    engine = create_db_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE example (id INTEGER)"))
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM example")) == 0
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
    finally:
        engine.dispose()


def test_request_session_commit_and_rollback(migrated_db, monkeypatch):
    engine, _ = migrated_db
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    app = FastAPI(lifespan=lifespan)
    register_error_handlers(app)

    @app.post("/users/{login_id}")
    def create_user(login_id: str, db: Session = Depends(get_db)):
        db.add(AppUser(login_id=login_id, password="h" * 60))
        db.flush()
        if login_id == "rollback":
            raise DomainError("INVALID_LOGIN_ID", "아이디를 확인해 주세요.")
        db.commit()
        return {"status": "ok"}

    with TestClient(app) as client:
        assert client.post("/users/saved").status_code == 200
        assert client.post("/users/rollback").status_code == 400
        with Session(engine) as session:
            assert session.scalars(select(AppUser.login_id)).all() == ["saved"]
