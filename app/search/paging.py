"""FNC-S-010: NULL last for either direction; newest publication breaks ties."""

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


def paginate(items, *, page=0, size=20, sort="publishedAt", order="desc"):
    if sort not in SORT_PATHS or order not in ("asc", "desc"):
        invalid("sort", "INVALID_SORT")
    if type(page) is not int or page < 0 or size not in (10, 20, 50):
        invalid("page")

    def value(item):
        for key in SORT_PATHS[sort]:
            item = item[key]
        return item

    ranked = sorted(items, key=lambda item: item["publishedAt"] or "", reverse=True)
    present = [item for item in ranked if value(item) is not None]
    absent = [item for item in ranked if value(item) is None]
    ranked = sorted(present, key=value, reverse=order == "desc") + absent
    return {
        "items": ranked[page * size : (page + 1) * size],
        "page": page,
        "size": size,
        "totalElements": len(items),
        "totalPages": (len(items) + size - 1) // size,
    }
