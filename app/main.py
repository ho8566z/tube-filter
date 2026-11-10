"""FastAPI entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = Settings()
    yield


app = FastAPI(title="tube-filter", lifespan=lifespan)


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
