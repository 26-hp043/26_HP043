"""대시보드 시연용 시드 확장 — GT축 1척·운항 상태·항차 이력·not under way 샘플

Revision ID: 027
Revises: 026
Create Date: 2026-08-15

이슈 #347 · #207(#34 잔여분). 018이 만든 DWT축 3척 시드를 대시보드(#351)·선박
상세(#356)·실시간 CII(#357) 화면이 성립하는 규모로 확장한다.

무엇을 넣는가
------------

1. **GT축 선박 1척** — ``RO_RO_PASSENGER``(GT 25,000, 합성). #34가 3번 선박을
   GT축으로 지정했다가 제원 미확보로 미뤄 둔 잔여분(#207)을 채운다.
   ``test_all_seeded_vessels_are_dwt_axis``가 이 시점에 깨지도록 설계돼 있었다 —
   같은 PR에서 해당 테스트를 갱신한다.
2. **운항 상태·위치 (026 컬럼)** — 운항 중·운하 통과 중·묘박 중·접안이 섞이게
   4척에 부여한다. 대시보드 카드가 상태별로 다르게 보이는 것이 목적이다.
3. **항차 이력** — 2025·2026 두 연도에 걸친 COMPLETED 항차(연료 실적 포함)와
   실시간 화면용 IN_PROGRESS 항차 1건.
4. **not under way 샘플** — 운하 통과(진행 중)·묘박(진행 중)·드라이독(종료) 3건과
   소비자별 연료 기록. ``consumer_type`` 4값을 전부 포함한다.

값의 성질
---------

- **전부 시연용 합성값이다.** 1번 선박의 제원만 ``PRD §13.1`` Fixture 1에서 왔다.
  4번 선박의 GT 25,000은 설계값이며 실선 제원이 아니다(018의 합성 IMO 규칙과
  같이 ``0``으로 시작하는 IMO를 쓴다).
- **위험 선박 서사(설계 의도)** — 1번 벌크선의 연료를 거리 대비 과다(620t/4,300nm)로
  넣어 연간 등급이 E에 가깝고 연도 사이 악화되는 흐름을 만든다. 경고 배너(#351·#352)
  시연용이며, 등급 자체는 파라미터 seed(``scripts/seed.py``) 적재 후 API가 계산한다.
- **UUID를 명시적으로 박는다** — 018과 같은 이유(환경 무관 재현). 블록 배치:
  voyage ``…0101~0109`` · period ``…0201~0203`` · not under way 연료 ``…0301~0306``
  · 항차 연료 ``…0401~0409``.
- **upsert를 쓰지 않는다** — 017·018과 같은 이유(마이그레이션은 과거 시점 스냅샷,
  upsert는 downgrade를 정의할 수 없다). 재실행 idempotency는 Alembic의
  revision 1회 실행 보장과 명시 UUID가 담당하며, 테스트가 정확히 4척인지 잠근다.
- **downgrade는 자기 행만 지운다** — 4번 선박과 027이 넣은 항차·연료·구간을 지우고,
  1~3번 선박의 상태·위치 컬럼을 NULL로 되돌린다. 018의 행은 건드리지 않는다.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "027"
down_revision: str | Sequence[str] | None = "026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """TIMESTAMPTZ 리터럴용 UTC datetime."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# --- UUID 블록 (018 계약값 재사용 + 027 신규) ---------------------------------
VESSEL_ID_RO_RO = "00000000-0000-4000-8000-000000000004"

# voyage: …0101~0109
V1_2025 = "00000000-0000-4000-8000-000000000101"
V1_2026 = "00000000-0000-4000-8000-000000000102"
V2_2025 = "00000000-0000-4000-8000-000000000103"
V2_2026 = "00000000-0000-4000-8000-000000000104"
V2_IN_PROGRESS = "00000000-0000-4000-8000-000000000105"
V3_2025 = "00000000-0000-4000-8000-000000000106"
V3_2026 = "00000000-0000-4000-8000-000000000107"
V4_2025 = "00000000-0000-4000-8000-000000000108"
V4_2026 = "00000000-0000-4000-8000-000000000109"

