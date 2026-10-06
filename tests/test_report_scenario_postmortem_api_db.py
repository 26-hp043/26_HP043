"""항차 리포트의 「시나리오 사후 비교」를 **HTTP로** 본다 (`PRD §25.2.1` · `#2092`).

서비스 검사(`test_reports_db.py`)는 비교 이력을 손으로 심는다. 그래서 **실제 비교가 남기는
이력의 모양**(`result_json.scenarios[].scenario_id` · `calculation_basis`)과 리포트가 읽는
모양이 어긋나도 보지 못한다. 여기서는 사용자가 지나는 길 그대로 간다.

    비교(`POST /scenarios/compare`) → 채택(`POST /scenarios/{id}/adopt`) → 완료 →
    리포트(`GET /voyages/{id}/report` — 미리보기 · CSV · PDF)

세 형식이 **같은 4행**(직항 · 우회 · 감속 · 실적)을 싣는지가 완료 기준이다.
"""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal
from html import escape
from uuid import UUID, uuid4

from conftest import insert_returning_id
from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import app
from cii_platform.reports.document import VOYAGE_CII_NOTE
from cii_platform.services.report import (
    ACTUAL_CII_NOT_COMPUTABLE,
    SCENARIO_NOT_STORED,
    _display,
)

_BASE = "https://testserver"

IMO = "7200589"

PAYLOAD = {
    "regulation_year": 2026,
    "current_speed_kn": 14.0,
    "fuel_type": "HFO",
    "base_daily_foc_ton": 35.0,
    "direct_distance_nm": 11000.0,
}


async def _seed(session) -> tuple[str, str]:
    vessel_id = await insert_returning_id(
        session,
        "INSERT INTO vessel (imo_number, name, ship_type, gross_tonnage, deadweight, "
        "reference_speed_kn, default_fuel_type) "
        "VALUES (:imo, 'POSTMORTEM TEST', 'BULK_CARRIER', 30000, 50000, 14.0, 'HFO') "
        "RETURNING id",
        {"imo": IMO},
    )
    voyage_id = await insert_returning_id(
        session,
        "INSERT INTO voyage (vessel_id, status, annual_inclusion_policy, regulation_year, "
        " departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn, "
        " planned_departure_at, created_from) "
        "VALUES (:vid, 'PLANNED', 'INCLUDE_AS_PLAN', 2026, 'BUSAN', 'ROTTERDAM', 11000, 14, "
        " '2026-03-01T00:00:00Z', 'MANUAL') RETURNING id",
        {"vid": vessel_id},
    )
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, cf_used, source) "
            "VALUES (:id, 'HFO', 1100, 3.114, 'USER_INPUT')"
        ),
        {"id": voyage_id},
    )
    await session.commit()
    return vessel_id, voyage_id


async def _complete(session, voyage_id: str) -> None:
    """항차를 끝낸다 — 실적 거리·시각·연료를 적고 확정한다."""
    await session.execute(
        text(
            "UPDATE voyage SET status = 'CONFIRMED', "
            "annual_inclusion_policy = 'INCLUDE_AS_ACTUAL', "
            "actual_distance_nm = 11200, actual_avg_speed_kn = 13.2, "
            "actual_departure_at = '2026-03-01T00:00:00Z', "
            "actual_arrival_at = '2026-04-05T08:00:00Z' WHERE id = :id"
        ),
        {"id": voyage_id},
    )
    await session.execute(
        text("UPDATE voyage_fuel_use SET actual_fuel_ton = 1180.5 WHERE voyage_id = :id"),
        {"id": voyage_id},
    )
    await session.commit()


async def _cleanup(session, vessel_id: str) -> None:
    await session.execute(
        text("DELETE FROM voyage_scenario WHERE vessel_id = :vid"), {"vid": vessel_id}
    )
    # calculation_run은 immutable 트리거가 DELETE를 막는다 — 잠시 끄고 즉시 복구한다
    # (`test_scenario_compare_db.py`와 같은 패턴).
    await session.execute(text("ALTER TRIGGER trg_calcrun_no_delete STATUS INACTIVE"))
    await session.execute(
        text("DELETE FROM calculation_run WHERE vessel_id = :vid"), {"vid": vessel_id}
    )
    await session.execute(text("ALTER TRIGGER trg_calcrun_no_delete STATUS ACTIVE"))
    await session.execute(
        text(
            "DELETE FROM voyage_fuel_use WHERE voyage_id IN "
            "(SELECT id FROM voyage WHERE vessel_id = :vid)"
        ),
        {"vid": vessel_id},
    )
    await session.execute(text("DELETE FROM voyage WHERE vessel_id = :vid"), {"vid": vessel_id})
    await session.execute(text("DELETE FROM vessel WHERE id = :vid"), {"vid": vessel_id})
    await session.execute(text("DELETE FROM audit_log"))
    await session.execute(
        text(
            "DELETE FROM user_session WHERE user_id IN "
            "(SELECT id FROM app_user WHERE email = 'dev@localhost')"
        )
    )
    await session.execute(text("DELETE FROM app_user WHERE email = 'dev@localhost'"))
    await session.commit()


