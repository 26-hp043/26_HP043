"""응답 timestamp 포맷 헬퍼 (API_SPEC §1.3 단일 소스).

성공/오류 응답의 ``meta.timestamp``와 요청 컨텍스트 미들웨어가 **같은 포맷**을
쓰도록 생성 지점을 한 곳으로 모은다. 포맷은 API_SPEC §1.3 예시를 그대로 따른다:
``2026-07-03T12:00:00Z`` (UTC, 초 단위, ``Z`` 접미, 소수점 없음).
"""

from __future__ import annotations

from datetime import UTC, datetime


def iso_utc_now() -> str:
    """현재 UTC 시각을 API_SPEC §1.3 포맷 문자열로 반환한다.

    예: ``"2026-07-24T12:00:00Z"``.
    """
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
