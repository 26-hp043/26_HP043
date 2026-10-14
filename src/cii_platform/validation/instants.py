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

from datetime import UTC, datetime

#: UTC로 옮길 수 없는 시각의 문구. 사용자에게 그대로 나간다.
OUT_OF_RANGE_MESSAGE = "UTC로 옮기면 0001-01-01~9999-12-31 범위를 벗어나는 시각입니다."


def to_utc(moment: datetime) -> datetime:
    """시간대가 붙은 시각을 UTC 표기로 옮긴다. 순간은 그대로다.

    :raises ValueError: UTC로 옮기면 ``datetime``이 표현할 수 있는 범위를 벗어난다.
    """
    try:
        return moment.astimezone(UTC)
    except OverflowError as exc:
        raise ValueError(OUT_OF_RANGE_MESSAGE) from exc
