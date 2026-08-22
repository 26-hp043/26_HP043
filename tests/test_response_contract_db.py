"""응답 계약 — 서버가 내는 필드 집합을 잠근다 (#559).

## 요청은 강제되고 응답은 강제되지 않았다

`#559` 실측이다.

    전체 오퍼레이션          50
    requestBody 스키마 있음  23   ← Pydantic 모델이 강제한다
    200 응답 스키마 있음      0   ← 하나도 없다

라우트 46개가 ``dict[str, object]``를 돌려주므로 FastAPI가 그 이상을 알 수 없고,
**응답이 조용히 바뀌어도 아무것도 잡지 않는다.**

## 왜 값이 아니라 **키**를 보는가

이 저장소가 반복해서 겪은 형태다 — 규칙은 지켜지고 있는데 확인하는 것이 없어
**어긋나는 순간을 아무도 모른다**(`#511` · `#534` · `#399` · `#523`).

응답 계약이 어긋나면 화면에 ``undefined``가 뜨거나 값이 **조용히 빠진다.** 앞의
사례들과 달리 **오류가 나지 않으므로** 더 늦게 발견된다. 그리고 그 결함의 실제
모습은 **이름이 바뀌거나 필드가 빠지는 것**이지 값이 틀리는 것이 아니다.

값까지 대조하는 안(`API_SPEC` 예시 30곳과 맞추기)은 유지비가 크고, 응답 모델
도입안(`response_model`)은 `API_SPEC §1.7`(Layer-1은 문자열)과의 양립 검토가
선행한다 — `#559`가 **B안**을 권고한 이유이며 그대로 따른다.

## 집합이 **같아야** 한다 (부분집합이 아니라)

필드가 늘어도 실패한다. 그것이 의도다 — 응답 계약이 넓어지는 것은 **화면 세 곳이
각자 타입을 고쳐야 한다**는 뜻이고(`#559` 코멘트: 같은 엔드포인트를 `ServerVoyage`
세 벌이 각자 적고 있다), 그 변화가 리뷰에 보여야 한다.

## 목록이 비면 조용히 통과하지 않는다

``data[]``가 빈 배열이면 그 아래 키가 통째로 사라진다. 집합 **동등** 비교라
그때 실패한다 — 부분집합 비교였다면 「빈 응답이 계약을 만족한다」가 된다.

`/calculations`가 정확히 그 자리다. 새 DB에서는 이력이 0건이므로 **테스트가 먼저
계산을 하나 만들고** 조회한다.

## 데이터

데모 시드(`conftest.migrated_db`)가 넣는 고정 UUID 선박을 쓴다. 시드가 바뀌어
항차·정박 구간이 사라지면 이 테스트가 먼저 깨진다 — 그것도 알아야 하는 변화다.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from cii_platform.api.main import API_V1_PREFIX, app

#: 데모 시드의 고정 선박 (`db/demo_seed.py`).
DEMO_VESSEL = "00000000-0000-4000-8000-000000000003"

_BASE = "https://testserver"


@pytest.fixture
def client(migrated_db, app_fresh_engine):
    with TestClient(app, base_url=_BASE) as c:
        c.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        yield c


def flatten(value: Any, prefix: str = "") -> set[str]:
    """응답을 **점 경로 키 집합**으로 편다.

    배열은 ``field[].key``로 적고 **모든 원소를 합집합**한다 — 첫 원소만 보면
    두 번째 항차에만 있는 필드를 놓친다.
    """
    keys: set[str] = set()
    if isinstance(value, dict):
        for name, child in value.items():
            path = f"{prefix}{name}"
            keys.add(path)
            keys |= flatten(child, f"{path}.")
    elif isinstance(value, list):
        for item in value:
            keys |= flatten(item, f"{prefix[:-1]}[].")
    return keys


#: 엔드포인트별 응답 필드 집합. 키는 요청 경로, 값은 :func:`flatten` 결과다.
#:
#: **여기를 고치는 것이 곧 계약 변경이다.** 필드를 늘리거나 이름을 바꾸면 이 표를
#: 함께 고쳐야 하고, 그 diff가 리뷰에 보인다.
#:
#: ⚠️ ``/calculations``는 **종류를 한정해 부른다** (`#587` 작업 중 발견). 이 목록은
#: 기능①·②·③ 실행을 함께 돌려주는데 ``model_version``의 모양이 기능마다 다르다 —
#: 연간 시뮬레이션 실행이 하나라도 있으면 ``model_version.issue``가 늘어난다. 한정하지
#: 않으면 **DB에 무엇이 쌓여 있느냐에 따라 계약이 달라져** 새 DB에서만 통과한다.
CONTRACTS: dict[str, frozenset[str]] = {
    # `API_SPEC §10`
    "/health": frozenset(
        {
            "data",
            "data.numpy_version",
            "data.rng_canonical_test",
            "data.status",
            "data.version",
        }
    ),
    # `API_SPEC §1.2`
    "/auth/me": frozenset(
        {
            "data",
            "data.display_name",
            "data.email",
            "data.email_verified_at",
            "data.id",
            "data.last_login_at",
            "meta",
            "meta.request_id",
            "meta.timestamp",
        }
    ),
    # `API_SPEC §2.1`
    "/vessels": frozenset(
        {
            "data",
            "data[].created_at",
            "data[].current_lat",
            "data[].current_lon",
            "data[].deadweight",
            "data[].default_fuel_type",
            "data[].detail_status",
            "data[].gross_tonnage",
            "data[].id",
            "data[].imo_number",
            "data[].is_cii_applicable_hint",
            "data[].name",
            "data[].position_updated_at",
            "data[].reference_daily_foc_ton",
            "data[].reference_speed_kn",
            "data[].ship_type",
            "data[].underway_state",
            "data[].updated_at",
            "meta",
            "meta.has_more",
            "meta.next_cursor",
            "meta.request_id",
            "meta.timestamp",
        }
    ),
    # `API_SPEC §2.2`
    "/vessels/{vessel_id}": frozenset(
        {
            "data",
            "data.created_at",
            "data.current_lat",
            "data.current_lon",
            "data.deadweight",
            "data.default_fuel_type",
            "data.detail_status",
            "data.gross_tonnage",
            "data.id",
            "data.imo_number",
            "data.is_cii_applicable_hint",
            "data.name",
            "data.position_updated_at",
            "data.reference_daily_foc_ton",
            "data.reference_speed_kn",
            "data.ship_type",
            "data.underway_state",
            "data.updated_at",
            "meta",
            "meta.request_id",
            "meta.timestamp",
        }
    ),
    # `API_SPEC §2.7`
    "/vessels/{vessel_id}/cii-history": frozenset(
        {
            "data",
            "data.from",
            "data.to",
            "data.transport_capacity_basis",
            "data.vessel_id",
            "data.years",
            "data.years[].attained_cii",
            "data.years[].data_available",
            "data.years[].rating",
            "data.years[].reason",
            "data.years[].regulation_year",
            "data.years[].required_cii",
            "data.years[].status",
            "data.years[].total_distance_nm",
            "data.years[].total_fuel_ton",
            "data.years[].voyage_count",
            "meta",
            "meta.as_of",
            "meta.request_id",
            "meta.timestamp",
        }
    ),
    # `API_SPEC §2.11`
    "/vessels/{vessel_id}/cii/current": frozenset(
        {
            "data",
            "data.current_voyage",
            "data.regulation_year",
            "data.transport_capacity_basis",
            "data.underway_state",
            "data.vessel_id",
            "data.vessel_name",
            "data.warnings",
            "data.year_end_projection",
            "data.year_end_projection.assumptions",
            "data.year_end_projection.assumptions.daily_distance_nm",
            "data.year_end_projection.assumptions.daily_fuel_ton",
            "data.year_end_projection.assumptions.elapsed_days",
            "data.year_end_projection.assumptions.fuel_type",
            "data.year_end_projection.assumptions.method",
            "data.year_end_projection.assumptions.projected_extra_distance_nm",
            "data.year_end_projection.assumptions.projected_extra_fuel_ton",
            "data.year_end_projection.assumptions.remaining_days",
            "data.year_end_projection.attained_cii",
            "data.year_end_projection.data_available",
            "data.year_end_projection.rating",
            "data.year_end_projection.ratio_to_required",
            "data.year_end_projection.reason",
            "data.year_end_projection.required_cii",
            "data.year_end_projection.risk_level",
            "data.ytd",
            "data.ytd.attained_cii",
            "data.ytd.boundaries",
            "data.ytd.boundaries.inferior_boundary",
            "data.ytd.boundaries.lower_boundary",
            "data.ytd.boundaries.superior_boundary",
            "data.ytd.boundaries.upper_boundary",
            "data.ytd.data_available",
            "data.ytd.margin_ratio",
            "data.ytd.not_underway_distance_nm",
            "data.ytd.not_underway_period_count",
            "data.ytd.rating",
            "data.ytd.ratio_to_required",
            "data.ytd.required_cii",
            "data.ytd.risk_level",
            "data.ytd.substitutions",
            "data.ytd.total_co2_ton",
            "data.ytd.total_distance_nm",
            "data.ytd.total_fuel_ton",
            "data.ytd.underway_distance_nm",
            "data.ytd.voyage_count",
            "meta",
            "meta.as_of",
            "meta.request_id",
            "meta.simulated",
            "meta.timestamp",
        }
    ),
    # `API_SPEC §3.1`
    "/vessels/{vessel_id}/voyages": frozenset(
        {
            "data",
            "data[].actual_arrival_at",
            "data[].actual_avg_speed_kn",
            "data[].actual_departure_at",
            "data[].actual_distance_nm",
            "data[].annual_inclusion_policy",
            "data[].arrival_lat",
            "data[].arrival_lon",
            "data[].arrival_port_name",
            "data[].created_at",
            "data[].created_from",
            "data[].departure_lat",
            "data[].departure_lon",
            "data[].departure_port_name",
            "data[].fuel_uses",
            "data[].fuel_uses[].actual_fuel_ton",
            "data[].fuel_uses[].cf_used",
            "data[].fuel_uses[].fuel_type",
            "data[].fuel_uses[].id",
            "data[].fuel_uses[].planned_fuel_ton",
            "data[].fuel_uses[].source",
            "data[].id",
            "data[].notes",
            "data[].planned_arrival_at",
            "data[].planned_departure_at",
            "data[].planned_distance_nm",
            "data[].planned_speed_kn",
            "data[].regulation_year",
            "data[].status",
            "data[].vessel_id",
            "data[].voyage_no",
            "meta",
            "meta.has_more",
            "meta.next_cursor",
            "meta.request_id",
            "meta.timestamp",
        }
    ),
    # `API_SPEC §3.2`
    "/voyages/{voyage_id}": frozenset(
        {
            "data",
            "data.actual_arrival_at",
            "data.actual_avg_speed_kn",
            "data.actual_departure_at",
            "data.actual_distance_nm",
            "data.annual_inclusion_policy",
            "data.arrival_lat",
            "data.arrival_lon",
            "data.arrival_port_name",
            "data.created_at",
            "data.created_from",
            "data.departure_lat",
            "data.departure_lon",
            "data.departure_port_name",
            "data.fuel_uses",
            "data.fuel_uses[].actual_fuel_ton",
            "data.fuel_uses[].cf_used",
            "data.fuel_uses[].fuel_type",
            "data.fuel_uses[].id",
            "data.fuel_uses[].planned_fuel_ton",
            "data.fuel_uses[].source",
            "data.id",
            "data.notes",
            "data.planned_arrival_at",
            "data.planned_departure_at",
            "data.planned_distance_nm",
            "data.planned_speed_kn",
            "data.regulation_year",
            "data.status",
            "data.vessel_id",
            "data.voyage_no",
            "meta",
            "meta.request_id",
            "meta.timestamp",
        }
    ),
    # `API_SPEC §2.9`
    "/vessels/{vessel_id}/not-underway-periods": frozenset(
        {
            "data",
            "data[].created_at",
            "data[].distance_nm",
            "data[].ended_at",
            "data[].fuel_uses",
            "data[].fuel_uses[].cf_used",
            "data[].fuel_uses[].consumer_type",
            "data[].fuel_uses[].fuel_ton",
            "data[].fuel_uses[].fuel_type",
            "data[].fuel_uses[].id",
            "data[].fuel_uses[].period_id",
            "data[].id",
            "data[].lat",
            "data[].lon",
            "data[].period_type",
            "data[].port_name",
            "data[].regulation_year",
            "data[].started_at",
            "data[].vessel_id",
            "data[].voyage_id",
            "meta",
            "meta.consumer_types",
            "meta.period_types",
            "meta.request_id",
            "meta.timestamp",
            "meta.total",
        }
    ),
    # `API_SPEC §2.8`
    "/fleet/summary?year=2026": frozenset(
        {
            "data",
            "data.actions",
            "data.actions[].message",
            "data.actions[].reason",
            "data.actions[].severity",
            "data.actions[].vessel_id",
            "data.actions[].vessel_name",
            "data.as_of",
            "data.regulation_year",
            "data.summary",
            "data.summary.at_risk",
            "data.summary.no_data",
            "data.summary.not_under_way",
            "data.summary.rating_distribution",
            "data.summary.rating_distribution.A",
            "data.summary.rating_distribution.B",
            "data.summary.rating_distribution.C",
            "data.summary.rating_distribution.D",
            "data.summary.rating_distribution.E",
            "data.summary.total",
            "data.summary.under_way",
            "data.summary.unknown_state",
            "data.vessels",
            "data.vessels[].current_lat",
            "data.vessels[].current_lon",
            "data.vessels[].data_available",
            "data.vessels[].days_to_d",
            "data.vessels[].days_to_d_reason",
            "data.vessels[].detail_status",
            "data.vessels[].gross_tonnage",
            "data.vessels[].imo_number",
            "data.vessels[].is_cii_applicable_hint",
            "data.vessels[].name",
            "data.vessels[].position_updated_at",
            "data.vessels[].risk_level",
            "data.vessels[].risk_reasons",
            "data.vessels[].ship_type",
            "data.vessels[].unavailable_reason",
            "data.vessels[].underway_state",
            "data.vessels[].vessel_id",
            "data.vessels[].ytd_attained_cii",
            "data.vessels[].ytd_rating",
            "data.vessels[].ytd_required_cii",
            "meta",
            "meta.as_of",
            "meta.request_id",
            "meta.timestamp",
        }
    ),
    # `API_SPEC §7.1`
    "/parameters/regulation-years": frozenset(
        {
            "data",
            "data[].effective_from",
            "data[].source_ref",
            "data[].version",
            "data[].year",
            "data[].z_factor_percent",
            "meta",
            "meta.request_id",
            "meta.timestamp",
            "meta.total",
        }
    ),
    # `API_SPEC §7.2`
    "/parameters/fuel-types": frozenset(
        {
            "data",
            "data[].cf",
            "data[].code",
            "data[].display_name",
            "data[].is_active",
            "data[].source_ref",
            "data[].unit",
            "meta",
            "meta.request_id",
            "meta.timestamp",
            "meta.total",
        }
    ),
    # `API_SPEC §7.3`
    "/parameters/reference-lines?regulation_year=2026": frozenset(
        {
            "data",
            "data[].a_decimal",
            "data[].a_raw",
            "data[].c",
            "data[].capacity_rule",
            "data[].condition_expr",
            "data[].ship_type",
            "data[].source_ref",
            "meta",
            "meta.request_id",
            "meta.timestamp",
            "meta.total",
        }
    ),
    # `API_SPEC §7.4`
    "/parameters/rating-boundaries?regulation_year=2026": frozenset(
        {
            "data",
            "data[].capacity_basis",
            "data[].condition_expr",
            "data[].d1",
            "data[].d2",
            "data[].d3",
            "data[].d4",
            "data[].ship_type",
            "data[].source_ref",
            "meta",
            "meta.request_id",
            "meta.timestamp",
            "meta.total",
        }
    ),
    # `API_SPEC §1.9` — **종류를 한정한다.** 아래 각주 참조.
    "/calculations?type=VOYAGE_ESTIMATE": frozenset(
        {
            "data",
            "data[].calculation_run_id",
            "data[].calculation_type",
            "data[].created_at",
            "data[].input_hash",
            "data[].model_version",
            "data[].model_version.decimal_precision",
            "data[].model_version.decimal_rounding",
            "data[].model_version.engine",
            "data[].model_version.numpy_version",
            "data[].model_version.python_version",
            "data[].model_version.rng_algorithm",
            "data[].needs_recalc",
            "data[].parameter_hash",
            "data[].result_summary",
            "data[].result_summary.attained_cii",
            "data[].result_summary.estimated_rating",
            "data[].vessel_id",
            "data[].voyage_id",
            "meta",
            "meta.has_more",
            "meta.next_cursor",
            "meta.request_id",
            "meta.timestamp",
        }
    ),
    # `API_SPEC §4.1`
    "POST /calculations/voyage-cii": frozenset(
        {
            "calculation_run_id",
            "data",
            "data.attained_cii",
            "data.calculation_basis",
            "data.calculation_basis.a_decimal",
            "data.calculation_basis.c",
            "data.calculation_basis.fuel_cf_details",
            "data.calculation_basis.fuel_cf_details[].cf",
            "data.calculation_basis.fuel_cf_details[].fuel_ton",
            "data.calculation_basis.fuel_cf_details[].fuel_type",
            "data.calculation_basis.ship_type",
            "data.calculation_basis.z_factor_percent",
            "data.co2_emission_ton",
            "data.distance_nm",
            "data.estimated_rating",
            "data.fuel_consumption_ton",
            "data.next_worse_boundary_margin",
            "data.next_worse_boundary_margin_ratio",
            "data.ratio_to_required",
            "data.reference_capacity",
            "data.reference_capacity_rule",
            "data.required_cii",
            "data.risk_level",
            "data.transport_capacity",
            "data.transport_capacity_basis",
            "disclaimer",
            "input_hash",
            "meta",
            "meta.duration_ms",
            "meta.request_id",
            "meta.timestamp",
            "model_version",
            "model_version.decimal_precision",
            "model_version.decimal_rounding",
            "model_version.engine",
            "model_version.numpy_version",
            "model_version.python_version",
            "model_version.rng_algorithm",
            "parameter_hash",
            "parameters_used",
            "parameters_used.fuel_types",
            "parameters_used.fuel_types[].cf",
            "parameters_used.fuel_types[].code",
            "parameters_used.parameter_source_version",
            "parameters_used.rating_boundary",
            "parameters_used.rating_boundary.d1",
            "parameters_used.rating_boundary.d2",
            "parameters_used.rating_boundary.d3",
            "parameters_used.rating_boundary.d4",
            "parameters_used.reference_line",
            "parameters_used.reference_line.a_decimal",
            "parameters_used.reference_line.c",
            "parameters_used.reference_line.reference_capacity_rule",
            "parameters_used.reference_line.ship_type",
            "parameters_used.regulation_year",
            "parameters_used.regulation_year.year",
            "parameters_used.regulation_year.z_factor_percent",
            "warnings",
        }
    ),
}


def _resolve(client: TestClient, path: str) -> str:
    """경로의 자리표시자를 데모 데이터의 실제 식별자로 바꾼다.

    계약 표의 키를 `{vessel_id}`로 두는 이유는 **UUID가 표에 박히면 시드가 바뀔 때
    표가 무엇을 가리키는지 알 수 없게 되기** 때문이다. 항차 id는 고정값을 적지 않고
    목록에서 **읽어 온다** — 시드가 항차 순서를 바꿔도 따라간다.
    """
    resolved = path.replace("{vessel_id}", DEMO_VESSEL)
    if "{voyage_id}" in resolved:
        listing = client.get(f"{API_V1_PREFIX}/vessels/{DEMO_VESSEL}/voyages").json()
        assert listing["data"], "데모 선박에 항차가 없다 — 시드를 확인할 것"
        resolved = resolved.replace("{voyage_id}", listing["data"][0]["id"])
    return resolved


def _get(client: TestClient, path: str):
    return client.get(f"{API_V1_PREFIX}{_resolve(client, path)}")


@pytest.mark.parametrize("path", [p for p in CONTRACTS if not p.startswith("POST ")])
def test_response_fields_match_the_contract(client, path):
    """GET 응답의 필드 집합이 계약과 **같다**."""
    response = _get(client, path)

    assert response.status_code == 200, response.text
    assert flatten(response.json()) == CONTRACTS[path]


def test_voyage_cii_response_fields_match_the_contract(client):
    """`POST /calculations/voyage-cii` (`API_SPEC §4.1`) — 화면이 가장 많이 매핑하는 응답.

    계산 이력을 하나 만들어 두는 역할도 한다 — 아래 `/calculations` 테스트가
    **빈 목록으로 조용히 통과하지 않게** 하려면 이력이 있어야 한다.
    """
    response = client.post(
        f"{API_V1_PREFIX}/calculations/voyage-cii",
        headers={"X-CSRF-Token": client.cookies.get("csrf")},
        json={
            "vessel_id": DEMO_VESSEL,
            "distance_nm": 1100,
            "speed_kn": 12.8,
            "regulation_year": 2026,
            "fuel_uses": [{"fuel_type": "HFO", "fuel_ton": 45}],
        },
    )

    assert response.status_code == 200, response.text
    assert flatten(response.json()) == CONTRACTS["POST /calculations/voyage-cii"]


def test_calculation_history_is_not_empty_before_it_is_compared(client):
    """`/calculations`는 **새 DB에서 0건**이다 (`#559` 작업 중 실측).

    이력이 없으면 `data[]` 아래 키가 통째로 사라지고, 부분집합 비교였다면 그대로
    통과했을 것이다. 집합 동등 비교라 실패하지만 **원인이 「계약이 바뀌었다」로
    읽히므로** 여기서 먼저 하나 만들어 둔다.
    """
    client.post(
        f"{API_V1_PREFIX}/calculations/voyage-cii",
        headers={"X-CSRF-Token": client.cookies.get("csrf")},
        json={
            "vessel_id": DEMO_VESSEL,
            "distance_nm": 1100,
            "speed_kn": 12.8,
            "regulation_year": 2026,
            "fuel_uses": [{"fuel_type": "HFO", "fuel_ton": 45}],
        },
    )

    body = _get(client, "/calculations?type=VOYAGE_ESTIMATE").json()
    assert body["data"], "계산 이력이 비어 있다 — 아래 계약 대조가 의미를 잃는다"


def test_every_contract_is_actually_checked():
    """계약이 하나라도 빠지면 **검사하지 않는 엔드포인트**가 생긴다.

    파라미터라이즈 목록이 `CONTRACTS`에서 나오므로 표를 지우면 검사도 함께
    사라진다 — 그것이 조용히 일어나지 않게 개수를 박는다.
    """
    assert len(CONTRACTS) >= 16
    assert sum(len(keys) for keys in CONTRACTS.values()) >= 400
    # 중첩까지 본다 — 최상위만 보면 `data` 한 칸이 통째로 바뀌어도 통과한다.
    assert any("." in key for keys in CONTRACTS.values() for key in keys)
    assert any("[]" in key for keys in CONTRACTS.values() for key in keys)


def test_meta_block_is_on_every_json_response():
    """`API_SPEC §1.1` — 모든 JSON 응답에 `meta.request_id` · `meta.timestamp`가 있다.

    계약 표를 눈으로 훑지 않고 **규칙으로** 확인한다. 표를 손으로 고치다 한 줄을
    빠뜨려도 여기서 걸린다.
    """
    without_meta = [
        path
        for path, keys in CONTRACTS.items()
        if path != "/health" and not {"meta.request_id", "meta.timestamp"} <= keys
    ]
    assert without_meta == []
