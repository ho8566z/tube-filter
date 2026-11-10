"""FNC-X-003: common Korean JSON error responses."""

import logging
from typing import TypedDict

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)


class FieldError(TypedDict):
    field: str
    message: str


class DomainError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        field_errors: list[FieldError] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.field_errors = field_errors


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    content = {"code": exc.code, "message": exc.message}
    if exc.field_errors is not None:
        content["fieldErrors"] = exc.field_errors
    return JSONResponse(status_code=exc.status_code, content=content)


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    fields = []
    for error in exc.errors():
        location = list(error["loc"])
        if location and location[0] in {"body", "query", "path", "header", "cookie"}:
            location = location[1:]
        fields.append(
            {
                "field": ".".join(str(part) for part in location),
                "message": "입력값이 올바르지 않습니다.",
            }
        )
    return JSONResponse(
        status_code=400,
        content={
            "code": "VALIDATION_ERROR",
            "message": "입력값을 확인해 주세요.",
            "fieldErrors": fields,
        },
    )


HTTP_ERRORS = {
    400: ("BAD_REQUEST", "잘못된 요청입니다."),
    401: ("UNAUTHORIZED", "로그인이 필요합니다."),
    403: ("FORBIDDEN", "접근 권한이 없습니다."),
    404: ("NOT_FOUND", "요청한 항목을 찾을 수 없습니다."),
    405: ("METHOD_NOT_ALLOWED", "허용되지 않은 요청 방식입니다."),
    429: ("TOO_MANY_REQUESTS", "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."),
}


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code, message = HTTP_ERRORS.get(
        exc.status_code, ("HTTP_ERROR", "요청을 처리할 수 없습니다.")
    )
    if exc.status_code >= 500:
        code, message = "INTERNAL_ERROR", "서버 오류가 발생했습니다."
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": code, "message": message},
        headers=exc.headers,
    )


async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled application error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": "서버 오류가 발생했습니다."},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(Exception, internal_error_handler)
