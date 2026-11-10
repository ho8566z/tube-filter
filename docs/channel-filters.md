# 5단계 채널 필터와 계산값

`ChannelInfo.from_youtube(item)`은 `channels.list` 어댑터 응답의 한 항목을
내부 불변 모델로 가공한다. 숨긴 구독자 수와 누락 통계는 `None`으로 유지한다.
`filters_channel.py`와 `activity.filter_activity`는 영상 필터와 같은
`FilterResult(filter_name, passed, reason)`을 반환하는 순수 함수다.
빈 조건은 통과하며 활성 조건에서 필요한 값이 없으면 `HIDDEN_VALUE`다.
구독자 0명은 구독자 수 조건에서는 비교 가능하지만 비율 계산에서는 값 없음이다.

```python
from app.search.channel_info import ChannelInfo
from app.search.filters_channel import filter_subscribers, filter_views_per_sub
from app.search.filters_video import NumberRange
from app.search.metrics import calculate_metrics

channel = ChannelInfo.from_youtube(item)
subscribers = filter_subscribers(channel, NumberRange(min=1))
ratio = filter_views_per_sub(video, channel, NumberRange(min=300))
output = calculate_metrics(video, channel, activity, now=now)
# output["calc"]["label"] == "계산값 · YouTube 제공 지표 아님"
```

`fetch_channels(db, adapter, cache, ids)`는 중복을 제거하고 입력 순서를 유지한다.
신선한 채널 캐시를 재사용하고 나머지만 50개씩 조회한다. 결과의 `unavailable_ids`는
실패·응답 누락 채널이며, 이때 `PARTIAL_FAILURE` 경고를 반환한다.

`await fetch_activity(db, adapter, cache, channels, conditions, now=now)`는
활동 조건이 없으면 조회하지 않는다. 입력의 첫 등장 순서로 최대 50개 채널을 선택하고,
각 캐시 미스에 `playlistItems.list`를 1회만 호출한다. 다음 페이지는 조회하지 않는다.
동기 어댑터를 `asyncio.to_thread`와 `gather`로 병렬 호출한다. 어댑터는 동시 호출을
지원해야 한다. 기존 프로덕션 어댑터는 요청별 HTTP 클라이언트와 잠긴 쿼터 가드를 쓴다.
서비스의 DB 세션은 호출자 스레드에서만 사용한다. DB 커밋은 호출자가 담당한다.

활동 결과는 채널별 `activities`, 판정 `results`, 한도 초과 `limited_ids`, 경고로 나뉜다.
한도 초과 채널은 `ACTIVITY_LIMIT`으로 안내하고 판정 대상에서 제외한다.
실패 채널은 값 없음 판정과 `PARTIAL_FAILURE` 경고를 반환하며 실패를 캐시하지 않는다.
성공한 빈 재생목록은 업로드 0개로 캐시한다. 마지막 업로드는
`activities[id].last_upload(now)`로 얻는다. 반환 시각은 UTC 내부값이며 표시할 때 KST로 변환한다.

활동 날짜는 기존 DB 필드 `recent_uploads`와 `recent_fetched_at`을 사용한다.
기능 명세의 `recent_upload_dates`는 같은 날짜 목록을 뜻하는 것으로 해석했다.
통계와 활동의 TTL은 독립적이며 기본 24시간이다. 활동 저장은 통계 조회 시각을 갱신하지
않고, 통계 갱신은 기존 활동 데이터·조회 시각을 보존한다. 활동 서비스는 채널 조회를
거쳐 캐시 레코드가 있는 `ChannelInfo`를 입력으로 사용한다.

계산값은 `calc`에만 담는다. 비율 3종·채널 영상당 평균 조회수 외에
`recentUploads["30"/"60"/"90"]`의 `count`·`atLeast`, KST 기준
`uploadWeekdayKst`(월=0~일=6)·`uploadHourKst`(0~23)를 제공한다.
모든 계산값에 공통 `label`을 함께 제공한다. 아직 조회하지 않았거나 실패한 활동의
개수는 `None`이다. 검색 파이프라인·HTTP API·화면·CSV는 연결하지 않았다.

명세에서 구체적으로 정하지 않은 부분은 다음과 같이 처리했다.

- 비율·평균 필터는 반올림 전 유리수로 비교한다. 출력만 소수점 둘째 자리로
  사사오입(half-up)한다. 예: 0.125 → 0.13.
- 범위 경계 포함 원칙에 따라 정확히 N일 전과 `created_before` 시각도 포함한다.
  최근 N일은 현재 시각에서 N×24시간을 뺀 시각부터 현재까지이며 미래 업로드는 세지 않는다.
  KST는 고정 +09:00이므로 UTC로 비교해도 같은 구간이다.
- 필터는 정규화된 일수·시각을 받는다. 개월·날짜 입력의 정규화는 검색 조건 처리의 몫이다.
- 국가 미설정 선택은 내부적으로 `None`으로 표현한다. 빈 국가 목록은 조건 없음이다.
- 최근 50개만 조회하므로 기간 안에서 50개가 잡히면 `count=50, atLeast=True`로
  ‘50개 이상’을 표현한다. 수치 필터는 관측한 개수(최대 50)로 비교하며,
  실제 51개 이상인지 확인하는 추가 호출은 하지 않는다.

경계·비공개·분모 0·KST 날짜 전환·반올림, 조회 묶음·병렬성·한도·부분 실패·독립 TTL은
mock 어댑터와 로컬 DB로 검증한다. 실제 YouTube API를 호출하지 않는다.
