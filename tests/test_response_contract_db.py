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

import ast
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cii_platform.api.main import API_V1_PREFIX, app

#: 데모 시드의 고정 선박 (`db/demo_seed.py`).
DEMO_VESSEL = "00000000-0000-4000-8000-000000000003"

_BASE = "https://testserver"
_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(migrated_db, app_fresh_engine):
    with TestClient(app, base_url=_BASE) as c:
        c.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        yield c


def _ensure_calculation_history(c: TestClient) -> None:
    """계산 이력이 **최소 한 건** 있게 한다.

    `/calculations`는 **새 DB에서 0건**이다(`#559` 작업 중 실측). 이력이 없으면 응답의
    ``data``가 빈 배열이 되어 ``data[].*`` 키가 **통째로 사라지고**, 집합 동등 비교가
    「계약이 바뀌었다」로 실패한다 — **실제 원인은 「행이 없다」인데.**
    """
    c.post(
        f"{API_V1_PREFIX}/calculations/voyage-cii",
        headers={"X-CSRF-Token": c.cookies.get("csrf")},
        json={
            "vessel_id": DEMO_VESSEL,
            "distance_nm": 1100,
            "speed_kn": 12.8,
            "regulation_year": 2026,
            "fuel_uses": [{"fuel_type": "HFO", "fuel_ton": 45}],
        },
    )