# not_underway_period: …0201~0203
P_CANAL = "00000000-0000-4000-8000-000000000201"
P_ANCHOR = "00000000-0000-4000-8000-000000000202"
P_DRYDOCK = "00000000-0000-4000-8000-000000000203"

SEED_VOYAGE_IDS = (
    V1_2025,
    V1_2026,
    V2_2025,
    V2_2026,
    V2_IN_PROGRESS,
    V3_2025,
    V3_2026,
    V4_2025,
    V4_2026,
)
SEED_PERIOD_IDS = (P_CANAL, P_ANCHOR, P_DRYDOCK)

# 018이 만든 3척(상태·위치 갱신 대상). id는 018 계약값.
VESSEL_IDS_018 = (
    "00000000-0000-4000-8000-000000000001",
    "00000000-0000-4000-8000-000000000002",
    "00000000-0000-4000-8000-000000000003",
)

# --- 데이터 --------------------------------------------------------------------
# 018 계약 UUID (프론트엔드 고정표가 참조).
BULK, CONTAINER, GENERAL_CARGO = VESSEL_IDS_018

#: GT축 신규 선박. GT 25,000 ≥ 5,000 → is_cii_applicable_hint = true (§2.1 규칙).
SEED_VESSEL_GT_AXIS: list[dict[str, object]] = [
    {
        "id": VESSEL_ID_RO_RO,
        # 합성 IMO — 실선 대역(5,000,000~)과 겹치지 않는 0 시작(018 규칙).
        "imo_number": "0000002",
        "name": "샘플 로로 여객선 (25,000 GT)",
        "ship_type": "RO_RO_PASSENGER",
        "gross_tonnage": Decimal("25000.00"),
        "deadweight": None,
        "default_fuel_type": None,  # 018과 같은 이유로 NULL (017 downgrade 보호).
        "reference_speed_kn": Decimal("18.00"),
        "reference_daily_foc_ton": None,
        "is_cii_applicable_hint": True,
        # 접안 중 — 부산항 여객터미널 위치.
        "underway_state": "NOT_UNDER_WAY",
        "detail_status": "IN_PORT",
        "current_lat": Decimal("35.095000"),
        "current_lon": Decimal("129.040000"),
        "position_updated_at": _utc(2026, 8, 15, 7, 20),
    },
]

#: 018의 3척에 부여하는 운항 상태·위치. 대시보드가 4가지 상태를 다르게 보이게
#: 하는 배분이다 — 항해 중(대한해협)·운하 통과(수에즈)·묘박(부산).
SEED_STATE_UPDATES: list[tuple[str, str, str, str, str, str]] = [
    # (vessel_id, underway_state, detail_status, lat, lon, position_updated_at)
    (BULK, "UNDER_WAY", "SAILING", "34.512345", "128.501234", "2026-08-15 06:00:00+00"),
    (
        CONTAINER,
        "NOT_UNDER_WAY",
        "CANAL_TRANSIT",
        "30.585200",
        "32.265400",
        "2026-08-15 05:30:00+00",
    ),
    (
        GENERAL_CARGO,
        "NOT_UNDER_WAY",
        "AT_ANCHOR",
        "35.091234",
        "129.041234",
        "2026-08-15 06:10:00+00",
    ),
]

