"""함대 감축 계획 요청 본문 (``API_SPEC §2.17`` · #513)."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from cii_platform.calc.fleet_reduction import MAX_REDUCTION_PERCENT


class VesselAdjustment(BaseModel):
    """선박 한 척의 감속률."""

    model_config = ConfigDict(extra="forbid")

    vessel_id: UUID
    #: 0~50% (``PRD §12.3.2``). 상한은 ``calc.fleet_reduction.MAX_REDUCTION_PERCENT`` 하나에 둔다.
    speed_reduction_percent: Annotated[Decimal, Field(ge=0, le=MAX_REDUCTION_PERCENT)]


class PriceAssumptions(BaseModel):
    """계획이 **가정한** 단가 — USD (2026-09-13 결정 C).

    비어 있어도 된다 — 그때 비용 칸은 「단가 입력 필요」로 비고 0으로 채우지 않는다.
    """

    model_config = ConfigDict(extra="forbid")

    #: 선박 ID → 일일 용선료(USD/일).
    charter_usd_per_day: dict[str, Annotated[Decimal, Field(ge=0)]] = {}
    #: 유종 코드 → 연료 단가(USD/t).
    fuel_usd_per_ton: dict[str, Annotated[Decimal, Field(ge=0)]] = {}

    @field_validator("charter_usd_per_day")
    @classmethod
    def _normalize_vessel_keys(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        """키를 **UUID 표준 표기(소문자)** 로 맞춘다 (#1070 ⑵).

        서비스는 선박을 ``str(UUID)``로 찾는다. 대문자 UUID 키를 그대로 두면 단가를 넣었는데도
        「단가 입력 필요」가 되고, 저장본에도 찾을 수 없는 키가 남는다. UUID가 아니면 422다.
        """
        normalized: dict[str, Decimal] = {}
        for key, amount in value.items():
            try:
                canonical = str(UUID(key))
            except ValueError as exc:
                raise ValueError(f"일일 용선료의 선박 ID가 올바르지 않습니다: {key}") from exc
            if canonical in normalized:
                raise ValueError(f"일일 용선료에 같은 선박이 두 번 있습니다: {canonical}")
            normalized[canonical] = amount
        return normalized


class ReductionPlanRequest(BaseModel):
    """``POST /fleet/reduction-plans/evaluate`` 본문."""

    model_config = ConfigDict(extra="forbid")

    regulation_year: Annotated[int, Field(ge=2000, le=2100)]
    target: Literal["NO_AT_RISK", "ALL_C_OR_BETTER"]
    adjustments: list[VesselAdjustment] = []
    prices: PriceAssumptions = PriceAssumptions()

    @field_validator("adjustments")
    @classmethod
    def _one_adjustment_per_vessel(cls, value: list[VesselAdjustment]) -> list[VesselAdjustment]:
        """같은 선박을 두 번 보내면 422다 (#1070 ⑶).

        받아 주면 계산은 **마지막 값**으로 하고 저장본에는 **두 값이 다 남아**, 다시 연 계획이
        어느 감속률이었는지 답할 수 없다. 모델 전체가 아니라 이 필드에 걸어야 오류 라벨이
        「요청 본문」이 아니라 「선박별 감속」으로 나간다.
        """
        seen: set[UUID] = set()
        for item in value:
            if item.vessel_id in seen:
                raise ValueError(f"같은 선박의 감속률이 두 번 있습니다: {item.vessel_id}")
            seen.add(item.vessel_id)
        return value


class ReductionPlanSaveRequest(ReductionPlanRequest):
    """``POST /fleet/reduction-plans`` 본문 — 계산 본문 + 이름."""

    #: ``name``이 아닌 이유 — 필드 라벨(``api/field_labels.py``)이 필드명 하나로 매겨지는데
    #: ``name``은 이미 「선명」이다. 같은 이름이면 계획 이름 오류가 「선명」으로 나간다.
    #:
    #: **앞뒤 공백을 먼저 걷고 길이를 잰다** (#1070 ⑴). 종전에는 공백만 있는 이름이
    #: 검증을 통과한 뒤 서비스의 ``strip()``으로 빈 문자열이 되어 DB 제약
    #: (``chk_fleet_reduction_plan_name``)에 걸렸고 **500**이 났다 — 그 전에 선대 전체
    #: 계산도 한 번 돌았다.
    plan_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
