"""Deterministic adapter using the production accounting, with no network."""

from copy import deepcopy

import httpx

from app.youtube.adapter import HttpYouTubeAdapter

CHANNELS = [
    {
        "id": f"UC{index:022d}",
        "snippet": {"title": f"Channel {index}", "country": "KR"},
        "statistics": {
            "subscriberCount": str(index * 100),
            "hiddenSubscriberCount": False,
            "videoCount": "3",
            "viewCount": str(index * 3000),
        },
        "contentDetails": {"relatedPlaylists": {"uploads": f"UU{index:022d}"}},
    }
    for index in range(10)
]
VIDEOS = [
    {
        "id": f"v{index:010d}",
        "snippet": {
            "title": f"Video {index}",
            "channelId": CHANNELS[index % 10]["id"],
            "publishedAt": "2026-11-01T00:00:00Z",
            "categoryId": "27",
        },
        "contentDetails": {"duration": "PT3M"},
        "statistics": {"viewCount": str(index * 100), "likeCount": "10"},
        "status": {"embeddable": True, "madeForKids": False},
    }
    for index in range(30)
]


class FakeYouTubeAdapter(HttpYouTubeAdapter):
    def __init__(self, guard, **kwargs):
        super().__init__("fake-key", guard, **kwargs)
        self.calls = []
        self.responses = []

    def _send(self, endpoint, params):
        self.calls.append((endpoint, deepcopy(params)))
        if self.responses:
            result = self.responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        if endpoint == "search.list":
            items = [{"id": {"videoId": video["id"]}} for video in VIDEOS]
        elif endpoint == "videos.list":
            ids = params.get("id", "").split(",")
            items = [video for video in VIDEOS if video["id"] in ids]
        elif endpoint == "channels.list":
            ids = params.get("id", "").split(",")
            items = [channel for channel in CHANNELS if channel["id"] in ids]
        elif endpoint == "playlistItems.list":
            channel_id = "UC" + params.get("playlistId", "")[2:]
            items = [
                {
                    "contentDetails": {
                        "videoId": video["id"],
                        "videoPublishedAt": video["snippet"]["publishedAt"],
                    }
                }
                for video in VIDEOS
                if video["snippet"]["channelId"] == channel_id
            ]
        else:
            items = [{"id": "27", "snippet": {"title": "교육", "assignable": True}}]
        return httpx.Response(200, json={"items": deepcopy(items)})
