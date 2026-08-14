"""기능② 요청 스키마 (API_SPEC §5.1).

기능① 스키마(``voyage_cii.py``)와 같은 원칙 — **요청만 Pydantic**으로 정의하고
응답은 서비스가 만든 dict를 그대로 내보낸다. Layer 1 값이 문자열이고 ``null``을
가질 수 있는 필드가 있어 응답 모델을 만들면 자릿수가 바뀔 여지가 생긴다.

``extra="forbid"``로 오타 필드를 차단한다 — 기능①과 같은 이유다.

``current_lat``·``current_lon``은 §5.1 필드 표에서 필수(Y)로 표기되어 있으나
**선택으로 둔다.** §5.1의 DIRECT 생성 규칙(PRD §11.2)이 *"사용자가 입력한 거리
또는 좌표 기반 대권거리"* 를 규정하는데, 거리를 직접 입력하는 경로에서 현재
좌표까지 강제하면 거리만으로 비교하는 요청(8/8 데모 provider 포함)이 좌표를
지어내야 한다. 필요 조건(거리가 없으면 좌표 4개)은 서비스가 검증한다.
#151이 §5.1 예시를 일괄 교체할 때 이 표기도 함께 정정한다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cii_platform.api.schemas.voyage_cii import WeatherModel


class ScenarioCompareRequest(BaseModel):
    """``POST /api/v1/scenarios/compare`` 요청 본문."""

    model_config = ConfigDict(extra="forbid")

    vessel_id: UUID
    # VAL-005 연도 존재 확인은 DB를 봐야 하므로 서비스가 한다. 상식적 범위만.
    regulation_year: Annotated[int, Field(ge=2000, le=2100)]
    # VAL-007: −90 ~ +90 / −180 ~ +180. direct_distance_nm이 없을 때 필요(서비스 검증).
    current_lat: Annotated[Decimal | None, Field(ge=-90, le=90)] = None
    current_lon: Annotated[Decimal | None, Field(ge=-180, le=180)] = None
    # §5.1 예시·PRD §11.3에 있는 표기용 필드. 계산에는 쓰이지 않는다.
    destination_port_name: Annotated[str | None, Field(max_length=200)] = None
    destination_lat: Annotated[Decimal | None, Field(ge=-90, le=90)] = None
    destination_lon: Annotated[Decimal | None, Field(ge=-180, le=180)] = None
    # VAL-009: >= 1.0. > 0이 아니다 — PRD §9.1이 1.0 하한을 규정한다.
    current_speed_kn: Annotated[Decimal, Field(ge=Decimal("1.0"))]
    # VAL-006 코드 존재·active 여부는 서비스가 확인한다.
    fuel_type: Annotated[str, Field(min_length=1, max_length=30)]
    # VAL-002: > 0. 선박 기준값(vessel.reference_daily_foc_ton)이 있으면 생략 가능.
    base_daily_foc_ton: Annotated[Decimal | None, Field(gt=0)] = None
    direct_distance_nm: Annotated[Decimal | None, Field(gt=0)] = None
    # 미지정 시 서버가 direct × 1.05 (API_SPEC §5.1).
    detour_distance_nm: Annotated[Decimal | None, Field(gt=0)] = None
    # VAL-009. 미지정 시 서버가 max(current_speed − 1, 1.0)로 계산 (API_SPEC §5.1).
    slow_speed_kn: Annotated[Decimal | None, Field(ge=Decimal("1.0"))] = None
    # 기본 NONE. #61(기상 연동) 전까지 NONE이 아닌 값은 fallback warning과 함께
    # NONE으로 계산한다 (API_SPEC §1.6 WEATHER_NONE_FALLBACK).
    weather_model: WeatherModel | None = None
