from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction

import pytest

from app.search.activity import ActivityConditions, filter_activity
from app.search.channel_info import ChannelInfo
from app.search.filters_channel import (
    filter_average_views,
    filter_channel_age,
    filter_country,
    filter_subscribers,
    filter_video_count,
    filter_views_per_sub,
)
from app.search.filters_video import NumberRange, filter_rate
from app.search.metrics import ChannelActivity, calculate_metrics, rounded
from app.search.video_info import VideoInfo

NOW = datetime(2026, 11, 10, 15, tzinfo=UTC)


@pytest.mark.parametrize(
    "predicate,field,code",
    [
        (filter_subscribers, "subscriber_count", "SUBSCRIBERS"),
        (filter_video_count, "video_count", "VIDEO_COUNT"),
        (filter_average_views, "view_count", "AVG_VIEWS"),
    ],
)
@pytest.mark.parametrize(
    "value,passed", [(None, False), (0, False), (9, False), (10, True), (11, False)]
)
def test_scale_boundaries(predicate, field, code, value, passed):
    channel = replace(ChannelInfo(video_count=1), **{field: value})
    result = predicate(channel, NumberRange(10, 10))
    assert result.filter_name == code
    assert result.passed is passed
    assert result.reason == (
        None if passed else "HIDDEN_VALUE" if value is None else code
    )
    assert predicate(channel).passed


@pytest.mark.parametrize("hidden,subs", [(True, 100), (False, None), (False, 0)])
def test_subscriber_hidden_and_zero(hidden, subs):
    channel = ChannelInfo(subscriber_count=subs, hidden_subscriber=hidden)
    assert filter_subscribers(channel).passed
    assert filter_views_per_sub(VideoInfo(), channel).passed
    ratio = filter_views_per_sub(VideoInfo(view_count=100), channel, NumberRange(min=0))
    assert ratio.reason == "HIDDEN_VALUE"
    result = filter_subscribers(channel, NumberRange(0, 0))
    assert result.passed is (not hidden and subs == 0)


@pytest.mark.parametrize(
    "views,passed", [(299, False), (300, True), (301, False), (None, False)]
)
def test_views_per_sub_boundaries(views, passed):
    result = filter_views_per_sub(
        VideoInfo(view_count=views),
        ChannelInfo(subscriber_count=100),
        NumberRange(300, 300),
    )
    assert result.passed is passed
    assert result.filter_name == "VIEWS_PER_SUB"
    assert filter_views_per_sub(
        VideoInfo(view_count=10**18),
        ChannelInfo(subscriber_count=1),
        NumberRange(min=300),
    ).passed


def test_average_zero_and_unrounded_ratios():
    assert (
        filter_average_views(
            ChannelInfo(video_count=0, view_count=1), NumberRange(min=0)
        ).reason
        == "HIDDEN_VALUE"
    )
    assert not filter_average_views(
        ChannelInfo(video_count=3, view_count=1), NumberRange(max=Decimal("0.33"))
    ).passed
    assert not filter_views_per_sub(
        VideoInfo(view_count=1),
        ChannelInfo(subscriber_count=3),
        NumberRange(max=Decimal("33.33")),
    ).passed
    assert not filter_rate(
        VideoInfo(view_count=3, like_count=1),
        "like_rate",
        NumberRange(max=Decimal("33.33")),
    ).passed


@pytest.mark.parametrize("offset,passed", [(-1, False), (0, True), (1, True)])
def test_age_recent_boundary(offset, passed):
    channel = ChannelInfo(
        published_at=NOW - timedelta(days=30) + timedelta(seconds=offset)
    )
    assert filter_channel_age(channel, now=NOW, created_within_days=30).passed is passed


@pytest.mark.parametrize("offset,passed", [(-1, True), (0, True), (1, False)])
def test_age_before_boundary(offset, passed):
    channel = ChannelInfo(published_at=NOW + timedelta(seconds=offset))
    assert filter_channel_age(channel, now=NOW, created_before=NOW).passed is passed


def test_age_missing_future_and_timezone():
    assert filter_channel_age(ChannelInfo(), now=NOW).passed
    assert (
        filter_channel_age(ChannelInfo(), now=NOW, created_within_days=30).reason
        == "HIDDEN_VALUE"
    )
    assert not filter_channel_age(
        ChannelInfo(published_at=NOW + timedelta(seconds=1)),
        now=NOW,
        created_within_days=30,
    ).passed
    assert filter_channel_age(
        ChannelInfo(published_at=NOW.replace(tzinfo=None)), now=NOW, created_before=NOW
    ).passed


