"""Pure shared calculations. Display values are explicitly grouped under calc."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction

from app.search.channel_info import ChannelInfo
from app.search.video_info import VideoInfo
from app.time_utils import to_kst, to_utc

CALCULATED_LABEL = "계산값 · YouTube 제공 지표 아님"


def ratio(
    numerator: int | None, denominator: int | None, *, percent: bool = False
) -> Fraction | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return Fraction(numerator * (100 if percent else 1), denominator)


def rounded(value: Fraction | None) -> float | None:
    """Exact half-up rounding for nonnegative YouTube statistics."""
    if value is None:
        return None
    scaled = value * 100
    return (scaled.numerator * 2 // scaled.denominator + 1) // 2 / 100


@dataclass(frozen=True)
class ChannelActivity:
    # None is failed/unknown; () is a successful empty uploads playlist.
    upload_dates: tuple[datetime, ...] | None = None

    def count(self, days: int, now: datetime) -> int | None:
        if self.upload_dates is None:
            return None
        end = to_utc(now)
        start = end - timedelta(days=days)
        return sum(start <= to_utc(d) <= end for d in self.upload_dates)

    def at_least(self, days: int, now: datetime) -> bool:
        return self.count(days, now) == 50

    def last_upload(self, now: datetime) -> datetime | None:
        return max(
            (to_utc(d) for d in self.upload_dates or () if to_utc(d) <= to_utc(now)),
            default=None,
        )


def calculate_metrics(
    video: VideoInfo,
    channel: ChannelInfo | None = None,
    activity: ChannelActivity | None = None,
    *,
    now: datetime,
) -> dict:
    """Serializable display fields; never feed rounded values into filters."""
    published = to_kst(video.published_at) if video.published_at else None
    activity = activity or ChannelActivity()
    return {
        "calc": {
            "label": CALCULATED_LABEL,
            "likeRate": rounded(
                ratio(video.like_count, video.view_count, percent=True)
            ),
            "commentRate": rounded(
                ratio(video.comment_count, video.view_count, percent=True)
            ),
            "viewsPerSub": rounded(
                ratio(
                    video.view_count,
                    channel.public_subscriber_count if channel else None,
                    percent=True,
                )
            ),
            "avgViews": rounded(
                ratio(
                    channel.view_count if channel else None,
                    channel.video_count if channel else None,
                )
            ),
            "recentUploads": {
                str(days): {
                    "count": activity.count(days, now),
                    "atLeast": activity.at_least(days, now),
                }
                for days in (30, 60, 90)
            },
            "uploadWeekdayKst": published.weekday() if published else None,
            "uploadHourKst": published.hour if published else None,
        }
    }
