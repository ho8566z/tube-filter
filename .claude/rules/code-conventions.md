---
paths:
  - "**/*.py"
---
# 코드 컨벤션 (Python) — 개인 프로젝트용

> 2차 팀 프로젝트(white-eyes) 규칙에서 프로젝트 전용 내용을 빼고 일반화했다. 코드를 쓰거나 고치기 전에 이 문서와 `file-structure.md`를 읽고 따른다.

## 1. 공통
- 가독성이 먼저다. 이름만 보고 역할과 의도를 알 수 있게 쓴다. 한 파일 안에서는 같은 스타일을 유지한다.
- Python 3.12, PEP 8. 들여쓰기 공백 4칸, UTF-8, LF, 파일 끝 줄바꿈 1개.
- **포매터·린트는 ruff**(`pyproject.toml`). 손으로 맞추지 말고 `uv run ruff format .`, `uv run ruff check .`를 돌린다. 완료 전에 `uv run pytest`와 ruff를 통과시킨다.
- 쓰지 않는 import는 지운다. `from x import *` 금지. 순서: 표준 라이브러리 → 외부 라이브러리 → 프로젝트 내부(ruff `I`가 맞춘다).
- 주석은 '왜 그렇게 했는지'를 쓴다. 주석 처리한 옛 코드는 남기지 않는다.
- 함수 하나가 여러 책임을 지지 않게 한다. 매직 넘버·문자열은 상수로 빼고, 운영 중 바뀔 수 있는 값은 환경변수(`config.py`)로 읽는다.
- `except: pass`처럼 예외를 삼키지 않는다. 예외는 처리하는 한 곳에서만 로그로 남긴다.

## 2. 이름
- 변수·함수·모듈·패키지 snake_case, 클래스·Enum PascalCase, 상수 UPPER_SNAKE_CASE(모듈 최상위).
- 계층 파일은 `service.py`·`{역할}.py`처럼 역할이 드러나게 쓴다. 모듈 안에서만 쓰는 함수·변수는 앞에 `_`.
- Boolean은 `is_running`, `has_quota`처럼 상태가 드러나게 쓴다. 의미 없는 축약 금지.

## 3. 작성 규칙
- 빈 줄: 최상위 함수·클래스 사이 2줄, 클래스 안 메서드 사이 1줄.
- 문자열 조합은 f-string. 단, 로그 메시지는 지연 포매팅(`%s`).
- 함수의 매개변수와 반환값에 타입 힌트를 쓴다. 요청·응답 구조는 Pydantic 모델 또는 `dataclass`로 정의한다.
- 시각은 timezone이 있는 `datetime`으로 다룬다.
- `print()`를 쓰지 않는다. 로거를 쓴다.

## 4. 테스트
- pytest. 파일 `test_{대상}.py`, 함수 `test_{조건}_{결과}`. 외부 API는 호출하지 않고 가짜(fake)를 쓴다.

## 5. 로깅
- `logging.getLogger(__name__)`로 모듈마다 로거를 만든다. 설정은 앱 시작 시 한 곳에서 한 번만 한다. 레벨은 환경변수 `LOG_LEVEL`.
- 메시지는 `logger.info("수집 완료 count=%s", n)`. f-string·문자열 더하기 금지.
- 레벨: ERROR(사람이 봐야 하는 실패), WARN(재시도·복구 중), INFO(운영에 의미 있는 1회성 변화), DEBUG(개발용). 반복 처리는 INFO로 남기지 않는다.
- 예외는 처리하는 한 곳에서 `logger.exception("…")`. 예상된 업무 예외는 스택 없이 WARN.
- 남기지 않는 것: 비밀번호·토큰·API 키·세션 ID, 개인 정보, 요청·응답 본문 전체.

## 6. JavaScript / 템플릿 (화면 정적 파일이 있을 때)
- `var` 금지(기본 `const`, 재대입만 `let`), 비교는 `===`. 비동기는 `async`/`await` + `fetch`.
- 서버 호출은 공용 모듈 한 곳을 거친다. 서버 값은 `textContent`로 넣고 `innerHTML`에 넣지 않는다(XSS).
- 템플릿에 인라인 이벤트 속성(`onclick="..."`)을 쓰지 않고 `addEventListener`로 연결한다. `console.log`를 남기지 않는다.
- 파일 이름은 kebab-case, 변수·함수 camelCase.

## 7. 이 프로젝트(tube-filter)의 예외
- 타입 힌트는 새로 쓰거나 고치는 함수부터 적용한다. 기존 함수의 빈 타입 힌트(ruff `ANN` 약 220건)는 일괄로 채우지 않고, 해당 파일을 기능 때문에 고칠 때 함께 채운다. 추측으로 타입을 쓰지 않는다.
