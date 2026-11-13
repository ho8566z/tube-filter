"""FNC-X-001: BOM UTF-8 CSV, safe Excel cells and calculated labels."""

import asyncio
import csv
import io
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Response

from app.search.metrics import CALCULATED_LABEL
from app.search.paging import sort_items
from app.search.service import SearchService, get_service
from app.time_utils import format_kst

router = APIRouter(prefix="/api/v1/search")


def safe_cell(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_csv(
    items: list[dict[str, Any]],
    now: datetime,
    *,
    sort: str = "publishedAt",
    order: str = "desc",
    warnings: Sequence[str] = (),
) -> bytes:
    items = sort_items(items, sort=sort, order=order)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            f"# 조회 일시: {format_kst(now)}; "
            f"출처: YouTube Data API v3; {CALCULATED_LABEL}"
        ]
    )
    if warnings:
        writer.writerow(["# 경고: " + ", ".join(warnings)])
    writer.writerow(
        [
            "영상 ID",
            "제목",
            "채널",
            "게시일(KST)",
            "길이(초)",
            "조회수",
            "좋아요",
            "댓글",
            "구독자",
            "좋아요율(계산값)",
            "구독자 대비 조회수(계산값)",
        ]
    )
    for item in items[:1000]:
        writer.writerow(
            map(
                safe_cell,
                [
                    item["videoId"],
                    item["title"],
                    item["channelTitle"],
                    item["publishedAt"],
                    item["durationSec"],
                    item["stats"]["views"],
                    item["stats"]["likes"],
                    item["stats"]["comments"],
                    item["channel"]["subscribers"],
                    item["calc"]["likeRatePct"],
                    item["calc"]["viewsPerSubPct"],
                ],
            )
        )
    return output.getvalue().encode("utf-8-sig")


@router.get("/{search_id}/export.csv")
def download_csv(
    search_id: str,
    sort: str = "publishedAt",
    order: str = "desc",
    service: SearchService = Depends(get_service),
) -> Response:
    sort_items([], sort=sort, order=order)
    items, warnings = asyncio.run(service.all_results(search_id))
    return Response(
        export_csv(items, service.clock(), sort=sort, order=order, warnings=warnings),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="tube-filter-results.csv"'
        },
    )
