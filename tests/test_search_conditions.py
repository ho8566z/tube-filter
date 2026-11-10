from datetime import UTC, datetime

import pytest

from app.errors import DomainError
from app.search.conditions import normalize

NOW = datetime(2026, 11, 10, 8, tzinfo=UTC)


@pytest.mark.parametrize("length", [1, 100])
@pytest.mark.parametrize("pages", [1, 5])
def test_keyword_and_page_edges(length, pages):
    assert normalize({"keyword": "a" * length, "pages": pages}).data["pages"] == pages


@pytest.mark.parametrize(
    "body,code",
    [
        ({"keyword": ""}, "VALIDATION_ERROR"),
        ({"keyword": " "}, "VALIDATION_ERROR"),
        ({"keyword": "x" * 101}, "VALIDATION_ERROR"),
        ({"pages": 0}, "VALIDATION_ERROR"),
        ({"pages": 6}, "VALIDATION_ERROR"),
        ({"pages": True}, "VALIDATION_ERROR"),
        ({"pages": 2.5}, "VALIDATION_ERROR"),
        ({"order": "unknown"}, "INVALID_SORT"),
        ({"video": {"views": {"min": 2, "max": 1}}}, "INVALID_RANGE"),
        ({"video": {"views": {"min": -1}}}, "INVALID_RANGE"),
        ({"video": {"views": {"min": 1.5}}}, "INVALID_RANGE"),
        ({"video": {"views": {"min": True}}}, "INVALID_RANGE"),
        ({"video": {"likeRatePct": {"max": 100.01}}}, "INVALID_RANGE"),
        ({"video": {"likeRatePct": {"min": 0.001}}}, "INVALID_RANGE"),
        ({"video": {"likeRatePct": {"min": float("nan")}}}, "INVALID_RANGE"),
        ({"video": {"durationSec": {"max": 43201}}}, "INVALID_DURATION"),
        ({"video": {"durationSec": {"min": "12:60"}}}, "INVALID_DURATION"),
        ({"video": {"durationSec": {"min": "12:00:01"}}}, "INVALID_DURATION"),
        (
            {"video": {"tags": {"include": [str(i) for i in range(31)]}}},
            "TOO_MANY_TAGS",
        ),
        (
            {"video": {"tags": {"exclude": [str(i) for i in range(31)]}}},
            "TOO_MANY_TAGS",
        ),
        ({"video": {"tags": {"include": ["x" * 51]}}}, "VALIDATION_ERROR"),
        (
            {"video": {"words": {"must": [str(i) for i in range(21)]}}},
            "VALIDATION_ERROR",
        ),
        ({"video": {"weekdays": [7]}}, "VALIDATION_ERROR"),
        ({"video": {"hours": {"from": 24}}}, "VALIDATION_ERROR"),
        ({"video": {"shorts": "yes"}}, "VALIDATION_ERROR"),
        ({"video": {"tags": {"mode": "X"}}}, "VALIDATION_ERROR"),
        ({"video": {"words": {"target": "X"}}}, "VALIDATION_ERROR"),
        ({"video": {"hd": "false"}}, "VALIDATION_ERROR"),
        ({"video": {"regionCode": "KRR"}}, "VALIDATION_ERROR"),
        ({"video": {"categoryIds": {"include": [0]}}}, "VALIDATION_ERROR"),
        ({"channel": {"subscribers": {"min": 10, "max": 9}}}, "INVALID_RANGE"),
        ({"channel": {"created": {"withinDays": 0}}}, "VALIDATION_ERROR"),
        ({"channel": {"activity": {"windowDays": 31}}}, "VALIDATION_ERROR"),
        ({"channel": {"activity": {"lastUploadWithinDays": 1}}}, "VALIDATION_ERROR"),
        ({"channel": {"activity": {"countMin": 2, "countMax": 1}}}, "INVALID_RANGE"),
        ({"published": {"after": "bad"}}, "VALIDATION_ERROR"),
        (
            {"published": {"after": "2026-11-11", "before": "2026-11-10"}},
            "INVALID_RANGE",
        ),
        ({"published": {"withinDays": 10, "before": "2026-11-10"}}, "VALIDATION_ERROR"),
        ({"extra": True}, "VALIDATION_ERROR"),
        ({"video": {"extra": True}}, "VALIDATION_ERROR"),
        ({"channel": []}, "VALIDATION_ERROR"),
    ],
)
def test_invalid_input(body, code):
    with pytest.raises(DomainError) as exc:
        normalize({"keyword": "x", **body}, now=NOW)
    assert exc.value.code == code
    assert exc.value.status_code == 400
    assert exc.value.field_errors[0]["field"]


