"""필드명 → 한글 라벨 매핑 (API_SPEC §1.3.2 ``details[].field_label``, §11).

오류 응답에서 ``distance_nm`` 같은 필드명을 사용자용 한글 라벨("운항 거리")로
바꾼다.

범위(#49): **조회 실패 계약**만 확정한다 — 미등록 필드는 ``KeyError``가 아니라
필드명 원문을 그대로 반환한다. 이렇게 하면 실제 요청 필드가 생기는 후행 이슈
(#50 vessel, #55 calculation 등)가 라벨을 안전하게 채워 넣을 수 있다. 여기서는
정본에 라벨이 명시된 필드만 최소로 등록하고, 나머지는 소비처에서 확장한다.
"""

from __future__ import annotations

# 정본에 라벨이 명시된 필드만 최소 등록한다. 나머지는 해당 필드를 검증하는
# 후행 이슈(#50/#55 등)에서 추가한다.
_FIELD_LABELS: dict[str, str] = {
    "distance_nm": "운항 거리",  # API_SPEC §1.3.2 예시, §11 VAL-002
    "speed_kn": "속력",  # API_SPEC §11 VAL-009
}


def field_label(field: str) -> str:
    """필드명에 대응하는 한글 라벨을 반환한다.

    미등록 필드는 예외를 던지지 않고 필드명 원문을 그대로 돌려준다(조회 실패 계약).
    """
    return _FIELD_LABELS.get(field, field)