#: 항차 이력. COMPLETED는 전부 INCLUDE_AS_ACTUAL + regulation_year(연간 집계 대상).
#: 1번 벌크선의 연료를 과다(620t/4,300nm)로 넣은 것이 위험 선박 서사의 핵심.
SEED_VOYAGES: list[dict[str, object]] = [
    {
        # 2025년 실적 400t — D 등급(실제 엔진 산출 ratio ≈ 1.13, D 구간 1.06~1.18).
        "id": V1_2025,
        "vessel_id": BULK,
        "voyage_no": "2025-01",
        "status": "COMPLETED",
        "annual_inclusion_policy": "INCLUDE_AS_ACTUAL",
        "regulation_year": 2025,
        "departure_port_name": "BUSAN",
        "arrival_port_name": "SINGAPORE",
        "planned_distance_nm": Decimal("4200.00"),
        "actual_distance_nm": Decimal("4265.00"),
        "planned_speed_kn": Decimal("12.00"),
        "actual_avg_speed_kn": Decimal("11.60"),
        "planned_departure_at": _utc(2025, 3, 2),
        "planned_arrival_at": _utc(2025, 3, 17),
        "actual_departure_at": _utc(2025, 3, 2, 8),
        "actual_arrival_at": _utc(2025, 3, 17, 21),
    },
    {
        # 위험 선박 서사 — 2026년 실적 620t(계획 530t 대비 초과). ratio ≈ 1.78로
        # E 등급으로 악화. 2025 D → 2026 E 악화 흐름 자체가 경고 배너 시연 데이터다.
        "id": V1_2026,
        "vessel_id": BULK,
        "voyage_no": "2026-01",
        "status": "COMPLETED",
        "annual_inclusion_policy": "INCLUDE_AS_ACTUAL",
        "regulation_year": 2026,
        "departure_port_name": "BUSAN",
        "arrival_port_name": "SINGAPORE",
        "planned_distance_nm": Decimal("4200.00"),
        "actual_distance_nm": Decimal("4300.00"),
        "planned_speed_kn": Decimal("12.00"),
        "actual_avg_speed_kn": Decimal("11.50"),
        "planned_departure_at": _utc(2026, 2, 10),
        "planned_arrival_at": _utc(2026, 2, 26),
        "actual_departure_at": _utc(2026, 2, 10, 7),
        "actual_arrival_at": _utc(2026, 2, 26, 23),
    },
    {
        "id": V2_2025,
        "vessel_id": CONTAINER,
        "voyage_no": "2025-01",
        "status": "COMPLETED",
        "annual_inclusion_policy": "INCLUDE_AS_ACTUAL",
        "regulation_year": 2025,
        "departure_port_name": "SHANGHAI",
        "arrival_port_name": "ROTTERDAM",
        "planned_distance_nm": Decimal("10500.00"),
        "actual_distance_nm": Decimal("10580.00"),
        "planned_speed_kn": Decimal("16.50"),
        "actual_avg_speed_kn": Decimal("16.30"),
        "planned_departure_at": _utc(2025, 9, 1),
        "planned_arrival_at": _utc(2025, 9, 28),
        "actual_departure_at": _utc(2025, 9, 1, 6),
        "actual_arrival_at": _utc(2025, 9, 28, 9),
    },
    {
        "id": V2_2026,
        "vessel_id": CONTAINER,
        "voyage_no": "2026-01",
        "status": "COMPLETED",
        "annual_inclusion_policy": "INCLUDE_AS_ACTUAL",
        "regulation_year": 2026,
        "departure_port_name": "SHANGHAI",
        "arrival_port_name": "ROTTERDAM",
        "planned_distance_nm": Decimal("10500.00"),
        "actual_distance_nm": Decimal("10620.00"),
        "planned_speed_kn": Decimal("16.50"),
        "actual_avg_speed_kn": Decimal("16.20"),
        "planned_departure_at": _utc(2026, 6, 1),
        "planned_arrival_at": _utc(2026, 6, 28),
        "actual_departure_at": _utc(2026, 6, 1, 5),
        "actual_arrival_at": _utc(2026, 6, 28, 14),
    },
    {
        # 실시간 CII 화면용 진행 중 항차 — 컨테이너선의 회항. 현재 수에즈 운하
        # 통과 중(= P_CANAL 구간과 연결).
        "id": V2_IN_PROGRESS,
        "vessel_id": CONTAINER,
        "voyage_no": "2026-02",
        "status": "IN_PROGRESS",
        "annual_inclusion_policy": "INCLUDE_AS_PLAN",
        "regulation_year": 2026,
        "departure_port_name": "SHANGHAI",
        "arrival_port_name": "ROTTERDAM",
        "planned_distance_nm": Decimal("10500.00"),
        "actual_distance_nm": None,
        "planned_speed_kn": Decimal("16.50"),
        "actual_avg_speed_kn": None,
        "planned_departure_at": _utc(2026, 8, 10),
        "planned_arrival_at": _utc(2026, 9, 6),
        "actual_departure_at": _utc(2026, 8, 10, 6),
        "actual_arrival_at": None,
    },
    {
        "id": V3_2025,
        "vessel_id": GENERAL_CARGO,
        "voyage_no": "2025-01",
        "status": "COMPLETED",
        "annual_inclusion_policy": "INCLUDE_AS_ACTUAL",
        "regulation_year": 2025,
        "departure_port_name": "BUSAN",
        "arrival_port_name": "HAKODATE",
        "planned_distance_nm": Decimal("900.00"),
        "actual_distance_nm": Decimal("915.00"),
        "planned_speed_kn": Decimal("12.80"),
        "actual_avg_speed_kn": Decimal("12.40"),
        "planned_departure_at": _utc(2025, 7, 5),
        "planned_arrival_at": _utc(2025, 7, 8),
        "actual_departure_at": _utc(2025, 7, 5, 9),
        "actual_arrival_at": _utc(2025, 7, 8, 15),
    },
    {
        "id": V3_2026,
        "vessel_id": GENERAL_CARGO,
        "voyage_no": "2026-01",
        "status": "COMPLETED",
        "annual_inclusion_policy": "INCLUDE_AS_ACTUAL",
        "regulation_year": 2026,
        "departure_port_name": "BUSAN",
        "arrival_port_name": "MANILA",
        "planned_distance_nm": Decimal("1100.00"),
        "actual_distance_nm": Decimal("1130.00"),
        "planned_speed_kn": Decimal("12.80"),
        "actual_avg_speed_kn": Decimal("12.50"),
        "planned_departure_at": _utc(2026, 4, 2),
        "planned_arrival_at": _utc(2026, 4, 6),
        "actual_departure_at": _utc(2026, 4, 2, 8),
        "actual_arrival_at": _utc(2026, 4, 6, 20),
    },
    {
        "id": V4_2025,
        "vessel_id": VESSEL_ID_RO_RO,
        "voyage_no": "2025-01",
        "status": "COMPLETED",
        "annual_inclusion_policy": "INCLUDE_AS_ACTUAL",
        "regulation_year": 2025,
        "departure_port_name": "BUSAN",
        "arrival_port_name": "OSAKA",
        "planned_distance_nm": Decimal("450.00"),
        "actual_distance_nm": Decimal("460.00"),
        "planned_speed_kn": Decimal("18.00"),
        "actual_avg_speed_kn": Decimal("17.60"),
        "planned_departure_at": _utc(2025, 12, 18),
        "planned_arrival_at": _utc(2025, 12, 19),
        "actual_departure_at": _utc(2025, 12, 18, 10),
        "actual_arrival_at": _utc(2025, 12, 19, 9),
    },
    {
        "id": V4_2026,
        "vessel_id": VESSEL_ID_RO_RO,
        "voyage_no": "2026-01",
        "status": "COMPLETED",
        "annual_inclusion_policy": "INCLUDE_AS_ACTUAL",
        "regulation_year": 2026,
        "departure_port_name": "BUSAN",
        "arrival_port_name": "OSAKA",
        "planned_distance_nm": Decimal("450.00"),
        "actual_distance_nm": Decimal("455.00"),
        "planned_speed_kn": Decimal("18.00"),
        "actual_avg_speed_kn": Decimal("17.80"),
        "planned_departure_at": _utc(2026, 8, 1),
        "planned_arrival_at": _utc(2026, 8, 2),
        "actual_departure_at": _utc(2026, 8, 1, 10),
        "actual_arrival_at": _utc(2026, 8, 2, 8),
    },
]

