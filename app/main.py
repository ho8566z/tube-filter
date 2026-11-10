"""FastAPI entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import create_db_engine
from app.errors import register_error_handlers
from app.quota.guard import QuotaGuard
from app.quota.status import router as quota_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = Settings()
    engine = create_db_engine(app.state.settings.database_url)
    app.state.engine = engine
    app.state.session_factory = sessionmaker(engine)
    app.state.quota_guard = QuotaGuard(
        app.state.session_factory, app.state.settings.quota_soft_limit
    )
    try:
        yield
    finally:
        engine.dispose()


app = FastAPI(title="tube-filter", lifespan=lifespan)
register_error_handlers(app)
app.include_router(quota_router)


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
