"""not under way 구간 요청 스키마 (API_SPEC §2.10~§2.13, #370).

항차 스키마(``schemas/voyage.py``)와 같은 규약이다 — **요청만 Pydantic으로 정의**하고
응답은 서비스가 만든 dict를 그대로 내보낸다. 형식·범위만 여기서 보고, DB를 봐야 아는
것(연료 active 여부, 구간 겹침)은 서비스가 확인한다.

**시각은 ``AwareDatetime``이다 (`#1333`).** 시간대 없는 시각을 받으면 두 가지가 난다 —
``PATCH``는 요청의 naive와 DB의 aware를 비교하다 ``TypeError``로 **500**이 되고,
``POST``는 서버 세션 시간대로 해석해 **조용히 다른 순간**을 저장한다. 같은 모듈의 CSV
경로(``not_underway_import``)는 처음부터 시간대를 요구했다 — **한 리소스의 두 입구가
다른 규칙을 쓰고 있었다.**

**열거값(``period_type``·``consumer_type``)을 여기서 보지 않는다.** DB CHECK 제약과
같은 목록을 두 곳에 두면 갈라지므로, 서비스의 ``PERIOD_TYPES``·``CONSUMER_TYPES``
하나만 둔다. 대신 ``max_length``로 컬럼 폭은 지킨다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from cii_platform.api.schemas.bounds import (
    NOT_UNDERWAY_DISTANCE,
    NOT_UNDERWAY_FUEL,
    REGULATION_YEAR,
)
from cii_platform.api.schemas.voyage import HumanTimeSource


class NotUnderwayFuelUseCreateRequest(BaseModel):
    """``fuel_uses[]`` 한 건.

    **``cf_used``를 받지 않는다.** 배출계수는 서버가 계산 시점 값으로 뜬다
    (``services.not_underway._snapshot_cf``) — 화면이 보내면 사용자가 배출계수를
    정하는 셈이 된다.
    """

    model_config = ConfigDict(extra="forbid")

    consumer_type: Annotated[str, Field(min_length=1, max_length=20)]
    fuel_type: Annotated[str, Field(min_length=1, max_length=30)]
    # chk_not_underway_fuel_positive: > 0. 0톤 기록은 「안 썼다」가 아니라 오타다.
    # 상·하한은 DB 저장 범위 `NUMERIC(12,2)`에서 온다 (#1086 · `schemas/bounds.py`).
    fuel_ton: Annotated[Decimal, Field(**NOT_UNDERWAY_FUEL)]


class NotUnderwayPeriodCreateRequest(BaseModel):
    """``POST /api/v1/vessels/{vessel_id}/not-underway-periods`` (API_SPEC §2.10)."""

    model_config = ConfigDict(extra="forbid")

    period_type: Annotated[str, Field(min_length=1, max_length=20)]
    started_at: AwareDatetime
    #: ``None``이면 **진행 중**이다. 「모름」이 아니다.
    ended_at: AwareDatetime | None = None
    port_name: Annotated[str | None, Field(max_length=200)] = None
    lat: Annotated[Decimal | None, Field(ge=-90, le=90)] = None
    lon: Annotated[Decimal | None, Field(ge=-180, le=180)] = None
    #: ``chk_nup_distance_non_negative``: >= 0. 접안·묘박은 0이 정상값이라 ``gt``가
    #: 아니라 ``ge``다(마이그레이션 028). 이 값은 CII 분모 ``Dt``에 더해진다.
    distance_nm: Annotated[Decimal, Field(**NOT_UNDERWAY_DISTANCE)] = Decimal(0)
    #: 생략하면 서버가 ``started_at``의 연도로 채운다.
    # DB CHECK `BETWEEN 2019 AND 2050`과 같다 (#1086 ①). 실재 여부는 서비스가 본다.
    regulation_year: Annotated[int | None, Field(**REGULATION_YEAR)] = None
    #: 맥락 참조용. 구간은 항차가 아니라 **선박+연도**에 귀속된다(``#345``).
    voyage_id: UUID | None = None
    #: 비워 둘 수 있다 — 정박이 끝나야 소모량을 아는 것이 보통이라, §2.13으로 뒤에
    #: 붙이는 경로를 함께 둔다.
    fuel_uses: list[NotUnderwayFuelUseCreateRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_time_order(self) -> NotUnderwayPeriodCreateRequest:
        """``chk_not_underway_period_time_order``를 요청 단계에서 먼저 본다.

        DB 제약에 맡기면 IntegrityError가 500으로 올라가고, 사용자는 고칠 수 있는
        입력을 「서버 오류」로 보게 된다.
        """
        if self.ended_at is not None and self.ended_at <= self.started_at:
            raise ValueError("종료 시각은 시작 시각보다 뒤여야 합니다.")
        return self


class NotUnderwayPeriodUpdateRequest(BaseModel):
    """``PATCH /api/v1/not-underway-periods/{period_id}`` (API_SPEC §2.11).

    모든 필드가 optional이다 — **생략 = 변경 없음**(항차 수정 ``#312``과 같은 규약).

    다만 ``ended_at``의 명시적 ``null``은 클리어가 아니라 **「다시 진행 중으로
    되돌림」**이다. 잘못 닫은 구간을 되돌릴 경로가 필요하고, 이 열에서 ``null``은
    원래 그 뜻이다.

    시각 순서 검사는 여기서 하지 않는다 — 한쪽만 보내는 것이 정상이라 **기존 행의
    값과 합쳐 봐야** 알 수 있고, 그 판단은 서비스가 한다.
    """

    model_config = ConfigDict(extra="forbid")

    period_type: Annotated[str | None, Field(min_length=1, max_length=20)] = None
    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    # #1923 — 시각을 바꾸면서 생략하면 출처는 `null`로 돌아간다(항차 실적 `§3.6`과 같은 규칙).
    # `PUBLIC_RECORD`는 `§3.12`만 붙인다.
    started_at_source: HumanTimeSource | None = None
    ended_at_source: HumanTimeSource | None = None
    port_name: Annotated[str | None, Field(max_length=200)] = None
    lat: Annotated[Decimal | None, Field(ge=-90, le=90)] = None
    lon: Annotated[Decimal | None, Field(ge=-180, le=180)] = None
    distance_nm: Annotated[Decimal | None, Field(**NOT_UNDERWAY_DISTANCE)] = None
    regulation_year: Annotated[int | None, Field(**REGULATION_YEAR)] = None
    voyage_id: UUID | None = None
