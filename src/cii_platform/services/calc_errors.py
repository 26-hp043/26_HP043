"""계산 엔진의 예외를 사용자 문구로 옮긴다 (``API_SPEC §1.3.2`` 언어 규정 · #999).

종전에는 세 계산 서비스(기능① ``voyage_cii`` · 기능② ``scenario_compare`` · 누적 ``ytd_cii``)가
엔진의 ``ValueError``를 **문구 뒤에 그대로 붙였다**::

    선박 제원이 부족해 계산할 수 없습니다: deadweight is required for
    ship_type 'BULK_CARRIER' (DWT 기준) but was None

엔진의 메시지는 개발자용 영문이다. 여기서 두 갈래로 나눈다.

- **사용자가 고칠 수 있는 원인** — 선종의 용량 축(DWT/GT)이 비었거나 0 이하. 무엇이 비었는지
  **한국어로** 말하고 422로 낸다(``field=vessel_id``). 기준선·등급 경계를 고르다가 이 원인을
  만나도 같다 — 종전에는 그 경우가 409(규정 파라미터 없음)로 나가 사용자가 고칠 수 있는 일을
  서버 문제로 보이게 했다
- **사용자가 고칠 수 없는 원인** — 기준선 구간의 빈틈, 계산 결과의 NaN 등. **정본 문구만**
  두고(``API_SPEC §11`` VAL-005 · VAL-008) 영문 진단은 **서버 로그로** 보낸다. 응답의
  ``request_id``로 그 로그를 찾는다
"""

from __future__ import annotations

import logging

from cii_platform.calc.capacity import CapacityUnavailableError
from cii_platform.errors import AppError, ParameterError, ValidationError

_log = logging.getLogger(__name__)

#: 용량 축 → 사용자에게 보이는 이름. ``api/field_labels.py``의 ``deadweight``·``gross_tonnage``
#: 라벨과 같다. 둘 다 받침 없이 끝나(「…톤수」) 조사는 「가」·「는」·「를」이다.
CAPACITY_LABELS: dict[str, str] = {"DWT": "재화중량톤수(DWT)", "GT": "총톤수(GT)"}

#: 용량 축으로 설명되지 않는 제원 문제(지원하지 않는 선종 등)의 문구.
SPEC_FALLBACK = (
    "선박 제원이 부족해 계산할 수 없습니다. 선종과 재화중량톤수(DWT)·총톤수(GT)를 확인해 주세요."
)

#: :func:`selection_error`가 받는 대상 → 목적격 조사를 붙인 꼴.
_WITH_OBJECT_PARTICLE: dict[str, str] = {"기준선": "기준선을", "등급 경계": "등급 경계를"}

#: ``API_SPEC §11`` VAL-008 원문.
CALCULATION_FAILED = "계산 오류: 입력값을 확인하세요."


def spec_error(exc: ValueError) -> ValidationError:
    """선박 제원 때문에 계산할 수 없다 → 422. 비어 있는 축이 있으면 그 이름을 말한다."""
    if isinstance(exc, CapacityUnavailableError):
        label = CAPACITY_LABELS.get(exc.axis, exc.axis)
        if exc.reason == "missing":
            message = (
                f"{label}가 없어 이 선박의 CII를 계산할 수 없습니다. "
                f"선박 제원에 {label}를 입력해 주세요."
            )
        else:
            # API_SPEC §11 VAL-002 틀 — 「{field_label}는 0보다 커야 합니다.」
            message = f"{label}는 0보다 커야 합니다. 선박 제원을 확인해 주세요."
    else:
        _log.warning("선박 제원으로 계산할 수 없음(용량 축 밖의 원인): %s", exc)
        message = SPEC_FALLBACK
    return ValidationError(message, field="vessel_id", field_label="선박")


def selection_error(what: str, exc: ValueError) -> AppError:
    """기준선·등급 경계를 고르지 못했다.

    용량 축이 비어서라면 **제원 문제**(422 · :func:`spec_error`)이고, 그 밖이면 규정 파라미터
    문제(409)다. 후자의 영문 진단(후보 조건식·선박 제원 값)은 로그로 보낸다.

    :param what: 「기준선」 또는 「등급 경계」.
    """
    if isinstance(exc, CapacityUnavailableError):
        return spec_error(exc)
    _log.warning("%s 선택 실패: %s", what, exc)
    return ParameterError(
        f"{_WITH_OBJECT_PARTICLE[what]} 고를 수 없습니다. "
        "해당 연도·선종의 규정 파라미터를 확인해 주세요."
    )


def log_calculation_failure(where: str, exc: ValueError) -> str:
    """계산 결과가 유효하지 않다(NaN 등) — 진단은 로그로, 사용자에게는 VAL-008 원문."""
    _log.warning("%s 계산 실패: %s", where, exc)
    return CALCULATION_FAILED
