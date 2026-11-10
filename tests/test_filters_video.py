from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.search.filters_video import (
    NumberRange,
    filter_category,
    filter_count,
    filter_duration,
    filter_hour,
    filter_kids,
    filter_language,
    filter_rate,
    filter_region,
    filter_shorts,
    filter_tags,
    filter_weekday,
    filter_words,
)
from app.search.video_info import VideoInfo
from app.time_utils import KST


@pytest.mark.parametrize(
    "bounds", [NumberRange(1, 3), NumberRange(1), NumberRange(max=3)]
)
@pytest.mark.parametrize("value", [0, 1, 2, 3, 4, None])
@pytest.mark.parametrize("field", ["duration", "views", "likes", "comments"])
def test_numeric_inclusive_and_one_sided_boundaries(bounds, value, field):
    if field == "duration":
        result = filter_duration(VideoInfo(duration_sec=value), bounds)
    else:
        attribute = {
            "views": "view_count",
            "likes": "like_count",
            "comments": "comment_count",
        }[field]
        result = filter_count(VideoInfo(**{attribute: value}), field, bounds)
    expected = (
        value is not None
        and (bounds.min is None or value >= bounds.min)
        and (bounds.max is None or value <= bounds.max)
        and not (field == "duration" and value == 0)
    )
    assert result.passed == expected
    assert result.filter_name == field.upper()
    assert result.reason == (
        None if expected else "HIDDEN_VALUE" if value is None else field.upper()
    )


@pytest.mark.parametrize("value", [None, 0, 1, 43200])
def test_disabled_numeric_filters_pass(value):
    video = VideoInfo(
        duration_sec=value, view_count=value, like_count=value, comment_count=value
    )
    assert filter_duration(video).passed
    for field in ["views", "likes", "comments"]:
        assert filter_count(video, field).passed


@pytest.mark.parametrize("value", [0, 1, 43200])
def test_equal_bounds_and_duration_zero_exception(value):
    bounds = NumberRange(value, value)
    assert filter_count(VideoInfo(view_count=value), "views", bounds).passed
    assert filter_duration(VideoInfo(duration_sec=value), bounds).passed == (value != 0)


def test_inverted_range_is_not_silently_reordered():
    with pytest.raises(ValueError, match="min must not exceed max"):
        NumberRange(2, 1)


@pytest.mark.parametrize("field", ["like_rate", "comment_rate"])
@pytest.mark.parametrize(
    ("views", "count", "bounds", "passed", "hidden"),
    [
        (10000, 1, NumberRange(0.01, 0.01), True, False),
        (10000, 1, NumberRange(0.02), False, False),
        (10000, 1, NumberRange(max=0), False, False),
        (100, 100, NumberRange(100, 100), True, False),
        (100, 0, NumberRange(0, 0), True, False),
        (0, 0, NumberRange(0), False, True),
        (0, 10, NumberRange(max=100), False, True),
        (None, 10, NumberRange(0), False, True),
        (100, None, NumberRange(0), False, True),
        (None, None, NumberRange(), True, False),
        (0, 0, NumberRange(), True, False),
        (3, 1, NumberRange(max=33.33), False, False),
        (3, 1, NumberRange(33.33), True, False),
        (10000, 101, NumberRange(Decimal("1.01"), Decimal("1.01")), True, False),
    ],
)
def test_percent_units_boundaries_and_unavailable(
    field, views, count, bounds, passed, hidden
):
    attr = "like_count" if field == "like_rate" else "comment_count"
    result = filter_rate(VideoInfo(view_count=views, **{attr: count}), field, bounds)
    assert result.passed == passed
    assert result.filter_name == field.upper()
    assert result.reason == (
        None if passed else "HIDDEN_VALUE" if hidden else field.upper()
    )


