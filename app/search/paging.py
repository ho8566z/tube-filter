"""FNC-S-010: NULL last for either direction; newest publication breaks ties."""

from typing import Any

from app.search.conditions import invalid

SORT_PATHS = {
    "views": ("stats", "views"),
    "likes": ("stats", "likes"),
    "comments": ("stats", "comments"),
    "likeRate": ("calc", "likeRatePct"),
    "commentRate": ("calc", "commentRatePct"),
    "viewsPerSub": ("calc", "viewsPerSubPct"),
    "duration": ("durationSec",),
    "publishedAt": ("publishedAt",),
}


def sort_items(
    items: list[dict[str, Any]], *, sort: str = "publishedAt", order: str = "desc"
) -> list[dict[str, Any]]:
    if sort not in SORT_PATHS or order not in ("asc", "desc"):
        invalid("sort", "INVALID_SORT")

    def value(item: dict[str, Any]) -> Any:
        for key in SORT_PATHS[sort]:
            item = item[key]
        return item

    ranked = sorted(items, key=lambda item: item["publishedAt"] or "", reverse=True)
    present = [item for item in ranked if value(item) is not None]
    absent = [item for item in ranked if value(item) is None]
    return sorted(present, key=value, reverse=order == "desc") + absent


def paginate(
    items: list[dict[str, Any]],
    *,
    page: int = 0,
    size: int = 20,
    sort: str = "publishedAt",
    order: str = "desc",
) -> dict[str, Any]:
    ranked = sort_items(items, sort=sort, order=order)
    if type(page) is not int or page < 0 or size not in (10, 20, 50):
        invalid("page")
    return {
        "items": ranked[page * size : (page + 1) * size],
        "page": page,
        "size": size,
        "totalElements": len(items),
        "totalPages": (len(items) + size - 1) // size,
    }
