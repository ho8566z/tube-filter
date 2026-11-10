# tube-filter

YouTube 영상 정밀 필터 검색 서비스.

Python 3.12와 uv를 사용합니다.

```powershell
uv sync
Copy-Item .env.example .env
# .env에 YOUTUBE_API_KEY와 32자 이상의 임의 SESSION_SECRET을 입력합니다.
uv run uvicorn app.main:app --port 8000
```

기동 시 필수 환경변수를 검증합니다. 운영체제 환경변수는 `.env`보다 우선합니다.
상태 확인: `GET http://127.0.0.1:8000/api/v1/health` → `{"status":"ok"}`.
현재는 0단계 뼈대만 구현되어 있으며 DB 연결이나 YouTube API 호출은 하지 않습니다.

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

- 명세서: [docs/spec](docs/spec/README.md)
- 구현 순서: [docs/implementation-plan.md](docs/implementation-plan.md)
- Codex 지침: [AGENTS.md](AGENTS.md)
