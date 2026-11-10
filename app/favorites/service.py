"""FNC-P-004/005: ID-only favorites using the shared 24-hour detail cache."""

import asyncio
import re

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.cache.entity_cache import EntityCache
from app.db import get_db
from app.errors import DomainError
from app.models import FavoriteVideo
from app.search.channel_info import ChannelInfo
from app.search.conditions import invalid
from app.search.details import fetch_details
from app.search.service import render_items
from app.users.auth import current_user
from app.youtube.adapter import get_youtube

router = APIRouter(prefix="/api/v1/favorites")


def validate_id(video_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise DomainError("INVALID_VIDEO_ID", "영상 ID가 올바르지 않습니다.")


@router.put("/{video_id}", status_code=204)
def add_favorite(video_id: str, request: Request, db: Session = Depends(get_db)):
    validate_id(video_id)
    uid = current_user(request, db).id
    if db.get(FavoriteVideo, (uid, video_id)) is None:
        count = db.scalar(
            select(func.count())
            .select_from(FavoriteVideo)
            .where(FavoriteVideo.user_id == uid)
        )
        if count >= 200:
            raise DomainError(
                "FAVORITE_LIMIT", "즐겨찾기는 최대 200개까지 등록할 수 있습니다."
            )
        db.add(
            FavoriteVideo(
                user_id=uid, video_id=video_id, created_at=request.app.state.clock()
            )
        )
        db.commit()
    return Response(status_code=204)


@router.delete("/{video_id}", status_code=204)
def remove_favorite(video_id: str, request: Request, db: Session = Depends(get_db)):
    validate_id(video_id)
    db.execute(
        delete(FavoriteVideo).where(
            FavoriteVideo.user_id == current_user(request, db).id,
            FavoriteVideo.video_id == video_id,
        )
    )
    db.commit()
    return Response(status_code=204)


@router.get("")
def list_favorites(
    request: Request,
    page: int = 0,
    size: int = 20,
    db: Session = Depends(get_db),
    adapter=Depends(get_youtube),
):
    if page < 0 or size not in (10, 20, 50):
        invalid("page" if page < 0 else "size")
    uid = current_user(request, db).id
    total = db.scalar(
        select(func.count())
        .select_from(FavoriteVideo)
        .where(FavoriteVideo.user_id == uid)
    )
    # Slice in Python: the per-member table is bounded at 200, and huge page
    # parameters cannot overflow SQLite's integer OFFSET binding.
    ids = list(
        db.scalars(
            select(FavoriteVideo.video_id)
            .where(FavoriteVideo.user_id == uid)
            .order_by(FavoriteVideo.created_at.desc(), FavoriteVideo.video_id)
        )
    )[page * size : (page + 1) * size]
    cache = EntityCache(request.app.state.settings, request.app.state.clock)
    lookup = asyncio.run(fetch_details(db, adapter, cache, ids))
    db.commit()
    channels = cache.get_channels(db, [v.channel_id for v in lookup.videos])
    # ChannelInfo supplies the public subscriber property used by render_items.
    channels = {
        key: ChannelInfo(
            title=row.title,
            subscriber_count=row.subscriber_count,
            hidden_subscriber=row.hidden_subscriber,
            video_count=row.video_count,
            view_count=row.view_count,
        )
        for key, row in channels.items()
    }
    rendered = {
        item["videoId"]: item
        for item in render_items(
            lookup.videos, lookup.rows, channels, request.app.state.clock()
        )
    }
    items = []
    for video_id in ids:
        if video_id in rendered:
            items.append({**rendered[video_id], "available": True})
        elif video_id in lookup.deleted_ids:
            items.append(
                {
                    "videoId": video_id,
                    "available": False,
                    "title": "더 이상 볼 수 없는 영상",
                }
            )
        else:
            # Failed refreshes do not prove that a video was deleted/private.
            items.append({"videoId": video_id, "available": False})
    result = {
        "items": items,
        "page": page,
        "size": size,
        "totalElements": total,
        "totalPages": (total + size - 1) // size,
    }
    if lookup.warnings:
        result["warnings"] = lookup.warnings
    return result
