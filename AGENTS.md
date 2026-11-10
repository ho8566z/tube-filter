# AGENTS.md (Codex 작업 지침)

tube-filter: YouTube Data API v3로 영상을 정밀 필터 검색하는 FastAPI 웹 서비스. 포트폴리오용 개인 프로젝트, 과하게 설계하지 않는다.

## 기준 문서
- 구현 기준은 `docs/spec/`의 명세서(시트별 .md). 엑셀 원본 `docs/spec/tube-filter 명세서 목록.xlsx`와 다르면 엑셀이 맞다.
- 구현 순서와 단계별 완료 기준은 `docs/implementation-plan.md`.
- 공통 값(환경변수, 쿼터 비용, 응답 형식)은 `docs/spec/11_설정_규약.md`.
- 구현 위치(app/... 경로)는 `docs/spec/05_기능_목록.md` 비고에 있다. 그 경로를 따른다.

## 작업 규칙
- 한 번에 요청받은 단계(또는 기능 ID)만 구현한다. 다음 단계를 미리 만들지 않는다.
- 명세에 없거나 모호하면 추측으로 확장하지 말고, 가장 단순한 쪽으로 구현하고 최종 보고에 적는다.
- 2순위 기능(`docs/spec/13_2순위_기능.md`)은 만들지 않는다.
- YouTube API 호출은 `app/youtube/` 어댑터 한 곳만 거친다(nfr-006). 테스트는 mock 어댑터를 쓰고 실제 API를 호출하지 않는다.
- API 키 등 비밀값은 환경변수로만 받고 저장소에 올리지 않는다(.env는 .gitignore, .env.example만 커밋).
- 스크래핑, 비공식 API, 영상 다운로드 금지(`docs/spec/12_정책_준수_체크.md`).

## 환경·명령
- Python 3.12, 패키지는 uv: `uv sync`, 실행 `uv run uvicorn app.main:app --port 8000`, 테스트 `uv run pytest`, 린트 `uv run ruff check . && uv run ruff format --check .`
- 완료 전에 pytest와 ruff를 통과시키고 결과를 보고한다.

## Git
- 커밋·push는 하지 않는다. 변경 파일 목록과 테스트 결과만 보고한다(커밋은 Claude가 한다).
