"""``simulation_parameter`` 적재·변환 검증 (#434).

``PRD §12.4.1``이 *"분포 기본값은 ``simulation_parameter``로 관리하며 **코드
하드코딩하지 않는다**"* 를 요구하는데 그 테이블이 없었다. ``#63``이 상수로 임시
처리한 것을 정본대로 되돌린 것이 이 변경이다.

여기서 보는 것 셋.

* **마이그레이션이 PRD 표를 그대로 담았는가** — 수치가 어긋나면 시뮬레이션 전체가
  다른 가정 위에서 돈다.
* **DB 행 → 엔진 프로파일 변환이 맞는가** — 특히 ``bound_type``이 갈리는 지점.
* **일부가 빠져도 죽지 않는가** — 파라미터 한 줄 때문에 시뮬레이션이 실패하면 안 된다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.calc.annual_simulation import DEFAULT_PROFILE, profile_from_rows
from cii_platform.db.repositories import parameters as param_repo


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


@pytest.mark.asyncio
async def test_default_profile_is_seeded_by_the_migration(session):
    """``alembic upgrade head`` 하나로 들어가야 한다 (032가 세운 원칙)."""
    rows = await param_repo.load_distribution_profile(session)
    assert {row.variable for row in rows} == {"DISTANCE", "FUEL", "SPEED"}


@pytest.mark.asyncio
async def test_seeded_values_match_the_prd_table(session):
    """`PRD §12.4.1` 표 — 수치를 임의로 재작성하지 않는다 (AGENTS §3)."""
    rows = {row.variable: row for row in await param_repo.load_distribution_profile(session)}

    assert (rows["DISTANCE"].min_value, rows["DISTANCE"].max_value) == (
        Decimal("0.9700"),
        Decimal("1.0500"),
    )
    assert (rows["FUEL"].min_value, rows["FUEL"].max_value) == (
        Decimal("0.9000"),
        Decimal("1.1500"),
    )
    assert (rows["SPEED"].min_value, rows["SPEED"].max_value) == (
        Decimal("-1.0000"),
        Decimal("1.0000"),
    )


@pytest.mark.asyncio
async def test_speed_carries_the_physical_floor(session):
    """[ORACLE 삼각분포 가드] — 계획 1.5kn이면 min이 0.5kn이 되므로 하한이 필요하다."""
    rows = {row.variable: row for row in await param_repo.load_distribution_profile(session)}
    assert rows["SPEED"].floor_value == Decimal("1.0000")
    # 배수 변수에는 하한이 없다 — 있으면 의미가 다른 값이 같은 열에 섞인다.
    assert rows["DISTANCE"].floor_value is None


@pytest.mark.asyncio
async def test_bound_type_separates_factor_from_delta(session):
    """거리·연료는 배수, 속도는 덧셈이다 — 해석 방식을 행이 스스로 말해야 한다."""
    rows = {row.variable: row for row in await param_repo.load_distribution_profile(session)}
    assert rows["DISTANCE"].bound_type == "FACTOR"
    assert rows["FUEL"].bound_type == "FACTOR"
    assert rows["SPEED"].bound_type == "DELTA"


@pytest.mark.asyncio
async def test_unknown_profile_returns_empty(session):
    """없는 프로파일은 오류가 아니다 — 판단은 서비스가 한다."""
    assert await param_repo.load_distribution_profile(session, "NOPE") == []


@pytest.mark.asyncio
async def test_db_rows_convert_to_the_same_profile_as_the_constant(session):
    """**이 이슈의 핵심** — 테이블에서 읽은 값이 종전 상수와 같아야 한다.

    다르면 `#63` 병합 이후 시뮬레이션 결과가 조용히 바뀐다.
    """
    rows = await param_repo.load_distribution_profile(session)
    profile = profile_from_rows(rows)

    assert profile.distance.min_factor == DEFAULT_PROFILE.distance.min_factor
    assert profile.distance.max_factor == DEFAULT_PROFILE.distance.max_factor
    assert profile.fuel.min_factor == DEFAULT_PROFILE.fuel.min_factor
    assert profile.fuel.max_factor == DEFAULT_PROFILE.fuel.max_factor
    assert profile.speed_delta_kn == DEFAULT_PROFILE.speed_delta_kn


def test_missing_rows_fall_back_per_variable():
    """파라미터 한 줄이 비었다고 시뮬레이션 전체를 죽이지 않는다."""
    profile = profile_from_rows([])
    assert profile.distance == DEFAULT_PROFILE.distance
    assert profile.fuel == DEFAULT_PROFILE.fuel


def test_delta_rows_do_not_become_factors():
    """``DELTA``를 배수로 옮기면 `0.97` 자리에 `-1.0`이 들어가 분포가 뒤집힌다."""

    class _Row:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    rows = [
        _Row(variable="SPEED", bound_type="DELTA", min_value=-2, mode_value=0, max_value=2),
    ]
    profile = profile_from_rows(rows)

    assert profile.speed_delta_kn == 2
    # 거리·연료는 손대지 않는다.
    assert profile.distance == DEFAULT_PROFILE.distance
