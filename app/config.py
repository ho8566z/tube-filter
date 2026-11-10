"""Environment settings defined in docs/spec/11_설정_규약.md."""

from typing import Annotated

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "sqlite:///data/tubefilter.db"


class Settings(DatabaseSettings):
    youtube_api_key: Annotated[SecretStr, Field(min_length=1)]
    session_secret: Annotated[SecretStr, Field(min_length=32)]
    quota_daily_limit: int = 10000
    quota_soft_limit: int = 9000
    cache_search_ttl_hours: int = 6
    cache_stats_ttl_hours: int = 24
    cache_max_days: Annotated[int, Field(le=30)] = 28
    limit_search_guest_per_day: int = 5
    limit_search_user_per_day: int = 20
    limit_search_per_min: int = 10
    limit_other_per_min: int = 60
