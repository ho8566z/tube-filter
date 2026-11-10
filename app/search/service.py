"""FNC-S-012: compose existing stage 1–5 parts into the search pipeline."""

import asyncio
import json
from dataclasses import fields
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cache.entity_cache import EntityCache
from app.cache.search_cache import SearchResultCache
from app.db import get_db
from app.errors import DomainError
from app.models import ChannelCache, QuotaUsage, SearchCache
from app.quota.clock import next_reset
from app.quota.estimate import estimate
from app.quota.status import used_units
from app.search import filters_channel as fc
from app.search import filters_video as fv
from app.search.activity import fetch_activity
from app.search.candidates import fetch_candidates
from app.search.channel_info import ChannelInfo
from app.search.channels import fetch_channels
from app.search.conditions import normalize
from app.search.details import fetch_details
from app.search.funnel import Funnel
from app.search.metrics import calculate_metrics
from app.search.paging import paginate
from app.time_utils import format_kst, to_utc, utc_now
from app.youtube.adapter import get_youtube

router = APIRouter(prefix="/api/v1/search")


def new_search_hook(request: Request):
    """Stage 7 attaches guest/member usage enforcement here, on cache misses only."""


def video_predicates(video, v):
    yield fv.filter_duration(video, fv.NumberRange(**v["durationSec"]))
    for key in ("views", "likes", "comments"):
        yield fv.filter_count(video, key, fv.NumberRange(**v[key]))
    for key, field in (
        ("likeRatePct", "like_rate"),
        ("commentRatePct", "comment_rate"),
    ):
        yield fv.filter_rate(video, field, fv.NumberRange(**v[key]))
    tags, words, cats = v["tags"], v["words"], v["categoryIds"]
    yield fv.filter_tags(video, tags["include"], tags["exclude"], tags["mode"])
    yield fv.filter_words(video, words["must"], words["not"], words["target"])
    # A single included category was already handled by search.list.
    yield fv.filter_category(
        video, cats["include"] if len(cats["include"]) > 1 else (), cats["exclude"]
    )
    yield fv.filter_language(
        video, v["languages"], include_missing=v["includeNoLanguage"]
    )
    yield fv.filter_kids(video, exclude=v["excludeKids"])
    r = v["excludeRestricted"]
    yield fv.filter_region(
        video,
        exclude_restricted=bool(r),
        country=r.get("country", "KR"),
        exclude_any=r.get("anyRestriction", False),
    )
    yield fv.filter_weekday(video, v["weekdays"])
    yield fv.filter_hour(video, v["hours"].get("from"), v["hours"].get("to"))
    yield fv.filter_shorts(video, v["shorts"])


def channel_predicates(video, channel, c, now):
    yield fc.filter_subscribers(channel, fv.NumberRange(**c["subscribers"]))
    yield fc.filter_views_per_sub(video, channel, fv.NumberRange(**c["viewsPerSubPct"]))
    yield fc.filter_video_count(channel, fv.NumberRange(**c["videoCount"]))
    yield fc.filter_average_views(channel, fv.NumberRange(**c["avgViews"]))
    created = c["created"]
    yield fc.filter_channel_age(
        channel,
        now=now,
        created_within_days=created.get("withinDays"),
        created_before=datetime.fromisoformat(created["before"])
        if "before" in created
        else None,
    )
    yield fc.filter_country(channel, c["countries"])


def cached_channels(db, ids, cache):
    result = {}
    names = [field.name for field in fields(ChannelInfo)]
    if ids:
        rows = db.scalars(
            select(ChannelCache).where(
                ChannelCache.channel_id.in_(ids),
                ChannelCache.fetched_at > to_utc(cache.clock()) - cache.max_age,
            )
        )
        for row in rows:
            result[row.channel_id] = ChannelInfo(
                **{key: getattr(row, key) for key in names}
            )
    return result