@pytest.mark.parametrize(
    ("tags", "include", "exclude", "mode", "passed", "reason"),
    [
        ((" Python ", "한글"), ["python", " 한글 "], [], "AND", True, None),
        (("Python",), ["python", "한글"], [], "AND", False, "TAGS"),
        (("Python",), ["python", "한글"], [], "OR", True, None),
        (("Python",), ["java", "한글"], [], "OR", False, "TAGS"),
        (("Python",), ["py"], [], "OR", False, "TAGS"),
        (("Python",), ["python"], ["PYTHON"], "AND", False, "TAGS"),
        ((), ["python"], [], "AND", False, "HIDDEN_VALUE"),
        ((), ["python"], [], "OR", False, "HIDDEN_VALUE"),
        ((), [], ["python"], "AND", True, None),
        ((), [], [], "OR", True, None),
        (("Python",), ["python", "PYTHON", " "], [], "AND", True, None),
        (("a b",), ["a  b"], [], "AND", False, "TAGS"),
    ],
)
def test_tags_exact_normalized_and_missing(
    tags, include, exclude, mode, passed, reason
):
    result = filter_tags(VideoInfo(tags=tags), include, exclude, mode)
    assert (result.filter_name, result.passed, result.reason) == (
        "TAGS",
        passed,
        reason,
    )


@pytest.mark.parametrize(
    ("title", "description", "include", "exclude", "target", "passed"),
    [
        ("한글 Python", "FastAPI 설명", ["한글", "PYTH", "api"], [], "BOTH", True),
        ("Python", "FastAPI", ["python", "api"], [], "TITLE", False),
        ("Python", "FastAPI", ["api"], [], "DESCRIPTION", True),
        ("Python", "FastAPI", [], ["API"], "TITLE", True),
        ("Python", "FastAPI", [], ["API"], "BOTH", False),
        ("Python", "", ["python"], [], "DESCRIPTION", False),
        ("", "", [], [], "BOTH", True),
        ("hello", "world", ["lo wo"], [], "BOTH", False),
        ("hello", "", [".*"], [], "BOTH", False),
    ],
)
def test_word_targets_substrings_all_include_any_exclude(
    title, description, include, exclude, target, passed
):
    result = filter_words(
        VideoInfo(title=title, description=description), include, exclude, target
    )
    assert (result.filter_name, result.passed) == ("WORDS", passed)
    assert result.reason == (None if passed else "WORDS")


@pytest.mark.parametrize(
    ("category", "include", "exclude", "passed", "reason"),
    [
        ("27", ["10", "27"], [], True, None),
        ("27", ["10"], [], False, "CATEGORY"),
        ("27", ["27"], ["27"], False, "CATEGORY"),
        ("27", [], ["10"], True, None),
        (None, [], [], True, None),
        (None, ["27"], [], False, "HIDDEN_VALUE"),
        (None, [], ["27"], False, "HIDDEN_VALUE"),
    ],
)
def test_category_inclusion_exclusion_and_missing(
    category, include, exclude, passed, reason
):
    result = filter_category(VideoInfo(category_id=category), include, exclude)
    assert (result.filter_name, result.passed, result.reason) == (
        "CATEGORY",
        passed,
        reason,
    )


@pytest.mark.parametrize(
    ("audio", "default", "languages", "missing", "passed", "reason"),
    [
        ("ko-KR", "en", ["ko"], True, True, None),
        ("en-US", "ko", ["ko"], True, False, "LANGUAGE"),
        (None, "ko-KR", ["ko"], True, True, None),
        ("", "ko", ["KO-kr"], True, True, None),
        (None, None, ["ko"], True, True, None),
        (None, None, ["ko"], False, False, "HIDDEN_VALUE"),
        (None, None, [], False, True, None),
        ("en", None, ["ko", "en"], True, True, None),
    ],
)
def test_language_priority_prefix_and_missing_option(
    audio, default, languages, missing, passed, reason
):
    result = filter_language(
        VideoInfo(default_audio_language=audio, default_language=default),
        languages,
        include_missing=missing,
    )
    assert (result.filter_name, result.passed, result.reason) == (
        "LANGUAGE",
        passed,
        reason,
    )


@pytest.mark.parametrize("kids", [True, False, None])
@pytest.mark.parametrize("exclude", [True, False])
def test_kids_missing_passes(kids, exclude):
    result = filter_kids(VideoInfo(made_for_kids=kids), exclude=exclude)
    passed = not exclude or kids is not True
    assert (result.filter_name, result.passed, result.reason) == (
        "KIDS",
        passed,
        None if passed else "KIDS",
    )


