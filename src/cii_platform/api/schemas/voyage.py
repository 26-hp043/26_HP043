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
