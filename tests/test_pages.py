"""10-1a: actual app routes, policy content, session identity, and static assets."""

from datetime import timedelta
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from app.db import Base, create_db_engine
from app.main import app
from app.users.auth import SESSION_SECONDS


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def attrs(self, tag, **matching):
        return next(
            attrs
            for name, attrs in self.tags
            if name == tag and all(attrs.get(k) == v for k, v in matching.items())
        )


@pytest.fixture
def client(monkeypatch, tmp_path):
    # Changing cwd also verifies that templates and assets use absolute paths.
    monkeypatch.chdir(tmp_path)
    database_url = f"sqlite:///{(tmp_path / 'pages.db').as_posix()}"
    engine = create_db_engine(database_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    with TestClient(app) as result:
        yield result


def token(response):
    return Elements(response.text).attrs("meta", name="csrf-token")["content"]


@pytest.mark.parametrize(
    ("path", "heading"),
    [
        ("/", "tube-filter"),
        ("/login", "로그인"),
        ("/signup", "회원가입"),
        ("/privacy", "개인정보처리방침"),
        ("/terms", "이용약관"),
    ],
)
def test_html_layout_and_policy_disclosures(client, path, heading):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    assert f"<h1>{heading}</h1>" in response.text
    elements = Elements(response.text)
    assert elements.attrs("html")["lang"] == "ko"
    assert elements.attrs("meta", name="viewport")
    assert elements.attrs("main", id="content")
    assert elements.attrs("progress", id="quota-bar")
    assert token(response) == client.get("/api/v1/auth/csrf").json()["csrfToken"]
    footer = response.text.split('<footer class="site-footer">')[1]
    links = Elements(footer)
    for href in ("/privacy", "/terms"):
        links.attrs("a", href=href)
    for href in (
        "https://www.youtube.com/t/terms",
        "https://policies.google.com/privacy",
    ):
        attrs = links.attrs("a", href=href)
        assert attrs["target"] == "_blank"
        assert "noopener" in attrs["rel"]
    assert "YouTube에서 가져온 콘텐츠를 사용자 조건으로 걸러 보여줍니다" in footer
    assert "YouTube 제공 지표가 아님" in footer
    assert "후보 안에서 걸러낸 결과" in footer


def test_account_form_elements(client):
    login = Elements(client.get("/login").text)
    assert login.attrs("form", id="auth-form")["data-mode"] == "login"
    assert login.attrs("form", id="auth-form")["method"] == "post"
    assert login.attrs("input", name="loginId")["maxlength"] == "20"
    assert login.attrs("input", name="password")["type"] == "password"
    signup = Elements(client.get("/signup").text)
    assert signup.attrs("form", id="auth-form")["data-mode"] == "signup"
    assert signup.attrs("form", id="auth-form")["method"] == "post"
    assert signup.attrs("input", name="loginId")["pattern"] == "[a-z][a-z0-9]{3,19}"
    assert signup.attrs("input", name="passwordConfirm")["type"] == "password"
    assert signup.attrs("input", name="agreePrivacy")["type"] == "checkbox"
    assert "disabled" in signup.attrs("button", id="submit-auth")
    for field in ("loginId", "password", "passwordConfirm", "agreePrivacy"):
        signup.attrs("p", id=f"{field}-error")


def test_page_csrf_signup_login_header_and_logout(client):
    guest = client.get("/signup")
    assert 'href="/login"' in guest.text
    assert 'href="/me"' not in guest.text
    body = {
        "loginId": "member01",
        "password": "password123",
        "passwordConfirm": "password123",
        "agreePrivacy": True,
    }
    assert client.post("/api/v1/auth/signup", json=body).status_code == 403
    headers = {"X-CSRF-Token": token(guest)}
    assert (
        client.post("/api/v1/auth/signup", json=body, headers=headers).status_code
        == 201
    )
    assert 'href="/me"' not in client.get("/privacy").text
    assert (
        client.post("/api/v1/auth/login", json=body, headers=headers).status_code == 200
    )
    member = client.get("/privacy")
    assert "member01 님" in member.text
    for href in ("/presets", "/favorites", "/history", "/me"):
        Elements(member.text).attrs("a", href=href)
    assert 'href="/login"' not in member.text
    assert 'id="logout"' in member.text
    assert token(member) != token(guest)
    redirect = client.get("/login", follow_redirects=False)
    assert redirect.status_code == 303
    assert redirect.headers["location"] == "/"
    assert client.get("/").status_code == 200
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 403
    assert (
        client.post(
            "/api/v1/auth/logout", headers={"X-CSRF-Token": token(member)}
        ).status_code
        == 204
    )
    assert 'href="/login"' in client.get("/terms").text


def test_expired_session_renders_guest_header(client):
    page = client.get("/login")
    headers = {"X-CSRF-Token": token(page)}
    body = {
        "loginId": "member01",
        "password": "password123",
        "passwordConfirm": "password123",
        "agreePrivacy": True,
    }
    assert (
        client.post("/api/v1/auth/signup", json=body, headers=headers).status_code
        == 201
    )
    assert (
        client.post("/api/v1/auth/login", json=body, headers=headers).status_code == 200
    )
    now = app.state.clock()
    app.state.clock = lambda: now + timedelta(seconds=SESSION_SECONDS)
    response = client.get("/login", follow_redirects=False)
    assert response.status_code == 200
    assert 'href="/me"' not in response.text


def test_privacy_required_contents_and_terms(client):
    privacy = client.get("/privacy").text
    for text in (
        "YouTube API 서비스",
        "Google 개인정보처리방침",
        "아이디",
        "비밀번호 해시",
        "프리셋",
        "즐겨찾기 영상 ID",
        "검색 기록",
        "이용 목적",
        "최대 28일",
        "회원 탈퇴",
        "즉시 삭제",
        "제3자에게 제공하지",
        "광고",
        "추적",
        "문의처",
        "https://github.com/ho8566z/tube-filter/issues",
    ):
        assert text in privacy
    terms = client.get("/terms").text
    for text in ("에 동의한 것으로 봅니다", "YouTube 제공 지표가 아니", "포트폴리오용"):
        assert text in terms


@pytest.mark.parametrize(
    ("path", "mime"),
    [
        ("/static/css/main.css", "text/css"),
        ("/static/js/common.js", "javascript"),
        ("/static/js/auth.js", "javascript"),
    ],
)
def test_static_files(client, path, mime):
    response = client.get(path)
    assert response.status_code == 200
    assert mime in response.headers["content-type"]
    assert response.text


@pytest.mark.parametrize(
    "path", ["/presets", "/favorites", "/history", "/me", "/channels/test"]
)
def test_later_screens_are_not_implemented(client, path):
    assert client.get(path).status_code == 404