@pytest.mark.parametrize(
    ("allowed", "blocked", "country_pass", "any_pass"),
    [
        (None, None, True, True),
        (("KR",), None, True, False),
        (("US",), None, False, False),
        (None, ("KR",), False, False),
        (None, ("US",), True, False),
        (("KR",), ("KR",), False, False),
        (("KR",), ("US",), True, False),
        (("US",), ("US",), False, False),
        ((), None, False, False),
        (None, (), True, False),
        ((), (), False, False),
    ],
)
def test_region_allowed_blocked_combinations(allowed, blocked, country_pass, any_pass):
    video = VideoInfo(region_allowed=allowed, region_blocked=blocked)
    assert filter_region(video).passed
    result = filter_region(video, exclude_restricted=True)
    assert (result.filter_name, result.passed, result.reason) == (
        "REGION",
        country_pass,
        None if country_pass else "REGION",
    )
    assert filter_region(video, exclude_any=True).passed == any_pass
    assert (
        filter_region(video, exclude_restricted=True, exclude_any=True).passed
        == any_pass
    )


def test_region_custom_country():
    assert filter_region(
        VideoInfo(region_allowed=("US",)), exclude_restricted=True, country="us"
    ).passed


@pytest.mark.parametrize(
    ("timestamp", "weekday", "hour"),
    [
        (datetime(2026, 11, 10, 14, 59, 59, tzinfo=UTC), 1, 23),
        (datetime(2026, 11, 10, 15, tzinfo=UTC), 2, 0),
        (datetime(2026, 11, 10, 16, tzinfo=UTC), 2, 1),
        (datetime(2026, 11, 15, 15, tzinfo=UTC), 0, 0),
        (datetime(2026, 12, 31, 15, tzinfo=UTC), 4, 0),
        (datetime(2026, 11, 10, 16), 2, 1),
    ],
)
def test_kst_weekday_and_hour_across_day_week_year(timestamp, weekday, hour):
    video = VideoInfo(published_at=timestamp)
    assert filter_weekday(video, [weekday]).passed
    assert not filter_weekday(video, [(weekday + 1) % 7]).passed
    assert filter_weekday(video, [weekday, (weekday + 1) % 7]).passed
    assert filter_hour(video, hour, hour).passed
    assert not filter_hour(video, (hour + 1) % 24, (hour + 1) % 24).passed


@pytest.mark.parametrize(
    ("start", "end", "included"),
    [
        (9, 17, set(range(9, 18))),
        (22, 3, {22, 23, 0, 1, 2, 3}),
        (0, 0, {0}),
        (0, 23, set(range(24))),
        (None, 3, {0, 1, 2, 3}),
        (22, None, {22, 23}),
    ],
)
def test_hour_inclusive_bins_overnight_equal_and_one_sided(start, end, included):
    for hour in range(24):
        # End of an hour is included as well as its start.
        for minute, second in [(0, 0), (59, 59)]:
            video = VideoInfo(
                published_at=datetime(2026, 11, 11, hour, minute, second, tzinfo=KST)
            )
            result = filter_hour(video, start, end)
            assert result.passed == (hour in included)
            assert result.filter_name == "HOUR"
            assert result.reason == (None if hour in included else "HOUR")


def test_missing_timestamp_when_enabled_and_disabled():
    video = VideoInfo()
    assert filter_weekday(video).passed
    assert filter_hour(video).passed
    for result in [filter_weekday(video, [0]), filter_hour(video, 0, 23)]:
        assert not result.passed
        assert result.reason == "HIDDEN_VALUE"


@pytest.mark.parametrize("duration", [None, 0, 1, 179, 180, 181, 43200])
@pytest.mark.parametrize("mode", ["ANY", "ONLY", "EXCLUDE"])
def test_shorts_estimate_boundary(duration, mode):
    result = filter_shorts(VideoInfo(duration_sec=duration), mode)
    passed = mode == "ANY" or (
        duration is not None and ((duration <= 180) == (mode == "ONLY"))
    )
    assert (result.filter_name, result.passed) == ("SHORTS", passed)
    assert result.reason == (
        None if passed else "HIDDEN_VALUE" if duration is None else "SHORTS"
    )


def test_predicates_are_independent_and_do_not_mutate_video_or_conditions():
    video = VideoInfo(duration_sec=180, tags=("Python",), like_count=None)
    original = replace(video)
    tags = [" PYTHON "]
    predicates = [
        lambda: filter_duration(video, NumberRange(180, 180)),
        lambda: filter_tags(video, tags),
        lambda: filter_count(video, "likes", NumberRange(0)),
        lambda: filter_shorts(video, "ONLY"),
    ]
    forward = [predicate() for predicate in predicates]
    backward = [predicate() for predicate in reversed(predicates)]
    assert forward == backward[::-1]
    assert video == original
    assert tags == [" PYTHON "]