#: 항차 연료. 전부 HFO(017 seed 코드). 진행 중 항차는 계획값만.
#: cf_used는 MEPC.364(79) §2.2.1의 HFO CF 3.114000 (DB_SCHEMA §3.2).
SEED_VOYAGE_FUELS: list[dict[str, object]] = [
    {
        "id": "00000000-0000-4000-8000-000000000401",
        "voyage_id": V1_2025,
        "planned_fuel_ton": Decimal("420.00"),
        "actual_fuel_ton": Decimal("400.00"),
    },
    {
        "id": "00000000-0000-4000-8000-000000000402",
        "voyage_id": V1_2026,
        "planned_fuel_ton": Decimal("530.00"),
        "actual_fuel_ton": Decimal("620.00"),
    },
    {
        "id": "00000000-0000-4000-8000-000000000403",
        "voyage_id": V2_2025,
        "planned_fuel_ton": Decimal("580.00"),
        "actual_fuel_ton": Decimal("585.00"),
    },
    {
        "id": "00000000-0000-4000-8000-000000000404",
        "voyage_id": V2_2026,
        "planned_fuel_ton": Decimal("590.00"),
        "actual_fuel_ton": Decimal("600.00"),
    },
    {
        "id": "00000000-0000-4000-8000-000000000405",
        "voyage_id": V2_IN_PROGRESS,
        "planned_fuel_ton": Decimal("590.00"),
        "actual_fuel_ton": None,
    },
    {
        "id": "00000000-0000-4000-8000-000000000406",
        "voyage_id": V3_2025,
        "planned_fuel_ton": Decimal("36.00"),
        "actual_fuel_ton": Decimal("34.00"),
    },
    {
        "id": "00000000-0000-4000-8000-000000000407",
        "voyage_id": V3_2026,
        "planned_fuel_ton": Decimal("45.00"),
        "actual_fuel_ton": Decimal("46.00"),
    },
    {
        "id": "00000000-0000-4000-8000-000000000408",
        "voyage_id": V4_2025,
        "planned_fuel_ton": Decimal("53.00"),
        "actual_fuel_ton": Decimal("55.00"),
    },
    {
        "id": "00000000-0000-4000-8000-000000000409",
        "voyage_id": V4_2026,
        "planned_fuel_ton": Decimal("62.00"),
        "actual_fuel_ton": Decimal("70.00"),
    },
]

