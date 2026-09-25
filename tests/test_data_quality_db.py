"""데이터 점검 서비스 DB 실동작 검증 (`API_SPEC §2.16` · `PRD §17.4` · #513).

판정 수식은 ``tests/test_data_quality.py``가 본다. 여기는 **실제 DB 행에서 다섯 심각도가
맞게 갈리는가**와 **CII 영향·완결성이 선박 누적값과 같은 재료로 나오는가**를 본다.

선대 전체를 도는 서비스라 시드된 데모 선박도 결과에 섞인다 — 검사는 **이 파일이 넣은
선박으로 걸러** 단언한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
import pytest_asyncio
from conftest import ensure_regulation_year, insert_returning_id, same_uuid, uuid_canon
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.services.data_quality import (
    IMPACT_ONLY_VOYAGE,
    SEVERITY_ANOMALY,
    SEVERITY_PUBLIC_RECORD,
    SEVERITY_SUBSTITUTED,
    SEVERITY_UNAVAILABLE,
    SEVERITY_UNCONFIRMED,
    UNAVAILABLE_FUEL_NO_RECORD,
    UNAVAILABLE_FUEL_UNFILLED,
    get_fleet_data_quality,
)
from cii_platform.services.ytd_cii import compute_ytd_cii

YEAR = 2026


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


@pytest_asyncio.fixture
async def vessel_id(session) -> str:
    """기준 속력 12kn · 기준 일일 연료 24t — 2,880nm를 12kn로 가면 기대 연료 240t."""
    await ensure_regulation_year(session, 2026)
    return await insert_returning_id(
        session,
        "INSERT INTO vessel (imo_number, name, ship_type, gross_tonnage, deadweight, "
        " reference_speed_kn, reference_daily_foc_ton) "
        "VALUES ('9513001', 'DQ TEST', 'BULK_CARRIER', 30000, 50000, 12, 24) RETURNING id",
        {},
    )


async def _voyage(
    session,
    vessel_id: str,
    *,
    no: str,
    status: str = "CONFIRMED",
    actual_distance: float | None = 2880,
    speed: float | None = 12,
    hours: int | None = 240,
    planned_fuel: float | None = 240,
    actual_fuel: float | None = 240,
    #: ``False``면 ``voyage_fuel_use`` 행을 **아예 넣지 않는다** (`#1095` ⑵).
    with_fuel_row: bool = True,
) -> str:
    departure = datetime.fromisoformat("2026-03-01T00:00:00+00:00")
    arrival = None if hours is None else departure + timedelta(hours=hours)
    voyage_id = await insert_returning_id(
        session,
        "INSERT INTO voyage "
        "(vessel_id, voyage_no, status, annual_inclusion_policy, regulation_year, "
        " departure_port_name, arrival_port_name, planned_distance_nm, actual_distance_nm, "
        " planned_speed_kn, actual_avg_speed_kn, actual_departure_at, actual_arrival_at) "
        "VALUES (:vid, :no, :st, 'INCLUDE_AS_ACTUAL', :yr, 'BUSAN', 'SINGAPORE', 2880, "
        " :dist, 12, :spd, :dep, :arr) RETURNING id",
        {
            "vid": vessel_id,
            "no": no,
            "st": status,
            "yr": YEAR,
            "dist": actual_distance,
            "spd": speed,
            "dep": None if hours is None else departure,
            "arr": arrival,
        },
    )
    if with_fuel_row:
        await session.execute(
            text(
                "INSERT INTO voyage_fuel_use "
                "(voyage_id, fuel_type, planned_fuel_ton, actual_fuel_ton, cf_used, source) "
                "VALUES (:vid, 'HFO', :pt, :at, 3.114, 'USER_INPUT')"
            ),
            {"vid": voyage_id, "pt": planned_fuel, "at": actual_fuel},
        )
    return voyage_id


async def _mine(session, vessel_id: str) -> tuple[dict, list[dict], dict]:
    result = await get_fleet_data_quality(session, regulation_year=YEAR)
    vessel = next(row for row in result["vessels"] if same_uuid(row["vessel_id"], vessel_id))
    issues = [item for item in result["issues"] if same_uuid(item["vessel_id"], vessel_id)]
    return vessel, issues, result["summary"]


def _voyage_ids(items) -> list[str]:
    """이슈 목록의 ``voyage_id``를 **대시 36자**로 (`#1058`).

    서비스가 내는 것은 대시 형식이고, :func:`insert_returning_id`가 돌려주는 픽스처 값은
    저장 형식(hex 32자)이다. 목록을 통째로 ``==``로 견주는 자리라
    :func:`conftest.same_uuid` 로 짝지어 볼 수 없어 **양쪽을 정규화**한다.
    """
    return [uuid_canon(item["voyage_id"]) for item in items]


def _by(issues: list[dict], severity: str) -> list[dict]:
    return [item for item in issues if item["severity"] == severity]


#: `API_SPEC §2.16` ``completeness`` — 비율의 분자·분모와 축별 제외 내역 (#1532).
_COMPLETENESS_KEYS = {
    "total_co2_ton",
    "measured_co2_ton",
    "excluded_unavailable_co2_ton",
    "excluded_substituted_co2_ton",
    "excluded_anomaly_co2_ton",
}


def _excluded_sum(block: dict[str, str]) -> Decimal:
    return sum(
        (Decimal(block[key]) for key in _COMPLETENESS_KEYS if key.startswith("excluded_")),
        Decimal(0),
    )


@pytest.mark.asyncio
async def test_clean_confirmed_voyages_raise_no_issue(session, vessel_id):
    await _voyage(session, vessel_id, no="A")
    await _voyage(session, vessel_id, no="B")

    vessel, issues, _ = await _mine(session, vessel_id)

    assert issues == []
    assert vessel["completeness_ratio"] == "1.0000"


@pytest.mark.asyncio
async def test_missing_actual_fuel_is_a_substitution_with_its_cii_impact(session, vessel_id):
    """⚠️ **CII 영향은 그 항차를 뺀 누적 CII와의 차이다** (`PRD §17.4.2`).

    서비스의 값을 **같은 함수로 따로 구한 두 누적값의 차**와 대조한다 — 식을 옮겨 적으면
    부호가 뒤집혀도 그럴듯한 값이 나온다.
    """
    keep = await _voyage(session, vessel_id, no="A")
    target = await _voyage(session, vessel_id, no="B", actual_fuel=None, planned_fuel=300)

    _, issues, _ = await _mine(session, vessel_id)
    substituted = _by(issues, SEVERITY_SUBSTITUTED)

    assert _voyage_ids(substituted) == [uuid_canon(target)]
    assert substituted[0]["codes"] == ["FUEL:HFO"]

    base = await compute_ytd_cii(session, vessel_id=UUID(vessel_id), regulation_year=YEAR)
    without = await compute_ytd_cii(
        session,
        vessel_id=UUID(vessel_id),
        regulation_year=YEAR,
        exclude_voyage_ids=frozenset({UUID(target)}),
    )
    impact = substituted[0]["cii_impact"]
    assert Decimal(impact["delta"]) == pytest.approx(
        base.attained_cii - without.attained_cii, abs=Decimal("1e-4")
    )
    # 계획 300t이 섞여 누적이 나빠졌다 — 빼면 좋아진다.
    assert Decimal(impact["delta"]) > 0
    assert keep != target


@pytest.mark.asyncio
async def test_a_fuel_row_with_nothing_in_it_is_unavailable_not_substituted(session, vessel_id):
    """실적도 계획도 없는 행은 **아무것도 들어가지 않았다** — 대체로 세면 「추정이 들어갔다」다."""
    await _voyage(session, vessel_id, no="A")
    target = await _voyage(session, vessel_id, no="B", actual_fuel=None, planned_fuel=None)

    _, issues, _ = await _mine(session, vessel_id)

    assert _by(issues, SEVERITY_SUBSTITUTED) == []
    unavailable = _by(issues, SEVERITY_UNAVAILABLE)
    assert _voyage_ids(unavailable) == [uuid_canon(target)]
    assert unavailable[0]["codes"] == [f"{UNAVAILABLE_FUEL_UNFILLED}:HFO"]


@pytest.mark.asyncio
async def test_fuel_far_from_the_model_is_an_anomaly(session, vessel_id):
    """기대 240t에 480t(2배) — 이상치. **계산에서는 빼지 않는다**(`PRD §17.1`)."""
    await _voyage(session, vessel_id, no="A")
    target = await _voyage(session, vessel_id, no="B", actual_fuel=480)

    _, issues, _ = await _mine(session, vessel_id)
    anomaly = _by(issues, SEVERITY_ANOMALY)

    assert _voyage_ids(anomaly) == [uuid_canon(target)]
    assert anomaly[0]["codes"] == ["FUEL_VS_MODEL"]

    ytd = await compute_ytd_cii(session, vessel_id=UUID(vessel_id), regulation_year=YEAR)
    assert ytd.voyage_count == 2


@pytest.mark.asyncio
async def test_completed_but_not_confirmed_is_unconfirmed(session, vessel_id):
    await _voyage(session, vessel_id, no="A")
    target = await _voyage(session, vessel_id, no="B", status="COMPLETED")

    vessel, issues, _ = await _mine(session, vessel_id)

    assert _voyage_ids(_by(issues, SEVERITY_UNCONFIRMED)) == [uuid_canon(target)]
    # 값 자체는 실측이다 — 완결성에서 빼지 않는다.
    assert vessel["completeness_ratio"] == "1.0000"


@pytest.mark.asyncio
async def test_completeness_is_the_measured_share_of_co2(session, vessel_id):
    """실측 240t + 대체 360t → 실측 CO₂ 비율 240 ÷ 600 = 0.4 (항차 수로 세면 0.5)."""
    await _voyage(session, vessel_id, no="A")
    await _voyage(session, vessel_id, no="B", actual_fuel=None, planned_fuel=360)

    vessel, _, _ = await _mine(session, vessel_id)

    assert vessel["completeness_ratio"] == "0.4000"


@pytest.mark.asyncio
async def test_an_anomalous_voyage_is_not_counted_as_measured(session, vessel_id):
    """⚠️ 이상치 항차는 값이 들어가 있어도 **믿기 어려운 값**이다 — 완결성의 「실측」에서 뺀다.

    실측 240t + 이상치 480t → 240 ÷ 720 = 0.3333. 이상치를 실측으로 세면 1.0000이 되어
    **믿기 어려운 데이터가 많은 선박일수록 완결돼 보인다.** (첫 판 검사가 이 결함을 못 잡았다 —
    돌연변이로 확인.)
    """
    await _voyage(session, vessel_id, no="A")
    await _voyage(session, vessel_id, no="B", actual_fuel=480)

    vessel, _, _ = await _mine(session, vessel_id)

    assert vessel["completeness_ratio"] == "0.3333"


@pytest.mark.asyncio
async def test_a_single_voyage_has_no_impact_to_compare(session, vessel_id):
    """항차가 하나뿐이면 빼고 난 누적이 없다 — 0이 아니라 **사유**를 낸다."""
    await _voyage(session, vessel_id, no="A", status="COMPLETED")

    _, issues, _ = await _mine(session, vessel_id)
    unconfirmed = _by(issues, SEVERITY_UNCONFIRMED)

    assert unconfirmed[0]["cii_impact"] is None
    assert unconfirmed[0]["cii_impact_reason"] == IMPACT_ONLY_VOYAGE


@pytest.mark.asyncio
async def test_voyages_that_cannot_be_judged_are_counted_apart(session, vessel_id):
    """⚠️ **판정 못 함은 이상치 0건과 섞지 않는다** — 제원·시각이 없는 항차."""
    await session.execute(
        text(
            "UPDATE vessel SET reference_speed_kn = NULL, reference_daily_foc_ton = NULL "
            "WHERE id = :id"
        ),
        {"id": vessel_id},
    )
    before = (await get_fleet_data_quality(session, regulation_year=YEAR))["summary"]
    await _voyage(session, vessel_id, no="A", hours=None)

    _, issues, after = await _mine(session, vessel_id)

    assert _by(issues, SEVERITY_ANOMALY) == []
    assert after["anomaly_unjudged_count"] == before["anomaly_unjudged_count"] + 1


@pytest.mark.asyncio
async def test_a_vessel_that_cannot_be_calculated_is_unavailable(session, vessel_id):
    """선대 요약(`#419`)과 **같은 사유 어휘**를 쓴다 — 제원이 없으면 ``MISSING_SPEC``."""
    await _voyage(session, vessel_id, no="A")
    await session.execute(
        text("UPDATE vessel SET deadweight = NULL WHERE id = :id"), {"id": vessel_id}
    )

    vessel, issues, _ = await _mine(session, vessel_id)

    assert vessel["unavailable_reason"] == "MISSING_SPEC"
    vessel_level = [item for item in _by(issues, SEVERITY_UNAVAILABLE) if item["voyage_id"] is None]
    assert vessel_level[0]["codes"] == ["MISSING_SPEC"]
    assert vessel["completeness_ratio"] is None


@pytest.mark.asyncio
async def test_issues_are_grouped_in_design_system_order(session, vessel_id):
    """그룹 순서 = `DESIGN_SYSTEM §2.3.1` 표 순서(대체 → 계산 불가 → 이상치 → 미입력)."""
    await _voyage(session, vessel_id, no="A", status="COMPLETED")
    await _voyage(session, vessel_id, no="B", actual_fuel=480)
    await _voyage(session, vessel_id, no="C", actual_fuel=None, planned_fuel=300)

    _, issues, _ = await _mine(session, vessel_id)

    assert [item["severity"] for item in issues] == [
        SEVERITY_SUBSTITUTED,
        SEVERITY_ANOMALY,
        SEVERITY_UNCONFIRMED,
    ]


@pytest.mark.asyncio
async def test_response_shape_matches_api_spec(session, vessel_id):
    """`API_SPEC §2.16` 필드 집합 — 영향이 **있는** 행과 **없는** 행을 함께 본다.

    선대 계약표(`test_response_contract_db.py`)에 넣지 않은 이유: 이 응답의 `issues[]`는
    **DB에 어떤 항차가 있느냐에 따라** 영향 블록의 유무가 갈려, 공용 데이터로 비교하면
    다른 파일이 남긴 행에 따라 결과가 흔들린다. 여기서 만든 데이터로 **양쪽 모양을 다** 본다.
    """
    await _voyage(session, vessel_id, no="A")
    await _voyage(session, vessel_id, no="B", actual_fuel=None, planned_fuel=300)
    await _voyage(session, vessel_id, no="C", status="COMPLETED")

    result = await get_fleet_data_quality(session, regulation_year=YEAR)

    assert set(result) == {"regulation_year", "summary", "vessels", "issues"}
    assert set(result["summary"]) == {
        "substituted_count",
        "unavailable_count",
        "anomaly_count",
        "unconfirmed_count",
        "public_record_count",
        "anomaly_unjudged_count",
        "completeness_ratio",
        "completeness",
    }
    assert set(result["summary"]["completeness"]) == _COMPLETENESS_KEYS
    mine = next(row for row in result["vessels"] if same_uuid(row["vessel_id"], vessel_id))
    assert set(mine) == {
        "vessel_id",
        "vessel_name",
        "data_available",
        "unavailable_reason",
        "ytd_attained_cii",
        "ytd_rating",
        "voyage_count",
        "completeness_ratio",
        "completeness",
    }
    assert set(mine["completeness"]) == _COMPLETENESS_KEYS
    issues = [item for item in result["issues"] if same_uuid(item["vessel_id"], vessel_id)]
    for item in issues:
        assert set(item) == {
            "severity",
            "vessel_id",
            "vessel_name",
            "voyage_id",
            "voyage_no",
            "codes",
            "cii_impact",
            "cii_impact_reason",
            "public_record",
        }
        # 공적 기록 대조 행이 아니면 비어 있다 (`#1197`)
        assert item["public_record"] is None
    with_impact = [item["cii_impact"] for item in issues if item["cii_impact"] is not None]
    assert with_impact, "영향 블록이 있는 행을 만들지 못했다 — 검사가 한쪽 모양만 본다"
    assert set(with_impact[0]) == {
        "attained_cii",
        "attained_cii_without",
        "delta",
        "rating",
        "rating_without",
    }


def test_the_route_answers_over_http(migrated_db, app_fresh_engine):
    """⚠️ **실제 HTTP 경로로 받아 본다** — 서비스 검사는 라우트 배선·봉투·인증을 보지 않는다.

    데모 시드 위라 ``issues[]`` 모양은 데이터에 따라 갈린다 — 여기서는 **데이터와 무관한
    키만** 단언하고, 행 모양은 위 ``test_response_shape_matches_api_spec``가 본다.
    """
    from fastapi.testclient import TestClient

    from cii_platform.api.main import API_V1_PREFIX, app

    with TestClient(app, base_url="https://testserver") as client:
        assert client.get(f"{API_V1_PREFIX}/fleet/data-quality").status_code == 401

        client.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        response = client.get(f"{API_V1_PREFIX}/fleet/data-quality?regulation_year={YEAR}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body) == {"data", "meta"}
        assert body["data"]["regulation_year"] == YEAR
        assert set(body["data"]["summary"]) >= {"anomaly_unjudged_count", "completeness_ratio"}

        out_of_range = client.get(f"{API_V1_PREFIX}/fleet/data-quality?regulation_year=1999")
        assert out_of_range.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# 연료 기록이 **한 행도 없는** 항차를 가리킨다 (#1095 ⑵)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_voyage_with_no_fuel_row_is_pointed_at(session, vessel_id):
    """행이 **아예 없는** 항차도 항차 행으로 나온다 (#1095 ⑵).

    종전에는 이 항차뿐일 때 선박 단위 `NO_DATA` 한 줄만 나오고 **항차 행이 0건**이었다
    — 「이 선박은 계산 불가」까지만 말하고 **어느 항차 때문인지**는 가리키지 못했다.
    데이터 점검은 「실측이 아닌 값이 어디에 들어갔는가」를 항차별로 보는 화면인데,
    가장 나쁜 경우에 아무것도 가리키지 않았다.
    """
    target = await _voyage(session, vessel_id, no="NF-ONLY", with_fuel_row=False)

    _, issues, _ = await _mine(session, vessel_id)

    # 선박 단위 행(`voyage_id: null` · `NO_DATA`)은 그대로 남는다 — 이 선박은 실제로
    # 계산 불가다. 새로 생긴 것은 **어느 항차 때문인지**를 말하는 항차 행이다.
    unavailable = _by(issues, SEVERITY_UNAVAILABLE)
    per_voyage = [item for item in unavailable if item["voyage_id"] is not None]
    assert _voyage_ids(per_voyage) == [uuid_canon(target)]
    # 유종 접미사가 없다 — 붙일 유종이 없다. `FUEL_UNFILLED`와 **가른다**:
    # 「행은 있는데 값이 빔」과 「행이 아예 없음」은 사용자가 할 일이 다르다.
    assert per_voyage[0]["codes"] == [UNAVAILABLE_FUEL_NO_RECORD]
    assert UNAVAILABLE_FUEL_UNFILLED not in per_voyage[0]["codes"]


@pytest.mark.asyncio
async def test_a_fuelless_voyage_is_pointed_at_even_when_mixed(session, vessel_id):
    """★ 연료가 있는 항차와 섞여도 가리킨다 (#1095 ⑵ · 결정요청 v7 §1.2 ⒝).

    종전에는 **아무것도 나오지 않았다** — 선박 행은 `data_available: true` ·
    `ytd_rating: "A"` · `completeness_ratio: "1.0000"`이고 항차 행도 0건이라, 화면
    어디에도 그 항차가 없었다. 완결성 비율이 **1.0000**인 것이 특히 나쁘다: 「전부
    실측」이라는 뜻인데 한 항차는 연료가 통째로 빠져 있었다.
    """
    await _voyage(session, vessel_id, no="OK")
    target = await _voyage(session, vessel_id, no="NF", with_fuel_row=False)

    vessel_row, issues, _ = await _mine(session, vessel_id)

    unavailable = _by(issues, SEVERITY_UNAVAILABLE)
    assert _voyage_ids(unavailable) == [uuid_canon(target)]
    assert unavailable[0]["codes"] == [UNAVAILABLE_FUEL_NO_RECORD]
    # 등급은 여전히 나온다 — 그래서 조용했다. 드러나는가를 보는 검사다.
    assert vessel_row["data_available"] is True
    # 🔴 **완결성 비율은 여전히 1.0000이다** — 잔여 결함으로 남긴다 (#1095 ⑵ 범위 밖).
    #
    # `completeness_ratio`는 **CO₂로 가중**한다(`data_quality.py`의 `measured`/`total`이
    # 둘 다 CO₂ 합이다). 연료 행이 없는 항차는 CO₂가 0이라 분자·분모 어디에도 보이지
    # 않아, 「계산 불가 항차는 실측에서 빼면 비율이 떨어진다」는 규칙이 이 경우에만
    # 작동하지 않는다. 고치려면 가중치를 항차 수로 바꾸거나 별도 분모를 두어야 하고
    # 그것은 `PRD §17.4.3` 개정이다 — 이번 결정(`가′` = 경고 + 항차별 목록)의 범위가
    # 아니므로 **현행을 그대로 잠그고 사실을 적어 둔다.** 이 비율이 눈감는 자리를
    # 위의 항차 행이 대신 가리키는 것이 이번 변경의 값이다.
    assert Decimal(vessel_row["completeness_ratio"]) == Decimal("1.0000")


# ─────────────────────────────────────────────────────────────────────────────
# 완결성의 분자·분모와 제외 내역 (`API_SPEC §2.16` `completeness` · #1532)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_completeness_carries_its_numerator_denominator_and_exclusions(session, vessel_id):
    """비율만 주면 검산할 수 없다 — 분자·분모와 빠진 CO₂를 축별로 싣는다 (#1532).

    실측 240t + 대체 360t(HFO CF 3.114): 누적 (240+360)×3.114 = 1868.40t · 실측 240×3.114
    = 747.36t · 대체로 빠진 360×3.114 = 1121.04t. 정수 검산: 600×3114 = 1868400 →
    1868.40 (`AGENTS §5`).
    """
    await _voyage(session, vessel_id, no="A")
    await _voyage(session, vessel_id, no="B", actual_fuel=None, planned_fuel=360)

    vessel, _, summary = await _mine(session, vessel_id)
    block = vessel["completeness"]

    assert block["total_co2_ton"] == "1868.40"
    assert block["measured_co2_ton"] == "747.36"
    assert block["excluded_substituted_co2_ton"] == "1121.04"
    assert block["excluded_unavailable_co2_ton"] == "0.00"
    assert block["excluded_anomaly_co2_ton"] == "0.00"
    # 실측 + 제외 합 = 누적 — 이 값들은 소수 2자리에서 정확히 떨어진다.
    assert Decimal(block["measured_co2_ton"]) + _excluded_sum(block) == Decimal(
        block["total_co2_ton"]
    )
    # 비율은 이 둘로 재현된다 — 「어디서 온 0.4인가」가 응답 안에서 닫힌다.
    assert vessel["completeness_ratio"] == "0.4000"
    assert Decimal(block["measured_co2_ton"]) / Decimal(block["total_co2_ton"]) == Decimal("0.4")
    # 선대 합에도 같은 내역이 있고, 이 선박분이 그 안에 들어 있다.
    assert Decimal(summary["completeness"]["total_co2_ton"]) >= Decimal(block["total_co2_ton"])


@pytest.mark.asyncio
async def test_a_lone_anomalous_voyage_explains_its_zero_completeness(session, vessel_id):
    """`#1532`의 발단 — 유일한 항차가 이상치라 완결성이 0%인데 **이유가 응답에 없었다.**

    이제 누적 전부가 이상치 축에 실린다: 480×3.114 = 1494.72t (정수 검산 480×3114 =
    1494720). 실측은 0이고 다른 축은 비어 있다 — 0%의 출처가 한 축으로 닫힌다.
    """
    await _voyage(session, vessel_id, no="A", actual_fuel=480)

    vessel, issues, _ = await _mine(session, vessel_id)
    block = vessel["completeness"]

    assert _by(issues, SEVERITY_ANOMALY), "이상치가 아니면 이 검사는 아무것도 보지 않는다"
    assert vessel["completeness_ratio"] == "0.0000"
    assert block["measured_co2_ton"] == "0.00"
    assert block["total_co2_ton"] == "1494.72"
    assert block["excluded_anomaly_co2_ton"] == "1494.72"
    assert block["excluded_substituted_co2_ton"] == "0.00"
    assert block["excluded_unavailable_co2_ton"] == "0.00"


@pytest.mark.asyncio
async def test_a_voyage_with_two_severities_is_excluded_on_one_axis_only(session, vessel_id):
    """⚠️ 겹치는 항차를 두 축에 다 더하면 「실측 + 제외 합 = 누적」이 깨진다.

    한 항차에 HFO는 계획값으로 대체(대체 계산)되고 LFO 행은 실적·계획 모두 비어(계산
    불가) 있다. 빠진 CO₂는 우선순위상 앞선 **계산 불가** 축에만 실린다 — 대체 축은 0이다.
    누적 (240+300)×3.114 = 1681.56t · 실측 747.36t · 계산 불가로 빠진 300×3.114 = 934.20t.
    """
    await _voyage(session, vessel_id, no="A")
    target = await _voyage(session, vessel_id, no="B", actual_fuel=None, planned_fuel=300)
    # 유종은 `fuel_type` 마스터에 있는 코드여야 한다(참조 트리거) — `DB_SCHEMA §3.2` LFO.
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use "
            "(voyage_id, fuel_type, planned_fuel_ton, actual_fuel_ton, cf_used, source) "
            "VALUES (:vid, 'LFO', NULL, NULL, 3.151, 'USER_INPUT')"
        ),
        {"vid": target},
    )

    vessel, issues, _ = await _mine(session, vessel_id)
    block = vessel["completeness"]

    # 정말 두 심각도에 걸렸는가 — 아니면 이 검사는 우선순위를 보지 않는다.
    assert _voyage_ids(_by(issues, SEVERITY_SUBSTITUTED)) == [uuid_canon(target)]
    assert _voyage_ids(_by(issues, SEVERITY_UNAVAILABLE)) == [uuid_canon(target)]
    assert block["total_co2_ton"] == "1681.56"
    assert block["measured_co2_ton"] == "747.36"
    assert block["excluded_unavailable_co2_ton"] == "934.20"
    assert block["excluded_substituted_co2_ton"] == "0.00"
    assert block["excluded_anomaly_co2_ton"] == "0.00"
    assert Decimal(block["measured_co2_ton"]) + _excluded_sum(block) == Decimal(
        block["total_co2_ton"]
    )


@pytest.mark.asyncio
async def test_a_vessel_without_a_ratio_has_no_breakdown_either(session, vessel_id):
    """비율을 낼 수 없는 선박(제원 결측)은 내역도 `null`이다 — 재료가 같다."""
    await _voyage(session, vessel_id, no="A")
    await session.execute(
        text("UPDATE vessel SET deadweight = NULL WHERE id = :id"), {"id": vessel_id}
    )

    vessel, _, _ = await _mine(session, vessel_id)

    assert vessel["completeness_ratio"] is None
    assert vessel["completeness"] is None


async def _port_call(session, *, sign: str, arrival: str, departure: str) -> None:
    """공적 재항 기록 한 건 (``DB_SCHEMA §2.25``) — 부산 항만청."""
    await session.execute(
        text(
            "INSERT INTO port_call_record (id, source, port_authority_code, port_authority_name, "
            " call_year, call_seq, call_sign, arrival_at, departure_at, reports, fetched_at) "
            "VALUES (:id, 'MOF_VESSEL_OPS', '020', '부산', 2026, '077', :sign, :arr, :dep, "
            " '[]', :fetched)"
        ),
        {
            "id": "c0ffee00000000000000000000001197",
            "sign": sign,
            "arr": datetime.fromisoformat(arrival),
            "dep": datetime.fromisoformat(departure),
            "fetched": datetime.fromisoformat("2026-09-26T00:00:00+00:00"),
        },
    )


@pytest.mark.asyncio
async def test_departure_twelve_hours_off_the_public_record_is_pointed_at(session, vessel_id):
    """출항을 12시간 어긋나게 넣은 항차가 「공적 기록과 다름」으로 뜬다 (`#1197` · `§17.4.4`).

    공적 기록: 부산 출항 2026-03-01 12:00Z. 항차의 실제 출항은 00:00Z(`_voyage`) — 12시간.
    값을 바꾸지 않고 **완결성에도 넣지 않는다** — 깨끗한 항차라 완결성은 그대로 1이다.
    """
    await session.execute(
        text("UPDATE vessel SET call_sign = 'DQ1197' WHERE id = :id"), {"id": vessel_id}
    )
    await _port_call(
        session,
        sign="DQ1197",
        arrival="2026-02-28T20:00:00+00:00",
        departure="2026-03-01T12:00:00+00:00",
    )
    await _voyage(session, vessel_id, no="A")
    await _voyage(session, vessel_id, no="B")

    vessel, issues, summary = await _mine(session, vessel_id)

    public = _by(issues, SEVERITY_PUBLIC_RECORD)
    assert len(public) == 2  # 두 항차 모두 같은 출항 시각을 넣었다
    item = public[0]
    assert item["codes"] == ["PUBLIC_RECORD:DEPARTURE"]
    block = item["public_record"]
    assert block["source"] == "MOF_VESSEL_OPS"
    assert block["fetched_at"].startswith("2026-09-26T00:00:00")
    [mismatch] = block["mismatches"]
    assert mismatch["field"] == "DEPARTURE"
    assert mismatch["difference_minutes"] == 12 * 60
    assert mismatch["port_authority_code"] == "020"
    assert mismatch["port_authority_name"] == "부산"
    assert summary["public_record_count"] >= 2
    # 대조는 계산 입력이 아니다 — 실측 항차의 완결성은 그대로다
    assert vessel["completeness_ratio"] == "1.0000"


@pytest.mark.asyncio
async def test_within_six_hours_or_without_call_sign_raises_nothing(session, vessel_id):
    """6시간 안이면 띄우지 않고, 호출부호가 없는 배는 기록이 있어도 견주지 않는다."""
    await _port_call(
        session,
        sign="DQ1198",
        arrival="2026-02-28T20:00:00+00:00",
        departure="2026-03-01T12:00:00+00:00",
    )
    await _voyage(session, vessel_id, no="A")
    # 호출부호 없음 — 12시간 어긋나도 대조하지 않는다(선박명으로 잇지 않는다)
    _, issues, _ = await _mine(session, vessel_id)
    assert _by(issues, SEVERITY_PUBLIC_RECORD) == []

    await session.execute(
        text("UPDATE vessel SET call_sign = 'DQ1198' WHERE id = :id"), {"id": vessel_id}
    )
    await session.execute(
        text("UPDATE port_call_record SET departure_at = :dep WHERE call_sign = 'DQ1198'"),
        {"dep": datetime.fromisoformat("2026-03-01T06:00:00+00:00")},
    )
    _, issues, _ = await _mine(session, vessel_id)
    assert _by(issues, SEVERITY_PUBLIC_RECORD) == []  # 6시간 정각 — 띄우지 않는다


async def _period(session, vessel_id: str, voyage_id: str, *, kind: str, start: str, end: str):
    await session.execute(
        text(
            "INSERT INTO not_underway_period (vessel_id, regulation_year, period_type, "
            " started_at, ended_at, port_name, voyage_id) "
            "VALUES (:vid, :yr, :kind, :st, :en, 'BUSAN', :voy)"
        ),
        {
            "vid": vessel_id,
            "yr": YEAR,
            "kind": kind,
            "st": datetime.fromisoformat(start),
            "en": datetime.fromisoformat(end),
            "voy": voyage_id,
        },
    )


async def _stay_scenario(session, vessel_id: str, sign: str, kind: str) -> list[dict]:
    """공적 기록: 부산 입항 02-20 00:00Z · 출항 02-21 00:00Z. 구간 시작을 12시간 늦게 넣는다."""
    await session.execute(
        text("UPDATE vessel SET call_sign = :sign WHERE id = :id"), {"sign": sign, "id": vessel_id}
    )
    await _port_call(
        session,
        sign=sign,
        arrival="2026-02-20T00:00:00+00:00",
        departure="2026-02-21T00:00:00+00:00",
    )
    voyage_id = await _voyage(session, vessel_id, no="A")
    await _period(
        session,
        vessel_id,
        voyage_id,
        kind=kind,
        start="2026-02-20T12:00:00+00:00",
        end="2026-02-21T00:00:00+00:00",
    )
    _, issues, _ = await _mine(session, vessel_id)
    return _by(issues, SEVERITY_PUBLIC_RECORD)


@pytest.mark.asyncio
async def test_port_stay_period_start_is_compared_with_arrival(session, vessel_id):
    """항차에 매인 정박 구간의 시작은 가장 이른 입항과 견준다 (`§17.4.4`)."""
    [item] = await _stay_scenario(session, vessel_id, "DQ1199", "IN_PORT")
    assert item["codes"] == ["PUBLIC_RECORD:BERTH_START"]
    [mismatch] = item["public_record"]["mismatches"]
    assert mismatch["field"] == "BERTH_START"
    assert mismatch["difference_minutes"] == 12 * 60


@pytest.mark.asyncio
async def test_drydock_period_is_not_compared(session, vessel_id):
    """드라이독 구간은 입출항 신고와 대응하지 않는다 — 같은 시각이어도 견주지 않는다."""
    assert await _stay_scenario(session, vessel_id, "DQ1200", "DRYDOCK") == []
