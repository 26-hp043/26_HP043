"""not under way 구간 요청 스키마 (API_SPEC §3.8, #370).

요청만 Pydantic으로 정의한다. 응답은 서비스가 만든 dict를 그대로 내보낸다.
열거 허용집합은 마이그레이션 025의 CHECK와 같은 값이다 — 스키마에서 먼저 걸러
``field`` 단위 422로 바꾼다. DB를 봐야 아는 것(연료 코드 존재·구간 겹침)은
서비스가 확인한다.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

#: MEPC.401(83) EOSP→FAOP 구간 실체 6값 (chk_not_underway_period_type).
PeriodType = Literal[
    "IN_PORT",
    "AT_ANCHOR",
    "DRIFTING",
    "STS",
    "CANAL_TRANSIT",
    "DRYDOCK",
]

#: MEPC.385(81) Appendix IX DCS 보고 항목 4값 (chk_not_underway_consumer_type).
ConsumerType = Literal["MAIN_ENGINE", "AUX_ENGINE", "OIL_FIRED_BOILER", "OTHER"]


class NotUnderwayFuelUseCreateRequest(BaseModel):
    """``fuel_uses[]`` 한 건."""

    model_config = ConfigDict(extra="forbid")

    consumer_type: ConsumerType
    fuel_type: Annotated[str, Field(min_length=1, max_length=30)]
    # chk_not_underway_fuel_positive — 0은 「안 썼다」가 아니라 기록하지 않는 것이다.
    fuel_ton: Annotated[Decimal, Field(gt=0)]


class NotUnderwayPeriodCreateRequest(BaseModel):
    """``POST /api/v1/vessels/{vessel_id}/not-underway-periods`` 요청 본문."""

    model_config = ConfigDict(extra="forbid")

    period_type: PeriodType
    started_at: datetime
    # NULL = 진행 중 구간 (chk_not_underway_period_time_order와 같은 의미).
    ended_at: datetime | None = None
    # chk_regulation_year_range (voyage)와 같은 하한. 상한은 스키마 방어값.
    regulation_year: Annotated[int, Field(ge=2019, le=2100)]
    port_name: Annotated[str | None, Field(max_length=200)] = None
    lat: Annotated[Decimal | None, Field(ge=-90, le=90)] = None
    lon: Annotated[Decimal | None, Field(ge=-180, le=180)] = None
    voyage_id: UUID | None = None
    # 028 — 접안·묘박은 0이 정상값이다(「모름」과 0을 섞지 않는다). 운하·표류·STS만 > 0.
    distance_nm: Annotated[Decimal, Field(ge=0)] = Decimal("0")
    # 구간만 먼저 등록하고 연료는 나중에 PATCH로 붙이는 흐름을 허용한다(빈 목록).
    fuel_uses: Annotated[list[NotUnderwayFuelUseCreateRequest], Field(default_factory=list)]


class NotUnderwayPeriodUpdateRequest(BaseModel):
    """``PATCH /api/v1/not-underway-periods/{period_id}`` 요청 본문.

    생략 = 변경 없음. ``ended_at``에 값을 주면 진행 중 구간의 **종료 처리**가 되고,
    명시적 ``null``은 「진행 중으로 되돌린다」다. ``fuel_uses``를 주면 목록 전체를
    교체한다 (#312 PATCH 의미론의 목록 확장).
    """

    model_config = ConfigDict(extra="forbid")

    period_type: PeriodType | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    regulation_year: Annotated[int | None, Field(ge=2019, le=2100)] = None
    port_name: str | None = None
    lat: Decimal | None = None
    lon: Decimal | None = None
    voyage_id: UUID | None = None
    distance_nm: Annotated[Decimal | None, Field(ge=0)] = None
    fuel_uses: list[NotUnderwayFuelUseCreateRequest] | None = None
