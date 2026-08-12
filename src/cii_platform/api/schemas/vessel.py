"""선박 등록 요청 스키마 (API_SPEC §2.3, #50).

요청만 Pydantic으로 정의한다. 응답은 ``services.vessel.to_dict()`` 결과를 그대로
내보낸다 — vessel 모델의 컬럼이 응답 형태를 결정하도록 두는 게 DB 스키마와 API
사이의 drift를 줄인다 (``services.vessel`` 모듈 docstring 참조).

검증 규칙은 API_SPEC §11 VAL-001/002/003/004에서 온다. 형식과 범위만 여기서 보고,
DB를 봐야 아는 것(VAL-004 ``ship_type`` 존재, 중복 IMO)은 서비스가 확인한다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class VesselCreateRequest(BaseModel):
    """``POST /api/v1/vessels`` 요청 본문 (API_SPEC §2.3).

    ``extra="forbid"``인 이유: 오타 필드(``imos_number`` 등)가 조용히 무시되면
    기본값으로 들어가 사용자가 의도하지 않은 선박이 등록된다.
    """

    model_config = ConfigDict(extra="forbid")

    # VAL-003: 7자리 숫자. 형식은 여기서, DB CHK 제약(chk_imo_format)과 이중 방어.
    imo_number: Annotated[str, Field(pattern=r"^\d{7}$", min_length=7, max_length=7)]
    # VAL-001: 1~100자.
    name: Annotated[str, Field(min_length=1, max_length=100)]
    # VAL-004(파라미터 테이블 존재)는 서비스가 DB 조회로 검증.
    ship_type: Annotated[str, Field(min_length=1, max_length=50)]
    # VAL-002: > 0. None 허용(선택 입력).
    gross_tonnage: Annotated[Decimal | None, Field(gt=0)] = None
    deadweight: Annotated[Decimal | None, Field(gt=0)] = None
    default_fuel_type: Annotated[str | None, Field(max_length=30)] = None
    reference_speed_kn: Annotated[Decimal | None, Field(gt=0)] = None
    reference_daily_foc_ton: Annotated[Decimal | None, Field(gt=0)] = None


class VesselUpdateRequest(BaseModel):
    """``PATCH /api/v1/vessels/{vessel_id}`` 요청 본문 (API_SPEC §2.4, #52).

    모든 필드는 optional이다 — None은 "이 필드는 안 바꾼다". **``imo_number``는
    아예 받지 않는다** — "변경 불가" 규칙(§2.4)을 스키마 단에서 보장한다. 클라이언트가
    ``imo_number``를 보내면 ``extra="forbid"``가 422로 거부한다.
    """

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str | None, Field(min_length=1, max_length=100)] = None
    # VAL-004(파라미터 테이블 존재)는 서비스가 DB 조회로 검증.
    ship_type: Annotated[str | None, Field(min_length=1, max_length=50)] = None
    gross_tonnage: Annotated[Decimal | None, Field(gt=0)] = None
    deadweight: Annotated[Decimal | None, Field(gt=0)] = None
    default_fuel_type: Annotated[str | None, Field(max_length=30)] = None
    reference_speed_kn: Annotated[Decimal | None, Field(gt=0)] = None
    reference_daily_foc_ton: Annotated[Decimal | None, Field(gt=0)] = None
