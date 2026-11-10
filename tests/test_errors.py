from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.errors import DomainError, register_error_handlers


class VideoInput(BaseModel):
    views: int = Field(ge=0)


class SearchInput(BaseModel):
    video: VideoInput


def error_app():
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/domain/{status}")
    def domain(status: int):
        code = {401: "UNAUTHORIZED", 429: "SEARCH_LIMIT", 503: "QUOTA_BLOCKED"}[status]
        raise DomainError(code, "요청을 처리할 수 없습니다.", status)

    @app.get("/range")
    def invalid_range():
        raise DomainError(
            "INVALID_RANGE",
            "최소값이 최대값보다 클 수 없습니다.",
            field_errors=[{"field": "video.views", "message": "범위를 확인해 주세요."}],
        )

    @app.post("/validate")
    def validate(body: SearchInput):
        return body

    @app.get("/unexpected")
    def unexpected():
        raise RuntimeError("private database path and secret")

    @app.get("/http")
    def http():
        raise HTTPException(
            401, "private detail", headers={"WWW-Authenticate": "Bearer"}
        )

    return app


def test_domain_errors():
    with TestClient(error_app()) as client:
        for status, code in [
            (401, "UNAUTHORIZED"),
            (429, "SEARCH_LIMIT"),
            (503, "QUOTA_BLOCKED"),
        ]:
            response = client.get(f"/domain/{status}")
            assert response.status_code == status
            assert response.json() == {
                "code": code,
                "message": "요청을 처리할 수 없습니다.",
            }
        response = client.get("/range")
        assert response.status_code == 400
        assert response.json() == {
            "code": "INVALID_RANGE",
            "message": "최소값이 최대값보다 클 수 없습니다.",
            "fieldErrors": [
                {"field": "video.views", "message": "범위를 확인해 주세요."}
            ],
        }


def test_validation_errors_are_400_with_korean_field_messages():
    with TestClient(error_app()) as client:
        for payload in ({"video": {"views": -1}}, {"video": {"views": "secret"}}, {}):
            response = client.post("/validate", json=payload)
            assert response.status_code == 400
            body = response.json()
            assert set(body) == {"code", "message", "fieldErrors"}
            assert body["code"] == "VALIDATION_ERROR"
            assert body["fieldErrors"][0]["field"] in {"video.views", "video"}
            assert body["fieldErrors"][0]["message"] == "입력값이 올바르지 않습니다."
            assert "secret" not in response.text
        malformed = client.post(
            "/validate", content="{", headers={"Content-Type": "application/json"}
        )
        assert malformed.status_code == 400
        assert malformed.json()["fieldErrors"]
        path_error = client.get("/domain/not-an-integer")
        assert path_error.status_code == 400
        assert path_error.json()["fieldErrors"][0]["field"] == "status"


def test_internal_error_is_safe():
    with TestClient(error_app(), raise_server_exceptions=False) as client:
        response = client.get("/unexpected")
    assert response.status_code == 500
    assert response.json() == {
        "code": "INTERNAL_ERROR",
        "message": "서버 오류가 발생했습니다.",
    }


def test_http_errors_use_common_format():
    with TestClient(error_app()) as client:
        response = client.get("/http")
        assert response.status_code == 401
        assert response.json() == {
            "code": "UNAUTHORIZED",
            "message": "로그인이 필요합니다.",
        }
        assert response.headers["WWW-Authenticate"] == "Bearer"
        response = client.get("/missing")
        assert response.status_code == 404
        assert response.json() == {
            "code": "NOT_FOUND",
            "message": "요청한 항목을 찾을 수 없습니다.",
        }
        response = client.post("/http")
        assert response.status_code == 405
        assert "fieldErrors" not in response.json()