@pytest.mark.parametrize(
    "value,seconds",
    [
        ("00:00", 0),
        ("07:32", 452),
        ("01:02:03", 3723),
        ("12:00:00", 43200),
        (43200, 43200),
    ],
)
def test_duration_conversion(value, seconds):
    c = normalize(
        {"keyword": "x", "video": {"durationSec": {"min": value, "max": value}}}
    )
    assert c.data["video"]["durationSec"] == {"min": seconds, "max": seconds}


def test_semantic_hash_and_empty_conditions():
    a = normalize(
        {
            "keyword": " x ",
            "video": {
                "tags": {"include": [" Python ", "python", "코딩"]},
                "categoryIds": {"include": [27, 10]},
                "languages": ["KO", "en", "ko"],
            },
        }
    )
    b = normalize(
        {
            "video": {
                "categoryIds": {"include": ["10", "27"]},
                "languages": ["en", "ko"],
                "tags": {"include": ["코딩", "python"]},
            },
            "keyword": "x",
            "pages": 2,
            "channel": {},
        }
    )
    assert a.cond_hash == b.cond_hash
    empty = normalize(
        {
            "keyword": "x",
            "video": {"views": {"min": "", "max": None}, "tags": {}},
            "published": None,
        }
    )
    assert empty.cond_hash == normalize({"keyword": "x"}).cond_hash
    assert len(a.cond_hash) == 64


def test_boundaries_and_midnight_hours():
    c = normalize(
        {
            "keyword": "x",
            "video": {
                "views": {"min": 0, "max": 0},
                "likeRatePct": {"min": 100, "max": 100},
                "hours": {"from": 23, "to": 0},
                "weekdays": [0, 6],
            },
            "channel": {
                "viewsPerSubPct": {"min": 1000000},
                "activity": {"countMin": 0, "windowDays": 90},
            },
        }
    )
    assert c.activity.active
    assert c.data["video"]["hours"] == {"from": 23, "to": 0}


def test_dates_are_kst_half_open_and_relative_dates_cacheable():
    c = normalize(
        {"keyword": "x", "published": {"after": "2026-11-10", "before": "2026-11-11"}}
    )
    assert c.data["published"] == {
        "after": "2026-11-09T15:00:00+00:00",
        "before": "2026-11-10T15:00:00+00:00",
    }
    a = normalize({"keyword": "x", "published": {"withinDays": 30}}, now=NOW)
    b = normalize(
        {"keyword": "x", "published": {"withinDays": 30}}, now=NOW.replace(hour=9)
    )
    assert a.cond_hash == b.cond_hash
    assert a.data["published"]["after"] == "2026-10-10T15:00:00+00:00"


def test_numeric_equivalence_and_date_overflow():
    a = normalize({"keyword": "x", "video": {"likeRatePct": {"min": 1}}})
    b = normalize({"keyword": "x", "video": {"likeRatePct": {"min": 1.0}}})
    assert a.cond_hash == b.cond_hash
    for body in (
        {"published": {"withinDays": 10**20}},
        {"channel": {"created": {"withinDays": 10**20}}},
    ):
        with pytest.raises(DomainError):
            normalize({"keyword": "x", **body}, now=NOW)
