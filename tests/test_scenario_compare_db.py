"""기능② DB 실동작 테스트 (#57) — 시나리오 3행·SCENARIO 이력·감사 저장.

계약 테스트(``test_scenario_compare_api.py``)가 저장소를 대역으로 쓰는 반면,
여기는 **실제 INSERT·제약·트리거**를 검증한다 — ``voyage_scenario`` 3행,
``calculation_run`` 1행(``SCENARIO``), ``audit_log`` 1건.

파라미터 시드 상태: **더 이상 여기서 심지 않는다 (#127).** 017이 ``fuel_type`` 8행을,
032가 ``regulation_year``·``cii_reference_line``·``cii_rating_boundary`` 42행을 넣으므로
``upgrade head``만으로 필요한 규제 파라미터가 전부 갖춰진다.

손으로 심던 값과 seed 값이 같은 결과를 낸다 — 이 테스트의 선박은
``BULK_CARRIER`` · DWT 50,000이고, seed의 ``DWT < 279000`` 행이 선택되어
``capacity_rule=DWT`` · ``a=4745`` · ``c=0.622``가 적용된다(전에 직접 넣던 값과 동일).

케이스: IT-WX-004 (`TEST_PLAN §3.6` · #904)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest_asyncio
from conftest import insert_returning_id, same_uuid, uuid_canon
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text

from cii_platform.api.main import app
from cii_platform.db.types import JSONText, UuidText

_BASE = "https://testserver"

IMO = "7200577"

PAYLOAD: dict[str, Any] = {
    "regulation_year": 2026,
    "current_speed_kn": 14.0,
    "fuel_type": "HFO",
    "base_daily_foc_ton": 35.0,
    "direct_distance_nm": 11000.0,
}


async def _insert_vessel(session) -> str:
    return await insert_returning_id(
        session,
        "INSERT INTO vessel (imo_number, name, ship_type, gross_tonnage, deadweight, "
        "reference_speed_kn) "
        "VALUES (:imo, 'SCENARIO DB TEST', 'BULK_CARRIER', 30000, 50000, 14.0) "
        "RETURNING id",
        {"imo": IMO},
    )


async def _cleanup(session, vessel_id: str) -> None:
    # voyage_scenario는 soft delete 대상이지만 테스트 정리는 물리 삭제로 한다.
    await session.execute(
        text("DELETE FROM voyage_scenario WHERE vessel_id = :vid"), {"vid": vessel_id}
    )
    # calculation_run은 immutable 트리거가 DELETE를 막는다 — 잠시 끄고 즉시 복구
    # (test_voyage_delete_db.py와 같은 패턴). audit_log는 _delete_stub_user가
    # 전량 삭제하므로 여기서 건드리지 않는다.
    await session.execute(text("ALTER TRIGGER trg_calcrun_no_delete STATUS INACTIVE"))
    await session.execute(
        text("DELETE FROM calculation_run WHERE vessel_id = :vid"), {"vid": vessel_id}
    )
    await session.execute(text("ALTER TRIGGER trg_calcrun_no_delete STATUS ACTIVE"))
    await session.execute(text("DELETE FROM vessel WHERE id = :vid"), {"vid": vessel_id})
    await session.execute(text("DELETE FROM cii_rating_boundary WHERE source_ref = 'TEST'"))
    await session.execute(text("DELETE FROM cii_reference_line WHERE source_ref = 'TEST'"))
    await session.execute(text("DELETE FROM regulation_year WHERE source_ref = 'TEST'"))
    await session.commit()


async def _delete_stub_user() -> None:
    from cii_platform.db.session import get_engine, get_sessionmaker

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as s:
        await s.execute(text("DELETE FROM audit_log"))
        await s.execute(
            text(
                "DELETE FROM user_session WHERE user_id IN "
                "(SELECT id FROM app_user WHERE email = 'dev@localhost')"
            )
        )
        await s.execute(text("DELETE FROM app_user WHERE email = 'dev@localhost'"))
        await s.commit()
    await get_engine().dispose()


async def test_compare_persists_three_scenarios_and_run(migrated_db, app_fresh_engine):
    """응답 200 + voyage_scenario 3행 + calculation_run(SCENARIO) 1행 + 감사 1건."""
    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = None
    try:
        async with sessionmaker() as s:
            vessel_id = await _insert_vessel(s)
            await s.commit()

        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            # dev-login이 csrf 쿠키(httponly=false)를 심는다 — 헤더로 올려 보낸다.
            csrf = client.cookies.get("csrf")
            resp = client.post(
                "/api/v1/scenarios/compare",
                json={"vessel_id": vessel_id, **PAYLOAD},
                headers={"X-CSRF-Token": csrf or ""},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        types = [s["scenario_type"] for s in body["data"]["scenarios"]]
        assert types == ["DIRECT", "DETOUR", "SLOW_STEAMING"]

        # 응답 scenario_id가 실제 저장된 행의 PK와 일치하는지.
        scenario_ids = {s["scenario_id"] for s in body["data"]["scenarios"]}

        async with sessionmaker() as s:
            rows = (
                (
                    await s.execute(
                        text(
                            "SELECT id, scenario_type, cii_value, estimated_rating, "
                            "risk_level, voyage_id, fuel_ton, duration_hours "
                            "FROM voyage_scenario WHERE vessel_id = :vid"
                        ),
                        {"vid": vessel_id},
                    )
                )
                .mappings()
                .all()
            )
            assert len(rows) == 3
            # 응답의 `scenario_id`는 대시 36자, 생 SQL이 읽은 PK는 저장 형식(hex 32자)
            # 이다. 집합을 통째로 견주므로 DB 쪽을 계약 형식으로 올린다 (`#1058`).
            assert {uuid_canon(r["id"]) for r in rows} == scenario_ids
            # created_at의 server_default now()는 트랜잭션 시각이라 3행이 같다 —
            # 순서 보장이 없으므로 type을 키로 잡아 비교한다.
            rows_by_type = {r["scenario_type"]: r for r in rows}
            assert set(rows_by_type) == {"DIRECT", "DETOUR", "SLOW_STEAMING"}
            assert all(r["voyage_id"] is None for r in rows)  # 독립 시나리오
            # 계약 테스트 앵커와 같은 값 — 계약(DB 없음) ↔ DB 양쪽이 같은 확정값.
            # fuel_ton은 DB scale이 4(1145.8333), 응답 직렬화는 2자리(1145.83)다.
            direct = rows_by_type["DIRECT"]
            assert round(float(direct["fuel_ton"]), 2) == 1145.83
            assert float(direct["duration_hours"]) == 785.71

            run = (
                await s.execute(
                    text(
                        "SELECT calculation_type, result_json FROM calculation_run "
                        "WHERE vessel_id = :vid"
                        # 생 SQL에는 컬럼 타입이 붙지 않아 `JSONText`가 돌지 않는다 —
                        # 문자열이 와서 `result_json["scenarios"]`가 선다 (`#1058`).
                    ).columns(result_json=JSONText()),
                    {"vid": vessel_id},
                )
            ).fetchone()
            assert run is not None
            assert run.calculation_type == "SCENARIO"
            assert len(run.result_json["scenarios"]) == 3

            audit = (
                await s.execute(
                    text(
                        "SELECT details_json FROM audit_log "
                        "WHERE \"action\" = 'CALCULATION_RUN' AND entity_id = :rid"
                        # `entity_id`는 `CHAR(32)`인데 API는 대시 36자를 준다. 타입을
                        # 붙이지 않으면 **오류 없이 0건**이 온다 (`#1058`).
                        # `details_json`도 붙이지 않으면 문자열로 온다.
                    )
                    .bindparams(bindparam("rid", type_=UuidText()))
                    .columns(details_json=JSONText()),
                    {"rid": body["calculation_run_id"]},
                )
            ).fetchone()
            assert audit is not None
            assert audit.details_json["calculation_type"] == "SCENARIO"
    finally:
        await _delete_stub_user()
        if vessel_id:
            async with sessionmaker() as s:
                await _cleanup(s, vessel_id)


async def test_compare_idempotent_rows_on_repeat(migrated_db, app_fresh_engine):
    """같은 요청을 반복해도 계산 이력·시나리오는 계속 쌓인다(멱등성 없음, #55 규칙)."""
    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = None
    try:
        async with sessionmaker() as s:
            vessel_id = await _insert_vessel(s)
            await s.commit()

        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            csrf = client.cookies.get("csrf")
            headers = {"X-CSRF-Token": csrf or ""}
            for _ in range(2):
                resp = client.post(
                    "/api/v1/scenarios/compare",
                    json={"vessel_id": vessel_id, **PAYLOAD},
                    headers=headers,
                )
                assert resp.status_code == 200, resp.text

        async with sessionmaker() as s:
            count = (
                await s.execute(
                    text("SELECT count(*) FROM voyage_scenario WHERE vessel_id = :vid"),
                    {"vid": vessel_id},
                )
            ).scalar_one()
            assert count == 6  # 요청 2회 × 시나리오 3행 — 계산은 append-only다.
    finally:
        await _delete_stub_user()
        if vessel_id:
            async with sessionmaker() as s:
                await _cleanup(s, vessel_id)


# ─────────────────────────────────────────────────────────────────────────────
# IT-WX-004 · 보정한 계산이 그 근거를 남긴다 (#904)
# ─────────────────────────────────────────────────────────────────────────────
#
# ``TECH_SPEC §5.4`` 4항 — 「이 계산은 어떤 기상 데이터로 실행되었나」를 사후에 답할 수
# 있어야 한다. 종전에는 ``calculation_run.weather_snapshot_id``가 삽입 경로에서 ``None``
# 으로 고정돼, **같은 요청의 시나리오 3행에는 스냅샷이 붙는데 계산 이력만 비었다**
# (라이브 DB 실측: 보정 모델을 쓴 시나리오 행 12개가 스냅샷을 가리키는데 SCENARIO 계산
# 이력 252건은 전부 NULL).
#
# 외부 조회는 **실패하게** 두고 캐시를 심는다 — 실제 시각에 맞는 응답을 지어낼 필요가
# 없고, 캐시 경로도 스냅샷을 쓰는 정상 경로다(``PRD §11.6`` 「6시간 이내 캐시」).

_WX_LAT, _WX_LON = Decimal("-12.34"), Decimal("56.78")


def _dead_provider():
    import httpx

    from cii_platform.weather.open_meteo import OpenMeteoProvider

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    return OpenMeteoProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


async def _seed_fresh_snapshot(session) -> UUID:
    from cii_platform.db.repositories import weather as weather_repo
    from cii_platform.services.weather import round_to_grid

    snapshot = await weather_repo.insert_snapshot(
        session,
        lat=_WX_LAT,
        lon=_WX_LON,
        lat_rounded=round_to_grid(float(_WX_LAT)),
        lon_rounded=round_to_grid(float(_WX_LON)),
        fetched_at=datetime.now(UTC) - timedelta(hours=1),
        wave_height_m=Decimal("3.0"),
        wave_direction_deg=Decimal("0"),
        wave_period_s=Decimal("7"),
        wind_speed_ms=Decimal("8.0"),
        wind_direction_deg=Decimal("90"),
        source="sample",
    )
    return snapshot.id


async def _compare(session, *, weather_model: str | None, with_coordinates: bool = True):
    from cii_platform.db.demo_seed import VESSEL_ID_BULK
    from cii_platform.services.scenario_compare import ScenarioCompareInput, compare_scenarios

    coordinates = {"current_lat": _WX_LAT, "current_lon": _WX_LON} if with_coordinates else {}
    payload = ScenarioCompareInput(
        vessel_id=UUID(VESSEL_ID_BULK),
        regulation_year=2026,
        current_speed_kn=Decimal("12.0"),
        fuel_type="HFO",
        base_daily_foc_ton=Decimal("23.04"),
        direct_distance_nm=Decimal("5000"),
        weather_model=weather_model,
        **coordinates,
    )
    return await compare_scenarios(session, payload, weather_provider=_dead_provider())


async def _recorded(session, run_id: str):
    run = (
        await session.execute(
            text("SELECT weather_snapshot_id, result_json FROM calculation_run WHERE id = :id")
            .bindparams(
                # 응답의 `calculation_run_id`는 대시 36자, 저장 형식은 hex 32자다. 타입을
                # 붙이지 않으면 **오류가 아니라 0행**이 와서 `NoResultFound`가 난다 (`#1058`).
                bindparam("id", type_=UuidText()),
            )
            # 생 SQL에는 컬럼 타입이 붙지 않아 `JSONText`의 result processor가 돌지 않는다 —
            # 붙이지 않으면 **문자열**이 와서 `run.result_json["scenarios"]`가
            # `TypeError: string indices must be integers`로 선다 (`#1058`).
            .columns(result_json=JSONText()),
            {"id": run_id},
        )
    ).one()
    scenario_ids = [s["scenario_id"] for s in run.result_json["scenarios"]]
    scenario_snapshots = (
        (
            await session.execute(
                # `= ANY(:ids)`는 **PostgreSQL 배열**이다 — CUBRID에 없고 pycubrid도 목록을
                # 한 파라미터로 묶어 보낸다. `expanding=True`가 실행 시점에 `IN (?, ?, …)`로
                # 펼치고 `UuidText`가 원소마다 저장 형식을 맞춘다
                # (`test_benchmarks`·`test_roles_db`와 같은 방식 · `#1058`).
                text("SELECT weather_snapshot_id FROM voyage_scenario WHERE id IN :ids").bindparams(
                    bindparam("ids", expanding=True, type_=UuidText()),
                ),
                {"ids": [UUID(i) for i in scenario_ids]},
            )
        )
        .scalars()
        .all()
    )
    factors = {s["weather_factor"] for s in run.result_json["scenarios"]}
    return run.weather_snapshot_id, set(scenario_snapshots), factors


@pytest_asyncio.fixture
async def wx_session(conn):
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def test_stored_block_coefficient_out_of_range_warns_in_scenarios(wx_session):
    """#966 — 선박에 저장된 CB가 범위 밖이면 시나리오 비교가 `CB_OUT_OF_RANGE`를 낸다.

    이 경로가 유일한 생산 경로다 — ``_resolve_weather``가 ``vessel.block_coefficient``를
    넘기는지를 잠근다. 컬럼이 생기기 전에는 CB가 **항상** None이라 이 경고가 나올 수
    없었다(범위 밖 실측값 자체가 없었다).
    """
    from cii_platform.db.demo_seed import VESSEL_ID_BULK

    await _seed_fresh_snapshot(wx_session)
    # 데모 벌크선의 CB를 하한(0.75) 밖으로 — 컬럼이 있으니 실측값이 계산에 들어간다.
    await wx_session.execute(
        text("UPDATE vessel SET block_coefficient = 0.700 WHERE id = :id").bindparams(
            bindparam("id", type_=UuidText())
        ),
        {"id": UUID(VESSEL_ID_BULK)},
    )

    result = await _compare(wx_session, weather_model="TOWNSIN_KWON_ALPHA")
    assert "CB_OUT_OF_RANGE" in result["warnings"], result["warnings"]
    assert "CB_ESTIMATED" not in result["warnings"], "실측값인데 추정 경고가 나왔다"
    # 원복은 rollback(conn fixture)이 한다 — 데모 선박은 다음 검사에 영향 없다.


async def test_corrected_comparison_records_the_snapshot_it_used(wx_session):
    """IT-WX-004 — 보정한 계산은 계산 이력이 **그 스냅샷**을 가리키고, 인자가 결과에 남는다."""
    snapshot_id = await _seed_fresh_snapshot(wx_session)

    result = await _compare(wx_session, weather_model="SIMPLE_RULE")

    run_snapshot, scenario_snapshots, factors = await _recorded(
        wx_session, result["calculation_run_id"]
    )
    # `weather_snapshot_id`는 생 SQL이 읽은 저장 형식이고 픽스처는 `UUID`다 (`#1058`).
    assert same_uuid(run_snapshot, snapshot_id)
    # 시나리오 3행과 계산 이력이 **같은 스냅샷**을 가리킨다 — 한 요청이 한 번 조회한다.
    # 집합 비교라 짝지을 수 없어 양쪽을 정규화한다.
    assert {uuid_canon(v) for v in scenario_snapshots} == {uuid_canon(snapshot_id)}
    # 보정 인자는 결과에 남는다. 세 계획이 같은 기상을 쓰므로 값은 하나다.
    assert len(factors) == 1
    (factor,) = factors
    assert factor > 1.0
    assert result["data"]["scenarios"][0]["weather_model_used"] == "SIMPLE_RULE"


async def test_uncorrected_comparison_points_at_no_snapshot(wx_session):
    """IT-WX-004 — ``NONE``은 스냅샷 없이 계산하는 정상 경로다(``TECH_SPEC §5.4`` 5항).

    캐시가 있어도 **조회하지 않았으니** 가리키지 않는다 — 가리키면 쓰지 않은 기상을
    근거로 적게 된다.
    """
    await _seed_fresh_snapshot(wx_session)

    result = await _compare(wx_session, weather_model="NONE")

    run_snapshot, scenario_snapshots, factors = await _recorded(
        wx_session, result["calculation_run_id"]
    )
    assert run_snapshot is None
    assert scenario_snapshots == {None}
    assert factors == {1.0}


async def test_fallback_comparison_points_at_no_snapshot(wx_session):
    """IT-WX-004 — 좌표가 없어 보정을 못 한 계산도 스냅샷을 가리키지 않는다.

    요청은 ``SIMPLE_RULE``이었으나 적용된 것은 ``NONE``이다 — 경고가 그 사실을 말하고,
    계산 이력은 **실제로 쓴 것**(없음)을 적는다.
    """
    await _seed_fresh_snapshot(wx_session)

    result = await _compare(wx_session, weather_model="SIMPLE_RULE", with_coordinates=False)

    run_snapshot, _, factors = await _recorded(wx_session, result["calculation_run_id"])
    assert run_snapshot is None
    assert factors == {1.0}
    assert "WEATHER_NONE_FALLBACK" in result["warnings"]