@pytest.fixture
def client_with_history(client):
    """계산 이력이 보장된 ``client`` (`#838`).

    ## 왜 fixture인가

    종전에는 이력을 만드는 테스트(``test_calculation_history_is_not_empty_before_it_is_compared``)가
    **비교 테스트보다 파일 아래쪽**에 있었다. pytest는 정의 순서로 돌므로 **비교가 먼저**
    돌았고, 그 docstring은 「여기서 **먼저** 하나 만들어 둔다」라고 적고 있었다 —
    **의도는 「먼저」인데 배치가 「나중」이었다.**

    전체 스위트에서는 알파벳순으로 앞선 파일들이 이미 행을 만들어 두어 **가려졌다.**
    드러나는 것은 이 파일만 단독으로 돌릴 때 — 계약을 고칠 때 가장 자연스러운 작업
    방식이다 — 그리고 DB를 막 새로 띄웠을 때다(2026-09-11 Docker 재시작 직후 실제로 났다).

    순서를 바꾸는 대신 **의존을 선언**한다. 순서에 기대면 무작위 순서 도구를 넣는 순간
    CI에서도 간헐 실패가 된다.
    """
    _ensure_calculation_history(client)
    return client


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
            # 리포트 PDF에 한글을 그릴 수 있는가 (`#689`). "ok"/"missing"/"unavailable".
            "data.pdf_korean_font",
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
    # `API_SPEC §2.15` (#982) — 선박 등록 화면이 제원을 채우는 샘플 목록
    "/vessels/samples": frozenset(
        {
            "data",
            "data[].default_fuel_type",
            "data[].deadweight",
            "data[].gross_tonnage",
            "data[].label",
            "data[].reference_daily_foc_ton",
            "data[].reference_speed_kn",
            "data[].sample_id",
            "data[].ship_type",
            "meta",
            "meta.request_id",
            "meta.timestamp",
        }
    ),
    # `API_SPEC §3.8` (#760) — 항차 입력이 출발·도착항의 이름·좌표를 채우는 샘플 항만
    "/ports/samples": frozenset(
        {
            "data",
            "data[].country_code",
            "data[].lat",
            "data[].locode",
            "data[].lon",
            "data[].name",
            "data[].name_ko",
            "meta",
            "meta.request_id",
            "meta.timestamp",
        }
    ),
    # `API_SPEC §3.9` (#760) — 좌표 기반 추정 거리(부산 → 싱가포르)
    "/ports/great-circle?from_lat=35.1&from_lon=129.0333&to_lat=1.2833&to_lon=103.85": frozenset(
        {"data", "data.distance_nm", "data.method", "meta", "meta.request_id", "meta.timestamp"}
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
            "data.years[].in_progress_voyage_count",
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
            # `#798` — 산출 방식이 일평균 외삽 → 남은 거리 기반으로 바뀌며 필드가
            # 교체됐다. `daily_*`·`elapsed_days`·`projected_extra_*`·`fuel_type`은
            # 일평균 외삽에서만 뜻이 있던 값이다.
            "data.year_end_projection.assumptions",
            "data.year_end_projection.assumptions.completed_co2_ton",
            "data.year_end_projection.assumptions.completed_distance_nm",
            "data.year_end_projection.assumptions.method",
            "data.year_end_projection.assumptions.planned_co2_ton",
            "data.year_end_projection.assumptions.planned_distance_nm",
            "data.year_end_projection.assumptions.remaining_days",
            "data.year_end_projection.assumptions.remaining_voyage_count",
            "data.year_end_projection.attained_cii",
            "data.year_end_projection.data_available",
            "data.year_end_projection.rating",
            "data.year_end_projection.ratio_to_required",
            "data.year_end_projection.reason",
            "data.year_end_projection.required_cii",
            "data.year_end_projection.risk_level",
            "data.year_end_projection.warnings",
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
            "data.ytd.in_progress_voyage_count",
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
            # `vessels[]`만 페이지로 자른다 — `§1.5` 페이지 정보 (#772)
            "meta.has_more",
            "meta.next_cursor",
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
    # `API_SPEC §5.1` — 기능② 시나리오 비교 (#753). 계산 봉투 7필드를 함께 본다.
    "POST /scenarios/compare": frozenset(
        {
            "calculation_run_id",
            "data",
            "data.scenarios",
            "data.scenarios[].attained_cii",
            "data.scenarios[].calculation_basis",
            "data.scenarios[].calculation_basis.a_decimal",
            "data.scenarios[].calculation_basis.c",
            "data.scenarios[].calculation_basis.reference_capacity",
            "data.scenarios[].calculation_basis.reference_capacity_rule",
            "data.scenarios[].calculation_basis.ship_type",
            "data.scenarios[].calculation_basis.transport_capacity",
            "data.scenarios[].calculation_basis.transport_capacity_basis",
            "data.scenarios[].calculation_basis.z_factor_percent",
            "data.scenarios[].co2_emission_ton",
            "data.scenarios[].distance_nm",
            "data.scenarios[].duration_hours",
            "data.scenarios[].estimated_rating",
            "data.scenarios[].fuel_ton",
            "data.scenarios[].next_worse_boundary_margin",
            "data.scenarios[].next_worse_boundary_margin_ratio",
            "data.scenarios[].ratio_to_required",
            "data.scenarios[].required_cii",
            "data.scenarios[].risk_level",
            "data.scenarios[].scenario_id",
            "data.scenarios[].scenario_name",
            "data.scenarios[].scenario_type",
            "data.scenarios[].speed_kn",
            "data.scenarios[].weather_factor",
            "data.scenarios[].weather_model_used",
            "data.summary",
            "data.summary.lowest_cii_scenarios",
            "data.summary.lowest_fuel_scenarios",
            "data.summary.shortest_duration_scenarios",
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
    # `API_SPEC §6.3` — 실행 당시 스냅샷 항차 (#753). 저장 형태가 아니라 **응답 형태**다.
    "GET /annual-simulations/{id}/snapshot-voyages": frozenset(
        {
            "data",
            "data[].annual_inclusion_policy",
            "data[].distance_nm",
            "data[].fuel_uses",
            "data[].fuel_uses[].cf_used",
            "data[].fuel_uses[].fuel_ton",
            "data[].fuel_uses[].fuel_type",
            "data[].original_voyage_id",
            "data[].snapshot_voyage_id",
            "data[].speed_kn",
            "data[].status_at_snapshot",
            "data[].voyage_no",
            "meta",
            "meta.request_id",
            "meta.timestamp",
        }
    ),
    # `API_SPEC §6.4` — 재현 검증 (#753). `§6.1`과 같은 봉투여야 한다.
    #
    # ⚠️ **민감도의 `voyage_plus_1`·`voyage_minus_1`은 이 표에 없다.**
    # `calc/annual_simulation.py`가 `if remaining:`으로 가른다 — `PRD §12.6`의 「잔여
    # 항차 1개 취소/추가」는 **항차가 있어야 성립하는 지렛대**이기 때문이다. 데모 시드는
    # 스냅샷에 잔여 계획이 잡히지 않아 그 여섯 키가 나오지 않는다.
    #
    # 표에 넣으면 거짓 실패가 나고, 뺐으므로 **그 지렛대가 사라져도 이 검사는 통과한다.**
    # 그 공백을 감추지 않고 적어 둔다 — 지렛대 자체의 검증은 `#756`(기능③ 민감도)
    # 소관이고, 시드에 잔여 계획을 넣는 것은 이 파일의 다른 계약(항차 목록·선대 요약)을
    # 함께 흔든다.
    "POST /annual-simulations/{id}/reproduce": frozenset(
        {
            "calculation_run_id",
            "data",
            "data.deterministic",
            "data.deterministic.completed_M_gco2",
            "data.deterministic.completed_W_capacity_nm",
            "data.deterministic.completed_voyage_count",
            "data.deterministic.planned_M_gco2",
            "data.deterministic.planned_W_capacity_nm",
            "data.deterministic.projected_attained_cii",
            "data.deterministic.projected_rating",
            "data.deterministic.remaining_voyage_count",
            "data.monte_carlo",
            "data.monte_carlo.mean_cii",
            "data.monte_carlo.p10",
            "data.monte_carlo.p50",
            "data.monte_carlo.p90",
            "data.monte_carlo.rating_probabilities",
            "data.monte_carlo.rating_probabilities.A",
            "data.monte_carlo.rating_probabilities.B",
            "data.monte_carlo.rating_probabilities.C",
            "data.monte_carlo.rating_probabilities.D",
            "data.monte_carlo.rating_probabilities.E",
            "data.monte_carlo.rng_metadata",
            "data.monte_carlo.rng_metadata.bit_generator",
            "data.monte_carlo.rng_metadata.numpy_version",
            "data.monte_carlo.rng_metadata.platform",
            "data.monte_carlo.rng_metadata.python_version",
            "data.monte_carlo.rng_metadata.seed_entropy",
            "data.monte_carlo.runs",
            "data.monte_carlo.target_rating",
            "data.monte_carlo.target_success_probability",
            "data.risk_level",
            "data.sensitivity_analysis",
            "data.sensitivity_analysis.distance_minus_5pct",
            "data.sensitivity_analysis.distance_minus_5pct.projected_cii",
            "data.sensitivity_analysis.distance_minus_5pct.rating_change",
            "data.sensitivity_analysis.distance_plus_5pct",
            "data.sensitivity_analysis.distance_plus_5pct.projected_cii",
            "data.sensitivity_analysis.distance_plus_5pct.rating_change",
            "data.sensitivity_analysis.fuel_minus_10pct",
            "data.sensitivity_analysis.fuel_minus_10pct.projected_cii",
            "data.sensitivity_analysis.fuel_minus_10pct.rating_change",
            "data.sensitivity_analysis.fuel_minus_10pct.target_probability_change",
            "data.sensitivity_analysis.fuel_plus_10pct",
            "data.sensitivity_analysis.fuel_plus_10pct.projected_cii",
            "data.sensitivity_analysis.fuel_plus_10pct.rating_change",
            "data.sensitivity_analysis.fuel_plus_10pct.target_probability_change",
            "data.sensitivity_analysis.interaction_note",
            "data.sensitivity_analysis.speed_minus_1kn",
            "data.sensitivity_analysis.speed_minus_1kn.projected_cii",
            "data.sensitivity_analysis.speed_minus_1kn.rating_change",
            "data.sensitivity_analysis.speed_minus_1kn.target_probability_change",
            "data.sensitivity_analysis.speed_plus_1kn",
            "data.sensitivity_analysis.speed_plus_1kn.projected_cii",
            "data.sensitivity_analysis.speed_plus_1kn.rating_change",
            "data.sensitivity_analysis.speed_plus_1kn.target_probability_change",
            "data.simulation_id",
            "data.snapshot",
            "data.snapshot.created_at",
            "data.snapshot.snapshot_id",
            "data.snapshot.voyage_count",
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
            "parameters_used.rating_boundary",
            "parameters_used.rating_boundary.d1",
            "parameters_used.rating_boundary.d2",
            "parameters_used.rating_boundary.d3",
            "parameters_used.rating_boundary.d4",
            "parameters_used.rating_boundary.ship_type",
            "parameters_used.reference_line",
            "parameters_used.reference_line.a_decimal",
            "parameters_used.reference_line.c",
            "parameters_used.reference_line.reference_capacity_rule",
            "parameters_used.reference_line.ship_type",
            "parameters_used.regulation_year",
            "parameters_used.regulation_year.year",
            "parameters_used.regulation_year.z_factor_percent",
            "parameters_used.simulation_profile",
            "parameters_used.simulation_profile.parameters",
            "parameters_used.simulation_profile.parameters[].bound_type",
            "parameters_used.simulation_profile.parameters[].max",
            "parameters_used.simulation_profile.parameters[].min",
            "parameters_used.simulation_profile.parameters[].mode",
            "parameters_used.simulation_profile.parameters[].variable",
            "parameters_used.simulation_profile.profile",
            "parameters_used.simulation_profile.version",
            "warnings",
        }
    ),
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
    # `API_SPEC §6.1` · `§1.3.1` — 기능③ 실행 (`#752`). **`§6.2` 조회도 같은 집합**이라
    # 두 경로가 이 하나를 공유한다. 갈리면 「§6.1의 응답과 동일」이 거짓이 된다.
    "POST /annual-simulations": frozenset(
        {
            "calculation_run_id",
            "data",
            "data.deterministic",
            "data.deterministic.completed_M_gco2",
            "data.deterministic.completed_W_capacity_nm",
            "data.deterministic.completed_voyage_count",
            "data.deterministic.planned_M_gco2",
            "data.deterministic.planned_W_capacity_nm",
            "data.deterministic.projected_attained_cii",
            "data.deterministic.projected_rating",
            "data.deterministic.remaining_voyage_count",
            "data.monte_carlo",
            "data.monte_carlo.mean_cii",
            "data.monte_carlo.p10",
            "data.monte_carlo.p50",
            "data.monte_carlo.p90",
            "data.monte_carlo.rating_probabilities",
            "data.monte_carlo.rating_probabilities.A",
            "data.monte_carlo.rating_probabilities.B",
            "data.monte_carlo.rating_probabilities.C",
            "data.monte_carlo.rating_probabilities.D",
            "data.monte_carlo.rating_probabilities.E",
            "data.monte_carlo.rng_metadata",
            "data.monte_carlo.rng_metadata.bit_generator",
            "data.monte_carlo.rng_metadata.numpy_version",
            "data.monte_carlo.rng_metadata.platform",
            "data.monte_carlo.rng_metadata.python_version",
            "data.monte_carlo.rng_metadata.seed_entropy",
            "data.monte_carlo.runs",
            "data.monte_carlo.target_rating",
            "data.monte_carlo.target_success_probability",
            "data.risk_level",
            "data.sensitivity_analysis",
            "data.sensitivity_analysis.distance_minus_5pct",
            "data.sensitivity_analysis.distance_minus_5pct.projected_cii",
            "data.sensitivity_analysis.distance_minus_5pct.rating_change",
            "data.sensitivity_analysis.distance_plus_5pct",
            "data.sensitivity_analysis.distance_plus_5pct.projected_cii",
            "data.sensitivity_analysis.distance_plus_5pct.rating_change",
            "data.sensitivity_analysis.fuel_minus_10pct",
            "data.sensitivity_analysis.fuel_minus_10pct.projected_cii",
            "data.sensitivity_analysis.fuel_minus_10pct.rating_change",
            "data.sensitivity_analysis.fuel_minus_10pct.target_probability_change",
            "data.sensitivity_analysis.fuel_plus_10pct",
            "data.sensitivity_analysis.fuel_plus_10pct.projected_cii",
            "data.sensitivity_analysis.fuel_plus_10pct.rating_change",
            "data.sensitivity_analysis.fuel_plus_10pct.target_probability_change",
            "data.sensitivity_analysis.interaction_note",
            "data.sensitivity_analysis.speed_minus_1kn",
            "data.sensitivity_analysis.speed_minus_1kn.projected_cii",
            "data.sensitivity_analysis.speed_minus_1kn.rating_change",
            "data.sensitivity_analysis.speed_minus_1kn.target_probability_change",
            "data.sensitivity_analysis.speed_plus_1kn",
            "data.sensitivity_analysis.speed_plus_1kn.projected_cii",
            "data.sensitivity_analysis.speed_plus_1kn.rating_change",
            "data.sensitivity_analysis.speed_plus_1kn.target_probability_change",
            "data.simulation_id",
            "data.snapshot",
            "data.snapshot.created_at",
            "data.snapshot.snapshot_id",
            "data.snapshot.voyage_count",
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
            "parameters_used.rating_boundary",
            "parameters_used.rating_boundary.d1",
            "parameters_used.rating_boundary.d2",
            "parameters_used.rating_boundary.d3",
            "parameters_used.rating_boundary.d4",
            "parameters_used.rating_boundary.ship_type",
            "parameters_used.reference_line",
            "parameters_used.reference_line.a_decimal",
            "parameters_used.reference_line.c",
            "parameters_used.reference_line.reference_capacity_rule",
            "parameters_used.reference_line.ship_type",
            "parameters_used.regulation_year",
            "parameters_used.regulation_year.year",
            "parameters_used.regulation_year.z_factor_percent",
            "parameters_used.simulation_profile",
            "parameters_used.simulation_profile.parameters",
            "parameters_used.simulation_profile.parameters[].bound_type",
            "parameters_used.simulation_profile.parameters[].max",
            "parameters_used.simulation_profile.parameters[].min",
            "parameters_used.simulation_profile.parameters[].mode",
            "parameters_used.simulation_profile.parameters[].variable",
            "parameters_used.simulation_profile.profile",
            "parameters_used.simulation_profile.version",
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


@pytest.mark.parametrize(
    "path",
    # 접두가 붙은 것은 각자 전용 테스트가 본다 — 만들어야 하거나 식별자가 필요하다.
    [p for p in CONTRACTS if not p.startswith(("POST ", "GET "))],
)
def test_response_fields_match_the_contract(client_with_history, path):
    """GET 응답의 필드 집합이 계약과 **같다**."""
    response = _get(client_with_history, path)

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


def test_scenario_compare_response_fields_match_the_contract(client):
    """`POST /scenarios/compare` (`API_SPEC §5.1`) — 기능②가 계산 결과 봉투를 따르는가 (`#753`).

    **이 자리가 비어 있었다.** `#751`(`rng_metadata` 키 불일치)·`#752`(계산 봉투 7필드
    누락)가 어느 가드에도 걸리지 않은 이유가 그것이다 — 계약 표가 계산 엔드포인트의
    절반을 덮지 않았다.

    `test_scenario_example_sync.py`가 같은 엔드포인트의 **값**을 본다. 층이 다르다 —
    이쪽은 **필드 집합**이고, 값이 맞아도 필드가 빠지면 화면에 `undefined`가 뜬다.
    """
    response = client.post(
        f"{API_V1_PREFIX}/scenarios/compare",
        headers={"X-CSRF-Token": client.cookies.get("csrf")},
        json={
            "vessel_id": DEMO_VESSEL,
            "regulation_year": 2026,
            "direct_distance_nm": 1000,
            "current_speed_kn": 12.8,
            "base_daily_foc_ton": 26.88,
            "fuel_type": "HFO",
        },
    )

    assert response.status_code == 200, response.text
    assert flatten(response.json()) == CONTRACTS["POST /scenarios/compare"]


def test_snapshot_voyages_and_reproduce_match_the_contract(client):
    """`API_SPEC §6.3`·`§6.4` — 스냅샷 조회와 재현 검증 (`#753`).

    **한 테스트에서 둘을 본다.** 둘 다 실행 하나를 먼저 만들어야 하는데, 나누면 같은
    준비를 두 번 하거나 **정의 순서에 기대게** 된다(`#838`이 그 상태를 다룬다).

    `§6.4`가 「`§6.1`과 같은 봉투」를 규정하므로 재현 응답의 필드 집합은 실행 응답과
    같아야 한다 — 갈리면 그 규정이 거짓이 된다.
    """
    created = client.post(
        f"{API_V1_PREFIX}/annual-simulations",
        headers={"X-CSRF-Token": client.cookies.get("csrf")},
        json={
            "vessel_id": DEMO_VESSEL,
            "regulation_year": 2026,
            "target_rating": "C",
            "simulation_runs": 1000,
            "random_seed": 12345,
        },
    )
    assert created.status_code == 200, created.text
    simulation_id = created.json()["data"]["simulation_id"]

    snapshot = client.get(f"{API_V1_PREFIX}/annual-simulations/{simulation_id}/snapshot-voyages")
    assert snapshot.status_code == 200, snapshot.text
    assert flatten(snapshot.json()) == CONTRACTS["GET /annual-simulations/{id}/snapshot-voyages"]

    reproduced = client.post(
        f"{API_V1_PREFIX}/annual-simulations/{simulation_id}/reproduce",
        headers={"X-CSRF-Token": client.cookies.get("csrf")},
    )
    assert reproduced.status_code == 200, reproduced.text
    assert flatten(reproduced.json()) == CONTRACTS["POST /annual-simulations/{id}/reproduce"]


def test_annual_simulation_response_fields_match_the_contract(client):
    """`API_SPEC §6.1`·`§6.2` (`#752`) — 기능③이 계산 결과 응답 봉투를 따르는가.

    **이 파일의 다른 테스트에 의존하지 않는다.** 실행을 여기서 만들고 바로 조회한다 —
    「먼저 만들어 두는 테스트」를 앞에 두는 방식은 정의 순서에 기대는 것이라, 함수를
    옮기면 조용히 깨진다(`#838`이 그 상태를 다룬다).

    **실행과 조회를 같은 표로 본다.** `§6.2`가 「§6.1의 응답과 동일」로 규정하므로
    둘이 갈리면 그 규정이 거짓이 된다 — 표를 나누면 갈린 것을 볼 수 없다.
    """
    response = client.post(
        f"{API_V1_PREFIX}/annual-simulations",
        headers={"X-CSRF-Token": client.cookies.get("csrf")},
        json={
            "vessel_id": DEMO_VESSEL,
            "regulation_year": 2026,
            "target_rating": "C",
            "simulation_runs": 1000,
            "random_seed": 12345,
        },
    )

    assert response.status_code == 200, response.text
    assert flatten(response.json()) == CONTRACTS["POST /annual-simulations"]

    # `§6.2` — 같은 봉투다.
    simulation_id = response.json()["data"]["simulation_id"]
    fetched = client.get(f"{API_V1_PREFIX}/annual-simulations/{simulation_id}")

    assert fetched.status_code == 200, fetched.text
    assert flatten(fetched.json()) == CONTRACTS["POST /annual-simulations"]


def test_calculation_history_is_not_empty_before_it_is_compared(client):
    """`/calculations`는 **새 DB에서 0건**이다 (`#559` 작업 중 실측).

    이력이 없으면 `data[]` 아래 키가 통째로 사라지고, 부분집합 비교였다면 그대로
    통과했을 것이다. 집합 동등 비교라 실패하지만 **원인이 「계약이 바뀌었다」로
    읽히므로** 여기서 먼저 하나 만들어 둔다.
    """
    _ensure_calculation_history(client)

    body = _get(client, "/calculations?type=VOYAGE_ESTIMATE").json()
    assert body["data"], "계산 이력이 비어 있다 — 아래 계약 대조가 의미를 잃는다"


def test_every_contract_is_actually_checked():
    """계약이 하나라도 빠지면 **검사하지 않는 엔드포인트**가 생긴다.

    파라미터라이즈 목록이 `CONTRACTS`에서 나오므로 표를 지우면 검사도 함께
    사라진다 — 그것이 조용히 일어나지 않게 개수를 박는다.
    """
    assert len(CONTRACTS) >= 19
    assert sum(len(keys) for keys in CONTRACTS.values()) >= 600
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


# ─────────────────────────────────────────────────────────────────────────────
# 쓰기 응답 (#753)
#
# 쓰기 라우트는 대부분 **조회와 같은 자원**을 돌려준다. 화면은 저장한 뒤 그 응답을
# 그대로 목록·상세에 끼워 넣으므로(`VoyagePanel` · `VesselManagement`), 저장 응답의 모양이
# 조회와 갈리면 **저장 직후에만** 칸이 비고 새로고침하면 멀쩡해진다 — 가장 늦게 발견되는
# 형태다. 그래서 새 계약을 쓰지 않고 **조회 계약과 같은지**를 본다.
#
# 데이터는 **새 선박 하나**에 만든다. 데모 선박에 항차를 더하면 위 조회 계약들이
# `_resolve`로 읽는 「첫 항차」가 바뀔 수 있다.
# ─────────────────────────────────────────────────────────────────────────────

#: 쓰기 전용 응답 — 조회에 같은 모양이 없는 것만 적는다.
WRITE_CONTRACTS: dict[str, frozenset[str]] = {
    "DELETE /vessels/{id}": frozenset(
        {"data", "data.deleted", "data.id", "meta", "meta.request_id", "meta.timestamp"}
    ),
    #: 정박 구간·그 연료 기록의 삭제는 같은 모양이다 — 둘 다 소프트 삭제 표지를 돌려준다.
    "DELETE /not-underway-periods/{id}": frozenset(
        {"data", "data.deleted", "data.id", "meta", "meta.request_id", "meta.timestamp"}
    ),
    "DELETE /not-underway-periods/{id}/fuel-uses/{id}": frozenset(
        {"data", "data.deleted", "data.id", "meta", "meta.request_id", "meta.timestamp"}
    ),
    #: ⚠️ ``errors``는 **성공하면 빈 배열**이라 원소의 키는 여기서 잠기지 않는다. 행별 오류의
    #: 모양은 `test_voyage_import_db.py`가 서비스 수준에서 본다.
    "POST /vessels/{id}/import": frozenset(
        {
            "data",
            "data.dry_run",
            "data.errors",
            "data.imported_count",
            "data.missing_departure_count",
            "data.skipped_count",
            "meta",
            "meta.request_id",
            "meta.timestamp",
        }
    ),
    "POST /scenarios/{id}/adopt": frozenset(
        {
            "data",
            "data.adopted_scenario_type",
            "data.invalidated_calculation_runs",
            "data.updated_fields",
            "data.voyage_id",
            "meta",
            "meta.request_id",
            "meta.timestamp",
        }
    ),
    "DELETE /voyages/{id}": frozenset(
        {
            "data",
            "data.deleted",
            "data.hard_delete",
            "data.id",
            "meta",
            "meta.request_id",
            "meta.timestamp",
        }
    ),
}

_WRITE_IMO = "9876543"


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("csrf", "")}


def _item_of(list_contract: frozenset[str]) -> frozenset[str]:
    """목록 계약(``data[].x``)을 단건 모양(``data.x``)으로 바꾼다 — ``meta``는 따로 본다."""
    return frozenset(
        k.replace("data[]", "data", 1) for k in list_contract if k.startswith("data")
    ) | {"meta", "meta.request_id", "meta.timestamp"}


async def _purge_vessel(vessel_id: str) -> None:
    """쓰기 테스트가 만든 선박과 딸린 행을 지운다 — 계산 이력은 만들지 않는다."""
    from uuid import UUID

    from sqlalchemy import text

    from cii_platform.db.session import get_sessionmaker

    vid = UUID(vessel_id)
    async with get_sessionmaker()() as s:
        for sql in (
            "DELETE FROM not_underway_fuel_use WHERE period_id IN "
            "(SELECT id FROM not_underway_period WHERE vessel_id = :v)",
            "DELETE FROM not_underway_period WHERE vessel_id = :v",
            "DELETE FROM voyage_scenario WHERE vessel_id = :v",
            "DELETE FROM voyage_fuel_use WHERE voyage_id IN "
            "(SELECT id FROM voyage WHERE vessel_id = :v)",
            "DELETE FROM voyage WHERE vessel_id = :v",
            "DELETE FROM vessel WHERE id = :v",
        ):
            await s.execute(text(sql), {"v": vid})
        await s.commit()


def _new_vessel(client: TestClient):
    response = client.post(
        f"{API_V1_PREFIX}/vessels",
        headers=_csrf(client),
        json={
            "imo_number": _WRITE_IMO,
            "name": "CONTRACT WRITE",
            "ship_type": "BULK_CARRIER",
            "deadweight": 50000,
            "gross_tonnage": 30000,
        },
    )
    assert response.status_code == 201, response.text
    return response


def _new_voyage(client: TestClient, vessel_id: str, voyage_no: str):
    response = client.post(
        f"{API_V1_PREFIX}/vessels/{vessel_id}/voyages",
        headers=_csrf(client),
        json={
            "voyage_no": voyage_no,
            "departure_port_name": "BUSAN",
            "arrival_port_name": "TOKYO",
            "planned_distance_nm": 900,
            "planned_speed_kn": 13.0,
            "regulation_year": 2026,
            "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": 90}],
        },
    )
    assert response.status_code == 201, response.text
    return response


async def test_vessel_write_responses_match_the_read_contract(client):
    """선박 생성·수정·위치 갱신은 **상세 조회와 같은 모양**을 돌려준다. 삭제는 따로다."""
    created = _new_vessel(client)
    vessel_id = created.json()["data"]["id"]
    try:
        read = CONTRACTS["/vessels/{vessel_id}"]
        assert flatten(created.json()) == read

        patched = client.patch(
            f"{API_V1_PREFIX}/vessels/{vessel_id}",
            headers=_csrf(client),
            json={"name": "CONTRACT WRITE 2"},
        )
        assert patched.status_code == 200, patched.text
        assert flatten(patched.json()) == read

        moved = client.patch(
            f"{API_V1_PREFIX}/vessels/{vessel_id}/position",
            headers=_csrf(client),
            json={
                "underway_state": "UNDER_WAY",
                "detail_status": "SAILING",
                "current_lat": "35.1",
                "current_lon": "129.0",
            },
        )
        assert moved.status_code == 200, moved.text
        assert flatten(moved.json()) == read

        deleted = client.delete(f"{API_V1_PREFIX}/vessels/{vessel_id}", headers=_csrf(client))
        assert deleted.status_code == 200, deleted.text
        assert flatten(deleted.json()) == WRITE_CONTRACTS["DELETE /vessels/{id}"]
    finally:
        await _purge_vessel(vessel_id)


async def test_voyage_write_responses_match_the_read_contract(client):
    """항차 생성·수정·상태 전이·실적 입력은 **상세 조회와 같은 모양**이다. 삭제는 따로다.

    상태 전이는 화면이 「출항」·「항해 완료」 버튼 뒤에 **응답으로 행을 갈아 끼우는**
    자리다(`VoyagePanel`). 모양이 갈리면 누른 직후 그 행만 칸이 빈다.
    """
    vessel_id = _new_vessel(client).json()["data"]["id"]
    try:
        read = CONTRACTS["/voyages/{voyage_id}"]

        created = _new_voyage(client, vessel_id, "CW-1")
        voyage_id = created.json()["data"]["id"]
        assert flatten(created.json()) == read

        steps = [
            ("PATCH", f"/voyages/{voyage_id}", {"planned_distance_nm": 950}),
            (
                "POST",
                f"/voyages/{voyage_id}/transition",
                {"to_status": "PLANNED", "annual_inclusion_policy": "INCLUDE_AS_PLAN"},
            ),
            ("POST", f"/voyages/{voyage_id}/transition", {"to_status": "IN_PROGRESS"}),
            (
                "PUT",
                f"/voyages/{voyage_id}/actuals",
                {
                    "actual_distance_nm": 905,
                    "actual_avg_speed_kn": 12.6,
                    "fuel_uses": [{"fuel_type": "HFO", "actual_fuel_ton": 92}],
                },
            ),
        ]
        for method, path, body in steps:
            response = client.request(
                method, f"{API_V1_PREFIX}{path}", headers=_csrf(client), json=body
            )
            assert response.status_code == 200, f"{method} {path}: {response.text}"
            assert flatten(response.json()) == read, f"{method} {path}"

        draft = _new_voyage(client, vessel_id, "CW-2").json()["data"]["id"]
        deleted = client.delete(f"{API_V1_PREFIX}/voyages/{draft}", headers=_csrf(client))
        assert deleted.status_code == 200, deleted.text
        assert flatten(deleted.json()) == WRITE_CONTRACTS["DELETE /voyages/{id}"]
    finally:
        await _purge_vessel(vessel_id)


async def test_not_underway_write_responses_match_the_read_contract(client):
    """정박 구간 생성·수정은 **목록의 한 원소와 같은 모양**이다."""
    vessel_id = _new_vessel(client).json()["data"]["id"]
    try:
        item = _item_of(CONTRACTS["/vessels/{vessel_id}/not-underway-periods"])

        created = client.post(
            f"{API_V1_PREFIX}/vessels/{vessel_id}/not-underway-periods",
            headers=_csrf(client),
            json={
                "period_type": "AT_ANCHOR",
                "started_at": "2026-08-10T00:00:00Z",
                "ended_at": "2026-08-12T00:00:00Z",
                "port_name": "Busan",
                "distance_nm": "0",
                "fuel_uses": [
                    {"consumer_type": "AUX_ENGINE", "fuel_type": "HFO", "fuel_ton": "1.5"}
                ],
            },
        )
        assert created.status_code == 201, created.text
        period_id = created.json()["data"]["id"]
        assert flatten(created.json()) == item

        patched = client.patch(
            f"{API_V1_PREFIX}/not-underway-periods/{period_id}",
            headers=_csrf(client),
            json={"port_name": "Busan North"},
        )
        assert patched.status_code == 200, patched.text
        assert flatten(patched.json()) == item

        added = client.post(
            f"{API_V1_PREFIX}/not-underway-periods/{period_id}/fuel-uses",
            headers=_csrf(client),
            json={"consumer_type": "MAIN_ENGINE", "fuel_type": "HFO", "fuel_ton": "0.5"},
        )
        assert added.status_code == 201, added.text
        # 목록 원소의 ``fuel_uses[]`` 한 칸과 같은 모양이다 — 화면이 그 배열에 끼워 넣는다.
        fuel_item = frozenset(
            k.replace("data[].fuel_uses[]", "data", 1)
            for k in CONTRACTS["/vessels/{vessel_id}/not-underway-periods"]
            if k.startswith("data[].fuel_uses[].")
        ) | {"data", "meta", "meta.request_id", "meta.timestamp"}
        assert flatten(added.json()) == fuel_item
        fuel_use_id = added.json()["data"]["id"]

        removed = client.delete(
            f"{API_V1_PREFIX}/not-underway-periods/{period_id}/fuel-uses/{fuel_use_id}",
            headers=_csrf(client),
        )
        assert removed.status_code == 200, removed.text
        assert (
            flatten(removed.json())
            == WRITE_CONTRACTS["DELETE /not-underway-periods/{id}/fuel-uses/{id}"]
        )

        gone = client.delete(
            f"{API_V1_PREFIX}/not-underway-periods/{period_id}", headers=_csrf(client)
        )
        assert gone.status_code == 200, gone.text
        assert flatten(gone.json()) == WRITE_CONTRACTS["DELETE /not-underway-periods/{id}"]
    finally:
        await _purge_vessel(vessel_id)


async def test_import_and_adopt_responses_match_the_contract(client):
    """CSV 가져오기와 시나리오 채택 — 조회에 같은 모양이 없는 두 쓰기 응답.

    채택할 시나리오는 SQL로 넣는다(`test_scenario_adopt_db.py`와 같은 방식). 비교 화면에서
    저장까지 거치면 이 검사가 기능② 계산 전체에 묶인다.
    """
    from uuid import UUID

    from sqlalchemy import text

    from cii_platform.db.session import get_sessionmaker

    vessel_id = _new_vessel(client).json()["data"]["id"]
    try:
        csv_body = (
            b"voyage_no,departure_port_name,arrival_port_name,planned_distance_nm,"
            b"planned_speed_kn,fuel_type,planned_fuel_ton\n"
            b"CW-IMPORT,BUSAN,TOKYO,900,13,HFO,90\n"
        )
        imported = client.post(
            f"{API_V1_PREFIX}/vessels/{vessel_id}/import",
            headers=_csrf(client),
            files={"file": ("voyages.csv", csv_body, "text/csv")},
        )
        assert imported.status_code == 200, imported.text
        assert flatten(imported.json()) == WRITE_CONTRACTS["POST /vessels/{id}/import"]

        target = _new_voyage(client, vessel_id, "CW-ADOPT").json()["data"]["id"]
        planned = client.post(
            f"{API_V1_PREFIX}/voyages/{target}/transition",
            headers=_csrf(client),
            json={"to_status": "PLANNED", "annual_inclusion_policy": "INCLUDE_AS_PLAN"},
        )
        assert planned.status_code == 200, planned.text

        async with get_sessionmaker()() as s:
            scenario_id = (
                await s.execute(
                    text(
                        "INSERT INTO voyage_scenario (vessel_id, scenario_type, scenario_name, "
                        " distance_nm, speed_kn, duration_hours, fuel_ton, cii_value, "
                        " estimated_rating, risk_level) "
                        "VALUES (:vid, 'SLOW_STEAMING', '감속 운항', 1000, 10.5, 95.2, 60.5, "
                        " 5.1, 'C', 'MEDIUM') RETURNING id"
                    ),
                    {"vid": UUID(vessel_id)},
                )
            ).scalar_one()
            await s.commit()

        adopted = client.post(
            f"{API_V1_PREFIX}/scenarios/{scenario_id}/adopt",
            headers=_csrf(client),
            json={"target_voyage_id": target},
        )
        assert adopted.status_code == 200, adopted.text
        assert flatten(adopted.json()) == WRITE_CONTRACTS["POST /scenarios/{id}/adopt"]
    finally:
        await _purge_vessel(vessel_id)


# ─────────────────────────────────────────────────────────────────────────────
# 누락 감지 — 계약 표에 없는 라우트가 조용히 남지 않는다 (#753)
#
# 계약 표는 손으로 유지하는 목록이라 **넓힐수록 「표에 없는 라우트」가 는다.** 그 문제를
# `test_api_spec_endpoints_sync.py`와 같은 방식으로 막는다 — 실제 라우트를 전부 세고, 표에
# 없는 것은 **어느 테스트가 보는지** 또는 **왜 보지 않는지**를 적게 한다.
# `#751`·`#752`가 늦게 잡힌 이유가 「표에 없는 것이 왜 없는지 아무 데도 적혀 있지 않았다」였다.
# ─────────────────────────────────────────────────────────────────────────────

_THIS = "tests/test_response_contract_db.py"
_AUTH = "tests/test_auth_api.py"
_TOKENS = "tests/test_auth_tokens.py"
_FILES = "tests/test_report_export_routes_api_db.py"

#: 두 계약 표 밖의 라우트 → 필드 집합을 보는 테스트(``파일::함수``) 또는 ``면제: 사유``.
ROUTE_COVERAGE: dict[str, str] = {
    # `API_SPEC §3.10` (#768) — 응답이 **외부 조회 결과**라 데모 시드로는 볼 수 없다.
    # 그 파일이 가짜 제공자로 샘플·캐시·조회 세 경로의 응답을 각각 확인한다.
    "GET /ports/lookup": (
        "tests/test_port_geocoding_db.py::test_lookup_is_cached_and_asked_only_once"
    ),
    # `API_SPEC §9.1` (#767) — 응답이 **저장된 스냅샷 하나**라 데모 시드로는 볼 수 없다.
    # 그 파일이 자기 좌표에 심고 지우며 키 11개를 정확히 단언한다(AT-WX-001).
    "GET /weather/snapshot": (
        "tests/test_weather_api_db.py::test_snapshot_is_returned_in_the_spec_shape"
    ),
    # 조회 계약과 같은 모양 — 새 계약을 쓰지 않고 조회 계약과 대조한다
    "POST /vessels": f"{_THIS}::test_vessel_write_responses_match_the_read_contract",
    "PATCH /vessels/{}": f"{_THIS}::test_vessel_write_responses_match_the_read_contract",
    "PATCH /vessels/{}/position": f"{_THIS}::test_vessel_write_responses_match_the_read_contract",
    "POST /vessels/{}/voyages": f"{_THIS}::test_voyage_write_responses_match_the_read_contract",
    "PATCH /voyages/{}": f"{_THIS}::test_voyage_write_responses_match_the_read_contract",
    "POST /voyages/{}/transition": f"{_THIS}::test_voyage_write_responses_match_the_read_contract",
    "PUT /voyages/{}/actuals": f"{_THIS}::test_voyage_write_responses_match_the_read_contract",
    "POST /vessels/{}/not-underway-periods": (
        f"{_THIS}::test_not_underway_write_responses_match_the_read_contract"
    ),
    "PATCH /not-underway-periods/{}": (
        f"{_THIS}::test_not_underway_write_responses_match_the_read_contract"
    ),
    "POST /not-underway-periods/{}/fuel-uses": (
        f"{_THIS}::test_not_underway_write_responses_match_the_read_contract"
    ),
    # §6.2는 「§6.1과 같은 봉투」 — 실행 계약으로 조회를 본다
    "GET /annual-simulations/{}": (
        f"{_THIS}::test_annual_simulation_response_fields_match_the_contract"
    ),
    # 인증 — 계정을 만들고 지우는 파일에 둔다(이 파일은 데모 시드를 읽는다)
    "POST /auth/signup": f"{_AUTH}::test_account_routes_share_the_user_contract",
    "POST /auth/login": f"{_AUTH}::test_account_routes_share_the_user_contract",
    "PATCH /auth/me": f"{_AUTH}::test_account_routes_share_the_user_contract",
    "POST /auth/password-change": f"{_AUTH}::test_account_routes_share_the_user_contract",
    "POST /auth/logout": f"{_AUTH}::test_logout_and_delete_have_no_body",
    "DELETE /auth/me": f"{_AUTH}::test_logout_and_delete_have_no_body",
    "POST /auth/verify-email/request": f"{_TOKENS}::test_token_routes_match_the_contract",
    "POST /auth/verify-email/confirm": f"{_TOKENS}::test_token_routes_match_the_contract",
    "POST /auth/password-reset/request": f"{_TOKENS}::test_token_routes_match_the_contract",
    "POST /auth/password-reset/confirm": f"{_TOKENS}::test_token_routes_match_the_contract",
    # 파일 응답 — 필드 집합이 없다. 형식·첨부 헤더(리포트)와 헤더 행(내보내기)이 계약이다
    "GET /vessels/{}/export": f"{_FILES}::test_내보내기_헤더_행이_정본의_열과_같다",
    "GET /vessels/{}/annual-report": f"{_FILES}::test_연간_리포트_csv는_첨부로_내려간다",
    "GET /voyages/{}/report": f"{_FILES}::test_항차_리포트_라우트도_같은_형식_분기를_탄다",
    # 면제
    "POST /auth/dev-login": (
        "면제: 개발 전용 — 프로덕션에서 등록되지 않는다(`test_dev_auth.py`). "
        "화면이 응답을 읽지 않고 쿠키만 쓴다"
    ),
}


def _normalize(key: str) -> str:
    """``"GET /x/{vessel_id}?a=1"``·``"/x/{id}"`` → ``"GET /x/{}"``. 접두가 없으면 GET이다."""
    method, _, path = key.partition(" ") if key[:1].isupper() else ("GET", " ", key)
    path = path.split("?", 1)[0].removeprefix(API_V1_PREFIX)
    return f"{method} {re.sub(r'\{[^}]*\}', '{}', path)}"


def _operations() -> set[str]:
    return {
        _normalize(f"{method.upper()} {path}")
        for path, item in app.openapi()["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    }


def _defined_tests(relative: str) -> set[str]:
    """그 파일에 정의된 테스트 함수 이름(클래스 메서드 포함) — 주석·문자열은 보지 않는다."""
    tree = ast.parse((_ROOT / relative).read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def test_every_route_has_a_contract_or_a_reason():
    """모든 라우트가 계약 표에 있거나, 보는 테스트를 가리키거나, 면제 사유를 적었다.

    새 엔드포인트를 만들고 아무것도 적지 않으면 여기서 걸린다 — 계약을 쓰거나, 왜
    쓰지 않는지를 적어야 한다. 사유를 적는 목록도 손으로 유지하지만 **근거가 남는다.**
    """
    tabled = {_normalize(k) for k in CONTRACTS} | {_normalize(k) for k in WRITE_CONTRACTS}
    missing = sorted(_operations() - tabled - ROUTE_COVERAGE.keys())
    assert not missing, (
        f"계약도 사유도 없는 라우트 {len(missing)}개: {missing}\n"
        "CONTRACTS·WRITE_CONTRACTS에 넣거나, ROUTE_COVERAGE에 보는 테스트·면제 사유를 적을 것"
    )


def test_route_coverage_points_at_real_routes_and_tests():
    """가리키는 라우트와 테스트가 **실재한다** — 이름을 바꾸면 목록이 조용히 낡는다."""
    stale_routes = sorted(ROUTE_COVERAGE.keys() - _operations())
    assert not stale_routes, f"없는 라우트를 가리킨다: {stale_routes}"

    tabled = {_normalize(k) for k in CONTRACTS} | {_normalize(k) for k in WRITE_CONTRACTS}
    doubled = sorted(ROUTE_COVERAGE.keys() & tabled)
    assert not doubled, f"계약 표에도 있고 ROUTE_COVERAGE에도 있다: {doubled}"

    broken = []
    for route, where in ROUTE_COVERAGE.items():
        if where.startswith("면제:"):
            assert len(where) > len("면제: ") + 10, f"{route}: 면제 사유가 비어 있다"
            continue
        relative, _, name = where.partition("::")
        if name not in _defined_tests(relative):
            broken.append(f"{route} → {where}")
    assert not broken, "가리키는 테스트가 없다:\n" + "\n".join(broken)
