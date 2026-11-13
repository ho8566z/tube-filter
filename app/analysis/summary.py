"""FNC-V-001: NULL-excluding result statistics."""

from collections.abc import Iterable, Sequence
from fractions import Fraction
from statistics import median
from typing import Any

from app.search.metrics import CALCULATED_LABEL, rounded


def summarize(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    def stats(values: Iterable[Any]) -> dict[str, Any]:
        values = [Fraction(str(value)) for value in values if value is not None]
        if not values:
            return {"avg": None, "median": None, "max": None}
        return {
            "avg": rounded(sum(values) / len(values)),
            "median": rounded(median(values)),
            "max": rounded(max(values)),
        }

    return {
        "count": len(items),
        "views": stats(item["stats"]["views"] for item in items),
        "likeRatePct": stats(item["calc"]["likeRatePct"] for item in items),
        "viewsPerSubPct": stats(item["calc"]["viewsPerSubPct"] for item in items),
        "label": CALCULATED_LABEL,
    }
