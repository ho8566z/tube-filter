# 10-2 채널·개인화 화면

SCR-005~009와 10-1b의 비활성 개인화 동작만 구현했다. 기존 7~9단계
JSON API, 공통 레이아웃·CSS·CSRF fetch 헬퍼와 검색 JS를 사용한다.
패키지·API·DB·마이그레이션 변경과 커밋·push는 없다.

## 동작

- `/channels/{channelId}`: 채널 정보, 최근 업로드 카드, 월별 막대와
  요일×시간대 히트맵. 로컬 Chart.js만 참조하며 동일 데이터를 표로도 제공한다.
- `/presets`: 목록, 조건 적용, 조건을 보존하는 이름 변경, 확인 후 삭제.
- `/favorites`: 20개씩 조회, 이전·다음 쪽, 재생·채널 이동·해제.
  삭제·비공개 영상은 안내와 해제 버튼만 제공한다. 쿼터 차단 시 API의
  캐시 대체 정보와 STALE_STATS/PARTIAL_FAILURE 경고를 표시한다.
- `/history`: 최근 50개, 주요 조건 요약, 조건 불러오기, 개별·전체 삭제.
- `/me`: 계정 정보, 현재/새/새 비밀번호 확인, 비밀번호 재입력 탈퇴 모달.
  WRONG_PASSWORD와 검증 오류는 해당 필드 아래 표시한다.
- 회원 전용 HTML은 비회원·만료 세션에 303 `/login`을 반환한다.
  화면을 연 뒤 API가 401을 반환해도 로그인으로 이동한다.
- 검색의 프리셋 저장·목록 불러오기와 즐겨찾기 토글, 채널 링크를 활성화했다.
  비회원은 화면 안 로그인 안내 링크를 받는다. 프리셋·기록 복원은 입력만 채우며
  자동 검색하지 않는다. 수치·기간·칩·다중 선택·요일·제한 국가 등을 복원한다.
- 변경 요청은 기존 `tubeFilter.api`의 CSRF 헤더를 사용한다. API 문자열은
  textContent로 표시한다. 삭제와 탈퇴 확인에 브라우저 alert/confirm을 쓰지 않는다.

## 명세가 정하지 않아 선택한 부분

- 화면 사이 조건 전달은 `/?preset={id}`, `/?history={id}` 링크로 한다.
  개인 조건 JSON을 URL이나 별도 브라우저 저장소에 저장하지 않고 기존 API로 조회한다.
  프리셋은 키워드를 보존하고 기록은 당시 키워드까지 복원한다.
- 즐겨찾기 여부 전용 API가 없어 검색·채널 카드의 별 상태는 기존 즐겨찾기 목록을
  50개씩 조회해 초기화한다(최대 200개, 4쪽). 같은 화면에서는 조회를 공유한다.
  이 목록 API도 기존 명세대로 캐시 갱신에 쿼터를 사용할 수 있다.
- 채널 HTML은 fetch용 200 셸이며, 채널 API의 404는 화면 안 ‘404 · 채널을 찾을
  수 없습니다’ 상태로 표시한다. 초기 HTML 렌더링은 YouTube를 호출하지 않는다.
- Chart.js 기본 배포에 matrix 유형이 없어 기존 검색 화면 방식처럼 로컬 플러그인으로
  히트맵 셀을 그린다. 월별·요일별 데이터는 표에서도 확인할 수 있다.
- 프리셋·검색 기록 삭제도 화면 안 확인 모달을 사용한다.

## 기존 파일 수정 이유

- `app/pages/policy.py`: 기존 HTML 라우터에 다섯 화면과 회원 접근 검사를 추가했다.
- `app/templates/base.html`: JS의 비회원 안내를 위한 회원 여부 data 속성을 추가했다.
- `app/templates/home.html`: 프리셋 버튼·이름 입력·목록을 연결하고 기존 재생 모달을
  `player.html` include로 옮겨 다른 영상 화면과 공유한다.
- `app/static/js/search.js`: 기존 카드·재생·서식 함수를 공용으로 내보내 재사용하고,
  즐겨찾기·채널 링크·프리셋 저장·불러오기·조건 복원을 연결했다.
- `app/static/css/main.css`: 기존 스타일에 관리 표·비밀번호 폼 스타일만 추가했다.
- `tests/test_pages.py`: ‘추후 화면 404/비활성’ 기대를 실제 화면·로그인 이동·핵심 요소
  검증으로 바꾸고, 신규 템플릿·자산과 채널 ID 이스케이프 검증을 추가했다.

## 신규 파일

- `app/templates/personal.html`: 공통 화면 셸과 삭제 확인 UI.
- `app/templates/player.html`: 기존 재생 모달을 추출한 공통 조각.
- `app/templates/channel.html`, `presets.html`, `favorites.html`, `history.html`, `me.html`.
- `app/static/js/personal.js`: 기존 JSON API에 연결하는 화면별 동작.
- `tests/js/personal.test.cjs`: 모의 DOM·fetch와 Node 내장 모듈만 사용하는 12개 테스트.
- 이 문서.

## 검증 결과

- `.venv/Scripts/python.exe -m pytest`: 556 passed, 기존 Starlette/httpx 경고 1개.
  기본 임시·캐시 폴더의 접근 제한 때문에 최초 실행은 519 passed/37 setup errors였다.
  `PYTEST_ADDOPTS='--basetemp=.test-tmp-10-2 -o cache_dir=.test-cache-10-2'`로
  저장소 안 임시 경로를 지정해 전체 통과했다. 생성한 임시 경로는 검증 후 정리한다.
- `.venv/Scripts/python.exe -m ruff check .`: 통과.
- `.venv/Scripts/python.exe -m ruff format --check .`: 통과.
- 기존 `tests/js/search.test.cjs`: 6개 통과.
- 신규 `tests/js/personal.test.cjs`: 12개 통과.
  로컬 PATH에 Node 실행 파일이 없어 Node 도구 런타임에서 내장 vm/createRequire로
  두 파일을 실행했다. Node가 설치된 환경에서는 각 파일을 `node`로 직접 실행할 수 있다.
- 신규 JS 검증: 활성 버튼의 요청·응답, CSRF, 로그인 안내·401 이동, 프리셋 중복,
  즐겨찾기 한도·페이지·누락 영상, 조건 복원/자동 검색 금지, 이름 변경 조건 보존,
  삭제 취소, 탈퇴 비밀번호 오류/성공, 재생 종료, 두 차트/표, XSS 문자열 처리.
- 실제 YouTube API 호출 없이 기존 mock 어댑터와 모의 fetch로 검증했다.
