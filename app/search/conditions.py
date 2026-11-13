"""FNC-S-001: validate API conditions and build a canonical cache key."""

import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Never

from app.cache.search_cache import condition_hash
from app.errors import DomainError
from app.search.activity import ActivityConditions
from app.search.filters_video import NumberRange
from app.time_utils import KST, to_utc, utc_now

VIDEO_RANGES = (
    "durationSec",
    "views",
    "likes",
    "comments",
    "likeRatePct",
    "commentRatePct",
)
CHANNEL_RANGES = ("subscribers", "viewsPerSubPct", "videoCount", "avgViews")
DEFAULTS = {
    "keyword": "",
    "pages": 2,
    "order": "relevance",
    "published": {},
    "video": {
        **dict.fromkeys(VIDEO_RANGES, {}),
        "tags": {"include": [], "exclude": [], "mode": "AND"},
        "words": {"must": [], "not": [], "target": "BOTH"},
        "categoryIds": {"include": [], "exclude": []},
        "languages": [],
        "includeNoLanguage": True,
        "excludeKids": False,
        "excludeRestricted": {},
        "weekdays": [],
        "hours": {},
        "shorts": "ANY",
        "hd": False,
        "caption": False,
        "cc": False,
        "embeddable": False,
        "regionCode": "KR",
        "relevanceLanguage": None,
    },
    "channel": {
        **dict.fromkeys(CHANNEL_RANGES, {}),
        "created": {},
        "countries": [],
        "activity": {},
    },
}


def invalid(field, code="VALIDATION_ERROR") -> Never:
    raise DomainError(
        code,
        "입력값을 확인해 주세요.",
        field_errors=[{"field": field, "message": "허용 범위와 형식을 확인해 주세요."}],
    )


def integer(value, field, low=0, high=None):
    if type(value) is not int or value < low or (high is not None and value > high):
        invalid(field)
    return value


def date_utc(value, field):
    try:
        if not isinstance(value, str):
            raise ValueError
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            result = result.replace(tzinfo=KST)
        return to_utc(result).isoformat()
    except ValueError:
        invalid(field)


def options(data, allowed, field):
    if not isinstance(data, dict) or data.keys() - set(allowed):
        invalid(field)
    return {k: v for k, v in data.items() if v is not None and v != ""}


def bounds(data, field, *, duration=False, percent=False, fractional=False):
    data = options(data, ("min", "max"), field)
    for key, value in data.items():
        if duration and isinstance(value, str):
            if not re.fullmatch(r"\d+:[0-5]\d(?::[0-5]\d)?", value):
                invalid(field, "INVALID_DURATION")
            parts = [int(v) for v in value.split(":")]
            value = sum(v * 60**i for i, v in enumerate(reversed(parts)))
        if (
            type(value) not in (int, float)
            or not Decimal(str(value)).is_finite()
            or value < 0
        ):
            invalid(field, "INVALID_DURATION" if duration else "INVALID_RANGE")
        if not fractional and type(value) is not int:
            invalid(field, "INVALID_RANGE")
        if (duration and value > 43200) or (percent and value > 100):
            invalid(field, "INVALID_DURATION" if duration else "INVALID_RANGE")
        if fractional and Decimal(str(value)).as_tuple().exponent < -2:
            invalid(field, "INVALID_RANGE")
        data[key] = int(value) if value == int(value) else value
    if data.get("min", 0) > data.get("max", float("inf")):
        invalid(field, "INVALID_RANGE")
    return data


def choices(value, field, transform, limit=None):
    if not isinstance(value, list):
        invalid(field)
    result = sorted(
        set(transform(item) for item in value), key=lambda v: (v is not None, str(v))
    )
    if limit and len(result) > limit:
        invalid(field, "TOO_MANY_TAGS" if "tags" in field else "VALIDATION_ERROR")
    return result


def text(value, field):
    if not isinstance(value, str):
        invalid(field)
    value = value.strip().lower()
    if not 1 <= len(value) <= 50:
        invalid(field)
    return value


def code(value, field, upper=False):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z]{2}", value):
        invalid(field)
    return value.upper() if upper else value.lower()


@dataclass(frozen=True)
class SearchConditions:
    data: dict

    @property
    def cond_hash(self):
        return condition_hash(self.data)

    @property
    def activity(self):
        a = self.data["channel"]["activity"]
        return ActivityConditions(
            a.get("windowDays", 30),
            NumberRange(a.get("countMin"), a.get("countMax")),
            a.get("lastUploadWithinDays"),
        )


