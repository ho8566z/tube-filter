"""Stage 4 pure video predicates. No API, DB, funnel, or pipeline dependencies.

Empty conditions pass even when data is missing. Results identify both the
filter and the drop code, so HIDDEN_VALUE does not lose the filter identity.
Callers supply normalized conditions; HTTP input validation belongs to stage 6.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from app.search.metrics import ratio
from app.search.video_info import VideoInfo
from app.time_utils import to_kst

FilterName = Literal[
    "DURATION",
    "VIEWS",
    "LIKES",
    "COMMENTS",
    "LIKE_RATE",
    "COMMENT_RATE",
    "TAGS",
    "WORDS",
    "CATEGORY",
    "LANGUAGE",
    "KIDS",
    "REGION",
    "WEEKDAY",
    "HOUR",
    "SHORTS",
    "SUBSCRIBERS",
    "VIEWS_PER_SUB",
    "VIDEO_COUNT",
    "AVG_VIEWS",
    "CHANNEL_AGE",
    "CHANNEL_COUNTRY",
    "ACTIVITY",
]
Number = int | float | Decimal


@dataclass(frozen=True)
class NumberRange:
    """Inclusive range; units are seconds, individual counts, or percent."""

    min: Number | None = None
    max: Number | None = None

    def __post_init__(self) -> None:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must not exceed max")

    @property
    def active(self) -> bool:
        return self.min is not None or self.max is not None

    def contains(self, value: Number | Fraction) -> bool:
        # Decimal-string conversion avoids binary float errors at % boundaries.
        return (self.min is None or value >= Fraction(str(self.min))) and (
            self.max is None or value <= Fraction(str(self.max))
        )


@dataclass(frozen=True)
class FilterResult:
    filter_name: FilterName
    passed: bool
    reason: str | None = None


def _result(name: FilterName, passed: bool, *, hidden: bool = False) -> FilterResult:
    return FilterResult(
        name, passed, None if passed else "HIDDEN_VALUE" if hidden else name
    )


def _range_result(
    name: FilterName, value: Number | Fraction | None, bounds: NumberRange
) -> FilterResult:
    if not bounds.active:
        return _result(name, True)
    if value is None:
        return _result(name, False, hidden=True)
    return _result(name, bounds.contains(value))


def filter_duration(
    video: VideoInfo, bounds: NumberRange = NumberRange()
) -> FilterResult:
    """FNC-F-002: seconds, inclusive; zero fails only when enabled."""
    if bounds.active and video.duration_sec == 0:
        return _result("DURATION", False)
    return _range_result("DURATION", video.duration_sec, bounds)


def filter_count(
    video: VideoInfo,
    field: Literal["views", "likes", "comments"],
    bounds: NumberRange = NumberRange(),
) -> FilterResult:
    """FNC-F-003: direct input accepts single counts, including zero."""
    name, value = {
        "views": ("VIEWS", video.view_count),
        "likes": ("LIKES", video.like_count),
        "comments": ("COMMENTS", video.comment_count),
    }[field]
    return _range_result(name, value, bounds)


def filter_rate(
    video: VideoInfo,
    field: Literal["like_rate", "comment_rate"],
    bounds: NumberRange = NumberRange(),
) -> FilterResult:
    """FNC-F-004: compare exact percent, without display rounding.

    Reuses the shared exact ratio calculation. Rounded display metrics are
    produced separately by metrics.calculate_metrics (FNC-S-009).
    """
    name, numerator = {
        "like_rate": ("LIKE_RATE", video.like_count),
        "comment_rate": ("COMMENT_RATE", video.comment_count),
    }[field]
    value = ratio(numerator, video.view_count, percent=True)
    return _range_result(name, value, bounds)


def _tags(values: Sequence[str]) -> set[str]:
    return {value.strip().lower() for value in values if value.strip()}


def filter_tags(
    video: VideoInfo,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    mode: Literal["AND", "OR"] = "AND",
) -> FilterResult:
    """FNC-F-005: exact tags; trim ends, lowercase, deduplicate."""
    actual, required, forbidden = _tags(video.tags), _tags(include), _tags(exclude)
    if not required and not forbidden:
        return _result("TAGS", True)
    if required and not actual:
        return _result("TAGS", False, hidden=True)
    included = not required or (
        required <= actual if mode == "AND" else bool(required & actual)
    )
    return _result("TAGS", included and not bool(forbidden & actual))


def filter_words(
    video: VideoInfo,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    target: Literal["TITLE", "DESCRIPTION", "BOTH"] = "BOTH",
) -> FilterResult:
    """FNC-F-006: each word may match either selected field, never across fields."""
    texts = {
        "TITLE": (video.title,),
        "DESCRIPTION": (video.description,),
        "BOTH": (video.title, video.description),
    }[target]
    texts = tuple(text.lower() for text in texts)

    def found(word: str) -> bool:
        return any(word.lower() in text for text in texts)

    return _result(
        "WORDS",
        all(found(word) for word in include)
        and not any(found(word) for word in exclude),
    )


def filter_category(
    video: VideoInfo, include: Sequence[str] = (), exclude: Sequence[str] = ()
) -> FilterResult:
    """FNC-F-007 predicate only; category retrieval is outside pure filters."""
    if not include and not exclude:
        return _result("CATEGORY", True)
    if video.category_id is None:
        return _result("CATEGORY", False, hidden=True)
    return _result(
        "CATEGORY",
        (not include or video.category_id in include)
        and video.category_id not in exclude,
    )


def filter_language(
    video: VideoInfo, languages: Sequence[str] = (), *, include_missing: bool = True
) -> FilterResult:
    """FNC-F-008: audio first, then default; compare first two characters."""
    if not languages:
        return _result("LANGUAGE", True)
    language = video.default_audio_language or video.default_language
    if not language:
        return _result("LANGUAGE", include_missing, hidden=True)
    return _result(
        "LANGUAGE", language.lower()[:2] in {v.lower()[:2] for v in languages}
    )


def filter_kids(video: VideoInfo, *, exclude: bool = False) -> FilterResult:
    """FNC-F-009: missing madeForKids explicitly passes."""
    return _result("KIDS", not exclude or video.made_for_kids is not True)


def filter_region(
    video: VideoInfo,
    *,
    exclude_restricted: bool = False,
    country: str = "KR",
    exclude_any: bool = False,
) -> FilterResult:
    """FNC-F-009: absent restrictions pass; empty allowed means nowhere allowed."""
    allowed, blocked = video.region_allowed, video.region_blocked
    restricted = allowed is not None or blocked is not None
    if exclude_any and restricted:
        return _result("REGION", False)
    country = country.upper()
    unavailable = (
        allowed is not None and country not in {v.upper() for v in allowed}
    ) or (blocked is not None and country in {v.upper() for v in blocked})
    return _result("REGION", not exclude_restricted or not unavailable)


def filter_weekday(video: VideoInfo, weekdays: Sequence[int] = ()) -> FilterResult:
    """FNC-F-010: Python weekday numbering, Monday=0 through Sunday=6, in KST."""
    if not weekdays:
        return _result("WEEKDAY", True)
    if video.published_at is None:
        return _result("WEEKDAY", False, hidden=True)
    return _result("WEEKDAY", to_kst(video.published_at).weekday() in weekdays)


def filter_hour(
    video: VideoInfo, hour_from: int | None = None, hour_to: int | None = None
) -> FilterResult:
    """FNC-F-010: inclusive KST hour bins; reversed bounds cross midnight.

    A missing endpoint extends to 00 or 23. Equal endpoints select one hour.
    """
    if hour_from is None and hour_to is None:
        return _result("HOUR", True)
    if video.published_at is None:
        return _result("HOUR", False, hidden=True)
    start = 0 if hour_from is None else hour_from
    end = 23 if hour_to is None else hour_to
    hour = to_kst(video.published_at).hour
    passed = start <= hour <= end if start <= end else hour >= start or hour <= end
    return _result("HOUR", passed)


def filter_shorts(
    video: VideoInfo, mode: Literal["ANY", "EXCLUDE", "ONLY"] = "ANY"
) -> FilterResult:
    """FNC-F-011: estimated Shorts means duration <= 180 seconds."""
    if mode == "ANY":
        return _result("SHORTS", True)
    if video.duration_sec is None:
        return _result("SHORTS", False, hidden=True)
    estimated = video.duration_sec <= 180
    return _result("SHORTS", estimated if mode == "ONLY" else not estimated)
