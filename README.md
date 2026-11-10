# tube-filter

YouTube 영상 정밀 필터 검색 서비스. YouTube 기본 검색에 없는 조건(정확한 길이,
조회수·좋아요 범위, 구독자 수 범위, 구독자 대비 조회수 %, 태그, 업로드 요일·시간대,
채널 업로드 빈도 등)으로 영상을 걸러 줍니다. 취업 포트폴리오용 개인 프로젝트입니다.

## 현재 상태

구현 순서(`docs/implementation-plan.md`)의 0~10단계를 모두 구현했습니다.
2순위 기능(`docs/spec/13_2순위_기능.md`)은 만들지 않았습니다.

- 검색 파이프라인: 조건 검증 → 쿼터 견적 → 검색 결과 캐시 → 후보 수집 → 영상 상세 →
  영상 필터 → 채널 조회·필터 → 채널 활동 → 지표 계산 → 정렬·페이지·단계별 집계
- 쿼터 관리: 호출별 units 기록, 소프트 상한(9,000) 차단, 검색 결과·통계 캐시, 28일 정리 작업
- 회원·세션·CSRF, 이용 횟수·속도 제한, 프리셋·즐겨찾기·검색 기록
- 분석(요약·산점도·히트맵), 채널 상세·업로드 패턴, CSV 내보내기
- 화면(Jinja2 + 바닐라 JS + Chart.js), 정책 고지

## 한계: YouTube Data API v3 키가 없으면 구동할 수 없습니다

이 서비스의 데이터는 모두 YouTube Data API v3(공식 API)에서 가져옵니다.
**유효한 `YOUTUBE_API_KEY`가 없으면 검색 결과를 만들 수 없어 서비스의 핵심 기능을
쓸 수 없습니다.** 스크래핑이나 비공식 API는 정책 준수 원칙(`docs/spec/12_정책_준수_체크.md`)에
따라 사용하지 않으므로 대체 수단이 없습니다.

이 프로젝트는 API 키를 발급하지 못한 상태로 마무리했습니다. 그래서 검증 범위가 다음과 같습니다.

| 구분 | 상태 |
|---|---|
| mock 어댑터 기반 자동 테스트(pytest 556개), ruff | 통과 |
| 서버 기동, 화면 렌더링, 오류·상태 화면, 모바일 폭(360px) 레이아웃 | 확인함(더미 키, 실제 Chrome) |
| 비회원·회원 접근 제어, CSRF, 이용 횟수·속도 제한, 쿼터 기록·차단, 캐시 TTL | mock 기반 테스트로 확인 |
| **실제 YouTube 응답으로 검색한 결과, 차트·재생 모달·CSV 출력** | **확인하지 못함** |
| **실제 응답 시간(명세 목표: 신규 15초, 캐시 적중 3초)** | **측정하지 못함** |
| **실제 응답 형식이 mock과 다를 때 생길 수 있는 오류** | **확인하지 못함** |

더미 키로 검색하면 `UPSTREAM_ERROR`(502) 오류 상태가 표시되고 입력 조건은 유지됩니다.
키가 있으면 아래 실행 방법대로 바로 동작해야 하지만, 실제 연동은 시험하지 않았습니다.

그 밖의 알려진 한계는 `docs/spec/03_프로젝트_개요.md`의 "알려진 한계"(후보 풀 한계,
쇼츠 추정, 쿼터 소진 등)를 참고하세요.

## 실행

Python 3.12와 uv를 사용합니다.

```powershell
uv sync
Copy-Item .env.example .env
# .env에 YOUTUBE_API_KEY와 32자 이상의 임의 SESSION_SECRET을 입력합니다.
uv run alembic upgrade head
uv run uvicorn app.main:app --port 8000
```

- 브라우저에서 `http://127.0.0.1:8000`을 엽니다.
- 상태 확인: `GET /api/v1/health` → `{"status":"ok"}`
- 기동 시 필수 환경변수를 검증합니다. 운영체제 환경변수는 `.env`보다 우선합니다.
- DB 기본 위치는 `data/tubefilter.db`이며 `DATABASE_URL`로 바꿀 수 있습니다. 앱은 테이블을
  자동 생성하지 않으므로 실행 전에 Alembic 마이그레이션을 적용합니다(API 키 없이 실행 가능).
  되돌리기: `uv run alembic downgrade base`(전체 테이블 삭제).
- 키는 `.env`에만 넣고 저장소에 올리지 않습니다(`.env`는 `.gitignore`).

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## 문서

- 명세서: [docs/spec](docs/spec/README.md)
- 구현 순서: [docs/implementation-plan.md](docs/implementation-plan.md)
- 단계별 구현 기록: `docs/` 아래 `video-filters.md`, `channel-filters.md`, `search-pipeline.md`,
  `users-and-limits.md`, `personalization.md`, `10-1b-search-ui.md`, `10-2-personal-ui.md`
- Codex 지침: [AGENTS.md](AGENTS.md)