#: not under way 구간. 운하 통과·묘박은 진행 중(ended_at NULL), 드라이독은 종료.
#: 운하 구간은 진행 중 항차(V2_IN_PROGRESS)를 맥락 참조로 건다.
SEED_PERIODS: list[dict[str, object]] = [
    {
        "id": P_CANAL,
        "vessel_id": CONTAINER,
        "regulation_year": 2026,
        "period_type": "CANAL_TRANSIT",
        "started_at": _utc(2026, 8, 14, 22),
        "ended_at": None,
        "port_name": "SUEZ CANAL",
        "lat": Decimal("30.585200"),
        "lon": Decimal("32.265400"),
        "voyage_id": V2_IN_PROGRESS,
    },
    {
        "id": P_ANCHOR,
        "vessel_id": GENERAL_CARGO,
        "regulation_year": 2026,
        "period_type": "AT_ANCHOR",
        "started_at": _utc(2026, 8, 13, 4),
        "ended_at": None,
        "port_name": "BUSAN",
        "lat": Decimal("35.091234"),
        "lon": Decimal("129.041234"),
        "voyage_id": None,
    },
    {
        "id": P_DRYDOCK,
        "vessel_id": VESSEL_ID_RO_RO,
        "regulation_year": 2025,
        "period_type": "DRYDOCK",
        "started_at": _utc(2025, 5, 10),
        "ended_at": _utc(2025, 5, 25),
        "port_name": "BUSAN",
        "lat": None,
        "lon": None,
        "voyage_id": None,
    },
]

