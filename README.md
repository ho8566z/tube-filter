# tube-filter

YouTube 영상 정밀 필터 검색 서비스.

Python 3.12와 uv를 사용합니다.

```powershell
uv sync
Copy-Item .env.example .env
# .env에 YOUTUBE_API_KEY와 32자 이상의 임의 SESSION_SECRET을 입력합니다.
uv run alembic upgrade head
uv run uvicorn app.main:app --port 8000
```

기동 시 필수 환경변수를 검증합니다. 운영체제 환경변수는 `.env`보다 우선합니다.
상태 확인: `GET http://127.0.0.1:8000/api/v1/health` → `{"status":"ok"}`.
1단계까지 구현되어 있습니다. DB 기본 위치는 `data/tubefilter.db`이며
`DATABASE_URL`로 변경할 수 있습니다. 앱은 테이블을 자동 생성하지 않으므로
실행 전에 Alembic 마이그레이션을 적용합니다. 마이그레이션은 API 키와 세션 키 없이도
실행할 수 있습니다. 되돌리기: `uv run alembic downgrade base` (전체 테이블 삭제).

DB의 모든 시각은 UTC로 저장하고, 모델 조회 시 UTC 시간대가 붙은 `datetime`으로
반환합니다. 시간대 없는 입력은 UTC로 간주합니다. 응답 시각은
`app/time_utils.py`의 `format_kst()`로 `+09:00` 오프셋을 포함해 직렬화합니다.
`usage_date`는 시각 변환 대상이 아닌 PT 날짜입니다.

공통 오류는 `app/errors.py`의 `DomainError`로 전달합니다. 요청 검증 오류는
400과 `fieldErrors`, 예상하지 못한 오류는 내부 정보를 제외한
500 `INTERNAL_ERROR`를 반환합니다. 명세에 일반 검증·HTTP 오류 코드가 지정되지 않아
`VALIDATION_ERROR`, `BAD_REQUEST`, `NOT_FOUND`, `METHOD_NOT_ALLOWED`, `HTTP_ERROR`를
사용합니다. 회원·검색·쿼터·캐시 서비스와 YouTube API 호출은 아직 구현하지 않았습니다.

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

- 명세서: [docs/spec](docs/spec/README.md)
- 구현 순서: [docs/implementation-plan.md](docs/implementation-plan.md)
- Codex 지침: [AGENTS.md](AGENTS.md)
