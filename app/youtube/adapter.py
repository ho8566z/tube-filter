"""Allowlisted YouTube adapter; replace get_youtube in FastAPI tests."""

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

import httpx
from fastapi import Request

from app.errors import DomainError
from app.quota.guard import QuotaGuard
from app.quota.log import ENDPOINT_COSTS
from app.time_utils import utc_now


class YouTubeAdapter(Protocol):
    def request(
        self, endpoint: str, params: dict[str, Any], *, search_id: str | None = None
    ) -> dict[str, Any]: ...


class HttpYouTubeAdapter:
    def __init__(
        self,
        api_key: str,
        guard: QuotaGuard,
        *,
        clock: Callable[[], datetime] = utc_now,
    ):
        self._api_key = api_key
        self.guard = guard
        self.clock = clock

    def request(
        self, endpoint: str, params: dict[str, Any], *, search_id: str | None = None
    ) -> dict[str, Any]:
        if endpoint not in ENDPOINT_COSTS:
            raise ValueError("Unsupported YouTube endpoint")
        now = self.clock()
        self.guard.before_call(endpoint, now, search_id)
        try:
            response = self._send(endpoint, params)
        except httpx.RequestError:
            raise DomainError(
                "UPSTREAM_ERROR",
                "YouTube 요청에 실패했습니다. 다시 시도해 주세요.",
                502,
            ) from None
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError
        except ValueError:
            raise DomainError(
                "UPSTREAM_ERROR", "YouTube 응답을 처리할 수 없습니다.", 502
            ) from None
        error = payload.get("error")
        errors = error.get("errors", []) if isinstance(error, dict) else []
        if not isinstance(errors, list):
            errors = []
        if response.status_code == 403 and any(
            isinstance(item, dict) and item.get("reason") == "quotaExceeded"
            for item in errors
        ):
            self.guard.block(now)
            self.guard.reject(now)
        if not response.is_success or error is not None:
            raise DomainError(
                "UPSTREAM_ERROR", "YouTube 요청을 처리할 수 없습니다.", 502
            )
        return payload

    def _send(self, endpoint: str, params: dict[str, Any]) -> httpx.Response:
        resource = endpoint.removesuffix(".list")
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            return client.get(
                f"https://www.googleapis.com/youtube/v3/{resource}",
                params={**params, "key": self._api_key},
            )


def get_youtube(request: Request) -> YouTubeAdapter:
    return HttpYouTubeAdapter(
        request.app.state.settings.youtube_api_key.get_secret_value(),
        request.app.state.quota_guard,
    )