#: not under way 연료. consumer_type 4값 전부 포함(메인엔진은 운하 저속 통항만).
SEED_PERIOD_FUELS: list[dict[str, object]] = [
    {
        "id": "00000000-0000-4000-8000-000000000301",
        "period_id": P_CANAL,
        "consumer_type": "MAIN_ENGINE",
        "fuel_type": "HFO",
        "fuel_ton": Decimal("1.80"),
    },
    {
        "id": "00000000-0000-4000-8000-000000000302",
        "period_id": P_CANAL,
        "consumer_type": "AUX_ENGINE",
        "fuel_type": "DIESEL_GAS_OIL",
        "fuel_ton": Decimal("3.20"),
    },
    {
        "id": "00000000-0000-4000-8000-000000000303",
        "period_id": P_ANCHOR,
        "consumer_type": "AUX_ENGINE",
        "fuel_type": "DIESEL_GAS_OIL",
        "fuel_ton": Decimal("4.50"),
    },
    {
        "id": "00000000-0000-4000-8000-000000000304",
        "period_id": P_DRYDOCK,
        "consumer_type": "AUX_ENGINE",
        "fuel_type": "DIESEL_GAS_OIL",
        "fuel_ton": Decimal("28.00"),
    },
    {
        "id": "00000000-0000-4000-8000-000000000305",
        "period_id": P_DRYDOCK,
        "consumer_type": "OIL_FIRED_BOILER",
        "fuel_type": "HFO",
        "fuel_ton": Decimal("6.50"),
    },
    {
        "id": "00000000-0000-4000-8000-000000000306",
        "period_id": P_DRYDOCK,
        "consumer_type": "OTHER",
        "fuel_type": "DIESEL_GAS_OIL",
        "fuel_ton": Decimal("2.00"),
    },
]

# --- 경량 테이블 (018 패턴 — 실제 컬럼 정의는 각 스키마 마이그레이션이 소유) ------
vessel_tbl = sa.table(
    "vessel",
    sa.column("id", postgresql.UUID),
    sa.column("imo_number", sa.String),
    sa.column("name", sa.String),
    sa.column("ship_type", sa.String),
    sa.column("gross_tonnage", sa.Numeric),
    sa.column("deadweight", sa.Numeric),
    sa.column("default_fuel_type", sa.String),
    sa.column("reference_speed_kn", sa.Numeric),
    sa.column("reference_daily_foc_ton", sa.Numeric),
    sa.column("is_cii_applicable_hint", sa.Boolean),
    sa.column("underway_state", sa.String),
    sa.column("detail_status", sa.String),
    sa.column("current_lat", sa.Numeric),
    sa.column("current_lon", sa.Numeric),
    sa.column("position_updated_at", sa.DateTime),
)
voyage_tbl = sa.table(
    "voyage",
    sa.column("id", postgresql.UUID),
    sa.column("vessel_id", postgresql.UUID),
    sa.column("voyage_no", sa.String),
    sa.column("status", sa.String),
    sa.column("annual_inclusion_policy", sa.String),
    sa.column("regulation_year", sa.Integer),
    sa.column("departure_port_name", sa.String),
    sa.column("arrival_port_name", sa.String),
    sa.column("planned_distance_nm", sa.Numeric),
    sa.column("actual_distance_nm", sa.Numeric),
    sa.column("planned_speed_kn", sa.Numeric),
    sa.column("actual_avg_speed_kn", sa.Numeric),
    sa.column("planned_departure_at", sa.DateTime),
    sa.column("planned_arrival_at", sa.DateTime),
    sa.column("actual_departure_at", sa.DateTime),
    sa.column("actual_arrival_at", sa.DateTime),
)
voyage_fuel_tbl = sa.table(
    "voyage_fuel_use",
    sa.column("id", postgresql.UUID),
    sa.column("voyage_id", postgresql.UUID),
    sa.column("fuel_type", sa.String),
    sa.column("planned_fuel_ton", sa.Numeric),
    sa.column("actual_fuel_ton", sa.Numeric),
    sa.column("cf_used", sa.Numeric),
    sa.column("source", sa.String),
)
period_tbl = sa.table(
    "not_underway_period",
    sa.column("id", postgresql.UUID),
    sa.column("vessel_id", postgresql.UUID),
    sa.column("regulation_year", sa.Integer),
    sa.column("period_type", sa.String),
    sa.column("started_at", sa.DateTime),
    sa.column("ended_at", sa.DateTime),
    sa.column("port_name", sa.String),
    sa.column("lat", sa.Numeric),
    sa.column("lon", sa.Numeric),
    sa.column("voyage_id", postgresql.UUID),
)
period_fuel_tbl = sa.table(
    "not_underway_fuel_use",
    sa.column("id", postgresql.UUID),
    sa.column("period_id", postgresql.UUID),
    sa.column("consumer_type", sa.String),
    sa.column("fuel_type", sa.String),
    sa.column("fuel_ton", sa.Numeric),
)

