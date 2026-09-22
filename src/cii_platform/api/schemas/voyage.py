"""항차 생성 요청 스키마 (API_SPEC §3.3, #53).

요청만 Pydantic으로 정의한다. 응답은 서비스가 만든 dict를 그대로 내보낸다.
검증 규칙은 API_SPEC §11에서 온다. 형식과 범위만 여기서 보고,
DB를 봐야 아는 것(VAL-005 연도 존재 · VAL-006 active fuel)은 서비스가 확인한다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from cii_platform.api.schemas.bounds import DISTANCE, REGULATION_YEAR, SPEED, VOYAGE_FUEL
from cii_platform.api.schemas.instants import Instant

#: 계획 거리의 출처 (#1256 · `DB_SCHEMA §2.2` `planned_distance_source`).
#:
#: `USER_INPUT`은 사용자가 직접 넣은 값(화면 입력 · CSV 가져오기), `COORDINATE_ESTIMATE`는
#: 두 좌표의 대권거리로 채운 값(`§3.9` · `PRD §15.2` 「좌표 기반 추정 거리」)이다. 생략하면
#: **`null` = 「모른다」**로 저장한다 — 서버는 클라이언트가 그 숫자를 어떻게 얻었는지 알 수
#: 없고, 모르는 것을 직접 입력으로도 추정으로도 적지 않는다(`PRD §0.3`).
DistanceSource = Literal["USER_INPUT", "COORDINATE_ESTIMATE"]

#: 059의 트리거가 허용하는 값과 같은 집합 — 마이그레이션 쪽이 정본이고 여기서 갈리면 500이다.
DISTANCE_SOURCES: tuple[str, ...] = get_args(DistanceSource)


#: 항차 메모의 길이 상한 (`PRD §10.2` ⑵ — 0~1000자). `AGENTS §3.1`상 PRD가 상위
#: 정본이므로 그 값을 코드가 따른다 (`#1348`).
NOTES_MAX_LENGTH = 1000


class VoyageFuelUseCreateRequest(BaseModel):
    """``fuel_uses[]`` 한 건."""

    model_config = ConfigDict(extra="forbid")

    fuel_type: Annotated[str, Field(min_length=1, max_length=30)]
    # VAL-002: > 0. 상·하한은 DB 저장 범위 `NUMERIC(12,4)`에서 온다 (#1086 · `schemas/bounds.py`).
    planned_fuel_ton: Annotated[Decimal, Field(**VOYAGE_FUEL)]
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
    # VAL-002 / VAL-009. 상·하한은 DB 저장 범위에서 온다 (#1086 · `schemas/bounds.py`) —
    # `0.001`은 0.00으로 반올림돼 `chk_distance_positive` 위반, `10000` kn은 `NUMERIC(6,2)` 초과.
    planned_distance_nm: Annotated[Decimal, Field(**DISTANCE)]
    # #1256 — 위 거리가 어디서 왔는가. 화면은 항상 보낸다(좌표로 채웠으면
    # `COORDINATE_ESTIMATE`, 사용자가 고쳤으면 `USER_INPUT`). 생략 = `null` = 「모른다」.
    planned_distance_source: DistanceSource | None = None
    planned_speed_kn: Annotated[Decimal, Field(**SPEED)]
    planned_departure_at: Instant | None = None
    planned_arrival_at: Instant | None = None
    # DB CHECK `BETWEEN 2019 AND 2050`과 같다 (#1086 ①). 실재 여부(VAL-005)는 서비스가 본다.
    regulation_year: Annotated[int | None, Field(**REGULATION_YEAR)] = None
    fuel_uses: Annotated[list[VoyageFuelUseCreateRequest], Field(min_length=1)]
    # PRD §10.2 ⑵ — 메모 0~1000자. 정본이 값을 정해 뒀는데 코드에 상한이 없어
    # 요청 본문 크기가 유일한 방어였다 (`#1348`). DB는 TEXT라 컬럼은 받지만,
    # 받는 것과 **받아도 되는 것**은 다르다.
    notes: Annotated[str | None, Field(max_length=NOTES_MAX_LENGTH)] = None


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
    planned_distance_nm: Annotated[Decimal | None, Field(**DISTANCE)] = None
    # #1256 — `planned_distance_nm`을 바꾸면서 이 키를 생략하면 출처는 **`null`로 돌아간다**
    # (옛 「추정」 표시가 새 숫자에 붙어 있으면 거짓말이다 · `services/voyage.py`). 함께 보내면
    # 그 값으로, 명시적 `null`은 지움이다(#312 규약과 같다).
    planned_distance_source: DistanceSource | None = None
    planned_speed_kn: Annotated[Decimal | None, Field(**SPEED)] = None
    planned_departure_at: Instant | None = None
    planned_arrival_at: Instant | None = None
    regulation_year: Annotated[int | None, Field(**REGULATION_YEAR)] = None
    # PRD §10.2 ⑵ — 메모 0~1000자. 정본이 값을 정해 뒀는데 코드에 상한이 없어
    # 요청 본문 크기가 유일한 방어였다 (`#1348`). DB는 TEXT라 컬럼은 받지만,
    # 받는 것과 **받아도 되는 것**은 다르다.
    notes: Annotated[str | None, Field(max_length=NOTES_MAX_LENGTH)] = None


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
    actual_fuel_ton: Annotated[Decimal, Field(**VOYAGE_FUEL)]
    source: Annotated[str | None, Field(default=None, max_length=30)] = None


class VoyageActualsRequest(BaseModel):
    """``PUT /api/v1/voyages/{voyage_id}/actuals`` 요청 본문 (`API_SPEC §3.6`, #440).

    모든 필드가 선택이다 — 실거리만 먼저 알고 연료는 나중에 오는 경우가 실제로 있다.
    **생략은 「변경 없음」이고 명시적 ``null``은 「지움」이다**(`#312`와 같은 규약).
    """

    model_config = ConfigDict(extra="forbid")

    actual_distance_nm: Annotated[Decimal | None, Field(**DISTANCE)] = None
    #: `chk_actual_speed_min` — DB가 1.0 이상을 요구한다. 스키마가 더 느슨하면
    #: 사용자는 422가 아니라 500(제약 위반)을 받는다.
    actual_avg_speed_kn: Annotated[Decimal | None, Field(**SPEED)] = None
    actual_departure_at: Instant | None = None
    actual_arrival_at: Instant | None = None
    fuel_uses: list[VoyageFuelActualRequest] | None = None
