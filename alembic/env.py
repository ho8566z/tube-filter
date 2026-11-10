"""Alembic uses DATABASE_URL (or the documented SQLite default)."""

from alembic import context
from app import models  # noqa: F401 -- register all tables in Base.metadata
from app.config import DatabaseSettings
from app.db import Base, create_db_engine

target_metadata = Base.metadata


def database_url() -> str:
    # Migrations do not need the API key or session secret.
    return DatabaseSettings().database_url


if context.is_offline_mode():
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_db_engine(database_url())
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
