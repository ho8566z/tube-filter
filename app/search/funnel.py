"""FNC-S-011: first failing filter owns the drop, so totals reconcile."""

from collections import Counter
from collections.abc import Iterable
from typing import Any

from app.search.filters_video import FilterResult


class Funnel:
    def __init__(self, candidates: int) -> None:
        self.stages = {"candidates": candidates}
        self.drops = Counter()
        self.filter_drops = Counter()

    def accept(self, results: Iterable[FilterResult]) -> bool:
        for result in results:
            if not result.passed:
                self.drops[result.reason] += 1
                self.filter_drops[result.filter_name] += 1
                return False
        return True

    def output(self, warnings: list[str]) -> dict[str, Any]:
        return {
            **self.stages,
            "drops": {key: value for key, value in self.drops.items() if value},
            "filterDrops": dict(self.filter_drops),
            "hiddenValues": self.drops["HIDDEN_VALUE"],
            "warnings": warnings,
        }
