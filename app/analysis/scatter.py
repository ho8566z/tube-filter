"""FNC-V-002: paired public statistics, limited to 500 points."""

from collections.abc import Iterable
from typing import Any


def scatter(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "videoId": item["videoId"],
            "title": item["title"],
            "subscribers": item["channel"]["subscribers"],
            "views": item["stats"]["views"],
        }
        for item in items
        if item["channel"]["subscribers"] is not None
        and item["stats"]["views"] is not None
    ][:500]
