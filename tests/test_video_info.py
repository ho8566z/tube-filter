from copy import deepcopy
from datetime import UTC, datetime

import pytest

from app.search.video_info import VideoInfo, parse_duration
from tests.fakes.fake_youtube import VIDEOS


@pytest.mark.parametrize(
    ("source", "seconds"),
    [
        ("PT7M32S", 452),
        ("PT1H", 3600),
        ("PT1H2M3S", 3723),
        ("P0D", 0),
        ("PT0S", 0),
        ("PT180S", 180),
        ("PT181S", 181),
        ("P1DT2H3M4S", 93784),
        ("PT12H", 43200),
        (None, None),
        ("", None),
        ("garbage", None),
        ("P", None),
        ("PT", None),
        ("P1DT", None),
        ("PT-1S", None),
        ("P1Y", None),
        ("PT1.5S", None),
        ("PT3Mextra", None),
    ],
)
def test_duration_conversion(source, seconds):
    assert parse_duration(source) == seconds


def test_adapter_item_mapping_preserves_absent_values_and_input():
    item = deepcopy(VIDEOS[1])
    original = deepcopy(item)
    video = VideoInfo.from_youtube(item)
    assert video.video_id == item["id"]
    assert video.channel_id == item["snippet"]["channelId"]
    assert video.duration_sec == 180
    assert video.view_count == 100
    assert video.like_count == 10
    assert video.comment_count is None
    assert video.published_at == datetime(2026, 11, 1, tzinfo=UTC)
    assert video.category_id == "27"
    assert video.tags == ()
    assert video.region_allowed is None
    assert video.region_blocked is None
    assert video.made_for_kids is False
    assert video.warnings == ()
    assert item == original


def test_optional_fields_and_zero_are_mapped_without_aliasing():
    item = {
        "snippet": {
            "tags": ["Python"],
            "title": "제목",
            "description": "설명",
            "defaultAudioLanguage": "ko-KR",
            "defaultLanguage": "en",
        },
        "statistics": {"viewCount": "0", "likeCount": "0", "commentCount": "0"},
        "contentDetails": {
            "duration": "P0D",
            "regionRestriction": {"allowed": [], "blocked": ["US"]},
        },
        "status": {"madeForKids": True},
    }
    video = VideoInfo.from_youtube(item)
    assert video.view_count == video.like_count == video.comment_count == 0
    assert video.duration_sec == 0
    assert video.region_allowed == ()
    assert video.region_blocked == ("US",)
    assert video.title == "제목" and video.description == "설명"
    assert video.default_audio_language == "ko-KR"
    assert video.default_language == "en"
    assert video.made_for_kids is True
    item["snippet"]["tags"].append("new")
    assert video.tags == ("Python",)


@pytest.mark.parametrize("duration", [None, "unknown"])
def test_unknown_duration_keeps_warning_without_logging_or_io(duration):
    video = VideoInfo.from_youtube({"contentDetails": {"duration": duration}})
    assert video.duration_sec is None
    assert video.warnings == ("영상 길이를 해석할 수 없습니다.",)
    assert video.view_count is video.like_count is video.comment_count is None


def test_timestamp_normalized_to_utc():
    video = VideoInfo.from_youtube(
        {"snippet": {"publishedAt": "2026-11-11T01:00:00+09:00"}}
    )
    assert video.published_at == datetime(2026, 11, 10, 16, tzinfo=UTC)