def _table(csv_text: str) -> list[list[str]]:
    """CSV에서 「시나리오 사후 비교」 표의 자료 행만 꺼낸다."""
    lines = list(csv.reader(io.StringIO(csv_text.lstrip("﻿"))))
    start = next(i for i, line in enumerate(lines) if line and line[0] == "구분")
    rows = []
    for line in lines[start + 1 :]:
        if len(line) != len(lines[start]):
            break
        rows.append(line)
    return rows


async def test_비교_채택_완료_뒤_리포트가_3종과_실적을_싣는다(migrated_db, app_fresh_engine):
    from cii_platform.db.session import get_engine, get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = None
    try:
        async with sessionmaker() as s:
            vessel_id, voyage_id = await _seed(s)

        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            headers = {"X-CSRF-Token": client.cookies.get("csrf") or ""}

            # 같은 항로를 두 번 비교한다 — 채택하지 않은 묶음이 섞이지 않는지 함께 본다.
            first = client.post(
                "/api/v1/scenarios/compare",
                json={"vessel_id": vessel_id, **PAYLOAD, "direct_distance_nm": 9000.0},
                headers=headers,
            )
            assert first.status_code == 200, first.text
            compared = client.post(
                "/api/v1/scenarios/compare",
                json={"vessel_id": vessel_id, **PAYLOAD},
                headers=headers,
            )
            assert compared.status_code == 200, compared.text
            scenarios = compared.json()["data"]["scenarios"]
            slow = next(s for s in scenarios if s["scenario_type"] == "SLOW_STEAMING")

            adopted = client.post(
                f"/api/v1/scenarios/{slow['scenario_id']}/adopt",
                json={"target_voyage_id": voyage_id},
                headers=headers,
            )
            assert adopted.status_code == 200, adopted.text

            async with sessionmaker() as s:
                await _complete(s, voyage_id)

            html = client.get(f"/api/v1/voyages/{voyage_id}/report", params={"format": "html"})
            csv_response = client.get(
                f"/api/v1/voyages/{voyage_id}/report", params={"format": "csv"}
            )
            assert html.status_code == 200, html.text
            assert csv_response.status_code == 200, csv_response.text

            rows = _table(csv_response.text)
            assert len(rows) == 4, rows

            # 3종 — 비교 응답의 값이 그대로다(표시 자릿수만 입힌다). 9,000 nm 묶음은 없다.
            for row, scenario in zip(rows[:3], scenarios, strict=True):
                assert row[0].startswith(scenario["scenario_name"])
                assert row[1] == _display(str(scenario["distance_nm"]), "distance_nm")
                assert row[3] == _display(scenario["duration_hours"], "hours")
                assert row[4] == _display(scenario["fuel_ton"], "fuel_ton")
                assert row[5] == _display(scenario["attained_cii"], "cii")
                assert row[6] == scenario["estimated_rating"]
            # 채택된 것은 감속 하나다.
            plain = [s["scenario_name"] for s in scenarios]
            assert [row[0] != name for row, name in zip(rows[:3], plain, strict=True)] == [
                False,
                False,
                True,
            ]

            # 실적 — 적은 값이 그대로다. 3/1 00:00 ~ 4/5 08:00 = 848 h.
            actual = rows[3]
            assert actual[1:5] == ["11,200", "13.2", "848.0", "1,180.5"]
            # CII = 1180.5 × 3.114 × 1,000,000 ÷ (50,000 × 11,200) = 3,676,077,000 ÷ 560,000,000
            assert actual[5] == _display(Decimal("3676077000") / Decimal("560000000"), "cii")

            # 미리보기가 같은 행을 싣는다.
            for row in rows:
                for cell in row:
                    assert f">{cell}<" in html.text, cell

            # 각주 — 「CII 기여도」 절과 같은 COR-1 문구, 그리고 비교가 쓴 용량 숫자(결정 1·2).
            assert html.text.count(escape(VOYAGE_CII_NOTE)) == 2
            assert "50,000 DWT" in html.text

            # PDF는 같은 문서에서 나온다 — 렌더러가 없는 환경에서는 건너뛴다.
            from cii_platform.reports import pdf as pdf_module

            if pdf_module.is_available() and pdf_module.has_korean_font():
                pdf = client.get(f"/api/v1/voyages/{voyage_id}/report", params={"format": "pdf"})
                assert pdf.status_code == 200, pdf.text
                assert pdf.content.startswith(b"%PDF-")
    finally:
        if vessel_id:
            async with sessionmaker() as s:
                await _cleanup(s, vessel_id)
        await get_engine().dispose()


