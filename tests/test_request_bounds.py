"""항차·시나리오·정박 요청이 **DB가 담을 수 없는 값**을 API에서 걸러내는가 (``#1086``).

`#860`이 선박 제원에서 고친 것을 나머지 세 스키마와 계산 단계로 넓힌다. **막으려는 것은
이상한 값이 저장되는 것이 아니라 500이다** — DB의 ``NUMERIC``·``CHECK``가 이미 막고 있었고,
사용자가 보는 것은 원인 설명 없는 500이었다.

## 두 층을 대조한다

경계값을 스키마에 적어 두면 DB 컬럼 정밀도가 바뀔 때 한쪽만 고쳐진다. ORM 모델의
``Numeric(precision, scale)``에서 기대 범위를 계산해 스키마와 맞춰 본다(`test_vessel_spec_bounds.py`
와 같은 방식). ``regulation_year``는 CHECK(``BETWEEN 2019 AND 2050``)와 대조한다.

케이스: `TEST_PLAN §14.2` 행 참조 — `#860`과 같은 방식
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError as PydanticValidationError

from cii_platform.api.schemas.not_underway import (
    NotUnderwayFuelUseCreateRequest,
    NotUnderwayPeriodCreateRequest,
    NotUnderwayPeriodUpdateRequest,
)
from cii_platform.api.schemas.scenario_compare import ScenarioCompareRequest
from cii_platform.api.schemas.voyage import (
    VoyageActualsRequest,
    VoyageCreateRequest,
    VoyageFuelActualRequest,
    VoyageFuelUseCreateRequest,
    VoyageUpdateRequest,
)
from cii_platform.db.models.not_underway_fuel_use import NotUnderwayFuelUse
from cii_platform.db.models.not_underway_period import NotUnderwayPeriod
from cii_platform.db.models.voyage import Voyage
from cii_platform.db.models.voyage_fuel_use import VoyageFuelUse
from cii_platform.db.models.voyage_scenario import VoyageScenario
from cii_platform.errors import ValidationError
from cii_platform.services.scenario_compare import _db_rows


def _column_bounds(model: type, name: str) -> tuple[Decimal, Decimal]:
    column_type = model.__table__.c[name].type
    smallest = Decimal(1).scaleb(-column_type.scale)
    largest = Decimal(10) ** (column_type.precision - column_type.scale) - smallest
    return smallest, largest


def _schema_bounds(model: type, name: str) -> tuple[Decimal, Decimal]:
    metadata = model.model_fields[name].metadata
    ge = next(m.ge for m in metadata if getattr(m, "ge", None) is not None)
    le = next(m.le for m in metadata if getattr(m, "le", None) is not None)
    return Decimal(ge), Decimal(le)


#: (스키마, 필드, ORM 모델, 컬럼, 하한이 저장 형식에서 오는가)
_PAIRS = [
    (VoyageCreateRequest, "planned_distance_nm", Voyage, "planned_distance_nm", True),
    (VoyageUpdateRequest, "planned_distance_nm", Voyage, "planned_distance_nm", True),
    (VoyageActualsRequest, "actual_distance_nm", Voyage, "actual_distance_nm", True),
    # 속력은 하한이 도메인(VAL-009 `>= 1.0`)이고 상한만 저장 형식이다
    (VoyageCreateRequest, "planned_speed_kn", Voyage, "planned_speed_kn", False),
    (VoyageUpdateRequest, "planned_speed_kn", Voyage, "planned_speed_kn", False),
    (VoyageActualsRequest, "actual_avg_speed_kn", Voyage, "actual_avg_speed_kn", False),
    (VoyageFuelUseCreateRequest, "planned_fuel_ton", VoyageFuelUse, "planned_fuel_ton", True),
    (VoyageFuelActualRequest, "actual_fuel_ton", VoyageFuelUse, "actual_fuel_ton", True),
    (ScenarioCompareRequest, "direct_distance_nm", VoyageScenario, "distance_nm", True),
    (ScenarioCompareRequest, "detour_distance_nm", VoyageScenario, "distance_nm", True),
    (ScenarioCompareRequest, "current_speed_kn", VoyageScenario, "speed_kn", False),
    (ScenarioCompareRequest, "slow_speed_kn", VoyageScenario, "speed_kn", False),
    (NotUnderwayFuelUseCreateRequest, "fuel_ton", NotUnderwayFuelUse, "fuel_ton", True),
    # 정박 이동 거리는 0이 정상값(접안·묘박)이라 하한이 0이다
    (NotUnderwayPeriodCreateRequest, "distance_nm", NotUnderwayPeriod, "distance_nm", False),
    (NotUnderwayPeriodUpdateRequest, "distance_nm", NotUnderwayPeriod, "distance_nm", False),
]


@pytest.mark.parametrize(("schema", "field", "orm", "column", "floor_is_storage"), _PAIRS)
def test_스키마_경계가_DB_컬럼_정밀도와_같다(schema, field, orm, column, floor_is_storage):
    """한쪽만 고치면 여기서 걸린다 — 정밀도가 바뀌면 경계도 따라 바뀌어야 한다."""
    smallest, largest = _column_bounds(orm, column)
    ge, le = _schema_bounds(schema, field)
    assert le == largest, f"{schema.__name__}.{field} 상한이 {orm.__tablename__}.{column}과 다르다"
    if floor_is_storage:
        assert ge == smallest
    else:
        assert ge in {Decimal("1.0"), Decimal(0)}, f"{schema.__name__}.{field} 하한은 도메인 값이다"


@pytest.mark.parametrize("schema", [VoyageCreateRequest, VoyageUpdateRequest])
def test_regulation_year_경계가_DB_CHECK와_같다(schema):
    """`voyage.regulation_year BETWEEN 2019 AND 2050`(마이그레이션 005). 2010·2080은 422다 (①)."""
    assert _schema_bounds(schema, "regulation_year") == (Decimal(2019), Decimal(2050))
    check = next(
        c
        for c in Voyage.__table__.constraints
        if getattr(c, "name", "") == "chk_regulation_year_range"
    )
    assert "2019" in str(check.sqltext) and "2050" in str(check.sqltext)


def _voyage(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "departure_port_name": "Busan",
        "arrival_port_name": "Tokyo",
        "planned_distance_nm": "1000",
        "planned_speed_kn": "13.5",
        "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": "80"}],
    }
    body.update(overrides)
    return body


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("regulation_year", 2010),  # ① CHECK 밖
        ("regulation_year", 2080),
        ("planned_distance_nm", "0.001"),  # ② 0.00으로 반올림 → chk_distance_positive
        ("planned_distance_nm", "10000000000"),  # NUMERIC(12,2) 초과
        ("planned_speed_kn", "10000"),  # ③ NUMERIC(6,2) 초과
    ],
)
def test_저장할_수_없는_항차_값은_스키마가_거부한다(field, value):
    """종전에는 이 다섯이 전부 IntegrityError 500이었다."""
    with pytest.raises(PydanticValidationError):
        VoyageCreateRequest.model_validate(_voyage(**{field: value}))


def test_저장할_수_있는_경계값은_그대로_받는다():
    ok = VoyageCreateRequest.model_validate(
        _voyage(planned_distance_nm="0.01", planned_speed_kn="9999.99", regulation_year=2050)
    )
    assert ok.planned_distance_nm == Decimal("0.01")
    assert VoyageCreateRequest.model_validate(_voyage(regulation_year=2019)).regulation_year == 2019


def test_정박_연료_0은_스키마가_거부한다():
    """`chk_not_underway_fuel_positive (fuel_ton > 0)` — 0.001도 0.00으로 반올림돼 같은 제약."""
    for value in ("0", "0.001"):
        with pytest.raises(PydanticValidationError):
            NotUnderwayFuelUseCreateRequest.model_validate(
                {"consumer_type": "AUX_ENGINE", "fuel_type": "MGO", "fuel_ton": value}
            )


def test_소요시간이_0_01시간_미만이면_계산_단계에서_422다():
    """④ 1 nm · 250 kn → 0.004 h → 스케일 0.01로 0.00 → 종전에는 duration CHECK 위반 500."""
    tiny = SimpleNamespace(
        plan=SimpleNamespace(distance_nm=Decimal("1"), speed_kn=Decimal("250")),
        duration_hours=Decimal("1") / Decimal("250"),
        fuel_ton=Decimal("0.05"),
    )
    with pytest.raises(ValidationError) as caught:
        _db_rows([tiny])
    assert caught.value.code == "VALIDATION_ERROR"
    assert caught.value.details and caught.value.details[0]["field"] == "direct_distance_nm"

    fine = SimpleNamespace(
        plan=SimpleNamespace(distance_nm=Decimal("100"), speed_kn=Decimal("10")),
        duration_hours=Decimal("10"),
        fuel_ton=Decimal("5"),
    )
    assert _db_rows([fine])[0]["duration_hours"] == Decimal("10.00")
