"""FNC-C-002: monthly and hourly counts from the latest 50 uploads."""

from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from app.analysis.heatmap import heatmap
from app.time_utils import to_kst


def upload_pattern(dates: Iterable[datetime | None]) -> dict[str, Any]:
    dates = [date for date in dates if date is not None][:50]
    monthly = Counter(to_kst(date).strftime("%Y-%m") for date in dates)
    return {
        "monthly": [
            {"month": month, "count": monthly[month]} for month in sorted(monthly)
        ],
        "matrix": heatmap(dates)["matrix"],
    }
