"""FNC-Q-003: check and record before sending a new upstream request."""

import logging
from collections.abc import Callable
from datetime import date, datetime
from threading import RLock

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.quota.clock import next_reset, pt_date
from app.quota.log import ENDPOINT_COSTS, record_call
from app.quota.status import used_units
from app.time_utils import format_kst

logger = logging.getLogger(__name__)


class QuotaGuard:
    def __init__(self, session_factory: Callable[[], Session], soft_limit: int) -> None:
        self.session_factory = session_factory
        self.soft_limit = soft_limit
        self._exhausted_date: date | None = None
        self._lock = RLock()

    def block(self, now: datetime) -> None:
        with self._lock:
            self._exhausted_date = pt_date(now)

    def reject(self, now: datetime) -> None:
        raise DomainError(
            "QUOTA_BLOCKED",
            "오늘의 YouTube API 사용 한도에 도달했습니다. "
            f"캐시된 결과를 이용해 주세요. 초기화: {format_kst(next_reset(now))}",
            503,
        )

    def before_call(
        self, endpoint: str, now: datetime, search_id: str | None = None
    ) -> None:
        cost = ENDPOINT_COSTS[endpoint]
        # One application process shares this guard. Commit the reservation before
        # releasing the lock so simultaneous requests cannot spend the same units.
        with self._lock:
            if self._exhausted_date == pt_date(now):
                self.reject(now)
            try:
                with self.session_factory() as db:
                    if self.soft_limit - used_units(db, now) < cost:
                        self.reject(now)
                    record_call(db, endpoint, now, search_id)
            except SQLAlchemyError:
                # The spec permits calls when accounting fails. Avoid exception
                # details: SQL parameters may contain application data.
                logger.warning("YouTube quota accounting failed; proceeding with call")
