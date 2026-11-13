"""FNC-V-003: KST Monday=0 through Sunday=6, 24 hourly buckets."""

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from app.time_utils import to_kst


def heatmap(dates: Iterable[datetime | None]) -> dict[str, Any]:
    matrix = [[0] * 24 for _ in range(7)]
    for date in dates:
        if date is not None:
            date = to_kst(date)
            matrix[date.weekday()][date.hour] += 1
    return {"matrix": matrix, "max": max(map(max, matrix))}
