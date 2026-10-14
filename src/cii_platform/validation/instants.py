"""시각을 UTC로 옮기는 단 한 벌 — 달력 범위를 벗어나면 검증 오류다 (`#2474`).

``datetime``은 0001-01-01부터 9999-12-31까지만 표현한다. 그 끝에 붙은 시각을 UTC로
옮기면 범위를 넘을 수 있다 — ``0001-01-01T00:00:00+09:00``은 UTC로 0년,
``9999-12-31T23:59:59-05:00``은 10000년이 된다. 그때 ``astimezone``은
``OverflowError``를 내는데, Pydantic은 검증 함수의 ``ValueError``·``AssertionError``만
검증 오류로 바꾸고 이 예외는 **그대로 올려** 500이 됐다. 항차 CSV·정박 CSV·``as_of``
쿼리도 각자 ``astimezone``을 불러 같은 식으로 터졌다.

그래서 변환을 이 함수 하나로 모으고, 넘치면 **한국어 ``ValueError``** 로 바꾼다. 받는
쪽은 그 문구를 그대로 쓴다 — 스키마는 422의 필드 문구로(``validation/messages.py``의
직접 만든 검증기 규칙), CSV는 행 오류로, 서비스는 도메인 ``ValidationError``로.

레이어 중립 모듈이다 — ``api``와 ``services``가 함께 부른다(TECH_SPEC §16 계층 방향).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

#: 받는 시각의 UTC 날짜 범위 (`#2487`). 달력 양 끝에서 하루씩 뺐다.
#:
#: UTC로 옮길 수 있는 것만으로는 모자랐다 — ``9999-12-31T15:00:00Z``는 UTC로는 멀쩡하지만
#: 화면·연도 판정이 한국 시간(+9시간)으로 옮기는 순간 10000년이 되어 같은 ``OverflowError``
#: (500)가 났다(``simulation_clock.current_regulation_year`` · 정박 겹침 문구 · 보고서 표기).
#: 시간대 오프셋은 최대 ±14시간이므로 하루 여유면 **어느 시간대로 옮겨도** 넘치지 않는다.
#: 경계를 「하루」로 두면 문구가 판정과 정확히 같아진다.
EARLIEST_UTC_DATE = date(1, 1, 2)
LATEST_UTC_DATE = date(9999, 12, 30)

#: 범위 밖 시각의 문구. 사용자에게 그대로 나간다.
OUT_OF_RANGE_MESSAGE = "시각은 0001-01-02부터 9999-12-30까지만 받습니다(UTC 기준)."


#: DB(CUBRID ``DATETIMETZ``)가 받는 UTC 오프셋 범위 (`#2503`). 실재하는 시간대도 이 안이다
#: (가장 서쪽 UTC−12:00 · 가장 동쪽 UTC+14:00). 밖이면 드라이버가 「Invalid utc offset」으로
#: 거부해 500이 났다 — 정박 구간은 받은 표기를 그대로 저장하므로(`#1333`) 입구에서 막는다.
EARLIEST_OFFSET = timedelta(hours=-12)
LATEST_OFFSET = timedelta(hours=14)

#: 범위 밖 오프셋의 문구. 사용자에게 그대로 나간다.
OFFSET_OUT_OF_RANGE_MESSAGE = "시간대는 -12:00부터 +14:00까지만 받습니다."


def check_offset(moment: datetime) -> datetime:
    """시간대 오프셋이 :data:`EARLIEST_OFFSET`~:data:`LATEST_OFFSET` 안인지 본다. 값은 그대로다.

    :raises ValueError: 범위 밖 오프셋 (`#2503`).
    """
    offset = moment.utcoffset()
    if offset is not None and not EARLIEST_OFFSET <= offset <= LATEST_OFFSET:
        raise ValueError(OFFSET_OUT_OF_RANGE_MESSAGE)
    return moment


def to_utc(moment: datetime) -> datetime:
    """시간대가 붙은 시각을 UTC 표기로 옮긴다. 순간은 그대로다.

    :raises ValueError: UTC로 옮기면 ``datetime``이 표현할 수 있는 범위를 벗어나거나, UTC
        날짜가 :data:`EARLIEST_UTC_DATE`~:data:`LATEST_UTC_DATE` 밖이다 — 그 밖의 값은 다른
        시간대로 옮길 때 넘칠 수 있다(`#2487`).
    """
    try:
        utc = moment.astimezone(UTC)
    except OverflowError as exc:
        raise ValueError(OUT_OF_RANGE_MESSAGE) from exc
    if not EARLIEST_UTC_DATE <= utc.date() <= LATEST_UTC_DATE:
        raise ValueError(OUT_OF_RANGE_MESSAGE)
    return utc
