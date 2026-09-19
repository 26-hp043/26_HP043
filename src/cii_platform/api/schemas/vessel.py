"""선박 등록 요청 스키마 (API_SPEC §2.3, #50).

요청만 Pydantic으로 정의한다. 응답은 ``services.vessel.to_dict()`` 결과를 그대로
내보낸다 — vessel 모델의 컬럼이 응답 형태를 결정하도록 두는 게 DB 스키마와 API
사이의 drift를 줄인다 (``services.vessel`` 모듈 docstring 참조).

검증 규칙은 API_SPEC §11 VAL-001/002/003/004에서 온다. 형식과 범위만 여기서 보고,
DB를 봐야 아는 것(VAL-004 ``ship_type`` 존재, 중복 IMO)은 서비스가 확인한다.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cii_platform.api.schemas.bounds import storable, storable_from


def _storable(precision: int, scale: int) -> dict[str, Decimal]:
    """DB ``NUMERIC(precision, scale)`` 컬럼이 **담을 수 있는** 양수 범위 (`#860`).

    ## 왜 필요한가

    종전 스키마는 ``gt=0``만 봤다. DB는 ``NUMERIC(12,2)`` 같은 고정 정밀도라, API를
    통과한 값이 **저장 단계에서 죽었다.**

    .. code-block:: text

        deadweight = 1e-7   →  0.00으로 반올림  →  chk_dwt_positive 위반  →  500
        deadweight = 1e10   →  정밀도 12·소수 2 초과                       →  500

    **아무것도 저장되지 않는다** — DB가 이미 막고 있었다. 결함은 「이상한 값이 저장된다」가
    아니라 「DB가 거부할 값을 API가 통과시켜 500이 난다」였다.

    ## 도메인 하한이 아니다

    여기 경계는 **저장 형식에서 나온다** — 가장 작은 저장 가능한 양수(``0.01``)와 가장 큰
    값(``10^(precision-scale) − 0.01``). 「DWT는 최소 100톤」 같은 도메인 판단은 이 결함을
    고치는 데 필요 없고, 여기서 정하지 않는다.

    소수 셋째 자리 이하는 **막지 않는다.** 종전처럼 받아서 DB가 반올림한다 — ``decimal_places``로
    거부하면 ``50000.125``처럼 멀쩡한 입력까지 422가 된다.

    값은 ORM 모델(``db/models/vessel.py``)의 ``Numeric(precision, scale)``과 같아야 하며,
    ``tests/test_vessel_spec_bounds.py``가 둘을 대조한다.
    """
    # 계산은 공용 모듈이 한다 (#1086 — 항차·시나리오·정박도 같은 규칙).
    return storable(precision, scale)


#: ``NUMERIC(12,2)`` — DWT · GT.
_TONNAGE = _storable(12, 2)
#: ``NUMERIC(6,2)`` — 기준 속력(kn).
_SPEED = _storable(6, 2)
#: ``NUMERIC(8,2)`` — 기준 일일 연료(t).
_DAILY_FOC = _storable(8, 2)
#: ``NUMERIC(4,3)`` — 방형계수(CB). 저장 범위 위에 **물리 범위**를 더 좁힌다(#966):
#: 체적 비율은 양수이고 1을 넘지 않는다. `DB chk_block_coefficient_range`(055)와 같은 값.
#: 하한 ``0.001``은 ``scale=3``의 최소 양수 — 그보다 작은 값은 저장에서 ``0.000``으로
#: 반올림돼 범위 검사를 통과하고 DB 제약에 걸린다(``#1086`` ⑥와 같은 결함).
_CB = dict(storable_from(Decimal("0.001"), 4, 3), le=Decimal("1"))

#: 호출부호(call sign)의 모양 — ITU 전파규칙 ``RR No. 19.55``의 선박국 네 형식은 전부
#: **영문 대문자·숫자 4~7자**에 든다(마이그레이션 ``058`` 본문). DB 트리거
#: ``trg_chk_call_sign_ins/upd``와 같은 식이다.
_CALL_SIGN = re.compile(r"^[A-Z0-9]{4,7}$")
#: 최대 길이는 DB 컬럼 ``VARCHAR(7)``에서 온다.
_CALL_SIGN_MAX_LENGTH = 7


def _normalize_call_sign(value: object) -> str | None:
    """호출부호를 **대조 키로 쓸 수 있는 모양**으로 접는다 (#1197 A단계).

    - 앞뒤 공백을 지우고 **대문자로** 올린다. 무선국허가증은 대문자로 적지만 사용자는
      소문자로 치기도 한다 — 같은 부호가 ``hlxq``·``HLXQ`` 두 키로 갈리면 공공데이터
      대조가 조용히 빈다.
    - 접은 뒤 비어 있으면 ``None`` — 「모른다」다. 등록에서는 미기록이고 수정(PATCH)에서는
      「안 바꾼다」다(``services.vessel.update_vessel`` 규약).
    - ``RR No. 19.50`` — 앞 두 글자는 국가 배정 계열이라 **둘 다 숫자일 수 없다.** 「문자
      바로 뒤에 0·1이 오지 않는다」 같은 세부는 보지 않는다 — 배정 관행이 나라마다 달라
      실재하는 부호를 거부할 수 있고, 이 칸은 인증서가 아니라 대조 키다.

    문구는 한국어로 곧바로 낸다 — ``validation_messages``가 ``ValueError`` 원문을 그대로
    쓴다(``API_SPEC §1.3.2``).
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("호출부호는 문자열이어야 합니다.")
    text = value.strip().upper()
    if text == "":
        return None
    if not _CALL_SIGN.fullmatch(text):
        raise ValueError(f"호출부호는 영문 대문자와 숫자 4~{_CALL_SIGN_MAX_LENGTH}자여야 합니다.")
    if text[0].isdigit() and text[1].isdigit():
        raise ValueError("호출부호의 앞 두 글자는 모두 숫자일 수 없습니다.")
    return text


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
    # VAL-002: > 0. None 허용(선택 입력). 상·하한은 DB 저장 범위에서 온다 (`_storable`, #860).
    gross_tonnage: Annotated[Decimal | None, Field(**_TONNAGE)] = None
    deadweight: Annotated[Decimal | None, Field(**_TONNAGE)] = None
    default_fuel_type: Annotated[str | None, Field(max_length=30)] = None
    reference_speed_kn: Annotated[Decimal | None, Field(**_SPEED)] = None
    reference_daily_foc_ton: Annotated[Decimal | None, Field(**_DAILY_FOC)] = None
    # #966 — 방형계수(선택). 기상 보정(Townsin–Kwon)의 선형 계수. 모르면 보내지
    # 않는다 — 그때는 선종 기본값 + CB_ESTIMATED 경고가 계약이다.
    block_coefficient: Annotated[Decimal | None, Field(**_CB)] = None
    # #1197 — 호출부호(선택). 공공데이터(해양수산부_선박운항정보)가 IMO가 아니라 이 값으로
    # 질의하므로 교차 대조의 키다. 모르면 보내지 않는다 — 그 배는 대조 대상이 아닐 뿐이다.
    # ``max_length``는 접은 **뒤**의 값에 걸린다(검증기가 ``mode="before"``) — 그래서
    # 「 hlxq 」는 422가 아니라 HLXQ로 들어간다. 실질 판정은 검증기의 정규식이고, 이
    # 상한은 OpenAPI에 컬럼 길이(7)를 드러내는 몫이다.
    call_sign: Annotated[str | None, Field(max_length=_CALL_SIGN_MAX_LENGTH)] = None

    @field_validator("call_sign", mode="before")
    @classmethod
    def _call_sign(cls, value: object) -> str | None:
        return _normalize_call_sign(value)


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
    gross_tonnage: Annotated[Decimal | None, Field(**_TONNAGE)] = None
    deadweight: Annotated[Decimal | None, Field(**_TONNAGE)] = None
    default_fuel_type: Annotated[str | None, Field(max_length=30)] = None
    reference_speed_kn: Annotated[Decimal | None, Field(**_SPEED)] = None
    reference_daily_foc_ton: Annotated[Decimal | None, Field(**_DAILY_FOC)] = None
    block_coefficient: Annotated[Decimal | None, Field(**_CB)] = None
    # #1197 — 빈 문자열은 None으로 접히므로 「안 바꾼다」가 된다. 지우는 경로는 GT와
    # 마찬가지로 PATCH에 없다.
    call_sign: Annotated[str | None, Field(max_length=_CALL_SIGN_MAX_LENGTH)] = None

    @field_validator("call_sign", mode="before")
    @classmethod
    def _call_sign(cls, value: object) -> str | None:
        return _normalize_call_sign(value)


class VesselPositionUpdateRequest(BaseModel):
    """``PATCH /api/v1/vessels/{vessel_id}/position`` 요청 본문 (API_SPEC §2.6, #369).

    ``#346``이 추가한 위치·상태 컬럼을 **실제로 바꾸는 유일한 경로**다. 그 전까지는
    컬럼만 있고 값을 바꿀 방법이 없어, 대시보드(``#351``)의 「지금 어디서 무엇을
    하고 있나」가 시드 이후 영원히 고정됐다.

    **상태 2축은 함께 보낸다.** ``underway_state``와 ``detail_status``는 마이그레이션
    026의 CHECK 제약으로 묶여 있어(``SAILING`` ↔ ``UNDER_WAY``) 한쪽만 바꾸면 조합이
    깨질 수 있다. 스키마에서 둘을 optional로 두되 서비스가 조합을 검증한다.

    **위경도도 함께 보낸다.** 026의 CHECK가 「둘 다 NULL이거나 둘 다 NOT NULL」을
    요구하며, 값이 있으면 ``position_updated_at``도 있어야 한다. 시각은 클라이언트가
    보내지 않고 **서버가 확정**한다 — 클라이언트 시계를 신뢰하면 「언제 기준 위치인가」가
    단말마다 갈린다.
    """

    model_config = ConfigDict(extra="forbid")

    underway_state: Annotated[str | None, Field(max_length=20)] = None
    detail_status: Annotated[str | None, Field(max_length=20)] = None
    current_lat: Annotated[Decimal | None, Field(ge=-90, le=90)] = None
    current_lon: Annotated[Decimal | None, Field(ge=-180, le=180)] = None
