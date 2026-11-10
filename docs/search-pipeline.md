# 6단계 검색 파이프라인

공개 API: `POST /api/v1/search/estimate`, `POST /api/v1/search`,
`GET /api/v1/search/{searchId}/results`, `GET /api/v1/meta`.
회원·횟수·속도 제한과 검색 기록 저장은 구현하지 않았다.
`app/search/service.py:new_search_hook`은 캐시 미적중일 때만 호출되는 7단계 연결 지점이다.

조건 정규화와 견적은 외부 호출 없이 처리한다. 신규 검색은 후보 수집,
영상 상세·영상 필터, 채널 조회·채널 필터, 조건부 활동 조회·필터,
계산·정렬·페이지 순으로 실행한다. 후보 쪽 수는 기본 2, 최대 5다.
영상·채널의 캐시 미적중 ID만 50개씩 묶어 병렬 호출한다.
네트워크 작업만 worker에서 실행하고 ORM Session은 공유하지 않는다.
각 단계의 캐시 저장을 커밋한 뒤 다음 단계로 넘어가 별도 쿼터 기록
트랜잭션과 SQLite 쓰기 잠금이 충돌하지 않게 한다.

검색 캐시는 정규화 조건과 최종 영상 ID·집계·경고를 저장한다.
검색 ID를 미리 정해 각 어댑터 호출의 quota_usage.search_id와 연결한다.
따라서 응답 spent는 다른 동시 검색의 비용을 포함하지 않는다.
검색 캐시 적중은 API 호출 없이 spent=0을 보장한다.
결과 조회 API는 24시간 이상 지난 영상 통계를 갱신하고,
쿼터 차단 시 보관 한도 안의 캐시 통계와 STALE_STATS 경고를 반환한다.
호출별 상한 차단은 기존 QuotaGuard가 수행한다.

## 명세의 빈 부분에 적용한 기준

- 날짜만 입력하면 KST 자정으로 해석하고 UTC로 변환한다. 기간은 시작 이상,
  끝 미만이다. `published.withinDays`는 같은 날 캐시를 공유할 수 있도록
  검색일 KST 자정을 기준으로 N일 전부터로 정규화한다.
- 요일은 기존 필터와 동일하게 월=0, 일=6이다. 미설정 채널 국가는
  `channel.countries`의 `null`로 선택한다.
- 첫 페이지의 기본 정렬은 게시일 내림차순이다. 동점은 게시일 최신순이며,
  게시일까지 같으면 후보 순서를 유지한다. 정렬 필드의 NULL은 항상 뒤다.
- 캐시 적중 견적은 비용 0이므로 estimatedSearchesLeft는 null이다.
  remainingUnits는 기존 쿼터 현황 API와 같은 일일 총 한도 기준이다.
- 태그·단어 수 제한은 소문자·앞뒤 공백 정리·중복 제거 후 적용한다.
  의미 없는 빈 범위와 기본 옵션은 같은 조건 해시로 정규화한다.
- 영상마다 첫 탈락 사유 한 개만 drops에 더해 총합을 보존한다.
  filterDrops는 필터별 탈락 수, hiddenValues는 비공개·누락 값 수다.
  상세 API가 누락한 ID는 DELETED, 호출 실패로 상세를 얻지 못하면
  HIDDEN_VALUE와 PARTIAL_FAILURE로 집계한다. 활동 조회 한도 초과는
  ACTIVITY 탈락과 ACTIVITY_LIMIT 경고로 집계한다.
- 고정 언어 선택지는 ko/en/ja/zh/es/fr/de, 국가는
  KR/US/JP/CN/GB/CA/DE/FR/IN이다. 입력은 다른 두 글자 코드도 허용한다.
  카테고리는 지역별 video_category_cache에서 7일 재사용하며,
  assignable=true만 선택지로 반환한다. 상한 차단 시 기존 카테고리를 반환한다.
- 네트워크 오류만 어댑터에서 1회 재시도하며 재시도 역시 쿼터를 기록한다.
  HTTP 오류와 quotaExceeded는 재시도하지 않는다. 부분 성공 결과는 보존한다.

테스트는 고정 mock 어댑터와 동시 실행을 검증하는 barrier를 사용한다.
실제 YouTube API 호출과 패키지 추가는 없다.
