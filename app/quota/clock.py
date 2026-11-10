"""Pacific calendar dates and DST-aware daily reset times."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.time_utils import to_utc

PT = ZoneInfo("America/Los_Angeles")  # Windows엔 시스템 tz DB가 없어 tzdata 패키지 사용


def pt_date(now: datetime):
    return to_utc(now).astimezone(PT).date()


def next_reset(now: datetime) -> datetime:
    return datetime.combine(pt_date(now) + timedelta(days=1), time.min, tzinfo=PT)
