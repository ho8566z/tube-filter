---
paths:
  - "**/*.py"
  - "app/**"
---
# 파일(모듈) 구조 (Python) — 개인 프로젝트용

> 2차 팀 프로젝트(white-eyes)의 package-structure 원칙을 단일 앱 개인 프로젝트(FastAPI)에 맞게 일반화했다.

## 1. 원칙
- 모듈은 **도메인(기능) 단위**로 묶고, 계층은 도메인 안에서 나눈다. 프로젝트 전체를 `routers/`, `services/`로 먼저 나누지 않는다.
- 한 도메인은 다른 도메인에 대한 의존을 최소로 한다.
- 공통 코드는 여러 도메인이 함께 쓰는 것만 둔다(`config.py`, `db.py`, `errors.py` 등).

## 2. 구조
```
{프로젝트}/
├── pyproject.toml            의존성, ruff·pytest 설정
├── app/
│   ├── main.py               create_app / 라우터 등록
│   ├── config.py             환경변수 읽기
│   ├── db.py · models.py     DB 연결, ORM 모델
│   ├── errors.py             공통 예외·오류 응답
│   ├── {도메인}/
│   │   ├── router.py         요청 받기, 입력 검증, service 호출 (HTTP 계층)
│   │   ├── service.py        비즈니스 로직, 트랜잭션
│   │   └── …                 역할이 드러나는 모듈 (예: pattern.py, estimate.py)
│   ├── templates/ · static/
│   └── {외부연동}/adapter.py 외부 API 호출은 이 어댑터 한 곳만 거친다
├── alembic/                  마이그레이션
└── tests/                    test_{대상}.py, fakes/
```
- 도메인이 작으면 `service.py` 하나만 둬도 된다. 한 프로젝트 안에서는 한 가지 방식으로 통일한다.

## 3. 의존 규칙
- 의존은 `router → service → (db/model, adapter)` 한 방향. router가 DB 세션을 직접 다루며 로직을 쓰지 않는다.
- 다른 도메인은 그 도메인 service의 공개 함수로만 부른다(`_`로 시작하는 함수·내부 상태를 가져다 쓰지 않는다).
- 순환 import가 생기면 설계를 다시 보거나 공통 부분을 아래 계층으로 내린다.

## 4. 요청·응답
- ORM 모델은 router 밖으로 그대로 내보내지 않는다. 요청·응답은 Pydantic 스키마로 정의하고 변환은 service에서 한다.
- JSON 필드 이름 규칙은 프로젝트 안에서 하나로 통일한다.

## 5. 기타
- 비밀값은 환경변수로만 받고 `.env`는 `.gitignore`, `.env.example`만 커밋한다.
- 가중치·캐시·대용량 파일은 저장소에 올리지 않는다.
