import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.fixture
def settings_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)


def test_settings_defaults(settings_env):
    settings = Settings()
    assert settings.model_dump(exclude={"youtube_api_key", "session_secret"}) == {
        "database_url": "sqlite:///data/tubefilter.db",
        "quota_daily_limit": 10000,
        "quota_soft_limit": 9000,
        "cache_search_ttl_hours": 6,
        "cache_stats_ttl_hours": 24,
        "cache_max_days": 28,
        "limit_search_guest_per_day": 5,
        "limit_search_user_per_day": 20,
        "limit_search_per_min": 10,
        "limit_other_per_min": 60,
    }


def test_dotenv_and_environment_override(settings_env, monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(
        "DATABASE_URL=sqlite:///custom.db\nQUOTA_SOFT_LIMIT=8000\n", encoding="utf-8"
    )
    monkeypatch.setenv("QUOTA_SOFT_LIMIT", "7000")
    settings = Settings()
    assert settings.database_url == "sqlite:///custom.db"
    assert settings.quota_soft_limit == 7000


@pytest.mark.parametrize("name", ["YOUTUBE_API_KEY", "SESSION_SECRET"])
def test_required_secret(settings_env, monkeypatch, name):
    monkeypatch.delenv(name)
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("YOUTUBE_API_KEY", ""),
        ("SESSION_SECRET", "x" * 31),
        ("CACHE_MAX_DAYS", "31"),
        ("QUOTA_DAILY_LIMIT", "invalid"),
    ],
)
def test_invalid_settings(settings_env, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()


def test_cache_max_days_boundary(settings_env, monkeypatch):
    monkeypatch.setenv("CACHE_MAX_DAYS", "30")
    assert Settings().cache_max_days == 30
