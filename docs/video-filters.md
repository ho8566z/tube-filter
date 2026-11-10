# 4단계 영상 필터

`app/search/filters_video.py`의 각 함수는 `VideoInfo`와 조건을 받아
`FilterResult(filter_name, passed, reason)`를 반환한다. API 호출·DB 접근·집계·
파이프라인 연결은 하지 않는다. `filter_name`은 항상 필터 코드이며, 탈락 시
`reason`은 해당 코드 또는 `HIDDEN_VALUE`, 통과 시에는 `None`이다.

```python
from app.search.filters_video import NumberRange, filter_count, filter_duration
from app.search.video_info import VideoInfo

# 기존 YouTube 어댑터 응답의 items 중 한 항목을 전달한다.
video = VideoInfo.from_youtube(item)
duration = filter_duration(video, NumberRange(min=60, max=180))
likes = filter_count(video, "likes", NumberRange(min=1))
```

내부 모델 변환은 숫자 문자열을 정수로 바꾸며, 누락된 통계는 0으로 대체하지
않는다. ISO 길이는 일·시·분·초 정수 형식을 지원한다. 알 수 없는 길이는
`None`과 모델의 `warnings` 메시지로 반환한다. 경고를 외부 응답으로 전달하는
일은 이후 호출자의 역할이다. 새 공개 경고 코드는 추가하지 않았다.

수치 범위는 양끝 포함이며 빈 범위는 조건 없음이다. 길이는 초, 통계는 개수,
비율은 % 단위다. UI의 5초·100개 증감 단위로 값을 반올림하지 않는다.
비율 필터는 원본 통계로 판정에 필요한 비율만 유리수로 비교한다. 5단계의
공용 지표 계산 모듈·출력용 지표는 이 문서 시점(4단계)에는 구현하지 않았고,
5단계에서 `app/search/metrics.py`로 추가했다(`channel-filters.md` 참고).

기준 엑셀의 기능·필터 명세서를 확인했다. 언어 우선순위는 04 요구 명세서와
달리 06·07 명세서에 명시된 오디오 언어 → 기본 언어를 따른다.

세부 해석과 내부 규약은 다음과 같다.

- 요일 번호는 Python 기준 월=0~일=6이다. 기존 시각 유틸리티에 따라 naive
  datetime은 UTC로 취급하고, 판정은 KST로 변환한 뒤 수행한다.
- 시간대는 시 단위 양끝 포함이다. 22~03은 22:00~03:59:59…이며, 같은 양끝은
  해당 한 시간을 뜻한다. 한쪽만 없으면 시작은 0시, 종료는 23시로 보충한다.
  요일은 자정 넘김 구간의 시작 날짜가 아니라 각 영상의 실제 KST 요일이다.
- 비율은 표시 반올림 전 값으로 비교한다. 예를 들어 1/3×100은 33.33% 이하에
  포함되지 않는다. 분모 0·누락, 분자 누락은 활성 조건에서 `HIDDEN_VALUE`다.
- 태그 공백 정규화는 11 설정·규약대로 앞뒤 공백 제거이며 내부 공백은 보존한다.
  태그 없음은 포함 조건에서 `HIDDEN_VALUE`, 제외 조건만 있으면 통과한다.
- 키워드 대상 BOTH에서는 각 단어가 제목 또는 설명 중 하나에 있어야 한다.
  두 필드 경계에 걸친 가상의 부분 문자열은 만들지 않는다.
- 지역 제한의 누락(`None`)과 명시적 빈 목록(`()`)을 구분한다. 빈 allowed는
  어느 국가도 허용하지 않는다. 모든 제한 제외 옵션은 allowed/blocked 필드가
  존재하면 빈 목록도 제외한다. 빈 제한 객체처럼 필드 자체가 없으면 통과한다.
- 0초는 길이 조건을 켰을 때 탈락한다. 쇼츠만 독립 적용하면 명시된 ≤180초
  규칙에 따라 0초도 쇼츠 추정에 해당한다.

이 단계의 함수는 정규화된 조건을 전제로 한다. 범위 역전은 `ValueError`로
거부하며, HTTP 입력 검증과 오류 응답 변환은 6단계 범위다. 카테고리는
FNC-F-007의 포함·제외 순수 판정만 구현했다. API·DB 접근이 필요한 목록 조회와
7일 캐시(`app/meta/categories.py`)는 이번 순수 함수 작업에 포함하지 않았다.
