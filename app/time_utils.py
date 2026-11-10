"""UTC storage and KST display helpers; naive datetimes mean UTC."""

from datetime import UTC, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), name="KST")


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_kst(value: datetime) -> datetime:
    return to_utc(value).astimezone(KST)


def format_kst(value: datetime) -> str:
    """Serialize an API timestamp with its +09:00 offset."""
    return to_kst(value).isoformat()
