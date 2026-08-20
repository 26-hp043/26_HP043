"""문서에 싣는 표시 문구 (#584).

## 왜 서버가 표시 문구를 갖는가

`AGENTS §4.6` 기준 선종의 한국어 이름은 **표시 문구**다 — 정본이 원문을 확정한 문구가
아니라 디자인 담당이 문서 개정 없이 바꿀 수 있는 값이며, 화면 쪽은
``frontend/src/features/vessel-registration/shipTypes.ts``가 갖는다.

그런데 **보고서 PDF는 서버가 만든다.** 문서에 ``BULK_CARRIER``가 그대로 나가면
읽는 사람은 그것이 무엇인지 모른다 — 심사·대외 제출에 나가는 산출물이라 더 그렇다.

**표기 자체를 여기서 새로 정하지 않는다.** 화면이 쓰는 것과 같은 문구를 옮겨 적고,
어긋나면 ``tests/test_report_labels_sync.py``가 실패한다. 코드 집합의 정본은
``calc/capacity.py``이며 그쪽과의 대조도 같은 테스트가 본다.

## 코드가 목록에 없으면 코드를 그대로 보여 준다

빈칸으로 두면 「선종이 없는 배」로 읽힌다. 새 선종이 들어왔는데 표기가 아직
없는 상태와, 값이 비어 있는 상태는 다르다.
"""

from __future__ import annotations

#: 선종 표시 문구. 화면(``shipTypes.ts``)과 같은 값이며 순서는 ``PRD §3.4.3`` 표를 따른다.
SHIP_TYPE_LABELS: dict[str, str] = {
    "BULK_CARRIER": "벌크선",
    "GAS_CARRIER": "가스운반선",
    "TANKER": "탱커",
    "CONTAINER_SHIP": "컨테이너선",
    "GENERAL_CARGO_SHIP": "일반화물선",
    "REFRIGERATED_CARGO_CARRIER": "냉동화물선",
    "COMBINATION_CARRIER": "겸용선",
    "LNG_CARRIER": "LNG운반선",
    "RO_RO_CARGO_VEHICLE": "차량운반선",
    "RO_RO_CARGO": "로로화물선",
    "RO_RO_PASSENGER": "로로여객선",
    "RO_RO_PASSENGER_HSC": "로로여객선(고속선)",
    "CRUISE_PASSENGER": "크루즈여객선",
}


def ship_type_label(code: str | None) -> str:
    """선종 코드를 표시 문구로. 없으면 코드를 그대로 돌려준다."""
    if not code:
        return "—"
    return SHIP_TYPE_LABELS.get(code, code)
