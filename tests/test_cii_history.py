"""연도별 CII 이력 (#355) — 창 규칙·상태 구분·API 배선 검증.

연 수치의 수학은 ``#353``(``tests/test_ytd_engine.py`` ·
``tests/test_ytd_cii_service_db.py``)이 이미 본다. 여기는 **이력 서비스의 고유
규칙**을 본다:

* 창 — 기본 최근 3년·명시 from/to·검증(2019 하한·from≤to·10년 상한)
* 상태 — ``as_of`` 연도 미만은 ``CONFIRMED``, 이상은 ``IN_PROGRESS``(YTD)
* 파라미터 없는 해·데이터 없는 해 → **오류가 아니라 행** (``data_available=false``)
* API 배선 — 실제 앱에서 dev-login으로 통과(#307 사례 대응)

실앱 테스트는 마이그레이션 027이 심은 1번 벌크선(2025 D → 2026 E 악화 서사)을
그대로 쓴다 — ``test_dashboard_seed``가 같은 데이터로 등급을 고정해 두었다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.errors import NotFoundError, ValidationError
from cii_platform.services.cii_history import (
    MAX_YEAR_SPAN,
    MIN_REGULATION_YEAR,
    REASON_NO_DATA,
    REASON_NO_REGULATION_PARAMS,
    STATUS_CONFIRMED,
    STATUS_IN_PROGRESS,
    list_cii_history,
)
from cii_platform.services.ytd_cii import compute_ytd_cii

# 018 계약 UUID — 1번 벌크선 (027이 2025·2026 항차와 위험 선박 서사를 심었다).
BULK_VESSEL_ID = "00000000-0000-4000-8000-000000000001"

# 판정 기준 시각 — 고정(시계 독립). 2026-08-15은 027 시드의 시연 기준시각이다.
AS_OF = datetime(2026, 8, 15, 0, 0, tzinfo=UTC)

HFO_CF = Decimal("3.114")


# --- 서비스 계층 픽스처 (conn 트랜잭션 — 롤백 격리) --------------------------------


@pytest_asyncio.fixture
async def session(conn):
    """``conn``의 트랜잭션에 올라타는 세션 — 테스트 종료 시 함께 롤백된다."""
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _ensure_params(session, *years: int) -> None:
    """규정 파라미터를 멱등하게 심는다 (``test_ytd_cii_service_db``와 같은 방식).

    ``scripts/seed.py``를 돌린 로컬 DB에서도 성립해야 한다 — 없을 때만 넣는다.
    """
    for year in years:
        await session.execute(
            text(
                "INSERT INTO regulation_year "
                "(year, z_factor_percent, effective_from, source_ref, version) "
                f"SELECT {year}, 11.0, '{year}-01-01', 'TEST', '1.0' "
                f"WHERE NOT EXISTS (SELECT 1 FROM regulation_year WHERE year = {year})"
            )
        )
    await session.execute(
        text(
            "INSERT INTO cii_reference_line "
            "(ship_type, condition_expr, capacity_rule, a_raw, a_decimal, c, source_ref) "
            "SELECT 'BULK_CARRIER', 'all', 'DWT', '4745', 4745, 0.622, 'TEST' "
            "WHERE NOT EXISTS "
            "(SELECT 1 FROM cii_reference_line WHERE ship_type = 'BULK_CARRIER')"
        )
    )
    await session.execute(
        text(
            "INSERT INTO cii_rating_boundary "
            "(ship_type, condition_expr, capacity_basis, d1, d2, d3, d4, source_ref) "
            "SELECT 'BULK_CARRIER', 'all', 'DWT', 0.86, 0.94, 1.06, 1.18, 'TEST' "
            "WHERE NOT EXISTS "
            "(SELECT 1 FROM cii_rating_boundary WHERE ship_type = 'BULK_CARRIER')"
        )
    )


async def _insert_vessel_with_history(session) -> str:
    """2025·2026 두 해에 COMPLETED 항차를 가진 선박을 넣고 id를 반환한다."""
    row = await session.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type, gross_tonnage, deadweight) "
            "VALUES ('7200301', 'HISTORY TEST', 'BULK_CARRIER', 30000, 50000) RETURNING id"
        )
    )
    vessel_id = str(row.scalar_one())

    for year, fuel, distance in [(2025, "400.00", "4265.00"), (2026, "620.00", "4300.00")]:
        voyage = await session.execute(
            text(
                "INSERT INTO voyage "
                "(vessel_id, status, annual_inclusion_policy, regulation_year, "
                " departure_port_name, arrival_port_name, planned_distance_nm, "
                " actual_distance_nm, planned_speed_kn, actual_avg_speed_kn) "
                f"VALUES ('{vessel_id}'::uuid, 'COMPLETED', 'INCLUDE_AS_ACTUAL', {year}, "
                f"'BUSAN', 'SINGAPORE', {distance}, {distance}, 12.0, 11.5) RETURNING id"
            )
        )
        voyage_id = voyage.scalar_one()
        await session.execute(
            text(
                "INSERT INTO voyage_fuel_use "
                "(voyage_id, fuel_type, planned_fuel_ton, actual_fuel_ton, cf_used, source) "
                f"VALUES ('{voyage_id}'::uuid, 'HFO', {fuel}, {fuel}, {HFO_CF}, 'SAMPLE')"
            )
        )
    return vessel_id


@pytest.mark.asyncio
async def test_default_window_and_statuses(session):
    """기본 창은 최근 3년 — 과거 CONFIRMED·올해 IN_PROGRESS·빈 해는 행으로."""
    await _ensure_params(session, 2024, 2025, 2026)
    vessel_id = await _insert_vessel_with_history(session)

    result = await list_cii_history(session, vessel_id=vessel_id, as_of=AS_OF)

    assert result["from"] == 2024  # to(2026) - 2
    assert result["to"] == 2026
    years = result["years"]
    assert [y["regulation_year"] for y in years] == [2024, 2025, 2026]

    by_year = {y["regulation_year"]: y for y in years}
    # 2024 — 파라미터는 있으나 데이터가 없다: 오류가 아니라 행.
    assert by_year[2024]["data_available"] is False
    assert by_year[2024]["reason"] == REASON_NO_DATA
    assert by_year[2024]["status"] == STATUS_CONFIRMED
    # 2025 — 과거 연도는 확정.
    assert by_year[2025]["status"] == STATUS_CONFIRMED
    assert by_year[2025]["data_available"] is True
    # 2026 — as_of 연도는 진행 중(YTD).
    assert by_year[2026]["status"] == STATUS_IN_PROGRESS
    assert by_year[2026]["data_available"] is True


@pytest.mark.asyncio
async def test_year_values_delegate_to_ytd_service(session):
    """연 수치는 compute_ytd_cii 위임 그대로 — 이력 서비스가 재계산하지 않는다."""
    await _ensure_params(session, 2025, 2026)
    vessel_id = await _insert_vessel_with_history(session)

    result = await list_cii_history(
        session, vessel_id=vessel_id, from_year=2025, to_year=2026, as_of=AS_OF
    )
    by_year = {y["regulation_year"]: y for y in result["years"]}

    for year in (2025, 2026):
        ytd = await compute_ytd_cii(session, vessel_id=vessel_id, regulation_year=year)
        row = by_year[year]
        # 직렬화 비교는 서비스와 같은 반올림(ROUND_HALF_UP)으로 — 기본 context의
        # HALF_EVEN과 tie에서 갈라진다.
        assert row["attained_cii"] == str(
            ytd.attained_cii.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        )
        assert row["required_cii"] == str(
            ytd.required_cii.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        )
        assert row["rating"] == ytd.rating
        assert row["voyage_count"] == ytd.voyage_count
        assert row["total_distance_nm"] == str(
            ytd.total_distance_nm.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
        assert row["total_fuel_ton"] == str(
            ytd.total_fuel_ton.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )


@pytest.mark.asyncio
async def test_year_without_regulation_params_is_a_row(session):
    """파라미터가 없는 해 — 요청 전체가 409로 죽지 않고 그 해만 NO_REGULATION_PARAMS."""
    await _ensure_params(session, 2026)
    # 로컬 DB에 이미 심어져 있을 수 있으므로 '확보 후 삭제'로 결정적으로 만든다.
    await session.execute(text("DELETE FROM regulation_year WHERE year = 2025"))
    vessel_id = await _insert_vessel_with_history(session)

    result = await list_cii_history(
        session, vessel_id=vessel_id, from_year=2025, to_year=2026, as_of=AS_OF
    )
    by_year = {y["regulation_year"]: y for y in result["years"]}

    assert by_year[2025]["data_available"] is False
    assert by_year[2025]["reason"] == REASON_NO_REGULATION_PARAMS
    assert by_year[2026]["data_available"] is True


@pytest.mark.asyncio
async def test_future_year_is_in_progress_with_no_data(session):
    """올해 이후 연도도 IN_PROGRESS로 표시된다 — 아직 집계된 것이 없을 뿐이다."""
    await _ensure_params(session, 2026, 2027)
    vessel_id = await _insert_vessel_with_history(session)

    result = await list_cii_history(
        session, vessel_id=vessel_id, from_year=2026, to_year=2027, as_of=AS_OF
    )
    by_year = {y["regulation_year"]: y for y in result["years"]}

    assert by_year[2027]["status"] == STATUS_IN_PROGRESS
    assert by_year[2027]["data_available"] is False


@pytest.mark.asyncio
async def test_window_validation(session):
    """from ≤ to · 10년 상한 · 2019 하한."""
    await _ensure_params(session, 2026)
    vessel_id = await _insert_vessel_with_history(session)

    with pytest.raises(ValidationError):
        await list_cii_history(
            session, vessel_id=vessel_id, from_year=2026, to_year=2025, as_of=AS_OF
        )
    with pytest.raises(ValidationError):
        await list_cii_history(
            session,
            vessel_id=vessel_id,
            from_year=2019,
            to_year=2019 + MAX_YEAR_SPAN,
            as_of=AS_OF,
        )
    with pytest.raises(ValidationError):
        await list_cii_history(
            session,
            vessel_id=vessel_id,
            from_year=MIN_REGULATION_YEAR - 1,
            to_year=2026,
            as_of=AS_OF,
        )


@pytest.mark.asyncio
async def test_unknown_vessel_is_404(session):
    await _ensure_params(session, 2026)
    with pytest.raises(NotFoundError):
        await list_cii_history(session, vessel_id=uuid4(), as_of=AS_OF)


# --- 실앱 배선 (실제 앱 + dev-login + 마이그레이션 시드) ---------------------------


async def _seed_params_committed() -> None:
    """실앱 엔진에 파라미터를 커밋한다 — TestClient의 세션이 보게 한다."""
    from cii_platform.db.session import get_sessionmaker

    maker = get_sessionmaker()
    async with maker() as s:
        await _ensure_params(s, 2025, 2026)
        await s.commit()


async def _drop_stub_user() -> None:
    from cii_platform.db.session import get_engine, get_sessionmaker

    maker = get_sessionmaker()
    async with maker() as s:
        await s.execute(
            text(
                "DELETE FROM user_session WHERE user_id IN "
                "(SELECT id FROM app_user WHERE google_sub = 'stub-dev-user-00000000')"
            )
        )
        await s.execute(text("DELETE FROM app_user WHERE google_sub = 'stub-dev-user-00000000'"))
        await s.commit()
    await get_engine().dispose()


async def test_cii_history_api_end_to_end(migrated_db, app_fresh_engine):
    """실제 앱에서 027 시드 벌크선의 이력 — 2025 D(확정) → 2026 E(진행 중)."""
    from cii_platform.api.main import app

    await _seed_params_committed()
    try:
        with TestClient(app, base_url="https://testserver") as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200

            resp = client.get(
                f"/api/v1/vessels/{BULK_VESSEL_ID}/cii-history",
                params={"from": 2025, "to": 2026, "as_of": "2026-08-15T00:00:00Z"},
            )
            assert resp.status_code == 200
            body = resp.json()

            assert body["data"]["vessel_id"] == BULK_VESSEL_ID
            assert body["data"]["from"] == 2025
            assert body["data"]["to"] == 2026
            years = body["data"]["years"]
            assert len(years) == 2

            by_year = {y["regulation_year"]: y for y in years}
            # test_dashboard_seed가 같은 데이터로 고정한 위험 선박 서사.
            assert by_year[2025]["rating"] == "D"
            assert by_year[2025]["status"] == STATUS_CONFIRMED
            assert by_year[2026]["rating"] == "E"
            assert by_year[2026]["status"] == STATUS_IN_PROGRESS
            # 수치는 문자열 직렬화 (API_SPEC §1.7).
            assert isinstance(by_year[2026]["attained_cii"], str)
            # meta.as_of — 재현성 계약 ⑶ (#368).
            assert body["meta"]["as_of"] == "2026-08-15T00:00:00+00:00"

            # 검증 오류 — from > to.
            bad = client.get(
                f"/api/v1/vessels/{BULK_VESSEL_ID}/cii-history",
                params={"from": 2026, "to": 2025, "as_of": "2026-08-15T00:00:00Z"},
            )
            assert bad.status_code == 422

            # 없는 선박 — 404.
            missing = client.get("/api/v1/vessels/00000000-0000-4000-8000-00000000ffff/cii-history")
            assert missing.status_code == 404
    finally:
        await _drop_stub_user()
