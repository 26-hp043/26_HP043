"""규제연도 입력의 허용 범위가 **용도별로 한 정의**에서 오는가 (`#2190`).

범위가 자리마다 달랐다 — 요청·쿼리는 ``2000~2100``, 서비스 상수는 ``2019~2100``, 항차·정박
저장은 ``2019~2050``. 같은 2010년이 입력 위치에 따라 422·409·빈 결과·정상 처리로 갈렸다.
결정(2026-10-08)은 용도별로 이름 있는 상수 셋이다.

* 조회·계산 ``REGULATION_YEAR`` — 2019~2100
* 저장 ``STORED_REGULATION_YEAR`` — 2019~2050 (DB CHECK와 같다)
* 입항연도 ``CALL_YEAR`` — 2000~2100 (규제연도가 아니다)

여기서는 **DB 없이** 확인한다 — 요청 모델·쿼리 파라미터의 경계와 상수의 출처. 정박 구간의
명시·생략·CSV 세 경로의 HTTP 결과는 ``test_not_underway_api_db.py`` ·
``test_not_underway_import_db.py``가 본다.

케이스: `TEST_PLAN §14.2` 행 참조 — ``test_request_bounds.py``와 같은 방식
"""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from cii_platform.api.main import app
from cii_platform.api.schemas.annual_simulation import AnnualSimulationRequest
from cii_platform.api.schemas.fleet_reduction import ReductionPlanRequest
from cii_platform.api.schemas.not_underway import (
    NotUnderwayPeriodCreateRequest,
    NotUnderwayPeriodUpdateRequest,
)
from cii_platform.api.schemas.scenario_compare import ScenarioCompareRequest
from cii_platform.api.schemas.voyage import (
    PublicRecordKey,
    VoyageCreateRequest,
    VoyageUpdateRequest,
)
from cii_platform.api.schemas.voyage_cii import VoyageCiiRequest
from cii_platform.services import cii_current, cii_history
from cii_platform.validation.bounds import (
    CALL_YEAR,
    MAX_REGULATION_YEAR,
    MAX_STORED_REGULATION_YEAR,
    MIN_REGULATION_YEAR,
    REGULATION_YEAR,
    STORED_REGULATION_YEAR,
)

#: 경계값 여섯 — 이슈 완료 기준.
_BOUNDARY = (2018, 2019, 2050, 2051, 2100, 2101)


def _accepts(model: type, name: str, value: int) -> bool:
    """요청 모델의 필드 하나가 값을 받는가 — 필드의 제약만 떼어 검사한다."""
    info = model.model_fields[name]
    adapter = TypeAdapter(Annotated[int, *info.metadata])
    try:
        adapter.validate_python(value)
    except PydanticValidationError:
        return False
    return True


def test_상수_값이_결정과_같다():
    """조회·계산 2019~2100 · 저장 2019~2050 · 입항연도 2000~2100 (`#2190` 결정 1~3)."""
    assert REGULATION_YEAR == {"ge": 2019, "le": 2100}
    assert STORED_REGULATION_YEAR == {"ge": 2019, "le": 2050}
    assert CALL_YEAR == {"ge": 2000, "le": 2100}
    # 하한은 조회·계산·저장이 같고, 입항연도만 다르다 — 입항연도에 규제연도 하한을 걸지 않는다.
    assert REGULATION_YEAR["ge"] == STORED_REGULATION_YEAR["ge"] == MIN_REGULATION_YEAR
    assert CALL_YEAR["ge"] < MIN_REGULATION_YEAR


def test_서비스_상수는_같은_출처를_본다():
    """값을 두 번 적지 않는다 — ``cii_current``·``cii_history``가 ``bounds``의 같은 객체를 쓴다."""
    assert cii_current.MIN_REGULATION_YEAR is MIN_REGULATION_YEAR
    assert cii_current.MAX_REGULATION_YEAR is MAX_REGULATION_YEAR
    assert cii_history.MIN_REGULATION_YEAR is MIN_REGULATION_YEAR
    assert cii_history.MAX_REGULATION_YEAR is MAX_REGULATION_YEAR
    assert MAX_STORED_REGULATION_YEAR == 2050


@pytest.mark.parametrize(
    "model",
    [AnnualSimulationRequest, ReductionPlanRequest, ScenarioCompareRequest, VoyageCiiRequest],
)
@pytest.mark.parametrize(("value", "ok"), [(y, 2019 <= y <= 2100) for y in _BOUNDARY])
def test_계산_요청의_규제연도는_2019_2100이다(model, value, ok):
    """2018은 422다. 종전 ``ge=2000``은 2000~2018을 받아 서비스마다 409·빈 결과로 갈렸다."""
    assert _accepts(model, "regulation_year", value) is ok


@pytest.mark.parametrize(
    "model",
    [
        VoyageCreateRequest,
        VoyageUpdateRequest,
        NotUnderwayPeriodCreateRequest,
        NotUnderwayPeriodUpdateRequest,
    ],
)
@pytest.mark.parametrize(("value", "ok"), [(y, 2019 <= y <= 2050) for y in _BOUNDARY])
def test_저장하는_요청의_규제연도는_2019_2050이다(model, value, ok):
    """항차·정박 구간은 DB CHECK와 같은 폭이다. 2051~2100은 조회는 받지만 저장은 거부한다."""
    assert _accepts(model, "regulation_year", value) is ok


@pytest.mark.parametrize(
    ("value", "ok"), [(1999, False), (2000, True), (2100, True), (2101, False)]
)
def test_call_year는_2000_2100이다(value, ok):
    """입항연도는 규제연도가 아니다 — 2018 아래도 받는다(오래된 기항 기록의 「채우기」)."""
    assert _accepts(PublicRecordKey, "call_year", value) is ok
    # 규제연도 하한 바로 아래도 받는다.
    assert _accepts(PublicRecordKey, "call_year", 2018) is True


def _year_query_params() -> list[tuple[str, str, dict]]:
    """연도를 쿼리로 받는 라우트의 (경로, 파라미터 이름, 스키마) — OpenAPI에서 읽는다."""
    found = []
    for path, operations in app.openapi()["paths"].items():
        for operation in operations.values():
            for param in operation.get("parameters", []):
                if param["in"] == "query" and param["name"] in {"year", "regulation_year"}:
                    found.append((path, param["name"], param["schema"]))
    return found


def _bounds_of(schema: dict) -> tuple[int | None, int | None]:
    """``int | None`` 쿼리는 ``anyOf`` 안에 범위가 들어간다."""
    for branch in schema.get("anyOf", [schema]):
        if "minimum" in branch or "maximum" in branch:
            return branch.get("minimum"), branch.get("maximum")
    return None, None


def test_연도_쿼리는_전부_같은_범위를_건다():
    """``year``·``regulation_year`` 쿼리 — 하나라도 2000을 받으면 이 검사가 잡는다.

    ``/vessels/{id}/cii/current``·``ytd-series``는 쿼리에 범위가 없고 서비스가
    ``MIN/MAX_REGULATION_YEAR``로 같은 422를 낸다(``cii_current``) — 여기서는 범위를 건 것만 본다.
    """
    checked = 0
    for path, name, schema in _year_query_params():
        low, high = _bounds_of(schema)
        if low is None and high is None:
            assert "/vessels/{vessel_id}/cii/" in path, (path, name)
            continue
        assert (low, high) == (2019, 2100), (path, name, low, high)
        checked += 1
    # fleet 3 + not_underway + reports + exports + voyages = 7곳 — 하나가 빠지면 목록이 바뀐 것이다.
    assert checked >= 7, checked
