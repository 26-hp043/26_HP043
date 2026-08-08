"""필드명 → 한글 라벨 매핑 (API_SPEC §1.3.2 ``details[].field_label``, §11).

오류 응답에서 ``distance_nm`` 같은 필드명을 사용자용 한글 라벨("운항 거리")로
바꾼다.

#49가 **조회 실패 계약**을 확정했다 — 미등록 필드는 ``KeyError``가 아니라 필드명
원문을 그대로 반환한다. 그 위에서 각 필드를 검증하는 이슈가 라벨을 채워 넣는다.

**#55(기능① 계산)가 채운 분이 아래 「기능① 요청 필드」 묶음이다.** 그 이슈에서
빠뜨렸다가 실 API 시연 준비 중에 드러났다 — 오류 응답의 ``field_label``이
``fuel_uses[0].fuel_ton``처럼 필드명 그대로 나가고 있었다.

배열 필드는 **인덱스가 붙은 경로**로 조회된다(``fuel_uses[0].fuel_ton``). 인덱스는
요청마다 달라지므로 정적 dict로는 덮을 수 없다 — :func:`field_label`이 인덱스를
지운 형태로 한 번 더 찾는다.
"""

from __future__ import annotations

import re

#: 배열 인덱스를 지우는 패턴. ``fuel_uses[0].fuel_ton`` → ``fuel_uses[].fuel_ton``
_ARRAY_INDEX = re.compile(r"\[\d+\]")

_FIELD_LABELS: dict[str, str] = {
    # --- 기능① 요청 필드 (#55 · API_SPEC §4.1) ---
    "vessel_id": "선박",
    "regulation_year": "규제연도",
    "distance_nm": "운항 거리",  # API_SPEC §1.3.2 예시, §11 VAL-002
    "speed_kn": "속력",  # API_SPEC §11 VAL-009
    "fuel_uses": "연료 사용량",
    "fuel_uses[].fuel_type": "연료 종류",  # VAL-006
    "fuel_uses[].fuel_ton": "연료 사용량",  # VAL-002
    "weather_model": "기상 모델",
    # --- 목록 조회 쿼리 파라미터 (#51 · API_SPEC §2.1) ---
    "limit": "페이지 크기",
    "cursor": "커서",
    "ship_type": "선종",
    "search": "검색어",
}


def field_label(field: str) -> str:
    """필드명에 대응하는 한글 라벨을 반환한다.

    **두 번 찾는다.** 먼저 경로 그대로, 없으면 **배열 인덱스를 지운 형태**로 —
    ``fuel_uses[0].fuel_ton``과 ``fuel_uses[3].fuel_ton``은 같은 필드이고 인덱스는
    요청마다 달라지므로 정적 dict에 모두 적을 수 없다.

    미등록 필드는 예외를 던지지 않고 필드명 원문을 그대로 돌려준다(조회 실패 계약).
    """
    if field in _FIELD_LABELS:
        return _FIELD_LABELS[field]
    return _FIELD_LABELS.get(_ARRAY_INDEX.sub("[]", field), field)