def normalize(raw: dict, *, now=None) -> SearchConditions:
    raw = options(raw, DEFAULTS, "conditions")
    d = deepcopy(DEFAULTS)
    for key in ("keyword", "pages", "order"):
        if key in raw:
            d[key] = raw[key]
    if not isinstance(d["keyword"], str) or not 1 <= len(d["keyword"].strip()) <= 100:
        invalid("keyword")
    d["keyword"] = d["keyword"].strip()
    integer(d["pages"], "pages", 1, 5)
    if d["order"] not in ("relevance", "date", "viewCount", "rating"):
        invalid("order", "INVALID_SORT")
    pub = options(
        raw.get("published", {}), ("after", "before", "withinDays"), "published"
    )
    if "withinDays" in pub:
        days = integer(pub.pop("withinDays"), "published.withinDays", 1)
        if pub:
            invalid("published")
        # Calendar-day anchor keeps relative conditions cacheable during the day.
        anchor = (
            (now or utc_now())
            .astimezone(KST)
            .replace(hour=0, minute=0, second=0, microsecond=0)
        )
        try:
            pub["after"] = (anchor - timedelta(days=days)).isoformat()
        except OverflowError:
            invalid("published.withinDays")
    d["published"] = {k: date_utc(v, "published." + k) for k, v in pub.items()}
    if d["published"].get("after", "") > d["published"].get("before", "9999"):
        invalid("published", "INVALID_RANGE")
    for section in ("video", "channel"):
        d[section].update(options(raw.get(section, {}), d[section], section))
    v, c = d["video"], d["channel"]
    for key in VIDEO_RANGES:
        v[key] = bounds(
            v[key],
            "video." + key,
            duration=key == "durationSec",
            percent=key.endswith("Pct"),
            fractional=key.endswith("Pct"),
        )
    for key in CHANNEL_RANGES:
        c[key] = bounds(
            c[key], "channel." + key, fractional=key in ("viewsPerSubPct", "avgViews")
        )
    for key, fields in (
        ("tags", ("include", "exclude", "mode")),
        ("words", ("must", "not", "target")),
        ("categoryIds", ("include", "exclude")),
    ):
        v[key] = {**DEFAULTS["video"][key], **options(v[key], fields, "video." + key)}
        for field in fields[:2]:
            path = "video." + key + "." + field
            if key == "categoryIds":

                def transform(x):
                    return str(
                        integer(
                            int(x) if isinstance(x, str) and x.isdecimal() else x,
                            path,
                            1,
                        )
                    )
            else:

                def transform(x):
                    return text(x, path)

            v[key][field] = choices(
                v[key][field],
                path,
                transform,
                30 if key == "tags" else 20 if key == "words" else None,
            )
    if (
        v["tags"]["mode"] not in ("AND", "OR")
        or v["words"]["target"] not in ("TITLE", "DESCRIPTION", "BOTH")
        or v["shorts"] not in ("ANY", "ONLY", "EXCLUDE")
    ):
        invalid("video")
    if not v["tags"]["include"]:
        v["tags"]["mode"] = "AND"
    if not v["words"]["must"] and not v["words"]["not"]:
        v["words"]["target"] = "BOTH"
    for key in (
        "includeNoLanguage",
        "excludeKids",
        "hd",
        "caption",
        "cc",
        "embeddable",
    ):
        if type(v[key]) is not bool:
            invalid("video." + key)
    v["languages"] = choices(
        v["languages"], "video.languages", lambda x: code(x, "video.languages")
    )
    if not v["languages"]:
        v["includeNoLanguage"] = True
    v["regionCode"] = code(v["regionCode"], "video.regionCode", True)
    if v["relevanceLanguage"] is not None:
        v["relevanceLanguage"] = code(v["relevanceLanguage"], "video.relevanceLanguage")
    v["weekdays"] = choices(
        v["weekdays"], "video.weekdays", lambda x: integer(x, "video.weekdays", 0, 6)
    )
    v["hours"] = options(v["hours"], ("from", "to"), "video.hours")
    for k, val in v["hours"].items():
        integer(val, "video.hours." + k, 0, 23)
    r = options(
        v["excludeRestricted"], ("country", "anyRestriction"), "video.excludeRestricted"
    )
    if r:
        r = {
            "country": code(
                r.get("country", "KR"), "video.excludeRestricted.country", True
            ),
            "anyRestriction": r.get("anyRestriction", False),
        }
        if type(r["anyRestriction"]) is not bool:
            invalid("video.excludeRestricted.anyRestriction")
    v["excludeRestricted"] = r
    c["countries"] = choices(
        c["countries"],
        "channel.countries",
        lambda x: None if x is None else code(x, "channel.countries", True),
    )
    created = options(c["created"], ("withinDays", "before"), "channel.created")
    if "withinDays" in created:
        days = integer(created["withinDays"], "channel.created.withinDays", 1)
        try:
            to_utc(now or utc_now()) - timedelta(days=days)
        except OverflowError:
            invalid("channel.created.withinDays")
    if "before" in created:
        created["before"] = date_utc(created["before"], "channel.created.before")
    c["created"] = created
    a = options(
        c["activity"],
        ("windowDays", "countMin", "countMax", "lastUploadWithinDays"),
        "channel.activity",
    )
    for key in ("windowDays", "lastUploadWithinDays"):
        if key in a and (type(a[key]) is not int or a[key] not in (30, 60, 90)):
            invalid("channel.activity." + key)
    bounds(
        {
            k: a[src]
            for k, src in (("min", "countMin"), ("max", "countMax"))
            if src in a
        },
        "channel.activity",
    )
    c["activity"] = (
        {"windowDays": 30, **a}
        if any(k in a for k in ("countMin", "countMax", "lastUploadWithinDays"))
        else {}
    )
    return SearchConditions(d)
