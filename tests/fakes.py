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


# --- 인증 미들웨어 대역 (#307) -------------------------------------------------------
#
# auth_middleware는 내부에서 get_sessionmaker()로 DB 세션을 만들어 UserSession·
# AppUser를 조회한다. DB 없이 main.app을 쓰는 API 계약 테스트가 배선 후에도 401에
# 막히지 않게, 이 조회를 고정 행을 돌려주는 대역으로 교체한다.

#: 테스트용 세션·CSRF 토큰 원문 — 쿠키/헤더에 넣는 값.
FAKE_SESSION_TOKEN = "fake-session-token-for-contract-tests"
FAKE_CSRF_TOKEN = "fake-csrf-token-for-contract-tests"

#: 대역 사용자 — 미들웨어가 request.state에 주입하는 AppUser 대신.
FAKE_USER_ID = UUID("00000000-0000-4000-8000-00000000face")


@dataclass
class FakeUserSessionRow:
    """``UserSession`` 대역 — 미들웨어·require_csrf가 읽는 속성만 갖는다."""

    user_id: UUID = FAKE_USER_ID
    csrf_token_hash: str = ""
    expires_at: dt.datetime = field(
        default_factory=lambda: dt.datetime.now(dt.UTC) + dt.timedelta(days=1)
    )
    revoked_at: dt.datetime | None = None


@dataclass
class FakeAppUserRow:
    """``AppUser`` 대역."""

    id: UUID = FAKE_USER_ID
    is_deleted: bool = False


class _FakeAuthResult:
    """``execute()`` 결과 대역 — 엔티티에 따라 고정 행을 돌려준다."""

    def __init__(self, row: Any) -> None:
        self._row = row

    def scalar_one_or_none(self) -> Any:
        return self._row


class _FakeAuthDbSession:
    """미들웨어 안에서 실행되는 select를 엔티티별로 분기해 응답한다."""

    async def execute(self, stmt: Any) -> _FakeAuthResult:
        from cii_platform.db.models.app_user import AppUser
        from cii_platform.db.models.user_session import UserSession

        entity = stmt.column_descriptions[0]["entity"]
        if entity is UserSession:
            from cii_platform.auth.session import hash_token

            return _FakeAuthResult(FakeUserSessionRow(csrf_token_hash=hash_token(FAKE_CSRF_TOKEN)))
        if entity is AppUser:
            return _FakeAuthResult(FakeAppUserRow())
        raise AssertionError(f"예상치 못한 조회: {entity}")


class _FakeAuthSessionmaker:
    """``async with sessionmaker() as s`` 형태만 지원하는 세션팩토리 대역."""

    def __call__(self) -> _FakeAuthSessionmaker:
        return self

    async def __aenter__(self) -> _FakeAuthDbSession:
        return _FakeAuthDbSession()

    async def __aexit__(self, *exc: object) -> bool:
        return False


def install_fake_auth(monkeypatch: Any) -> None:
    """auth_middleware의 DB 조회를 대역으로 교체한다 (#307).

    ``cii_platform.auth.middleware``는 함수 안에서
    ``from cii_platform.db.session import get_sessionmaker``을 부르므로
    원본 모듈의 속성을 갈아끼운다. 요청에는
    ``FAKE_SESSION_TOKEN`` 쿠키와 ``FAKE_CSRF_TOKEN`` 헤더를 함께 보낸다.
    """
    import cii_platform.db.session as db_session_mod

    monkeypatch.setattr(db_session_mod, "get_sessionmaker", _FakeAuthSessionmaker)


def auth_cookie_header() -> dict[str, str]:
    """상태 변경 요청용 기본 헤더 — CSRF 토큰."""
    return {"X-CSRF-Token": FAKE_CSRF_TOKEN}
