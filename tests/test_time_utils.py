from datetime import UTC, datetime

import pytest

from app.time_utils import KST, format_kst, to_kst, to_utc, utc_now


@pytest.mark.parametrize(
    ("utc_value", "kst_value"),
    [
        (datetime(2026, 11, 10, 16, tzinfo=UTC), "2026-11-11T01:00:00+09:00"),
        (datetime(2026, 12, 31, 15, tzinfo=UTC), "2027-01-01T00:00:00+09:00"),
        (datetime(2028, 2, 28, 15, tzinfo=UTC), "2028-02-29T00:00:00+09:00"),
    ],
)
def test_kst_serialization_and_round_trip(utc_value, kst_value):
    assert format_kst(utc_value) == kst_value
    assert to_utc(to_kst(utc_value)) == utc_value


def test_naive_values_are_utc():
    value = datetime(2026, 11, 10, 16)
    assert to_utc(value) == value.replace(tzinfo=UTC)
    assert to_kst(value) == datetime(2026, 11, 11, 1, tzinfo=KST)


def test_utc_now_is_aware():
    before = datetime.now(UTC)
    value = utc_now()
    assert value.tzinfo == UTC
    assert before <= value <= datetime.now(UTC)
