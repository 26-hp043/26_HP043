"""규제 파라미터 조회 (API_SPEC §7.1~§7.4, #444).

**막으려는 것은 화면이 규제값을 자기 코드에 갖는 상태다.**

`#370`(정박 구간 CRUD) 때 연료 선택지를 받을 경로가 없어, **관계없는 엔드포인트의
`meta`에 연료 목록을 실어 보내는 우회**가 들어갔다. 우회는 하나로 끝나지 않는다 —
다른 화면이 같은 목록을 필요로 하면 또 생기고, 그때부터 어느 쪽이 정본인지 흐려진다.

여기서 잠그는 것은 넷이다.

1. **네 종류가 모두 조회된다** — 없으면 우회가 다시 만들어진다
2. **수치가 문자열이다** (`API_SPEC §1.7`) — JSON float 파싱으로 정밀도가 깎이면
   클라이언트 계산이 서버와 미세하게 갈리고, 그 차이는 등급 경계 근처에서만 드러난다
3. **값이 DB와 같다** — 자릿수가 아니라 값으로 대조한다
4. **모르는 선종은 빈 배열이 아니라 오류** — 오타와 「아직 없다」가 구분되어야 한다

세 번째가 중요하다. 문자열이라는 것만 보면 `"0"`을 돌려주는 구현도 통과한다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.errors import ValidationError
from cii_platform.services.parameters import (
    list_fuel_types,
    list_rating_boundaries,
    list_reference_lines,
    list_regulation_years,
)


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _scalar(session, sql: str, **params):
    return (await session.execute(text(sql), params)).scalar_one()


# ─────────────────────────────────────────────────────────────────────────────
# §7.1 규정 연도
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regulation_years_are_listed_with_the_contract_fields(session):
    rows = await list_regulation_years(session)

    assert rows, "규정 연도 seed가 비어 있다 — 계산 자체가 불가능한 상태다"
    for row in rows:
        assert set(row) == {
            "year",
            "z_factor_percent",
            "effective_from",
            "source_ref",
            "version",
        }
        assert isinstance(row["year"], int)
        assert isinstance(row["z_factor_percent"], str)
        # 날짜는 ISO 문자열이다 — `date` 객체를 그대로 두면 JSON 직렬화가 갈린다.
        assert row["effective_from"].count("-") == 2


@pytest.mark.asyncio
async def test_regulation_year_value_matches_the_database(session):
    """자릿수가 아니라 **값**으로 대조한다.

    문자열이라는 것만 보면 `"0"`을 돌려주는 구현도 통과한다.
    """
    stored = await _scalar(
        session, "SELECT z_factor_percent FROM regulation_year WHERE year = 2026"
    )

    rows = await list_regulation_years(session)
    row = next(r for r in rows if r["year"] == 2026)

    assert Decimal(row["z_factor_percent"]) == stored


@pytest.mark.asyncio
async def test_regulation_years_are_sorted_by_year(session):
    years = [row["year"] for row in await list_regulation_years(session)]
    assert years == sorted(years)


@pytest.mark.asyncio
async def test_superseded_regulation_year_is_not_listed(session):
    """개정으로 대체된 행이 현행처럼 보이면 안 된다.

    계산이 쓰는 것도 활성 행이다(`get_regulation_year`) — 조회만 다르게 두면 화면이
    계산과 다른 Z계수를 보여 준다.
    """
    await session.execute(text("UPDATE regulation_year SET is_active = false WHERE year = 2026"))

    years = [row["year"] for row in await list_regulation_years(session)]

    assert 2026 not in years


# ─────────────────────────────────────────────────────────────────────────────
# §7.2 연료 종류
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fuel_types_carry_cf_as_string(session):
    rows = await list_fuel_types(session)

    assert rows
    for row in rows:
        assert set(row) == {"code", "display_name", "cf", "unit", "source_ref", "is_active"}
        assert isinstance(row["cf"], str)
        assert Decimal(row["cf"]) > 0


@pytest.mark.asyncio
async def test_fuel_cf_matches_the_database(session):
    stored = await _scalar(session, "SELECT cf FROM fuel_type WHERE code = 'HFO'")

    rows = await list_fuel_types(session)
    hfo = next(row for row in rows if row["code"] == "HFO")

    assert Decimal(hfo["cf"]) == stored


@pytest.mark.asyncio
async def test_inactive_fuel_is_hidden_by_default(session):
    """비활성 연료가 선택지에 섞이면 **사용자는 저장 단계에서야 거부를 만난다.**"""
    await session.execute(text("UPDATE fuel_type SET is_active = false WHERE code = 'ETHANOL'"))

    codes = [row["code"] for row in await list_fuel_types(session)]

    assert "ETHANOL" not in codes


@pytest.mark.asyncio
async def test_inactive_fuel_can_be_requested_explicitly(session):
    """이력을 보려는 호출자는 명시해서 받는다."""
    await session.execute(text("UPDATE fuel_type SET is_active = false WHERE code = 'ETHANOL'"))

    codes = [row["code"] for row in await list_fuel_types(session, active=False)]
    every = [row["code"] for row in await list_fuel_types(session, active=None)]

    assert codes == ["ETHANOL"]
    assert "ETHANOL" in every and "HFO" in every


# ─────────────────────────────────────────────────────────────────────────────
# §7.3 기준선 · §7.4 등급 경계
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reference_lines_keep_the_imo_raw_notation(session):
    """`a_raw`(`14405E7`)를 빼면 **호출자가 우리 변환을 검증할 수 없다** (`PRD §3.4.3`)."""
    rows = await list_reference_lines(session, ship_type="GAS_CARRIER")

    assert rows
    for row in rows:
        assert set(row) == {
            "ship_type",
            "condition_expr",
            "capacity_rule",
            "a_raw",
            "a_decimal",
            "c",
            "source_ref",
        }
        assert isinstance(row["a_raw"], str)
        assert isinstance(row["a_decimal"], str)
    assert any("E" in row["a_raw"] for row in rows), "지수 표기 원문이 사라졌다"


@pytest.mark.asyncio
async def test_reference_lines_can_be_listed_for_every_ship_type(session):
    """선종을 지정하지 않으면 전부. 화면이 선종 목록을 만들 수 있어야 한다."""
    filtered = await list_reference_lines(session, ship_type="BULK_CARRIER")
    every = await list_reference_lines(session)

    assert len(every) > len(filtered)
    assert {row["ship_type"] for row in every} >= {"BULK_CARRIER", "CRUISE_PASSENGER"}


@pytest.mark.asyncio
async def test_rating_boundaries_carry_the_d_vector(session):
    rows = await list_rating_boundaries(session, ship_type="BULK_CARRIER")

    assert rows
    row = rows[0]
    assert set(row) == {
        "ship_type",
        "condition_expr",
        "capacity_basis",
        "d1",
        "d2",
        "d3",
        "d4",
        "source_ref",
    }
    # d1 < d2 < d3 < d4 — 경계의 정의 자체다 (`PRD §3.4.4`).
    values = [Decimal(row[key]) for key in ("d1", "d2", "d3", "d4")]
    assert values == sorted(values)


@pytest.mark.asyncio
async def test_d_vector_values_match_the_database(session):
    stored = await _scalar(
        session,
        "SELECT d1 FROM cii_rating_boundary WHERE ship_type = 'BULK_CARRIER' LIMIT 1",
    )

    rows = await list_rating_boundaries(session, ship_type="BULK_CARRIER")

    assert Decimal(rows[0]["d1"]) == stored


@pytest.mark.asyncio
async def test_unknown_ship_type_is_rejected_not_emptied(session):
    """오타와 「그 선종의 파라미터가 아직 없다」가 **둘 다 빈 배열**이면 원인을 알 수 없다."""
    with pytest.raises(ValidationError):
        await list_reference_lines(session, ship_type="BULK_CARIER")
    with pytest.raises(ValidationError):
        await list_rating_boundaries(session, ship_type="BULK_CARIER")


# ─────────────────────────────────────────────────────────────────────────────
# 우회 제거 · 라우트 등록
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_period_list_no_longer_carries_fuel_types(session):
    """`#370`의 임시 우회가 사라졌는지 본다.

    남겨 두면 같은 목록을 주는 곳이 둘이 되고, 어느 쪽이 정본인지 흐려진다. 화면은
    이제 `/parameters/fuel-types`를 직접 부른다.
    """
    from cii_platform.api.routes import not_underway

    source = not_underway.list_periods_route.__doc__ or ""
    assert "fuel_types=" not in source
    assert not hasattr(not_underway, "list_fuel_type_codes")


def test_the_four_routes_are_registered():
    """서비스가 있어도 **라우트를 잊으면 아무도 부를 수 없다.**"""
    from cii_platform.api.main import app

    paths = app.openapi()["paths"]
    for path in (
        "/api/v1/parameters/regulation-years",
        "/api/v1/parameters/fuel-types",
        "/api/v1/parameters/reference-lines",
        "/api/v1/parameters/rating-boundaries",
    ):
        assert "get" in paths[path], path