async def _old_shape_comparison(session, vessel_id: str, voyage_id: str) -> None:
    """옛 모양의 이력 한 건을 저장 형태 그대로 심고 감속 행을 채택한다.

    비교 API를 부르지 않는 것은, 같은 초에 저장된 이력 둘의 순서가 id로 갈려 어느 쪽이
    인용될지 정해지지 않기 때문이다. 여기서는 이 묶음이 **유일한** 이력이다.
    """
    from cii_platform.db.repositories import calculation_run as calc_run_repo

    ids = {}
    for kind, name, speed, hours, fuel, cii, rating in (
        ("DIRECT", "직항", "14", "785.71", "1145.8333", "3.56800000", "A"),
        ("DETOUR", "우회", "14", "857.14", "1250.0000", "3.56800000", "A"),
        ("SLOW_STEAMING", "감속", "11.9", "924.37", "993.3000", "3.09300000", "A"),
    ):
        ids[kind] = uuid4()
        await session.execute(
            text(
                "INSERT INTO voyage_scenario (id, vessel_id, scenario_type, scenario_name, "
                "distance_nm, speed_kn, duration_hours, fuel_ton, cii_value, "
                "estimated_rating, risk_level) VALUES (:id, :vid, :kind, :name, 11000, "
                ":speed, :hours, :fuel, :cii, :rating, 'LOW')"
            ),
            {
                "id": ids[kind],
                "vid": UUID(vessel_id),
                "kind": kind,
                "name": name,
                "speed": Decimal(speed),
                "hours": Decimal(hours),
                "fuel": Decimal(fuel),
                "cii": Decimal(cii),
                "rating": rating,
            },
        )
    await calc_run_repo.insert_scenario(
        session,
        vessel_id=UUID(vessel_id),
        input_hash="sha256:" + "a" * 64,
        parameter_hash="sha256:" + "b" * 64,
        model_version={"engine": "test"},
        # 형제 두 항목에 표가 읽는 키가 없고, 용량 블록도 없다.
        result_json={
            "scenarios": [
                {"scenario_id": str(ids["DIRECT"]), "scenario_type": "DIRECT"},
                {"scenario_id": str(ids["DETOUR"]), "scenario_type": "DETOUR"},
                {"scenario_id": str(ids["SLOW_STEAMING"]), "scenario_type": "SLOW_STEAMING"},
            ]
        },
        parameters_used={},
        warnings=[],
        duration_ms=1,
    )
    await session.execute(
        text("UPDATE voyage_scenario SET voyage_id = :yid, is_adopted = 1 WHERE id = :id"),
        {"yid": UUID(voyage_id), "id": ids["SLOW_STEAMING"]},
    )
    await session.commit()


async def test_옛_모양의_이력은_그_행만_내려가고_리포트는_산다(migrated_db, app_fresh_engine):
    """`result_json.scenarios[]`에 키가 빠진 이력 — 종전에는 `KeyError`가 올라가 리포트가 500이었다.

    HTTP로 보는 것은 결함이 **응답 코드**로 드러난 것이기 때문이다. 키가 빠진 종류는 「이력
    없음」, 채택 행은 제 행의 값, 실적 CII는 용량을 몰라 「계산 불가」 — 그리고 미리보기의
    수치 열은 표지가 섞여도 오른쪽 정렬을 지킨다.
    """
    from cii_platform.db.session import get_engine, get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = None
    try:
        async with sessionmaker() as s:
            vessel_id, voyage_id = await _seed(s)
            await _old_shape_comparison(s, vessel_id, voyage_id)
            await _complete(s, voyage_id)

        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200

            html = client.get(f"/api/v1/voyages/{voyage_id}/report", params={"format": "html"})
            csv_response = client.get(
                f"/api/v1/voyages/{voyage_id}/report", params={"format": "csv"}
            )
            assert html.status_code == 200, html.text
            assert csv_response.status_code == 200, csv_response.text

            direct, detour, slow, actual = _table(csv_response.text)
            assert direct == ["직항", *[SCENARIO_NOT_STORED] * 6]
            assert detour == ["우회", *[SCENARIO_NOT_STORED] * 6]
            assert slow == ["감속 (채택)", "11,000", "11.9", "924.4", "993.3", "3.093", "A"]
            assert actual[1:5] == ["11,200", "13.2", "848.0", "1,180.5"]
            assert actual[5] == ACTUAL_CII_NOT_COMPUTABLE
            assert "용량을 알 수 없어" in html.text

            # 수치 열 다섯(거리·속력·소요·연료·CII)은 표지가 있어도 오른쪽 정렬 — 표지 셀도
            # `num` 클래스를 받는다. 등급 열은 글자 열이라 왼쪽 그대로다(2행).
            section_html = html.text.split("시나리오 사후 비교", 1)[1].split("</table>", 1)[0]
            cells = re.findall(r"<td( class=\"num\")?>([^<]*)</td>", section_html)
            assert cells.count((' class="num"', SCENARIO_NOT_STORED)) == 10
            assert cells.count(("", SCENARIO_NOT_STORED)) == 2
            assert cells.count((' class="num"', ACTUAL_CII_NOT_COMPUTABLE)) == 1
            assert cells.count(("", ACTUAL_CII_NOT_COMPUTABLE)) == 0
    finally:
        if vessel_id:
            async with sessionmaker() as s:
                await _cleanup(s, vessel_id)
        await get_engine().dispose()
