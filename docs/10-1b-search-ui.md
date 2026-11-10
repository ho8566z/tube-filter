# 10-1b 검색 화면 구현 메모

SCR-003(`/`)과 SCR-004만 구현한다. 기존 HTML 라우트와 JSON API는 변경하지 않는다.

- `home.html`은 `base.html`을 상속한다. 공통 CSS에 검색 화면 스타일을 추가하고 `common.js`의 CSRF/fetch 헬퍼를 사용한다. 기존 쿼터 표시 함수를 `tubeFilter.refreshQuota()`로 노출해 검색 완료 후에도 갱신한다. CSV는 JSON이 아닌 Blob이므로 별도 GET fetch를 사용한다.
- 프리셋 저장/불러오기, 즐겨찾기, 채널 상세 링크는 비활성 자리만 제공한다. 10-2 화면이나 동작을 추가하지 않는다.
- 검색 API에는 진행 상황 스트림이 없어 로딩 중 처리 순서만 안내한다. 실제 단계별 개수와 탈락 수는 완료 응답의 funnel로 표시한다.
- 날짜 종료는 기존 API와 같은 미포함 경계다. 요일은 월=0~일=6이다. 초기화는 키워드를 유지하고 후보 2쪽·관련도·언어 누락 포함 등 기본값으로 되돌린다.
- 구독자 슬라이더 최대값이 명세에 없어 1,000,000명으로 정했다. 직접 숫자 입력에는 이 상한을 적용하지 않는다. 길이 슬라이더는 0~3시간, mm:ss 직접 입력은 기존 API 검증 범위를 따른다. 수치의 쉼표는 입력 아래 안내에 표시한다.
- 영상 ID는 ASCII 영문/숫자/밑줄/하이픈 11자만 허용한다. 공식 youtube-nocookie iframe을 사용하고 닫기·Esc 시 제거한다. YouTube 대체 링크를 항상 제공한다.
- 현재 검색 JSON과 DB에는 임베드 가능 여부가 없다. DB/API를 확장하지 않고 알 수 없는 영상은 공식 플레이어와 대체 링크를 제공한다. `embeddable: false`가 전달되면 링크만 표시한다. 실제 재생 제한은 공식 플레이어가 처리한다.
- Chart.js 기본 배포에는 matrix 차트가 없어 로컬 플러그인으로 히트맵 셀을 그린다. 같은 데이터를 표로도 제공한다. 산점도의 다른 페이지 점을 선택하면 저장된 결과 API로 카드를 찾는다. 로그 축에서는 0인 점을 제외한다.
- API 문자열은 textContent로 표시한다. 썸네일은 HTTPS YouTube 이미지 호스트만 허용한다. Chart.js 툴팁은 canvas에 그린다.

검증 결과:

- `.venv/Scripts/python.exe -m pytest`: 555 passed, 기존 Starlette/httpx 경고 1개. 기본 임시 경로 접근 제한으로 PYTEST_ADDOPTS에 저장소 내부 basetemp/cache_dir을 지정했다.
- `.venv/Scripts/python.exe -m ruff check .`, `.venv/Scripts/python.exe -m ruff format --check .`: 통과.
- `tests/js/search.test.cjs`: Node 내장 vm과 모의 DOM 테스트 6개 통과. 전체 필터 요청 변환, 기본값, 날짜·수치·요일·활동·칩, 영상 ID와 길이 형식을 검사한다. Node가 있으면 `node tests/js/search.test.cjs`로 실행한다. 이번 환경에서는 Node 도구 런타임에서 실행했다.
- 모의 fetch를 주입한 Chrome 검사: 데스크톱·360px, 검색·XSS 문자열·모달 종료·요약·산점도·히트맵·로그 축·429/503·기존 결과 및 입력 유지 통과. 실제 YouTube API 호출 없음.

`app/static/vendor/chart.umd.js`는 작업 시작 전부터 있던 미추적 파일을 그대로 참조했다. 커밋 시 함께 포함해야 한다.
