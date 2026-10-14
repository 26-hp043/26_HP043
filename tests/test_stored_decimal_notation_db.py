"""저장 수치 입력의 **표기·자릿수**가 500이 되지 않는다 (#2502).

## 무엇이 깨졌었나

드라이버가 파라미터를 SQL 리터럴로 인라인하므로 ``"1E+1"``·``"0.0000001"``·40자리 값이
``CAST(... AS NUMERIC(p,s))`` 문법 오류·``Data overflow``(500)가 됐다. 스키마의 ``ge``·``le``는
값 범위만 보고 표기를 보지 않는다. 지금은 ``validation.bounds.stored(scale)``이 컬럼 scale의
고정 소수 표기로 맞춘다 — 소수 아래 자릿수는 거절하지 않고 **반올림**한다(종전 정책 유지).

첫 묶음(DB 없음)은 정규화 규칙을, 둘째 묶음(실제 HTTP · DB)은 저장 경로 전부가 500이 아님을 본다.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text

from cii_platform.api.main import app
from cii_platform.api.schemas.vessel import VesselPositionUpdateRequest, VesselUpdateRequest
from cii_platform.api.schemas.voyage import VoyageFuelActualRequest, VoyageUpdateRequest

_BASE = "https://testserver"
_LONG = "1." + "1" * 40  # 유효숫자 41자리


# --- DB 없는 검사: 정규화 규칙 --------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected", "text_form"),
    [
        ("1.5E+1", "15.00", "15.00"),  # 지금 200이던 입력은 값 그대로
        ("5E+4", "50000.00", "50000.00"),
        ("1E+1", "10.00", "10.00"),
        ("50000.125", "50000.13", "50000.13"),  # 반올림(0에서 먼 쪽) — 종전 정책
        ("0.01", "0.01", "0.01"),
    ],
)
def test_지수_표기는_고정_소수_표기로_정규화된다(raw, expected, text_form):
    got = VesselUpdateRequest(deadweight=raw).deadweight
    assert got == Decimal(expected)
    assert str(got) == text_form  # 지수 표기가 남지 않는다 — 드라이버가 리터럴로 인라인한다


def test_위경도는_scale_6으로_맞추고_음의_0을_남기지_않는다():
    req = VesselPositionUpdateRequest(
        underway_state="UNDER_WAY", current_lat="-0.0000001", current_lon="1E+1"
    )
    assert str(req.current_lat) == "0.000000"
    assert str(req.current_lon) == "10.000000"
    assert (
        str(VesselPositionUpdateRequest(underway_state="UNDER_WAY", current_lat=_LONG).current_lat)
        == "1.111111"
    )


@pytest.mark.parametrize("value", ["1E-7", "0.0000001", "1E+10", "1" + "0" * 40])
def test_범위_밖은_표기와_무관하게_거절된다(value):
    with pytest.raises(ValidationError):
        VesselUpdateRequest(deadweight=value)


def test_항차_연료는_scale_4_거리는_scale_2():
    assert (
        str(
            VoyageFuelActualRequest(
                fuel_type="HFO", actual_fuel_ton="1E+1", source="USER_INPUT"
            ).actual_fuel_ton
        )
        == "10.0000"
    )
    assert str(VoyageUpdateRequest(planned_distance_nm="1E+3").planned_distance_nm) == "1000.00"


def test_None은_그대로_통과한다():
    assert VesselUpdateRequest(deadweight=None).deadweight is None


# --- 실제 HTTP · DB ---------------------------------------------------------------------------


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf"]}


async def _seed() -> tuple[str, str, str]:
    from cii_platform.db.session import get_sessionmaker

    vid, voy, voy2 = uuid4(), uuid4(), uuid4()
    async with get_sessionmaker()() as s:
        await s.execute(
            text(
                "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
                "default_fuel_type) VALUES (:id, :imo, 'NOTATION TEST', 'BULK_CARRIER', "
                "50000, 'HFO')"
            ),
            {"id": vid, "imo": f"9{vid.int % 1000000:06d}"},
        )
        await s.execute(
            text(
                "INSERT INTO voyage (id, vessel_id, status, departure_port_name, "
                "arrival_port_name, planned_distance_nm, planned_speed_kn, "
                "annual_inclusion_policy, created_from) "
                "VALUES (:id, :v, 'DRAFT', 'Busan', 'Singapore', 3000, 14, 'EXCLUDE', 'MANUAL')"
            ),
            {"id": voy, "v": vid},
        )
        await s.execute(
            text(
                "INSERT INTO voyage (id, vessel_id, status, departure_port_name, "
                "arrival_port_name, planned_distance_nm, planned_speed_kn, "
                "annual_inclusion_policy, created_from) "
                "VALUES (:id, :v, 'IN_PROGRESS', 'Busan', 'Singapore', 3000, 14, "
                "'EXCLUDE', 'MANUAL')"
            ),
            {"id": voy2, "v": vid},
        )
        await s.commit()
    return str(vid), str(voy), str(voy2)


async def _cleanup(vid: str) -> None:
    from cii_platform.db.session import get_sessionmaker

    v = UUID(vid)
    async with get_sessionmaker()() as s:
        for q in (
            "DELETE FROM not_underway_fuel_use WHERE period_id IN "
            "(SELECT id FROM not_underway_period WHERE vessel_id = :v)",
            "DELETE FROM not_underway_period WHERE vessel_id = :v",
            "DELETE FROM vessel_position_snapshot WHERE vessel_id = :v",
            "DELETE FROM voyage_fuel_use WHERE voyage_id IN "
            "(SELECT id FROM voyage WHERE vessel_id = :v)",
            "DELETE FROM voyage WHERE vessel_id = :v",
            "DELETE FROM vessel WHERE id = :v",
        ):
            await s.execute(text(q), {"v": v})
        await s.commit()


async def test_저장_경로가_표기와_자릿수로_500이_되지_않는다(migrated_db, app_fresh_engine):
    """선박·위치·항차·실적·정박 — 이슈 재현 경로 전부. 허용은 정상 저장, 범위 밖은 422."""
    vid, voy, voy2 = await _seed()
    try:
        with TestClient(app, base_url=_BASE, raise_server_exceptions=False) as c:
            assert c.post("/api/v1/auth/dev-login").status_code == 200
            h = _csrf(c)
            bad: list[str] = []

            def call(label, method, url, body, ok):
                r = c.request(method, url, json=body, headers=h)
                if r.status_code >= 500 or (r.status_code in (200, 201)) != ok:
                    bad.append(f"{label}: {r.status_code} {r.text[:160]}")
                return r

            # 선박 — 톤수·속력·연료·방형계수
            vurl = f"/api/v1/vessels/{vid}"
            for f, val, ok in [
                ("deadweight", "1E+1", True),
                ("deadweight", "5E+4", True),
                ("deadweight", "1.5E+1", True),
                ("deadweight", _LONG, True),
                ("deadweight", "0.0000001", False),
                ("deadweight", "1E-7", False),
                ("deadweight", "1" + "0" * 40, False),
                ("gross_tonnage", "1E+4", True),
                ("reference_speed_kn", "1E+1", True),
                ("reference_daily_foc_ton", "3E+1", True),
                ("reference_daily_foc_ton", "1E+7", False),
                ("block_coefficient", "8E-1", True),
                ("block_coefficient", "0.8" + "1" * 38, True),
            ]:
                call(f"vessel {f}={val[:20]}", "PATCH", vurl, {f: val}, ok)

            # 위치 — 위·경도(둘은 함께 지정해야 한다)
            for lat, lon, ok in [
                ("1E+1", "1E+1", True),
                ("0.0000001", "0.0000001", True),
                ("-0.0000001", _LONG, True),
                ("1E+3", "1", False),
            ]:
                call(
                    f"position {lat[:12]}/{lon[:12]}",
                    "PATCH",
                    f"{vurl}/position",
                    {
                        "underway_state": "UNDER_WAY",
                        "detail_status": "SAILING",
                        "current_lat": lat,
                        "current_lon": lon,
                    },
                    ok,
                )

            # 항차 수정 — 좌표·거리·속력
            for f, val, ok in [
                ("departure_lat", "1E+1", True),
                ("arrival_lon", "0.0000001", True),
                ("planned_distance_nm", "3E+3", True),
                ("planned_distance_nm", _LONG, True),
                ("planned_speed_kn", "1.4E+1", True),
                ("planned_distance_nm", "1E-7", False),
                ("planned_speed_kn", "1E+3", False),
            ]:
                call(f"voyage {f}={val[:20]}", "PATCH", f"/api/v1/voyages/{voy}", {f: val}, ok)

            # 항차 생성 — 연료(scale 4)
            created = call(
                "voyage create",
                "POST",
                f"{vurl}/voyages",
                {
                    "departure_port_name": "Busan",
                    "arrival_port_name": "Singapore",
                    "planned_distance_nm": "3E+3",
                    "planned_speed_kn": "1E+1",
                    "regulation_year": 2026,
                    "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": "1E+2"}],
                },
                True,
            )
            call(
                "voyage create tiny fuel",
                "POST",
                f"{vurl}/voyages",
                {
                    "departure_port_name": "Busan",
                    "arrival_port_name": "Singapore",
                    "planned_distance_nm": "3000",
                    "planned_speed_kn": "10",
                    "regulation_year": 2026,
                    "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": "1E-7"}],
                },
                False,
            )

            # 실적
            for fuel, ok in [("1E+2", True), (_LONG, True), ("1E-7", False)]:
                call(
                    f"actuals fuel={fuel[:20]}",
                    "PUT",
                    f"/api/v1/voyages/{voy2}/actuals",
                    {
                        "actual_distance_nm": "3E+3",
                        "actual_avg_speed_kn": "1.4E+1",
                        "fuel_uses": [
                            {"fuel_type": "HFO", "actual_fuel_ton": fuel, "source": "USER_INPUT"}
                        ],
                    },
                    ok,
                )

            # 정박 — 좌표·거리·연료, 연료 추가
            nu = {
                "period_type": "AT_ANCHOR",
                "started_at": "2026-08-10T00:00:00Z",
                "ended_at": "2026-08-12T00:00:00Z",
                "port_name": "Busan",
                "lat": "1E+1",
                "lon": "0.0000001",
                "distance_nm": "0E+1",
                "regulation_year": 2026,
                "fuel_uses": [
                    {"consumer_type": "AUX_ENGINE", "fuel_type": "HFO", "fuel_ton": "1E+1"}
                ],
            }
            made = call("nu create", "POST", f"{vurl}/not-underway-periods", nu, True)
            call(
                "nu create bad",
                "POST",
                f"{vurl}/not-underway-periods",
                {
                    **nu,
                    "started_at": "2026-09-10T00:00:00Z",
                    "ended_at": "2026-09-12T00:00:00Z",
                    "fuel_uses": [
                        {"consumer_type": "AUX_ENGINE", "fuel_type": "HFO", "fuel_ton": "1E-7"}
                    ],
                },
                False,
            )
            if made.status_code == 201:
                pid = made.json()["data"]["id"]
                call(
                    "nu patch",
                    "PATCH",
                    f"/api/v1/not-underway-periods/{pid}",
                    {"lat": _LONG, "distance_nm": "0E+2"},
                    True,
                )
                call(
                    "nu fuel add",
                    "POST",
                    f"/api/v1/not-underway-periods/{pid}/fuel-uses",
                    {"consumer_type": "OIL_FIRED_BOILER", "fuel_type": "HFO", "fuel_ton": "2E+1"},
                    True,
                )

            assert not bad, "\n".join(bad)

            # 값 확인 — 지수 표기가 **같은 값**으로 저장됐다
            from cii_platform.db.session import get_sessionmaker

            async with get_sessionmaker()() as s:
                row = (
                    await s.execute(
                        text(
                            "SELECT gross_tonnage, current_lat, current_lon FROM vessel "
                            "WHERE id = :v"
                        ),
                        {"v": UUID(vid)},
                    )
                ).one()
            assert row[0] == Decimal("10000.00")
            assert row[1] == Decimal("0.000000")  # -0.0000001 → 0 (음의 0 없음)
            assert row[2] == Decimal("1.111111")
            assert created.status_code == 201
    finally:
        await _cleanup(vid)
