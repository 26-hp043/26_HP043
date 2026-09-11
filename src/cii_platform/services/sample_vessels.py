"""샘플 선박 목록 — 선박 등록에서 제원을 채우는 출발점 (#982 · `PRD §5.1` · `§6.2 SCR-002`).

## 값은 어디서 오는가

**데모 시드의 합성 샘플 3척을 그대로 쓴다.** 새 제원 값을 만들지 않는다 — 기준속도·
기준 일일 연료는 정본 픽스처에서 역산해 검증된 값이다(`#587`). 값을 여기에 다시 적으면
시드와 샘플이 따로 고쳐져 「샘플로 등록한 배」와 「데모의 같은 이름 배」가 다른 계산을 낸다.

실존 선박 2척(`STAR SKIPPER` · `DONGJIN ENDURANCE`)은 넣지 않는다. 실존 선박을 「샘플」로
내면 남의 배 제원을 제품이 권하는 꼴이고, 두 척 다 기준 일일 연료가 비어 있어 샘플의
목적(**바로 계산되는 제원**)에 맞지 않는다.

## 무엇을 채우지 않는가

**선명·IMO는 없다.** 샘플은 「이런 배라면」의 제원이지 등록할 배의 신원이 아니다 —
IMO는 배마다 유일하고(`chk_imo_format` · 유일 인덱스), 샘플의 합성 IMO를 그대로 쓰면
두 번째 사용자부터 충돌한다.
"""

from __future__ import annotations

from decimal import Decimal

from cii_platform.db.demo_seed import (
    SEED_VESSEL_GT_AXIS,
    SEED_VESSEL_WATCH,
    SEED_VESSELS,
    VESSEL_ID_BULK,
    VESSEL_ID_RO_RO,
    VESSEL_ID_WATCH,
)

#: ``sample_id`` → 데모 시드 선박 id. 순서가 화면 목록 순서다(용량 큰 벌크 → 작은 벌크 → GT 축).
#:
#: ``sample_id``를 시드 UUID로 두지 않는 이유 — 그 UUID는 **실제 DB에 있는 데모 선박의 id**다.
#: 응답에 실으면 화면이 그것을 선박 id로 오인해 상세 화면으로 보낼 수 있다.
_SAMPLE_SOURCES: tuple[tuple[str, str], ...] = (
    ("bulk-50000-dwt", VESSEL_ID_BULK),
    ("bulk-30000-dwt", VESSEL_ID_WATCH),
    ("ro-ro-passenger-25000-gt", VESSEL_ID_RO_RO),
)

#: 샘플이 싣는 제원 필드 — `API_SPEC §2.3` 등록 요청 필드 중 **신원(IMO·선명)을 뺀 전부**.
SAMPLE_SPEC_FIELDS: tuple[str, ...] = (
    "ship_type",
    "gross_tonnage",
    "deadweight",
    "default_fuel_type",
    "reference_speed_kn",
    "reference_daily_foc_ton",
)


def _number(value: object) -> float | None:
    """CRUD 층 수치는 JSON 숫자다(`API_SPEC §1.7` 「입력/CRUD」 행 · `services.vessel._number`)."""
    return None if value is None else float(Decimal(str(value)))


def list_sample_vessels() -> list[dict[str, object]]:
    """`GET /vessels/samples` 응답의 ``data``.

    ``label``은 시드의 선명이다 — 사용자가 목록에서 고를 때 읽는 이름이며, 등록할 배의
    이름으로 채우지 않는다(위 모듈 설명).
    """
    by_id = {
        str(row["id"]): row for row in (*SEED_VESSELS, *SEED_VESSEL_WATCH, *SEED_VESSEL_GT_AXIS)
    }
    samples: list[dict[str, object]] = []
    for sample_id, seed_id in _SAMPLE_SOURCES:
        row = by_id[seed_id]
        samples.append(
            {
                "sample_id": sample_id,
                "label": row["name"],
                "ship_type": row["ship_type"],
                "gross_tonnage": _number(row["gross_tonnage"]),
                "deadweight": _number(row["deadweight"]),
                "default_fuel_type": row["default_fuel_type"],
                "reference_speed_kn": _number(row["reference_speed_kn"]),
                "reference_daily_foc_ton": _number(row["reference_daily_foc_ton"]),
            }
        )
    return samples
