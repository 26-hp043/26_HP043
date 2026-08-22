"""데모·시연용 샘플 데이터 적재 (#451).

## 왜 마이그레이션이 아니라 여기인가

종전에는 마이그레이션 018·027이 이 데이터를 넣었다. 그런데 **데모 선박으로 계산을 한 번
돌리면 018의 다운그레이드가 막혔다** — ``calculation_run``이 그 선박을 참조하고
``fk_calculation_run_vessel``이 ``RESTRICT``이기 때문이다.

018 자신은 *"그 컬럼에는 FK가 없어(003) 실제로는 막히지 않는다"* 고 적어 두었으나, **그
전제가 023에서 깨졌다.** FK가 생긴 뒤로 018의 다운그레이드는 참조가 있는 한 실패한다.

세 안을 두고 골랐다.

=========================  =========================================================
 안                         판단
=========================  =========================================================
 다운그레이드가 참조 행까지  기각. **마이그레이션이 사용자 계산 이력을 지우는 선례**가
 삭제                        된다. ``calculation_run``은 immutable 가드까지 걸린
                             보존 대상이다(`DB_SCHEMA §7.1`).
 참조 있으면 남기고 경고     기각. 다운그레이드가 완전히 되돌리지 않게 되어 「롤백했는데
                             흔적이 남는」 상태가 된다.
 **seed에서 분리**           **채택.** 마이그레이션이 지울 것 자체를 없앤다. 스키마
                             마이그레이션은 스키마만 다룬다 — `DB_SCHEMA §8.1`의
                             「스키마 변경과 seed 데이터 분리」 원칙 그대로다.
=========================  =========================================================

## 규제 파라미터 seed와 무엇이 다른가

``db.seed``(규제 파라미터)는 **모든 환경에 필요하다** — 없으면 계산 자체가 되지 않는다.
이 모듈의 데이터는 **시연·개발 편의**이며 운영 데이터가 아니다. 그래서 마이그레이션 체인에
넣지 않고 필요할 때만 부른다.

## 재실행 가능하다

``ON CONFLICT DO NOTHING``이라 여러 번 돌려도 행이 늘지 않는다. **덮어쓰지도 않는다** —
누군가 데모 선박의 값을 고쳐 두었다면 그 편집을 존중한다. 초기화가 목적이면 지우고 다시
넣는 편이 의도가 분명하다.

## 고정 UUID는 계약이다

``00000000-0000-4000-8000-00000000000N``은 시드가 넣는 데모 선박의 고정 UUID다.
프론트엔드 고정표가 이 값을 복사해 두고 있었으나 ``#542``가 그 표를 없앴다 —
화면은 이제 ``GET /vessels``로 받는다. 값 자체는 테스트·픽스처가 참조하므로
**바꾸려면 그쪽을 함께 고친다.**

## 행 수는 ``rowcount``로 묻지 않는다 (#481)

이 모듈의 모든 헬퍼는 ``RETURNING id``로 **돌려받은 행을 센다.**

``rowcount``는 드라이버·실행 경로에 따라 뜻이 달라진다. 실제로 executemany 경로의
asyncpg는 ``-1``을 돌려주며, 종전 코드의 ``result.rowcount or 0``은 ``-1``이 truthy라
그대로 새어 나갔다 — 출력이 ``vessel: -1행 신규 적재``였다. 그 값은 **「이미 다 들어
있다(0)」와 「방금 넣었다(N)」를 구분하지 못한다.** 이 출력의 목적이 정확히 그 구분이다.

단일 DELETE의 ``rowcount``는 정상 값을 주지만 거기도 같은 방식을 쓴다. **두 규칙이
공존하면 다음 사람이 어느 쪽이 맞는지 매번 확인해야 한다.**

실행: ``python -m cii_platform.db.demo_seed``
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection


# 데모 선박의 고정 UUID (#132 계약 · #135 입력 폼). 프론트엔드 고정표가 이 값을
# 복사해 두었으나 #542가 그 표를 없앴다 — 지금 참조하는 곳은 테스트·픽스처다.
VESSEL_ID_BULK = "00000000-0000-4000-8000-000000000001"
VESSEL_ID_CONTAINER = "00000000-0000-4000-8000-000000000002"
VESSEL_ID_GENERAL_CARGO = "00000000-0000-4000-8000-000000000003"

#: 1번 선박의 합성 IMO 번호.
#:
#: 실존 선박이 아니므로 **IMO가 실제로 발급하지 않는 대역(0으로 시작)** 을 써서
#: 실선과 충돌할 수 없게 한다. 동시에 **체크섬을 만족한다** — 앞 6자리에 7·6·5·4·3·2를
#: 곱한 합의 1의 자리가 7번째 자리와 같다 (#525).
#:
#: 종전 값 ``0000001``은 대역만 지키고 체크섬은 고려하지 않았다. 0으로 시작하면서
#: 체크섬이 맞는 7자리는 10만 개 있으므로 **두 조건을 함께 만족할 수 있다.**
#: 이미 적재된 DB는 마이그레이션 ``036``이 고친다 — 이 seed는
#: ``ON CONFLICT DO NOTHING``이라 덮어쓰지 않는다.
SYNTHETIC_IMO_BULK = "0000012"

# 3척. 값의 출처를 행마다 주석으로 남긴다.
#
# op.bulk_insert()는 executemany라 모든 dict의 키 집합이 완전히 동일해야 한다.
# 아래 리터럴은 NULL인 컬럼도 키를 채워 그것을 보장한다.
#
# INSERT 대상에서 뺀 컬럼과 위임 대상(003의 server_default):
#   is_deleted → false · created_at → now() · updated_at → now()
SEED_VESSELS: list[dict[str, object]] = [
    {
        # PRD §13.1 Fixture 1 — Bulk carrier 50,000 DWT. 실존 선박이 아니다.
        # name에 제원을 함께 적는 이유: 이 배는 실선명이 없고 "무엇을 위한 배인가"가
        # 곧 이름이다. 프론트엔드 고정표가 쓰던 표시 문자열과 같아 전환 시 화면이
        # 바뀌지 않는다. 2·3번은 실선이라 실제 선박명만 넣는다.
        "id": VESSEL_ID_BULK,
        "imo_number": SYNTHETIC_IMO_BULK,
        "name": "샘플 벌크선 (50,000 DWT)",
        "ship_type": "BULK_CARRIER",
        # tests/fixtures/cii/bulk_50000_hfo_2026.json 의 input.gross_tonnage 와 같다.
        # 정본 픽스처가 이 배의 제원을 이미 정의하고 있으므로 새로 만들지 않는다.
        "gross_tonnage": Decimal("30000.00"),
        "deadweight": Decimal("50000.00"),
        # `default_fuel_type`은 NULL을 유지한다 — 018 모듈 주석 참조.
        # 값을 넣으면 `fk_vessel_default_fuel_type`이 걸려 **017의 downgrade가
        # 막힌다**(CF 8행을 지울 수 없다). `test_default_fuel_type_is_null`이 잠근다.
        "default_fuel_type": None,
        #
        # 기준 제원 두 값은 **정본 픽스처에서 역산**한다 (#587). 지어낸 값이 아니다.
        #
        #   bulk_50000_hfo_2026.json  distance 1,000nm · speed 12.0kn
        #                             fuel 80.0t · weather_model NONE
        #   TECH_SPEC §4.1            fuel = base_foc_per_day × (v/v_ref)³
        #                                    × weather × distance/(v×24)
        #
        # `v = v_ref`·`weather = 1.0`로 두면 `speed_factor = 1`이 되어
        # 픽스처 값이 그대로 재현된다. 그때 역산은
        #
        #   base_foc_per_day = 80.0 × 12.0 × 24 / 1,000 = 23.04
        #
        # **두 값은 서로 다른 것을 지배한다** — 하나만 채우면 반쪽이 된다.
        #   `reference_speed_kn`      → 기능②(항로 비교)의 연료 추정 가드.
        #                                없으면 422로 막힌다.
        #   `reference_daily_foc_ton` → 시뮬레이션 시계가 진행 중 항차의 연료·거리를
        #                                만드는 입력(TECH_SPEC §시계). 없으면 그 기여를
        #                                통째로 버리고 `SIMULATION_NO_FUEL_RATE`를 낸다.
        #                                기능③의 감속 민감도도 이 값이 없으면 **0이 된다**
        #                                (`calc/annual_simulation.py` `_shift_speed`).
        "reference_speed_kn": Decimal("12.00"),
        "reference_daily_foc_ton": Decimal("23.04"),
        # GT 30,000 >= 5,000 → 공식 CII 적용 대상.
        "is_cii_applicable_hint": True,
    },
    {
        # 제원 조사 회신 2026-08-07 (조사: sty2581). 출처 namsung.co.kr (남성해운).
        "id": VESSEL_ID_CONTAINER,
        "imo_number": "9448839",
        "name": "STAR SKIPPER",
        "ship_type": "CONTAINER_SHIP",
        # GT 미회신. 모듈 docstring 「is_cii_applicable_hint」 항 참조.
        "gross_tonnage": None,
        "deadweight": Decimal("9520.00"),
        "default_fuel_type": None,
        "reference_speed_kn": Decimal("16.50"),
        "reference_daily_foc_ton": None,
        "is_cii_applicable_hint": False,
    },
    {
        # 제원 조사 회신 2026-08-07 (조사: sty2581). 출처 djship.co.kr (동진상선).
        "id": VESSEL_ID_GENERAL_CARGO,
        "imo_number": "9633862",
        "name": "DONGJIN ENDURANCE",
        "ship_type": "GENERAL_CARGO_SHIP",
        "gross_tonnage": None,
        "deadweight": Decimal("6405.77"),
        "default_fuel_type": None,
        # 회신 원문은 "12,8 KNOT"이며 소수점 구분자가 쉼표로 적힌 것이다.
        "reference_speed_kn": Decimal("12.80"),
        "reference_daily_foc_ton": None,
        "is_cii_applicable_hint": False,
    },
]


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
# 벌크선(발표 동선의 위험 선박)에 진행 중·계획 항차를 준다 (#587).
V1_IN_PROGRESS = "00000000-0000-4000-8000-000000000110"
V1_PLANNED = "00000000-0000-4000-8000-000000000111"

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
        "imo_number": "0000024",
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
    {
        # 벌크선의 진행 중 항차 (#587).
        #
        # 종전에는 이 배가 `UNDER_WAY / SAILING`(대한해협)인데 **진행 중 항차가
        # 없었다** — 선박 상세는 「항해 중」인데 실시간 CII는 「진행 중 항차가
        # 없습니다」를 냈다. 발표 동선이 이 배로 드릴다운하므로 그 화면이 비어 보였다.
        #
        # 효율은 V1_2026 실적(620t / 4,300nm ≈ 0.144 t/nm)에 맞춰 둔다. 위험 선박
        # 서사를 흔들지 않기 위해서다.
        "id": V1_IN_PROGRESS,
        "vessel_id": VESSEL_ID_BULK,
        "voyage_no": "2026-02",
        "status": "IN_PROGRESS",
        "annual_inclusion_policy": "INCLUDE_AS_PLAN",
        "regulation_year": 2026,
        "departure_port_name": "BUSAN",
        "arrival_port_name": "SINGAPORE",
        "planned_distance_nm": Decimal("2300.00"),
        "actual_distance_nm": None,
        "planned_speed_kn": Decimal("14.00"),
        "actual_avg_speed_kn": None,
        #
        # 시각을 **도착 예정일이 아직 오지 않은 구간**으로 둔다 (#587).
        #
        # 시뮬레이션 시계는 도착 실적이 없으면 `as_of`까지 계속 누적한다
        # (TECH_SPEC §시계 — `window_end = min(as_of, actual_arrival_at)`).
        # 종전 값(08-12 출항 · 08-19 도착 예정)은 **도착 예정일이 이미 지나** 있어
        # 누적이 날짜마다 늘었다 — 하루에 연료 약 23t · 거리 약 336nm씩이다.
        # 그만큼 YTD가 매일 달라져 **같은 시연을 두 번 돌리면 값이 다르다.**
        #
        # 출항을 뒤로 옮겨 누적 구간을 좁힌다. 도착 예정을 09-02로 두어
        # 그때까지는 「진행 중」 상태가 유지된다 — 실시간 CII 화면의 진행 중 항차
        # 기여 카드가 시연 소재를 잃지 않는다.
        #
        # ⚠️ 이것은 **완화이지 해결이 아니다.** 도착 예정일을 지나면 같은 상태로
        # 돌아간다. 시계가 예정일 초과를 어떻게 다룰지는 시드가 아니라 구현의
        # 문제이므로 후속 이슈로 분리한다.
        "planned_departure_at": _utc(2026, 8, 20),
        "planned_arrival_at": _utc(2026, 9, 2),
        "actual_departure_at": _utc(2026, 8, 20, 6),
        "actual_arrival_at": None,
    },
    {
        # 벌크선의 계획 항차 (#587).
        #
        # 종전 시드에는 `PLANNED`·`DRAFT`가 **한 건도 없었다.** 항로 비교 결과 채택
        # (`scenario_adopt`)이 계획 단계 항차만 받으므로(`services/scenario_adopt.py`
        # `PLANNING_STATUSES`) 그 동선을 시연할 대상이 없었다.
        #
        # `INCLUDE_AS_PLAN`이라 **YTD 집계에는 들어가지 않는다**(`services/ytd_cii.py`
        # 표) — Fixture 1의 4.982 / 5.045 / C는 그대로다. 연간 시뮬레이션의
        # 「남은 계획 항차」로만 잡혀 `DESIGN_SYSTEM §10.2` 스택 바가 여러 구간을 낸다.
        "id": V1_PLANNED,
        "vessel_id": VESSEL_ID_BULK,
        "voyage_no": "2026-03",
        "status": "PLANNED",
        "annual_inclusion_policy": "INCLUDE_AS_PLAN",
        "regulation_year": 2026,
        "departure_port_name": "SINGAPORE",
        "arrival_port_name": "BUSAN",
        "planned_distance_nm": Decimal("2300.00"),
        "actual_distance_nm": None,
        "planned_speed_kn": Decimal("14.00"),
        "actual_avg_speed_kn": None,
        "planned_departure_at": _utc(2026, 9, 5),
        "planned_arrival_at": _utc(2026, 9, 12),
        "actual_departure_at": None,
        "actual_arrival_at": None,
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
    {
        # 진행 중 항차 — 계획값만. 실적은 항해가 끝나야 들어온다.
        "id": "00000000-0000-4000-8000-000000000410",
        "voyage_id": V1_IN_PROGRESS,
        "planned_fuel_ton": Decimal("331.00"),
        "actual_fuel_ton": None,
    },
    {
        "id": "00000000-0000-4000-8000-000000000411",
        "voyage_id": V1_PLANNED,
        "planned_fuel_ton": Decimal("331.00"),
        "actual_fuel_ton": None,
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
    sa.column("position_updated_at", sa.DateTime(timezone=True)),
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
    sa.column("planned_departure_at", sa.DateTime(timezone=True)),
    sa.column("planned_arrival_at", sa.DateTime(timezone=True)),
    sa.column("actual_departure_at", sa.DateTime(timezone=True)),
    sa.column("actual_arrival_at", sa.DateTime(timezone=True)),
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
    sa.column("started_at", sa.DateTime(timezone=True)),
    sa.column("ended_at", sa.DateTime(timezone=True)),
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
    #
    # 030이 신설한 CF snapshot (`#378`). **027 시점에는 없던 컬럼**이라 그때의 seed에는
    # 값이 없었고 030의 backfill이 채웠다. 지금은 head 스키마에 넣으므로 처음부터
    # 채워야 한다 — NOT NULL이다.
    #
    sa.column("cf_used", sa.Numeric),
)

# HFO CF (tCO₂/tFuel) — 017 seed·DB_SCHEMA §3.2와 동일한 값.
HFO_CF = Decimal("3.114000")

# 적재 대상 테이블의 경량 선언. 실제 컬럼 정의는 각 스키마 마이그레이션이 소유한다.
#
# ⚠️ ``id``를 ``String``으로 두면 안 된다. 실제 컬럼은 ``uuid``이고 asyncpg는 서버 타입과
# 파라미터 타입이 다르면 캐스팅하지 않고 거부한다 — 문자열로 값을 적더라도 **선언은 실제
# 타입을 따라야** 한다.
_vessel = sa.table(
    "vessel",
    sa.column("id", postgresql.UUID(as_uuid=False)),
    sa.column("imo_number", sa.String),
    sa.column("name", sa.String),
    sa.column("ship_type", sa.String),
    sa.column("gross_tonnage", sa.Numeric),
    sa.column("deadweight", sa.Numeric),
    sa.column("default_fuel_type", sa.String),
    sa.column("reference_speed_kn", sa.Numeric),
    sa.column("reference_daily_foc_ton", sa.Numeric),
    sa.column("is_cii_applicable_hint", sa.Boolean),
)


async def _insert_ignoring_existing(conn: AsyncConnection, table, rows: list[dict]) -> int:
    """이미 있는 행은 건너뛴다. 돌려주는 값은 **실제로 넣은** 행 수다.

    ``ON CONFLICT DO NOTHING``은 충돌한 행에 대해 아무것도 반환하지 않으므로,
    ``RETURNING``으로 돌아온 행의 수가 곧 신규 적재 수다.

    ``rowcount``를 쓰지 않는 이유는 모듈 docstring 참조 (#481) — executemany 경로에서
    ``-1``이 나온다.
    """
    if not rows:
        return 0
    result = await conn.execute(
        pg_insert(table).on_conflict_do_nothing().returning(table.c.id), rows
    )
    return len(result.fetchall())


async def seed_demo(conn: AsyncConnection) -> dict[str, int]:
    """데모 데이터를 적재하고 테이블별 **신규 적재 행 수**를 돌려준다.

    호출자가 트랜잭션을 관리한다 — 이 함수는 commit하지 않는다(``db.seed``와 같은 규약).
    """
    counts = {
        "vessel": await _insert_ignoring_existing(conn, _vessel, SEED_VESSELS),
    }
    counts["vessel"] += await _insert_ignoring_existing(conn, vessel_tbl, SEED_VESSEL_GT_AXIS)

    #
    # 운항 상태·위치는 018의 3척에 **덧씌우는** 값이라 INSERT가 아니라 UPDATE다.
    # 이미 상태가 있는 선박은 건드리지 않는다 — 사용자가 위치를 갱신했을 수 있다.
    #
    for vid, underway, detail, lat, lon, updated in SEED_STATE_UPDATES:
        await conn.execute(
            sa.text(
                "UPDATE vessel SET underway_state = :st, detail_status = :ds, "
                "current_lat = CAST(:lat AS numeric), current_lon = CAST(:lon AS numeric), "
                "position_updated_at = :ts "
                "WHERE id = CAST(:vid AS uuid) AND underway_state IS NULL"
            ),
            {
                "st": underway,
                "ds": detail,
                "lat": lat,
                "lon": lon,
                # 문자열을 그대로 바인딩하면 asyncpg가 거부한다 — 서버 타입이
                # timestamptz인데 파라미터가 str이면 캐스팅하지 않는다. 이 데이터는
                # 027에서 raw SQL 리터럴로 쓰였던 것이라 문자열로 남아 있다.
                "ts": datetime.fromisoformat(updated),
                "vid": vid,
            },
        )

    counts["voyage"] = await _insert_ignoring_existing(conn, voyage_tbl, SEED_VOYAGES)
    counts["voyage_fuel_use"] = await _insert_ignoring_existing(
        conn,
        voyage_fuel_tbl,
        [
            {**row, "fuel_type": "HFO", "cf_used": HFO_CF, "source": "SAMPLE"}
            for row in SEED_VOYAGE_FUELS
        ],
    )
    counts["not_underway_period"] = await _insert_ignoring_existing(conn, period_tbl, SEED_PERIODS)
    counts["not_underway_fuel_use"] = await _insert_ignoring_existing(
        conn,
        period_fuel_tbl,
        [{**row, "cf_used": HFO_CF} for row in SEED_PERIOD_FUELS],
    )
    return counts


async def clear_demo(conn: AsyncConnection) -> dict[str, int]:
    """데모 데이터를 지운다. **계산 이력이 참조하는 것은 남긴다.**

    ## 왜 전부 지우지 못하는가

    ``calculation_run``은 UPDATE·DELETE가 트리거로 차단된 **보존 대상**이다
    (`DB_SCHEMA §7.3`). 그 이력이 참조하는 항차·선박은 ``RESTRICT``에 걸려 지워지지
    않는다 — 그리고 그것이 옳다. 계산 이력은 「그때 무슨 데이터로 계산했나」에 답하는
    근거이고, 참조 대상이 사라지면 그 답이 불완전해진다.

    그래서 이 함수는 **막히는 것을 억지로 지우지 않고, 남긴 수를 돌려준다.** 조용히
    실패하거나 조용히 성공한 척하지 않는다.

    ## 스키마 롤백 전에 부른다

    데모 데이터가 남아 있으면 ``downgrade 016``(fuel_type CF seed 회수)이
    ``fk_voyage_fuel_use_fuel_type``에 막힌다. 데모 연료 실적이 HFO를 참조하기
    때문이다. **데모 데이터는 스키마가 아니므로 스키마 롤백이 그것을 치우게 만들지
    않는다** — 지우는 것은 이 함수의 몫이다.
    """
    voyage_ids = [row["id"] for row in SEED_VOYAGES]
    period_ids = [row["id"] for row in SEED_PERIODS]
    vessel_ids = [row["id"] for row in SEED_VESSELS] + [row["id"] for row in SEED_VESSEL_GT_AXIS]

    counts: dict[str, int] = {}

    #
    # 참조가 없는 자식부터. 이 둘이 ``fuel_type``을 참조하므로 **여기까지만 지워도
    # 017 롤백이 풀린다.**
    #
    counts["not_underway_fuel_use"] = await _delete_where(
        conn, "not_underway_fuel_use", "period_id", period_ids
    )
    counts["not_underway_period"] = await _delete_where(
        conn, "not_underway_period", "id", period_ids
    )
    counts["voyage_fuel_use"] = await _delete_where(
        conn, "voyage_fuel_use", "voyage_id", voyage_ids
    )

    # 항차·선박은 계산 이력이 걸려 있으면 남는다.
    counts["voyage"] = await _delete_unreferenced(conn, "voyage", voyage_ids, "voyage_id")
    counts["vessel"] = await _delete_unreferenced(conn, "vessel", vessel_ids, "vessel_id")
    counts["kept_voyage"] = len(voyage_ids) - counts["voyage"]
    counts["kept_vessel"] = len(vessel_ids) - counts["vessel"]
    return counts


async def _delete_where(conn: AsyncConnection, table: str, column: str, ids: list) -> int:
    """지운 행 수를 돌려준다. 세는 방법은 모듈 docstring의 규칙을 따른다 (#481)."""
    if not ids:
        return 0
    result = await conn.execute(
        sa.text(  # noqa: S608 - 테이블·컬럼명은 이 모듈의 리터럴, 값은 바인딩된다
            f"DELETE FROM {table} WHERE {column} = ANY(CAST(:ids AS uuid[])) RETURNING id"
        ),
        {"ids": ids},
    )
    return len(result.fetchall())


async def _delete_unreferenced(
    conn: AsyncConnection,
    table: str,
    ids: list,
    calc_run_column: str,
) -> int:
    """``calculation_run``이 참조하지 않는 행만 지운다.

    ``RESTRICT``에 걸려 예외로 중단되는 대신 **미리 걸러낸다** — 한 척이 막혔다고 나머지를
    못 지우게 되면, 부분 정리조차 불가능해진다.

    돌려주는 값은 **실제로 지운** 행 수이며, 호출자는 이것으로 「남긴 수」를 계산한다
    (``kept_voyage``·``kept_vessel``). 그래서 이 값이 틀리면 **남긴 수까지 함께 틀린다.**
    """
    if not ids:
        return 0
    result = await conn.execute(
        sa.text(  # noqa: S608 - 테이블·컬럼명은 이 모듈의 리터럴, 값은 바인딩된다
            f"DELETE FROM {table} WHERE id = ANY(CAST(:ids AS uuid[])) "
            f"AND id NOT IN (SELECT {calc_run_column} FROM calculation_run "
            f"WHERE {calc_run_column} IS NOT NULL) RETURNING id"
        ),
        {"ids": ids},
    )
    return len(result.fetchall())


async def main() -> None:  # pragma: no cover - 프로세스 진입점
    """엔진을 열고 단일 트랜잭션으로 데모 데이터를 적재한다.

    ``python -m cii_platform.db.demo_seed``로 실행한다. 진입점을 패키지 안에 둔 이유는
    ``db.seed``와 같다 — **프로덕션 이미지가 wheel만 설치**하므로 ``scripts/``를 배포
    절차의 명령으로 쓸 수 없다.
    """
    from sqlalchemy import pool
    from sqlalchemy.ext.asyncio import create_async_engine

    from cii_platform.config import DATABASE_URL
    from cii_platform.db.url import normalize_to_asyncpg

    engine = create_async_engine(normalize_to_asyncpg(DATABASE_URL), poolclass=pool.NullPool)
    try:
        async with engine.begin() as conn:
            counts = await seed_demo(conn)
    finally:
        await engine.dispose()

    for table, count in counts.items():
        print(f"{table}: {count}행 신규 적재")


if __name__ == "__main__":  # pragma: no cover - 프로세스 진입점
    import asyncio

    asyncio.run(main())
