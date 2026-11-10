"""FastAPI entry point."""

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import create_db_engine
from app.errors import register_error_handlers
from app.jobs.cleanup import run_cleanup, schedule_cleanup
from app.meta.service import router as meta_router
from app.quota.guard import QuotaGuard
from app.quota.status import router as quota_router
from app.search.service import router as search_router
from app.time_utils import utc_now


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = Settings()
    engine = create_db_engine(app.state.settings.database_url)
    app.state.engine = engine
    app.state.session_factory = sessionmaker(engine)
    app.state.quota_guard = QuotaGuard(
        app.state.session_factory, app.state.settings.quota_soft_limit
    )
    cleanup_task = None
    try:
        await asyncio.to_thread(
            run_cleanup, app.state.session_factory, app.state.settings, utc_now()
        )
        cleanup_task = asyncio.create_task(
            schedule_cleanup(app.state.session_factory, app.state.settings)
        )
        yield
    finally:
        if cleanup_task is not None:
            cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup_task
        engine.dispose()


app = FastAPI(title="tube-filter", lifespan=lifespan)
register_error_handlers(app)
app.include_router(quota_router)
app.include_router(search_router)
app.include_router(meta_router)


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
