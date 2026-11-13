"""Public analytics routes: never fetch additional YouTube data."""

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends

from app.analysis.heatmap import heatmap
from app.analysis.scatter import scatter
from app.analysis.summary import summarize
from app.search.service import SearchService, get_service

router = APIRouter(prefix="/api/v1/search")


@router.get("/{search_id}/summary")
def result_summary(
    search_id: str, service: SearchService = Depends(get_service)
) -> dict[str, Any]:
    items, _ = asyncio.run(service.all_results(search_id))
    return summarize(items)


@router.get("/{search_id}/scatter")
def result_scatter(
    search_id: str, service: SearchService = Depends(get_service)
) -> list[dict[str, Any]]:
    items, _ = asyncio.run(service.all_results(search_id))
    return scatter(items)


@router.get("/{search_id}/heatmap")
def result_heatmap(
    search_id: str, service: SearchService = Depends(get_service)
) -> dict[str, Any]:
    items, _ = asyncio.run(service.all_results(search_id))
    return heatmap(
        datetime.fromisoformat(item["publishedAt"])
        for item in items
        if item["publishedAt"] is not None
    )
