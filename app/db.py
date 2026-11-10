"""Database setup. Schema changes are applied only through Alembic."""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from fastapi import Request
from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator

from app.time_utils import to_utc


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator[datetime]):
    """Store naive UTC in SQL; always return aware UTC to Python."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return to_utc(value).replace(tzinfo=None) if value is not None else None

    def process_result_value(self, value, dialect):
        return to_utc(value) if value is not None else None


def create_db_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    options = {}
    if url.get_backend_name() == "sqlite":
        options["connect_args"] = {"check_same_thread": False}
        if url.database in (None, "", ":memory:"):
            options["poolclass"] = StaticPool
        else:
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **options)
    if url.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def get_db(request: Request) -> Iterator[Session]:
    """Close sessions (and roll back uncommitted work) after each request."""
    with request.app.state.session_factory() as session:
        yield session
