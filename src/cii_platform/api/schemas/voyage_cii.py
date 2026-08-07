"""기능① 요청 스키마 (API_SPEC §4.1).

**요청만 Pydantic으로 정의한다.** 응답은 서비스가 만든 dict를 그대로 내보낸다 —
Layer 1 값이 문자열이고 일부 필드가 ``null``을 가질 수 있어(``next_worse_boundary_margin``)
응답 모델을 만들면 그 문자열을 다시 검증·재직렬화하게 되고, **그 과정에서 자릿수가
바뀔 여지**가 생긴다. §1.7이 문자열로 내리는 이유가 정밀도 보존이므로 손대지 않는다.

검증 규칙은 API_SPEC §11(VAL-002 · VAL-006 · VAL-009)에서 온다. 여기서는 **형식과
범위**만 보고, DB를 봐야 아는 것(VAL-005 연도 존재 · VAL-006 active 여부)은 서비스가
확인한다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

#: API_SPEC §4.1 ``weather_model`` enum. 8/8 UI는 이 값을 보내지 않으며 기본값 NONE이다.
WeatherModel = Literal["NONE", "SIMPLE_RULE", "TOWNSIN_KWON_ALPHA"]


class FuelUseRequest(BaseModel):
    """``fuel_uses[]`` 한 건."""

    model_config = ConfigDict(extra="forbid")

    fuel_type: Annotated[str, Field(min_length=1, max_length=30)]
    # VAL-002: > 0. gt=0을 쓰면 0이 거부된다(ge=0이 아니다).
    fuel_ton: Annotated[Decimal, Field(gt=0)]


class VoyageCiiRequest(BaseModel):
    """``POST /api/v1/calculations/voyage-cii`` 요청 본문.

    ``extra="forbid"``인 이유: 오타 필드(``speed_knots`` 등)를 조용히 무시하면
    **기본값으로 계산이 돌아가 사용자가 보낸 값이 반영되지 않은 결과**가 나온다.
    #55 이슈 본문이 ``speed_kn``/``speed_knots`` 혼동을 명시적으로 경고한다.
    """

    model_config = ConfigDict(extra="forbid")

    vessel_id: UUID
    # 연도 존재 확인(VAL-005)은 DB를 봐야 하므로 서비스가 한다. 여기서는 상식적
    # 범위만 막는다 — 음수·4자리 아닌 값이 DB 조회까지 가지 않게 한다.
    regulation_year: Annotated[int, Field(ge=2000, le=2100)]
    # VAL-002: > 0
    distance_nm: Annotated[Decimal, Field(gt=0)]
    # VAL-009: >= 1.0. **> 0이 아니다** — PRD §9.1이 1.0 하한을 규정한다.
    speed_kn: Annotated[Decimal, Field(ge=Decimal("1.0"))]
    # 최소 1개. 빈 배열이면 계산할 CO₂가 없다.
    fuel_uses: Annotated[list[FuelUseRequest], Field(min_length=1)]
    weather_model: WeatherModel | None = None
