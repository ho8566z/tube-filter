"""FNC-V-002: paired public statistics, limited to 500 points."""


def scatter(items):
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
