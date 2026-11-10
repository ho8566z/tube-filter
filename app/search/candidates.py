"""FNC-S-003 / FNC-F-001: server filters and sequential token pagination."""

import asyncio

from app.errors import DomainError


def search_params(conditions):
    d, v = conditions.data, conditions.data["video"]
    params = {
        "part": "id",
        "type": "video",
        "maxResults": 50,
        "safeSearch": "moderate",
        "q": d["keyword"],
        "order": d["order"],
    }
    for key, target in (("after", "publishedAfter"), ("before", "publishedBefore")):
        if key in d["published"]:
            params[target] = d["published"][key]
    for key, target, value in (
        ("hd", "videoDefinition", "high"),
        ("caption", "videoCaption", "closedCaption"),
        ("cc", "videoLicense", "creativeCommon"),
        ("embeddable", "videoEmbeddable", "true"),
    ):
        if v[key]:
            params[target] = value
    for key in ("regionCode", "relevanceLanguage"):
        if v[key]:
            params[key] = v[key]
    if len(v["categoryIds"]["include"]) == 1:
        params["videoCategoryId"] = v["categoryIds"]["include"][0]
    return params


async def fetch_candidates(adapter, conditions, *, search_id):
    params, ids, warnings = search_params(conditions), [], []
    for _ in range(conditions.data["pages"]):
        try:
            payload = await asyncio.to_thread(
                adapter.request, "search.list", params.copy(), search_id=search_id
            )
        except DomainError:
            if not ids:
                raise
            warnings.append("PARTIAL_FAILURE")
            break
        for item in payload.get("items", []):
            key = item.get("id", {}).get("videoId")
            if key and key not in ids:
                ids.append(key)
        token = payload.get("nextPageToken")
        if not token:
            break
        params["pageToken"] = token
    return ids[:250], warnings
