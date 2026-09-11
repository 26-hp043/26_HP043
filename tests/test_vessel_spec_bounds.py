"""선박 제원이 **DB가 담을 수 없는 값**을 API에서 걸러내는가 (``#860``).

**막으려는 것은 이상한 값이 저장되는 것이 아니라, 500이다.**

종전 스키마는 ``gt=0``만 봤고 DB는 고정 정밀도(``NUMERIC(12,2)`` 등)였다. API를 통과한
값이 저장 단계에서 죽었다.

.. code-block:: text

    deadweight = 1e-7   →  0.00으로 반올림  →  chk_dwt_positive 위반  →  500
    deadweight = 1e10   →  정밀도 초과                                →  500

이슈 본문은 「1e-7 DWT가 저장된다」로 적었으나 실측하면 **저장되지 않는다** — DB의
CHECK 제약과 정밀도가 이미 막고 있었다. 사용자가 보는 것은 저장된 이상값이 아니라
**원인 설명 없는 500**이었다.

## 두 층을 대조한다

경계값을 API 스키마에 적어 두면 **DB 컬럼 정밀도가 바뀔 때 한쪽만 고쳐진다.** 그래서
ORM 모델의 ``Numeric(precision, scale)``에서 기대 범위를 계산해 스키마와 맞춰 본다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from cii_platform.api.schemas.vessel import VesselCreateRequest, VesselUpdateRequest
from cii_platform.db.models.vessel import Vessel

#: 스키마 필드 → ORM 컬럼. 둘이 같은 이름이다.
_FIELDS = ("deadweight", "gross_tonnage", "reference_speed_kn", "reference_daily_foc_ton")


def _column_bounds(name: str) -> tuple[Decimal, Decimal]:
    column_type = Vessel.__table__.c[name].type
    smallest = Decimal(1).scaleb(-column_type.scale)
    largest = Decimal(10) ** (column_type.precision - column_type.scale) - smallest
    return smallest, largest


def _schema_bounds(model: type, name: str) -> tuple[Decimal, Decimal]:
    metadata = model.model_fields[name].metadata
    ge = next(m.ge for m in metadata if getattr(m, "ge", None) is not None)
    le = next(m.le for m in metadata if getattr(m, "le", None) is not None)
    return ge, le


@pytest.mark.parametrize("model", [VesselCreateRequest, VesselUpdateRequest])
@pytest.mark.parametrize("name", _FIELDS)
def test_스키마_경계가_DB_컬럼_정밀도와_같다(model, name):
    """한쪽만 고치면 여기서 걸린다 — 정밀도가 바뀌면 경계도 따라 바뀌어야 한다."""
    assert _schema_bounds(model, name) == _column_bounds(name)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("deadweight", "0.0000001"),  # 0.00으로 반올림돼 CHECK 위반이 되던 값
        ("deadweight", "10000000000"),  # 정밀도 초과로 500이 되던 값
        ("gross_tonnage", "0.004"),
        ("reference_speed_kn", "10000"),  # NUMERIC(6,2) 초과
        ("reference_daily_foc_ton", "1000000"),  # NUMERIC(8,2) 초과
    ],
)
def test_저장할_수_없는_값은_스키마가_거부한다(name, value):
    base = {"imo_number": "9123456", "name": "BOUNDS", "ship_type": "BULK_CARRIER"}
    with pytest.raises(ValidationError):
        VesselCreateRequest(**base, **{name: value})


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("deadweight", "0.01"),  # 저장 가능한 가장 작은 양수
        ("deadweight", "9999999999.99"),  # 저장 가능한 가장 큰 값
        ("deadweight", "50000.125"),  # 소수 셋째 자리 — 막지 않는다. DB가 반올림한다
        ("reference_speed_kn", "12.5"),
    ],
)
def test_저장할_수_있는_값은_그대로_받는다(name, value):
    """⚠️ **소수 셋째 자리를 막지 않는다** — ``decimal_places``로 거부하면 멀쩡한 입력까지
    422가 된다. 종전처럼 받아서 DB가 반올림하게 둔다."""
    base = {"imo_number": "9123456", "name": "BOUNDS", "ship_type": "BULK_CARRIER"}
    assert getattr(VesselCreateRequest(**base, **{name: value}), name) == Decimal(value)
