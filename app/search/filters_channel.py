"""Stage 5 pure channel predicates; no pipeline or funnel aggregation."""

from collections.abc import Sequence
from datetime import datetime, timedelta

from app.search.channel_info import ChannelInfo
from app.search.filters_video import FilterResult, NumberRange, _range_result, _result
from app.search.metrics import ratio
from app.search.video_info import VideoInfo
from app.time_utils import to_utc


def filter_subscribers(
    channel: ChannelInfo, bounds: NumberRange = NumberRange()
) -> FilterResult:
    return _range_result("SUBSCRIBERS", channel.public_subscriber_count, bounds)


def filter_video_count(
    channel: ChannelInfo, bounds: NumberRange = NumberRange()
) -> FilterResult:
    return _range_result("VIDEO_COUNT", channel.video_count, bounds)


def filter_average_views(
    channel: ChannelInfo, bounds: NumberRange = NumberRange()
) -> FilterResult:
    return _range_result(
        "AVG_VIEWS", ratio(channel.view_count, channel.video_count), bounds
    )


def filter_views_per_sub(
    video: VideoInfo, channel: ChannelInfo, bounds: NumberRange = NumberRange()
) -> FilterResult:
    return _range_result(
        "VIEWS_PER_SUB",
        ratio(video.view_count, channel.public_subscriber_count, percent=True),
        bounds,
    )


def filter_channel_age(
    channel: ChannelInfo,
    *,
    now: datetime,
    created_within_days: int | None = None,
    created_before: datetime | None = None,
) -> FilterResult:
    if created_within_days is None and created_before is None:
        return _result("CHANNEL_AGE", True)
    if channel.published_at is None:
        return _result("CHANNEL_AGE", False, hidden=True)
    published = to_utc(channel.published_at)
    passed = (
        created_within_days is None
        or to_utc(now) - timedelta(days=created_within_days) <= published <= to_utc(now)
    ) and (created_before is None or published <= to_utc(created_before))
    return _result("CHANNEL_AGE", passed)


def filter_country(
    channel: ChannelInfo, countries: Sequence[str | None] = ()
) -> FilterResult:
    """None is the explicit '미설정' choice; empty choices disable the filter."""
    if not countries:
        return _result("CHANNEL_COUNTRY", True)
    country = channel.country.upper() if channel.country else None
    selected = {c.upper() if c else None for c in countries}
    return _result("CHANNEL_COUNTRY", country in selected, hidden=country is None)
