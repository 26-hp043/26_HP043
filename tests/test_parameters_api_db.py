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
5. **`active`의 기본은 현행과 같고, `False`만 이행 행을 연다** (`#1515`) — 개정 다음 날
   옛 판본을 볼 경로가 그것뿐인데, 그 경로가 **계산으로 새면** 대체된 값으로 등급이
   나온다. 계산 경로가 저장소 기본값(활성만)만 쓰는지 소스를 훑어 함께 잠근다

세 번째가 중요하다. 문자열이라는 것만 보면 `"0"`을 돌려주는 구현도 통과한다.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.db.repositories import parameters as param_repo
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


#: 세 조회(연도·기준선·경계)가 똑같이 싣는 판본 필드 (`API_SPEC §7.1`·`§7.3`·`§7.4` · `#1515`).
REVISION_FIELDS = ("version", "is_active", "created_at")


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
            *REVISION_FIELDS,
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
        session, 'SELECT z_factor_percent FROM regulation_year WHERE "year" = 2026'
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
    await session.execute(text('UPDATE regulation_year SET is_active = false WHERE "year" = 2026'))

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
            *REVISION_FIELDS,
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
        *REVISION_FIELDS,
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
# `active` — 기본은 현행, `False`는 이행 행까지 (#1515)
# ─────────────────────────────────────────────────────────────────────────────


async def _deactivate_one_of_each(session) -> None:
    """세 표에서 한 행씩 이행 행으로 끈다 — `conn` 트랜잭션 안이라 되돌아간다."""
    await session.execute(text('UPDATE regulation_year SET is_active = 0 WHERE "year" = 2026'))
    await session.execute(
        text(
            "UPDATE cii_reference_line SET is_active = 0 "
            "WHERE ship_type = 'BULK_CARRIER' AND condition_expr = 'DWT >= 279000'"
        )
    )
    await session.execute(
        text("UPDATE cii_rating_boundary SET is_active = 0 WHERE ship_type = 'BULK_CARRIER'")
    )


@pytest.mark.asyncio
async def test_active_default_is_the_same_as_active_true(session):
    """`?active`를 생략한 호출자는 **종전과 같은 목록**을 받는다 — 호환이 이 인자의 조건이다."""
    await _deactivate_one_of_each(session)

    assert await list_regulation_years(session) == await list_regulation_years(session, active=True)
    assert await list_reference_lines(session) == await list_reference_lines(session, active=True)
    assert await list_rating_boundaries(session) == await list_rating_boundaries(
        session, active=True
    )
    for rows in (
        await list_regulation_years(session),
        await list_reference_lines(session),
        await list_rating_boundaries(session),
    ):
        assert rows and all(row["is_active"] is True for row in rows)


@pytest.mark.asyncio
async def test_active_false_adds_the_superseded_rows_with_is_active_false(session):
    """이행 행은 **명시했을 때만** 오고, 왔을 때는 `is_active`가 그것을 말한다.

    `is_active`는 `bool`이어야 한다 — CUBRID가 `1`/`0`으로 돌려주면 화면의 `=== true`가
    현행 행을 이행 행으로 그린다.
    """
    await _deactivate_one_of_each(session)

    years = await list_regulation_years(session, active=False)
    lines = await list_reference_lines(session, ship_type="BULK_CARRIER", active=False)
    bounds = await list_rating_boundaries(session, ship_type="BULK_CARRIER", active=False)

    off_year = [r for r in years if r["year"] == 2026]
    off_line = [r for r in lines if r["condition_expr"] == "DWT >= 279000"]
    assert off_year and off_year[0]["is_active"] is False
    assert off_line and off_line[0]["is_active"] is False
    assert bounds and all(r["is_active"] is False for r in bounds)
    # 현행 행도 같은 목록에 함께 온다 — 「전부」이지 「비활성만」이 아니다 (`§7.2` 연료와 다르다)
    assert any(r["is_active"] is True for r in years)
    assert any(r["is_active"] is True for r in lines)
    # 판본·적재 시각이 문자열로 실린다
    for row in (*years, *lines, *bounds):
        assert isinstance(row["version"], str) and row["version"]
        assert isinstance(row["created_at"], str) and "T" in row["created_at"]


@pytest.mark.asyncio
async def test_active_false_is_a_superset_of_the_default(session):
    """`active=False`는 기본 목록을 **포함**한다 — 빠지는 행이 있으면 화면의 「전체」가 거짓이다."""
    await _deactivate_one_of_each(session)

    def keys(rows, *fields):
        return {tuple(row[f] for f in fields) for row in rows}

    assert keys(await list_regulation_years(session), "year", "version") <= keys(
        await list_regulation_years(session, active=False), "year", "version"
    )
    assert keys(await list_reference_lines(session), "ship_type", "condition_expr") <= keys(
        await list_reference_lines(session, active=False), "ship_type", "condition_expr"
    )


@pytest.mark.asyncio
async def test_calculation_path_repository_calls_still_see_only_active_rows(session):
    """계산이 부르는 저장소 갈래(인자 없음)는 **여전히 활성 행만** 준다.

    조회 API용 인자가 계산으로 새면 대체된 기준선으로 등급이 나온다 — 같은 항차를 다시
    계산했을 때 값이 달라지는 것이 `TECH_SPEC §5.4` 재현성 계약 위반이다.
    """
    await _deactivate_one_of_each(session)

    assert await param_repo.get_regulation_year(session, 2026) is None
    lines = await param_repo.list_reference_lines(session, "BULK_CARRIER")
    assert lines and all(row.condition_expr != "DWT >= 279000" for row in lines)
    bounds = await param_repo.list_rating_boundaries(session)
    assert bounds and all(row.ship_type != "BULK_CARRIER" for row in bounds)
    assert all(bool(row.is_active) for row in (*lines, *bounds))


def test_only_the_lookup_service_opens_the_superseded_rows():
    """`active_only=`를 넘기는 곳은 `services/parameters.py` 하나여야 한다.

    동작 검사로는 잡히지 않는다 — 계산 경로 하나가 `active_only=False`를 넘겨도 개정이
    한 번도 없었던 DB에서는 모든 결과가 같다. 그래서 소스를 훑는다
    (`test_regulation_ship_type_sync_db.py`가 `#834`에서 같은 이유로 같은 방법을 썼다).
    """
    root = Path(__file__).resolve().parents[1] / "src" / "cii_platform"
    # 저장소 자신(시그니처·docstring)과 조회 서비스만 이 이름을 가질 수 있다.
    allowed = {"db/repositories/parameters.py", "services/parameters.py"}
    offenders = [
        f"{path.relative_to(root).as_posix()}:{i}"
        for path in sorted(root.rglob("*.py"))
        if path.relative_to(root).as_posix() not in allowed
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "active_only=" in line
    ]
    assert not offenders, f"계산 경로가 이행 행을 열고 있다: {offenders} (#1515)"


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
