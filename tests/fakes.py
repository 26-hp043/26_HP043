"""DB 없이 API·서비스 계층을 검증하기 위한 대역 (#55 · #51).

**왜 필요한가** — 계산 API의 결함은 대부분 「계산이 틀렸다」가 아니라 **「조립이 틀렸다」**
(필드명·자릿수·타입·오류 코드)이고, 그건 DB 없이도 잡을 수 있다. PostgreSQL이 있어야만
돌아가는 테스트로 몰아 두면 로컬에서 한 번도 실행되지 않은 채 CI에서 처음 돌게 된다.

DB가 필요한 성질(마이그레이션·제약·트랜잭션)은 별도 테스트가 담당한다.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

# --- 정본 픽스처와 같은 조건 ---------------------------------------------------------
#
# tests/fixtures/cii/bulk_50000_hfo_2026.json 의 input 과 같은 값이다. 이 값을 쓰면
# API 응답이 #132 계약 기대값과 같아야 한다.

DEMO_VESSEL_ID = UUID("00000000-0000-4000-8000-000000000001")
DEMO_YEAR = 2026


@dataclass
class FakeVessel:
    """``db.models.vessel.Vessel`` 대역. 서비스가 읽는 속성만 갖는다."""

    id: UUID = DEMO_VESSEL_ID
    imo_number: str = "0000001"
    name: str = "샘플 벌크선 (50,000 DWT)"
    ship_type: str = "BULK_CARRIER"
    gross_tonnage: Decimal | None = Decimal("30000.00")
    deadweight: Decimal | None = Decimal("50000.00")
    default_fuel_type: str | None = None
    reference_speed_kn: Decimal | None = None
    reference_daily_foc_ton: Decimal | None = None
    is_cii_applicable_hint: bool = True
    is_deleted: bool = False
    created_at: dt.datetime = dt.datetime(2026, 8, 7, tzinfo=dt.UTC)
    updated_at: dt.datetime = dt.datetime(2026, 8, 7, tzinfo=dt.UTC)


@dataclass
class FakeRegulationYear:
    """``regulation_year`` 대역. Z계수는 MEPC.400(83) 2026년 값이다."""

    year: int = DEMO_YEAR
    z_factor_percent: Decimal = Decimal("11.0000")
    is_active: bool = True


@dataclass
class FakeReferenceLine:
    """``cii_reference_line`` 대역. BULK_CARRIER DWT < 279,000 행이다."""

    ship_type: str = "BULK_CARRIER"
    condition_expr: str = "DWT < 279000"
    capacity_rule: str = "DWT"
    a_raw: str = "4745"
    a_decimal: Decimal = Decimal("4745.000000")
    c: Decimal = Decimal("0.622000")
    source_ref: str = "MEPC.353(78)"


@dataclass
class FakeRatingBoundary:
    """``cii_rating_boundary`` 대역. BULK_CARRIER d-vector다."""

    ship_type: str = "BULK_CARRIER"
    condition_expr: str = "all"
    capacity_basis: str = "DWT"
    d1: Decimal = Decimal("0.8600")
    d2: Decimal = Decimal("0.9400")
    d3: Decimal = Decimal("1.0600")
    d4: Decimal = Decimal("1.1800")
    source_ref: str = "MEPC.354(78)"


@dataclass
class FakeFuelType:
    """``fuel_type`` 대역."""

    code: str = "HFO"
    display_name: str = "Heavy Fuel Oil"
    cf: Decimal = Decimal("3.114000")
    is_active: bool = True


@dataclass
class FakeCalculationRun:
    """저장된 ``calculation_run`` 대역. 응답의 ``calculation_run_id``에 쓰인다."""

    id: UUID = field(default_factory=uuid4)


class FakeSession:
    """``AsyncSession`` 대역.

    저장소 함수를 monkeypatch로 갈아 끼우므로 세션 자체는 **아무 일도 하지 않는다.**
    ``commit``·``flush``가 호출됐는지만 기록해 두어, 서비스가 트랜잭션을 닫는지
    테스트가 확인할 수 있게 한다.
    """

    def __init__(self) -> None:
        self.committed = 0
        self.flushed = 0
        self.added: list[Any] = []

    async def commit(self) -> None:
        self.committed += 1

    async def flush(self) -> None:
        self.flushed += 1

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def close(self) -> None:
        return None
