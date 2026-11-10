"""FNC-X-004: fixed choices and region-specific seven-day category cache."""

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import DomainError
from app.models import VideoCategoryCache
from app.search.conditions import code
from app.time_utils import utc_now
from app.youtube.adapter import get_youtube

router = APIRouter(prefix="/api/v1")
LANGUAGES = [
    ("ko", "한국어"),
    ("en", "영어"),
    ("ja", "일본어"),
    ("zh", "중국어"),
    ("es", "스페인어"),
    ("fr", "프랑스어"),
    ("de", "독일어"),
]
COUNTRIES = [
    ("KR", "대한민국"),
    ("US", "미국"),
    ("JP", "일본"),
    ("CN", "중국"),
    ("GB", "영국"),
    ("CA", "캐나다"),
    ("DE", "독일"),
    ("FR", "프랑스"),
    ("IN", "인도"),
]


def metadata(db, adapter, region_code="KR", *, now=None):
    region = code(region_code, "regionCode", True)
    now = now or utc_now()
    rows = list(
        db.scalars(
            select(VideoCategoryCache).where(VideoCategoryCache.region_code == region)
        )
    )
    if not rows or any(row.fetched_at <= now - timedelta(days=7) for row in rows):
        try:
            payload = adapter.request(
                "videoCategories.list",
                {"part": "snippet", "regionCode": region, "hl": "ko"},
            )
        except DomainError as exc:
            if exc.code != "QUOTA_BLOCKED" or not rows:
                raise
            result = category_response(rows)
            result["warnings"] = ["STALE_STATS"]
            return result
        db.execute(
            delete(VideoCategoryCache).where(VideoCategoryCache.region_code == region)
        )
        rows = [
            VideoCategoryCache(
                region_code=region,
                category_id=int(item["id"]),
                title=item["snippet"]["title"],
                assignable=item["snippet"].get("assignable", True),
                fetched_at=now,
            )
            for item in payload.get("items", [])
        ]
        db.add_all(rows)
        db.commit()
    return category_response(rows)


def category_response(rows):
    return {
        "categories": [
            {"id": row.category_id, "title": row.title}
            for row in sorted(rows, key=lambda row: row.category_id)
            if row.assignable
        ],
        "languages": [{"code": key, "name": name} for key, name in LANGUAGES],
        "countries": [{"code": key, "name": name} for key, name in COUNTRIES],
        "limits": {"maxTags": 30, "maxWords": 20, "maxPages": 5, "presetMax": 30},
    }


@router.get("/meta")
def get_metadata(
    regionCode: str = "KR", db: Session = Depends(get_db), adapter=Depends(get_youtube)
):
    return metadata(db, adapter, regionCode)
