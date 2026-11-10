"""All nine tables from docs/spec/10_테이블_명세서.md.

JSON values remain TEXT strings. Limits and cache policies belong to services
implemented in later stages.
"""

from datetime import date, datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    login_id: Mapped[str] = mapped_column(String(20), unique=True)
    password: Mapped[str] = mapped_column(String(60))
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.current_timestamp()
    )


class FilterPreset(Base):
    __tablename__ = "filter_preset"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(30))
    conditions: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.current_timestamp()
    )


class FavoriteVideo(Base):
    __tablename__ = "favorite_video"
    __table_args__ = (Index("ix_favorite_video_user_created", "user_id", "created_at"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    video_id: Mapped[str] = mapped_column(String(11), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.current_timestamp()
    )


class SearchHistory(Base):
    __tablename__ = "search_history"
    __table_args__ = (
        Index("ix_search_history_user_searched", "user_id", "searched_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    keyword: Mapped[str] = mapped_column(String(100))
    conditions: Mapped[str] = mapped_column(Text)
    result_count: Mapped[int] = mapped_column(Integer, server_default="0")
    searched_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.current_timestamp()
    )


class SearchCache(Base):
    __tablename__ = "search_cache"
    __table_args__ = (
        Index("ix_search_cache_cond_expires", "cond_hash", "expires_at"),
        Index("ix_search_cache_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(CHAR(32), primary_key=True)
    cond_hash: Mapped[str] = mapped_column(CHAR(64))
    conditions: Mapped[str] = mapped_column(Text)
    video_ids: Mapped[str] = mapped_column(Text)
    funnel: Mapped[str] = mapped_column(Text)
    warnings: Mapped[str | None] = mapped_column(Text)
    quota_spent: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.current_timestamp()
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class VideoCache(Base):
    __tablename__ = "video_cache"
    __table_args__ = (
        Index("ix_video_cache_channel_id", "channel_id"),
        Index("ix_video_cache_fetched_at", "fetched_at"),
    )

    video_id: Mapped[str] = mapped_column(String(11), primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime] = mapped_column(UTCDateTime)
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    tags: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(Integer)
    default_language: Mapped[str | None] = mapped_column(String(10))
    definition: Mapped[str | None] = mapped_column(String(2))
    made_for_kids: Mapped[bool | None] = mapped_column(Boolean)
    region_allowed: Mapped[str | None] = mapped_column(Text)
    region_blocked: Mapped[str | None] = mapped_column(Text)
    view_count: Mapped[int | None] = mapped_column(BigInteger)
    like_count: Mapped[int | None] = mapped_column(BigInteger)
    comment_count: Mapped[int | None] = mapped_column(BigInteger)
    fetched_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.current_timestamp()
    )


class ChannelCache(Base):
    __tablename__ = "channel_cache"
    __table_args__ = (Index("ix_channel_cache_fetched_at", "fetched_at"),)

    channel_id: Mapped[str] = mapped_column(String(24), primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    thumbnail_url: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(2))
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    subscriber_count: Mapped[int | None] = mapped_column(BigInteger)
    hidden_subscriber: Mapped[bool] = mapped_column(Boolean, server_default=false())
    video_count: Mapped[int | None] = mapped_column(Integer)
    view_count: Mapped[int | None] = mapped_column(BigInteger)
    uploads_playlist_id: Mapped[str | None] = mapped_column(String(34))
    recent_uploads: Mapped[str | None] = mapped_column(Text)
    recent_fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    fetched_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.current_timestamp()
    )


class VideoCategoryCache(Base):
    __tablename__ = "video_category_cache"

    region_code: Mapped[str] = mapped_column(String(2), primary_key=True)
    category_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    assignable: Mapped[bool] = mapped_column(Boolean, server_default=true())
    fetched_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.current_timestamp()
    )


class QuotaUsage(Base):
    __tablename__ = "quota_usage"
    __table_args__ = (Index("ix_quota_usage_usage_date", "usage_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usage_date: Mapped[date] = mapped_column(Date)
    endpoint: Mapped[str] = mapped_column(String(30))
    units: Mapped[int] = mapped_column(Integer)
    search_id: Mapped[str | None] = mapped_column(CHAR(32))
    called_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.current_timestamp()
    )
