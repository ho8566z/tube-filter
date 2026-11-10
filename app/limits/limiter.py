"""FNC-Q-007: process-local counters with an injectable UTC clock."""

from collections import defaultdict, deque
from datetime import timedelta
from threading import Lock

from app.errors import DomainError
from app.time_utils import to_kst, utc_now


class Limiter:
    def __init__(self, settings, clock=utc_now):
        self.settings, self.clock = settings, clock
        self.lock = Lock()
        self.requests = defaultdict(deque)
        self.daily = {}
        self.day = None

    def check_request(self, ip, path):
        search = path in ("/api/v1/search", "/api/v1/search/estimate")
        limit = (
            self.settings.limit_search_per_min
            if search
            else self.settings.limit_other_per_min
        )
        now = self.clock()
        with self.lock:
            cutoff = now - timedelta(minutes=1)
            # Evict inactive IPs as well as expired timestamps.
            for key in list(self.requests):
                queue = self.requests[key]
                while queue and queue[0] <= cutoff:
                    queue.popleft()
                if not queue:
                    del self.requests[key]
            queue = self.requests[(ip, search)]
            if len(queue) >= limit:
                raise DomainError(
                    "TOO_MANY_REQUESTS",
                    "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                    429,
                )
            queue.append(now)

    def new_search(self, ip, user_id=None):
        day = to_kst(self.clock()).date()
        key = ("user", user_id) if user_id is not None else ("ip", ip)
        limit = (
            self.settings.limit_search_user_per_day
            if user_id is not None
            else self.settings.limit_search_guest_per_day
        )
        with self.lock:
            if day != self.day:
                self.daily.clear()
                self.day = day
            count = self.daily.get(key, 0)
            if count >= limit:
                raise DomainError(
                    "SEARCH_LIMIT", "오늘의 신규 검색 횟수를 모두 사용했습니다.", 429
                )
            self.daily[key] = count + 1