# HFO CF (tCO₂/tFuel) — 017 seed·DB_SCHEMA §3.2와 동일한 값.
HFO_CF = Decimal("3.114000")


def upgrade() -> None:
    # 1) GT축 선박 1척 (상태·위치 포함 — 026 컬럼).
    op.bulk_insert(vessel_tbl, SEED_VESSEL_GT_AXIS)

    # 2) 018의 3척에 운항 상태·위치 부여.
    for vid, underway, detail, lat, lon, updated in SEED_STATE_UPDATES:
        op.execute(
            sa.text(  # noqa: S608 — 리터럴 UUID 상수 결합, 외부 입력 없음
                f"UPDATE vessel SET underway_state = '{underway}', "
                f"detail_status = '{detail}', current_lat = {lat}, "
                f"current_lon = {lon}, "
                f"position_updated_at = '{updated}'::timestamptz "
                f"WHERE id = '{vid}'::uuid"
            )
        )

    # 3) 항차 이력 + 연료 실적.
    op.bulk_insert(voyage_tbl, SEED_VOYAGES)
    op.bulk_insert(
        voyage_fuel_tbl,
        [
            {**row, "fuel_type": "HFO", "cf_used": HFO_CF, "source": "SAMPLE"}
            for row in SEED_VOYAGE_FUELS
        ],
    )

    # 4) not under way 구간 + 소비자별 연료.
    op.bulk_insert(period_tbl, SEED_PERIODS)
    op.bulk_insert(period_fuel_tbl, SEED_PERIOD_FUELS)


def downgrade() -> None:
    """027이 넣은 행만 지운다. 018의 행(선박 3척)은 상태·위치만 NULL로 되돌린다."""
    period_ids = ",".join(f"'{p}'::uuid" for p in SEED_PERIOD_IDS)
    voyage_ids = ",".join(f"'{v}'::uuid" for v in SEED_VOYAGE_IDS)

    op.execute(f"DELETE FROM not_underway_fuel_use WHERE period_id IN ({period_ids})")
    op.execute(f"DELETE FROM not_underway_period WHERE id IN ({period_ids})")
    op.execute(f"DELETE FROM voyage_fuel_use WHERE voyage_id IN ({voyage_ids})")
    op.execute(f"DELETE FROM voyage WHERE id IN ({voyage_ids})")
    op.execute(f"DELETE FROM vessel WHERE id = '{VESSEL_ID_RO_RO}'::uuid")

    for vid, *_ in SEED_STATE_UPDATES:
        op.execute(
            sa.text(  # noqa: S608
                f"UPDATE vessel SET underway_state = NULL, detail_status = NULL, "
                f"current_lat = NULL, current_lon = NULL, "
                f"position_updated_at = NULL WHERE id = '{vid}'::uuid"
            )
        )
