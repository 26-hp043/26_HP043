"""항차 생성 요청 스키마 (API_SPEC §3.3, #53).

요청만 Pydantic으로 정의한다. 응답은 서비스가 만든 dict를 그대로 내보낸다.
검증 규칙은 API_SPEC §11에서 온다. 형식과 범위만 여기서 보고,
DB를 봐야 아는 것(VAL-005 연도 존재 · VAL-006 active fuel)은 서비스가 확인한다.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class VoyageFuelUseCreateRequest(BaseModel):
    """``fuel_uses[]`` 한 건."""

    model_config = ConfigDict(extra="forbid")

    fuel_type: Annotated[str, Field(min_length=1, max_length=30)]
    # VAL-002: > 0
    planned_fuel_ton: Annotated[Decimal, Field(gt=0)]
    source: Annotated[str, Field(default="USER_INPUT", max_length=30)]


class VoyageCreateRequest(BaseModel):
    """``POST /api/v1/vessels/{vessel_id}/voyages`` 요청 본문 (API_SPEC §3.3)."""

    model_config = ConfigDict(extra="forbid")

    voyage_no: Annotated[str | None, Field(max_length=100)] = None
    departure_port_name: Annotated[str, Field(min_length=1, max_length=200)]
    departure_lat: Annotated[Decimal | None, Field(ge=-90, le=90)] = None
    departure_lon: Annotated[Decimal | None, Field(ge=-180, le=180)] = None
    arrival_port_name: Annotated[str, Field(min_length=1, max_length=200)]
    arrival_lat: Annotated[Decimal | None, Field(ge=-90, le=90)] = None
    arrival_lon: Annotated[Decimal | None, Field(ge=-180, le=180)] = None
    # VAL-002 / VAL-009
    planned_distance_nm: Annotated[Decimal, Field(gt=0)]
    planned_speed_kn: Annotated[Decimal, Field(ge=Decimal("1.0"))]
    planned_departure_at: datetime | None = None
    planned_arrival_at: datetime | None = None
    regulation_year: Annotated[int | None, Field(ge=2000, le=2100)] = None
    fuel_uses: Annotated[list[VoyageFuelUseCreateRequest], Field(min_length=1)]
    notes: str | None = None


class VoyageUpdateRequest(BaseModel):
    """``PATCH /api/v1/voyages/{voyage_id}`` 요청 본문 (API_SPEC §3.4, #54).

    모든 필드는 optional이다 — **생략 = 변경 없음, 명시적 ``null`` = 클리어** (#312).
    ``status`` 변경은 §3.5 transition 엔드포인트에서만 가능하다.
    """

    model_config = ConfigDict(extra="forbid")

    voyage_no: Annotated[str | None, Field(max_length=100)] = None
    departure_port_name: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    departure_lat: Annotated[Decimal | None, Field(ge=-90, le=90)] = None
    departure_lon: Annotated[Decimal | None, Field(ge=-180, le=180)] = None
    arrival_port_name: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    arrival_lat: Annotated[Decimal | None, Field(ge=-90, le=90)] = None
    arrival_lon: Annotated[Decimal | None, Field(ge=-180, le=180)] = None
    planned_distance_nm: Annotated[Decimal | None, Field(gt=0)] = None
    planned_speed_kn: Annotated[Decimal | None, Field(ge=Decimal("1.0"))] = None
    planned_departure_at: datetime | None = None
    planned_arrival_at: datetime | None = None
    regulation_year: Annotated[int | None, Field(ge=2000, le=2100)] = None
    notes: str | None = None


class VoyageTransitionRequest(BaseModel):
    """``POST /api/v1/voyages/{voyage_id}/transition`` (API_SPEC §3.5, #54)."""

    model_config = ConfigDict(extra="forbid")

    to_status: Annotated[str, Field(min_length=1, max_length=20)]
    annual_inclusion_policy: Annotated[str | None, Field(max_length=30)] = None


class VoyageFuelActualRequest(BaseModel):
    """``PUT /voyages/{id}/actuals``의 ``fuel_uses[]`` 한 건 (#440).

    생성 요청과 달리 **계획값을 받지 않는다.** 실적 입력이 계획값을 덮어쓰면
    `PRD §8.4`의 「계획값과 실제값을 모두 보존」이 깨지고, 계획 대비 실적 비교(`#363`)의
    근거가 사라진다.
    """

    model_config = ConfigDict(extra="forbid")

    fuel_type: Annotated[str, Field(min_length=1, max_length=30)]
    #: `chk_actual_fuel_positive` — DB도 같은 조건을 건다. 0을 「안 썼다」로 쓰려면
    #: 그 행을 넣지 않는 것이 맞다.
    actual_fuel_ton: Annotated[Decimal, Field(gt=0)]
    source: Annotated[str | None, Field(default=None, max_length=30)] = None


class VoyageActualsRequest(BaseModel):
    """``PUT /api/v1/voyages/{voyage_id}/actuals`` 요청 본문 (`API_SPEC §3.6`, #440).

    모든 필드가 선택이다 — 실거리만 먼저 알고 연료는 나중에 오는 경우가 실제로 있다.
    **생략은 「변경 없음」이고 명시적 ``null``은 「지움」이다**(`#312`와 같은 규약).
    """

    model_config = ConfigDict(extra="forbid")

    actual_distance_nm: Annotated[Decimal | None, Field(gt=0)] = None
    #: `chk_actual_speed_min` — DB가 1.0 이상을 요구한다. 스키마가 더 느슨하면
    #: 사용자는 422가 아니라 500(제약 위반)을 받는다.
    actual_avg_speed_kn: Annotated[Decimal | None, Field(ge=Decimal("1.0"))] = None
    actual_departure_at: datetime | None = None
    actual_arrival_at: datetime | None = None
    fuel_uses: list[VoyageFuelActualRequest] | None = None