@pytest.mark.parametrize(
    "country,selected,passed",
    [
        (None, (), True),
        (None, ("KR",), False),
        (None, (None,), True),
        ("kr", ("KR",), True),
        ("US", ("KR",), False),
        ("US", ("KR", "US"), True),
    ],
)
def test_country(country, selected, passed):
    result = filter_country(ChannelInfo(country=country), selected)
    assert result.filter_name == "CHANNEL_COUNTRY"
    assert result.passed is passed


@pytest.mark.parametrize("days", [30, 60, 90])
@pytest.mark.parametrize("offset,passed", [(-1, False), (0, True), (1, True)])
def test_activity_time_boundary(days, offset, passed):
    activity = ChannelActivity(
        (NOW - timedelta(days=days) + timedelta(seconds=offset),)
    )
    for conditions in (
        ActivityConditions(days, NumberRange(1, 1)),
        ActivityConditions(last_upload_within_days=days),
    ):
        result = filter_activity(activity, conditions, now=NOW)
        assert result.filter_name == "ACTIVITY"
        assert result.passed is passed


@pytest.mark.parametrize("count,passed", [(0, False), (1, True), (2, False)])
def test_activity_count_boundaries(count, passed):
    activity = ChannelActivity((NOW,) * count)
    assert (
        filter_activity(
            activity, ActivityConditions(count=NumberRange(1, 1)), now=NOW
        ).passed
        is passed
    )


def test_activity_unknown_empty_future_saturation():
    unknown = ChannelActivity()
    assert filter_activity(unknown, now=NOW).passed
    assert (
        filter_activity(
            unknown, ActivityConditions(count=NumberRange(min=0)), now=NOW
        ).reason
        == "HIDDEN_VALUE"
    )
    empty = ChannelActivity(())
    assert filter_activity(
        empty, ActivityConditions(count=NumberRange(0, 0)), now=NOW
    ).passed
    assert not filter_activity(
        empty, ActivityConditions(last_upload_within_days=30), now=NOW
    ).passed
    assert ChannelActivity((NOW + timedelta(seconds=1),)).count(30, NOW) == 0
    saturated = ChannelActivity((NOW,) * 50)
    calc = calculate_metrics(VideoInfo(), activity=saturated, now=NOW)["calc"]
    assert calc["recentUploads"]["30"] == {"count": 50, "atLeast": True}
    with pytest.raises(ValueError):
        ActivityConditions(window_days=31)
    with pytest.raises(ValueError):
        NumberRange(2, 1)


@pytest.mark.parametrize(
    "value,expected",
    [
        (Fraction(1, 8), 0.13),
        (Fraction(1249, 10000), 0.12),
        (Fraction(1251, 10000), 0.13),
        (Fraction(1, 3), 0.33),
        (None, None),
    ],
)
def test_rounding(value, expected):
    assert rounded(value) == expected


def test_calculated_fields_and_kst_midnight():
    video = VideoInfo(view_count=8, like_count=1, comment_count=0, published_at=NOW)
    calc = calculate_metrics(
        video, ChannelInfo(subscriber_count=1, view_count=1, video_count=8), now=NOW
    )["calc"]
    assert calc["label"] == "계산값 · YouTube 제공 지표 아님"
    assert (
        calc["likeRate"],
        calc["commentRate"],
        calc["viewsPerSub"],
        calc["avgViews"],
    ) == (12.5, 0.0, 800.0, 0.13)
    assert (calc["uploadWeekdayKst"], calc["uploadHourKst"]) == (2, 0)
    for channel in (
        None,
        ChannelInfo(subscriber_count=0, video_count=0),
        ChannelInfo(subscriber_count=100, hidden_subscriber=True),
    ):
        calc = calculate_metrics(VideoInfo(view_count=0), channel, now=NOW)["calc"]
        assert all(
            calc[key] is None
            for key in ("likeRate", "commentRate", "viewsPerSub", "avgViews")
        )


def test_channel_mapping_hidden_missing_and_zero():
    channel = ChannelInfo.from_youtube(
        {
            "id": "c",
            "statistics": {
                "hiddenSubscriberCount": True,
                "subscriberCount": "123",
                "videoCount": "0",
            },
            "snippet": {"publishedAt": "2026-11-10T00:00:00Z"},
            "contentDetails": {"relatedPlaylists": {"uploads": "u"}},
        }
    )
    assert channel.subscriber_count is None and channel.hidden_subscriber
    assert channel.video_count == 0 and channel.view_count is None
    assert channel.published_at.tzinfo == UTC
    assert channel.uploads_playlist_id == "u"
    assert ChannelInfo.from_youtube({}).subscriber_count is None
