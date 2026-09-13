"""함대 감축 계획 요청 본문 (``API_SPEC §2.17`` · #513)."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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


class ReductionPlanRequest(BaseModel):
    """``POST /fleet/reduction-plans/evaluate`` 본문."""

    model_config = ConfigDict(extra="forbid")

    regulation_year: Annotated[int, Field(ge=2000, le=2100)]
    target: Literal["NO_AT_RISK", "ALL_C_OR_BETTER"]
    adjustments: list[VesselAdjustment] = []
    prices: PriceAssumptions = PriceAssumptions()


class ReductionPlanSaveRequest(ReductionPlanRequest):
    """``POST /fleet/reduction-plans`` 본문 — 계산 본문 + 이름."""

    #: ``name``이 아닌 이유 — 필드 라벨(``api/field_labels.py``)이 필드명 하나로 매겨지는데
    #: ``name``은 이미 「선명」이다. 같은 이름이면 계획 이름 오류가 「선명」으로 나간다.
    plan_name: Annotated[str, Field(min_length=1, max_length=100)]