def render_items(videos, rows, channels, now, activities=None):
    items = []
    for video in videos:
        channel = channels.get(video.channel_id)
        calc = calculate_metrics(
            video, channel, (activities or {}).get(video.channel_id), now=now
        )["calc"]
        # Public API names from 08_API; reuse the exact shared metric calculations.
        for old, new in (
            ("likeRate", "likeRatePct"),
            ("commentRate", "commentRatePct"),
            ("viewsPerSub", "viewsPerSubPct"),
        ):
            calc[new] = calc.pop(old)
        items.append(
            {
                "videoId": video.video_id,
                "title": video.title,
                "channelId": video.channel_id,
                "channelTitle": channel.title if channel else None,
                "publishedAt": format_kst(video.published_at)
                if video.published_at
                else None,
                "durationSec": video.duration_sec,
                "thumbnailUrl": rows[video.video_id].thumbnail_url,
                "stats": {
                    "views": video.view_count,
                    "likes": video.like_count,
                    "comments": video.comment_count,
                },
                "channel": {
                    "subscribers": channel.public_subscriber_count if channel else None
                },
                "calc": calc,
            }
        )
    return items


class SearchService:
    def __init__(self, db, adapter, settings, *, clock=utc_now):
        self.db, self.adapter, self.settings, self.clock = db, adapter, settings, clock
        self.cache = EntityCache(settings, clock)
        self.search_cache = SearchResultCache(settings, clock)

    def spent(self, search_id):
        return self.db.scalar(
            select(func.coalesce(func.sum(QuotaUsage.units), 0)).where(
                QuotaUsage.search_id == search_id
            )
        )

    async def result_items(self, row, *, cache_only):
        lookup = await fetch_details(
            self.db,
            self.adapter,
            self.cache,
            json.loads(row.video_ids),
            cache_only=cache_only,
        )
        self.db.commit()
        channels = cached_channels(
            self.db, [v.channel_id for v in lookup.videos], self.cache
        )
        activities = self.cache.get_channel_activity(self.db, list(channels))
        return render_items(
            lookup.videos, lookup.rows, channels, self.clock(), activities
        ), lookup.warnings

    async def execute(self, conditions, *, on_new_search=lambda: None):
        now, db = self.clock(), self.db
        row = self.search_cache.get(db, conditions.data)
        if row is not None:
            items, extra_warnings = await self.result_items(row, cache_only=True)
            return self.response(row, paginate(items), True, 0, extra_warnings)
        on_new_search()
        search_id = uuid4().hex
        ids, warnings = await fetch_candidates(
            self.adapter, conditions, search_id=search_id
        )
        funnel = Funnel(len(ids))
        lookup = await fetch_details(
            db, self.adapter, self.cache, ids, search_id=search_id
        )
        db.commit()  # Release entity writes before workers reserve quota independently.
        warnings.extend(lookup.warnings)
        funnel.drops["DELETED"] += len(lookup.deleted_ids)
        available = {v.video_id for v in lookup.videos}
        funnel.drops["HIDDEN_VALUE"] += sum(
            key not in available for key in lookup.failed_ids
        )
        v, c = conditions.data["video"], conditions.data["channel"]
        videos = [
            video
            for video in lookup.videos
            if funnel.accept(video_predicates(video, v))
        ]
        funnel.stages["afterVideoFilters"] = len(videos)
        channels = {}
        if videos:
            # fetch_channels itself parallelizes the 50-ID adapter batches.
            channel_lookup = fetch_channels(
                db,
                self.adapter,
                self.cache,
                [video.channel_id for video in videos],
                search_id=search_id,
            )
            db.commit()
            warnings.extend(channel_lookup.warnings)
            channels = {
                channel.channel_id: channel for channel in channel_lookup.channels
            }
        # Missing channels only fail when a channel condition needs their data.
        first_channel_filter = next(
            (
                name
                for key, name in (
                    ("subscribers", "SUBSCRIBERS"),
                    ("viewsPerSubPct", "VIEWS_PER_SUB"),
                    ("videoCount", "VIDEO_COUNT"),
                    ("avgViews", "AVG_VIEWS"),
                    ("created", "CHANNEL_AGE"),
                    ("countries", "CHANNEL_COUNTRY"),
                )
                if c[key]
            ),
            None,
        )

        def channel_results(video):
            if video.channel_id not in channels and first_channel_filter:
                yield fv.FilterResult(first_channel_filter, False, "HIDDEN_VALUE")
            else:
                yield from channel_predicates(
                    video, channels.get(video.channel_id, ChannelInfo()), c, now
                )

        videos = [video for video in videos if funnel.accept(channel_results(video))]
        funnel.stages["afterChannelFilters"] = len(videos)
        activities = {}
        if videos and conditions.activity.active:
            selected = list(dict.fromkeys(video.channel_id for video in videos))
            activity = await fetch_activity(
                db,
                self.adapter,
                self.cache,
                [channels[key] for key in selected if key in channels],
                conditions.activity,
                now=now,
                search_id=search_id,
            )
            db.commit()
            warnings.extend(activity.warnings)
            activities = activity.activities
            videos = [
                video
                for video in videos
                if funnel.accept(
                    (
                        activity.results.get(
                            video.channel_id,
                            fv.FilterResult("ACTIVITY", False, "ACTIVITY"),
                        ),
                    )
                )
            ]
        funnel.stages.update(afterActivityFilters=len(videos), final=len(videos))
        warnings = list(dict.fromkeys(warnings))
        spent = self.spent(search_id)
        row = self.search_cache.save(
            db,
            conditions.data,
            [video.video_id for video in videos],
            funnel.output(warnings),
            warnings=warnings,
            quota_spent=spent,
            search_id=search_id,
        )
        db.commit()
        items = render_items(videos, lookup.rows, channels, now, activities)
        return self.response(row, paginate(items), False, spent)

    def response(self, row, page, cached, spent, extra_warnings=()):
        now = self.clock()
        used = used_units(self.db, now)
        return {
            "searchId": row.id,
            "cached": cached,
            "funnel": json.loads(row.funnel),
            "quota": {
                "spent": spent,
                "usedToday": used,
                "remainingToday": max(0, self.settings.quota_daily_limit - used),
                "resetAt": format_kst(next_reset(now)),
            },
            "warnings": list(
                dict.fromkeys(json.loads(row.warnings or "[]") + list(extra_warnings))
            ),
            "page": page,
        }

    async def results(self, search_id, **paging):
        # Validate query even for empty results.
        paginate([], **paging)
        row = self.db.get(SearchCache, search_id)
        if row is None or row.expires_at <= to_utc(self.clock()):
            raise DomainError(
                "SEARCH_NOT_FOUND",
                "검색 결과가 만료되었습니다. 다시 검색해 주세요.",
                404,
            )
        items, warnings = await self.result_items(row, cache_only=False)
        page = paginate(items, **paging)
        if warnings:
            page["warnings"] = warnings
        return page


def get_service(
    request: Request, db: Session = Depends(get_db), adapter=Depends(get_youtube)
):
    return SearchService(db, adapter, request.app.state.settings)


@router.post("/estimate")
def estimate_search(body: dict, service=Depends(get_service)):
    conditions = normalize(body, now=service.clock())
    return estimate(
        service.db, conditions, service.search_cache, service.settings, service.clock()
    )


@router.post("")
def execute_search(body: dict, request: Request, service=Depends(get_service)):
    # A sync route keeps the complete Session lifecycle on its worker thread.
    return asyncio.run(
        service.execute(
            normalize(body, now=service.clock()),
            on_new_search=lambda: new_search_hook(request),
        )
    )


@router.get("/{search_id}/results")
def search_results(
    search_id: str,
    page: int = 0,
    size: int = 20,
    sort: str = "publishedAt",
    order: str = "desc",
    service=Depends(get_service),
):
    return asyncio.run(
        service.results(search_id, page=page, size=size, sort=sort, order=order)
    )
