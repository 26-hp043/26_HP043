"""계산 엔진 예외 → 사용자 문구 (``services/calc_errors.py`` · ``API_SPEC §1.3.2`` · #999).

종전에는 세 계산 서비스가 엔진의 영문 ``ValueError``를 문구 뒤에 붙였다 — 선박 제원에 DWT가
비면 사용자는 「… deadweight is required for ship_type 'BULK_CARRIER' (DWT 기준) but was None」을
받았다. 여기서는 두 갈래를 본다.

- **고칠 수 있는 원인**(용량 축이 비었거나 0 이하)은 **무엇이 비었는지** 한국어로, 422로
- **고칠 수 없는 원인**은 정본 문구만 — 영문 진단은 **로그에** 남는다(버리지 않는다)

DB가 필요 없다.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import pytest
from fakes import FakeVessel

from cii_platform.calc.capacity import (
    CapacityUnavailableError,
    resolve_transport_capacity,
    select_reference_line,
)
from cii_platform.errors import ParameterError, ValidationError
from cii_platform.services.calc_errors import (
    CALCULATION_FAILED,
    SPEC_FALLBACK,
    log_calculation_failure,
    selection_error,
    spec_error,
)


def _capacity_error(**vessel) -> CapacityUnavailableError:
    with pytest.raises(CapacityUnavailableError) as info:
        resolve_transport_capacity(FakeVessel(**vessel))
    return info.value


def test_engine_says_which_axis_and_why():
    """엔진이 형으로 알려 준다 — 메시지(영문)는 엔진 검사가 단언하는 그대로다."""
    missing = _capacity_error(deadweight=None)
    assert (missing.axis, missing.reason) == ("DWT", "missing")
    assert "is required" in str(missing)
    zero = _capacity_error(deadweight=Decimal("0"))
    assert (zero.axis, zero.reason) == ("DWT", "non_positive")
    # 종전의 `except ValueError`가 그대로 잡는다.
    assert isinstance(missing, ValueError)


def test_missing_capacity_names_the_field_in_korean():
    error = spec_error(_capacity_error(deadweight=None))
    assert isinstance(error, ValidationError)
    assert error.message == (
        "재화중량톤수(DWT)가 없어 이 선박의 CII를 계산할 수 없습니다. "
        "선박 제원에 재화중량톤수(DWT)를 입력해 주세요."
    )
    assert "deadweight" not in error.message


def test_gt_axis_is_named_too():
    error = spec_error(_capacity_error(ship_type="RO_RO_PASSENGER", gross_tonnage=None))
    assert error.message.startswith("총톤수(GT)가 없어")


def test_non_positive_capacity_follows_val_002():
    error = spec_error(_capacity_error(deadweight=Decimal("-1")))
    assert error.message.startswith("재화중량톤수(DWT)는 0보다 커야 합니다.")


def test_other_spec_failures_keep_the_diagnosis_in_the_log(caplog):
    caplog.set_level(logging.WARNING, logger="cii_platform.services.calc_errors")
    error = spec_error(ValueError("Unknown ship_type for capacity axis: 'SUBMARINE'"))
    assert error.message == SPEC_FALLBACK
    assert "SUBMARINE" in caplog.text, "영문 진단을 버리지 않고 로그로 보낸다"


def test_selecting_a_line_for_a_vessel_without_dwt_is_a_spec_problem():
    """**종전에는 409였다** — 기준선 조건식을 평가하다 DWT가 비어 터지면 「규정 파라미터」
    오류로 나가, 사용자가 제원을 채우면 풀리는 일을 서버 문제로 보이게 했다.
    """

    class _Line:
        ship_type = "BULK_CARRIER"
        condition_expr = "DWT >= 279000"
        capacity_rule = "DWT"

    with pytest.raises(ValueError) as info:
        select_reference_line(FakeVessel(deadweight=None), [_Line()])
    error = selection_error("기준선", info.value)
    assert isinstance(error, ValidationError)
    assert error.message.startswith("재화중량톤수(DWT)가 없어")


def test_parameter_gaps_stay_409_in_korean(caplog):
    caplog.set_level(logging.WARNING, logger="cii_platform.services.calc_errors")
    error = selection_error("등급 경계", ValueError("No rating boundary condition matched …"))
    assert isinstance(error, ParameterError)
    assert error.message == (
        "등급 경계를 고를 수 없습니다. 해당 연도·선종의 규정 파라미터를 확인해 주세요."
    )
    assert "No rating boundary" in caplog.text
    assert selection_error("기준선", ValueError("x")).message.startswith("기준선을 고를 수")


def test_invalid_result_uses_val_008_verbatim(caplog):
    caplog.set_level(logging.WARNING, logger="cii_platform.services.calc_errors")
    assert log_calculation_failure("기능①", ValueError("Invalid CO₂ result: NaN")) == (
        CALCULATION_FAILED
    )
    assert CALCULATION_FAILED == "계산 오류: 입력값을 확인하세요."  # API_SPEC §11 VAL-008
    assert "NaN" in caplog.text
