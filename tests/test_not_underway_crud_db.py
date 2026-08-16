"""not under way 구간 CRUD 서비스 검증 (#370).

이 이슈의 위험은 **계산이 아니라 쓰기 규칙**에 있다. 값 자체는 ``#353``이 이미
읽어 계산하고 그 테스트가 따로 있으므로, 여기서는 넷을 본다.

* **겹침 금지** — 같은 정박이 두 번 들어가면 ``M``이 두 배가 되고 등급이 실제보다
  나쁘게 나온다. 열린 구간(진행 중)의 취급이 특히 갈리기 쉽다.
* **CF snapshot** — ``cf_used``는 NOT NULL이며 서버가 뜬다. 화면이 보내면 사용자가
  배출계수를 정하게 된다(``PRD §8.4``).
* **소프트 삭제** — 지운 구간이 집계에서 즉시 빠지되 행은 남아야 한다.
* **DB CHECK 제약을 422로 먼저 잡는 것** — 제약에 맡기면 500이 되고, 사용자는
  고칠 수 있는 입력을 「서버 오류」로 보게 된다.

DB 없이 볼 수 있는 규칙(연도 귀속)은 순수 함수로 보고, 나머지는 DB로 본다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.db.repositories import not_underway as nu_repo
from cii_platform.errors import ConflictError, NotFoundError, ValidationError
from cii_platform.services.not_underway import (
    _resolve_regulation_year,
    add_fuel_use,
    create_period,
    delete_fuel_use,
    delete_period,
    list_periods,
    update_period,
)

YEAR = 2026


def _at(month: int, day: int, hour: int = 0) -> datetime:
    return datetime(YEAR, month, day, hour, tzinfo=UTC)


# ─────────────────────────────────────────────────────────────────────────────
# 귀속 연도 — DB 없이 본다
# ─────────────────────────────────────────────────────────────────────────────


def test_year_defaults_to_start_year():
    """생략하면 시작 시각의 연도다. 매번 묻는 것은 실수를 만드는 질문이다."""
    assert _resolve_regulation_year(_at(8, 10), _at(8, 12), None) == YEAR


def test_year_may_be_the_end_year_when_period_spans_new_year():
    """연말을 걸치는 구간은 **어느 해에 넣을지가 판단 사항**이라 선택을 받는다."""
    start = datetime(2026, 12, 30, tzinfo=UTC)
    end = datetime(2027, 1, 2, tzinfo=UTC)
    assert _resolve_regulation_year(start, end, 2027) == 2027
    assert _resolve_regulation_year(start, end, 2026) == 2026


def test_year_unrelated_to_the_period_is_rejected():
    """2020년 구간을 2026년으로 넣는 것은 판단이 아니라 오타다."""
    with pytest.raises(ValidationError):
        _resolve_regulation_year(_at(8, 10), _at(8, 12), 2020)


def test_open_period_allows_only_the_start_year():
    """진행 중 구간은 끝난 해를 알 수 없으므로 시작 연도만 허용한다."""
    with pytest.raises(ValidationError):
        _resolve_regulation_year(_at(8, 10), None, YEAR + 1)


# ─────────────────────────────────────────────────────────────────────────────
# DB 기반
# ─────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


@pytest_asyncio.fixture
async def vessel_id(session):
    """이 테스트 전용 선박. 트랜잭션이 롤백되므로 실제 데이터는 그대로다."""
    new_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
            "default_fuel_type) VALUES (:id, :imo, 'NU TEST', 'BULK_CARRIER', "
            "50000, 'HFO')"
        ),
        # IMO는 UNIQUE다. 7자리 숫자 형식 제약을 지키면서 충돌하지 않도록 UUID에서 뽑는다.
        {"id": new_id, "imo": f"9{new_id.int % 1000000:06d}"},
    )
    return new_id


async def _create(session, vessel_id, *, start, end, fuel_uses=None, **over):
    payload = {
        "period_type": "AT_ANCHOR",
        "started_at": start,
        "ended_at": end,
        "port_name": "Busan",
        "lat": None,
        "lon": None,
        "distance_nm": Decimal("0"),
        "regulation_year": None,
        "voyage_id": None,
        "fuel_uses": fuel_uses or [],
    }
    payload.update(over)
    return await create_period(session, vessel_id, **payload)


# ── 겹침 ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_overlapping_period_is_rejected(session, vessel_id):
    """같은 정박이 두 번 들어가면 M이 두 배가 된다 — 등급이 실제보다 나빠진다."""
    await _create(session, vessel_id, start=_at(8, 10), end=_at(8, 12))
    with pytest.raises(ConflictError):
        await _create(session, vessel_id, start=_at(8, 11), end=_at(8, 13))


@pytest.mark.asyncio
async def test_touching_periods_are_allowed(session, vessel_id):
    """앞 구간의 종료 == 뒤 구간의 시작은 겹침이 아니다.

    접안 종료 즉시 운하 진입 같은 연속 기록이 정상이다. 경계를 닫힘-닫힘으로 보면
    이 정상 기록이 막힌다.
    """
    await _create(session, vessel_id, start=_at(8, 10), end=_at(8, 12))
    later = await _create(
        session, vessel_id, start=_at(8, 12), end=_at(8, 13), period_type="CANAL_TRANSIT"
    )
    assert later["period_type"] == "CANAL_TRANSIT"


@pytest.mark.asyncio
async def test_open_period_blocks_everything_after_it(session, vessel_id):
    """진행 중 구간은 무한대로 취급한다.

    이 규칙이 없으면 「정박 중」인 선박에 다음 정박을 미리 넣을 수 있고, 그러면 둘
    중 하나는 반드시 틀린 기록이다.
    """
    await _create(session, vessel_id, start=_at(8, 10), end=None)
    with pytest.raises(ConflictError):
        await _create(session, vessel_id, start=_at(9, 1), end=_at(9, 2))


@pytest.mark.asyncio
async def test_period_before_an_open_period_is_allowed(session, vessel_id):
    """열린 구간이 있어도 그보다 **앞선** 구간은 겹치지 않는다."""
    await _create(session, vessel_id, start=_at(8, 10), end=None)
    earlier = await _create(session, vessel_id, start=_at(7, 1), end=_at(7, 3))
    assert earlier["ended_at"] is not None


@pytest.mark.asyncio
async def test_another_vessel_may_overlap(session, vessel_id):
    """겹침은 **같은 선박 안에서만** 문제다. 선대의 배들은 동시에 정박한다."""
    other = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
            "default_fuel_type) VALUES (:id, :imo, 'NU TEST 2', 'BULK_CARRIER', "
            "50000, 'HFO')"
        ),
        {"id": other, "imo": f"9{other.int % 1000000:06d}"},
    )
    await _create(session, vessel_id, start=_at(8, 10), end=_at(8, 12))
    twin = await _create(session, other, start=_at(8, 10), end=_at(8, 12))
    assert twin["vessel_id"] == str(other)


@pytest.mark.asyncio
async def test_closing_an_open_period_does_not_clash_with_itself(session, vessel_id):
    """자기 자신을 겹침으로 보면 진행 중 구간을 영영 닫을 수 없다."""
    period = await _create(session, vessel_id, start=_at(8, 10), end=None)
    closed = await update_period(session, uuid_of(period), ended_at=_at(8, 12))
    assert closed["ended_at"] is not None


def uuid_of(period: dict) -> object:
    from uuid import UUID

    return UUID(str(period["id"]))


# ── CF snapshot ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cf_is_snapshotted_by_the_server(session, vessel_id):
    """화면은 CF를 보내지 않는다. 서버가 계산 시점 값을 떠서 행에 박는다."""
    created = await _create(
        session,
        vessel_id,
        start=_at(8, 10),
        end=_at(8, 12),
        fuel_uses=[
            {
                "consumer_type": "OIL_FIRED_BOILER",
                "fuel_type": "HFO",
                "fuel_ton": Decimal("12"),
            }
        ],
    )
    cf = created["fuel_uses"][0]["cf_used"]
    assert cf is not None and cf > 0

    stored = await session.scalar(
        text("SELECT cf FROM fuel_type WHERE code = 'HFO'"),
    )
    assert Decimal(str(cf)) == Decimal(str(stored))


@pytest.mark.asyncio
async def test_unknown_fuel_is_rejected_before_any_write(session, vessel_id):
    """알 수 없는 연료는 422다. 구간만 남고 연료가 빠지는 상태를 만들지 않는다."""
    with pytest.raises(ValidationError):
        await _create(
            session,
            vessel_id,
            start=_at(8, 10),
            end=_at(8, 12),
            fuel_uses=[
                {"consumer_type": "AUX_ENGINE", "fuel_type": "UNOBTANIUM", "fuel_ton": Decimal("1")}
            ],
        )
    assert await list_periods(session, vessel_id) == []


@pytest.mark.asyncio
async def test_duplicate_fuel_rows_in_one_request_are_rejected(session, vessel_id):
    """DB unique 인덱스에 맡기면 IntegrityError로 500이 된다 — 먼저 422로 잡는다."""
    row = {"consumer_type": "AUX_ENGINE", "fuel_type": "HFO", "fuel_ton": Decimal("3")}
    with pytest.raises(ValidationError):
        await _create(session, vessel_id, start=_at(8, 10), end=_at(8, 12), fuel_uses=[row, row])


@pytest.mark.asyncio
async def test_adding_a_duplicate_fuel_later_is_a_conflict(session, vessel_id):
    """뒤에 붙이는 경로도 같은 규칙이다. 409로 「이미 있다」를 알린다."""
    period = await _create(
        session,
        vessel_id,
        start=_at(8, 10),
        end=_at(8, 12),
        fuel_uses=[{"consumer_type": "AUX_ENGINE", "fuel_type": "HFO", "fuel_ton": Decimal("3")}],
    )
    with pytest.raises(ConflictError):
        await add_fuel_use(
            session,
            uuid_of(period),
            consumer_type="AUX_ENGINE",
            fuel_type="HFO",
            fuel_ton=Decimal("1"),
        )


# ── 열거값 ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_period_type_is_422_not_500(session, vessel_id):
    """DB CHECK 제약에 맡기면 IntegrityError가 500이 된다."""
    with pytest.raises(ValidationError):
        await _create(session, vessel_id, start=_at(8, 10), end=_at(8, 12), period_type="MOORED")


@pytest.mark.asyncio
async def test_unknown_consumer_type_is_422_not_500(session, vessel_id):
    with pytest.raises(ValidationError):
        await _create(
            session,
            vessel_id,
            start=_at(8, 10),
            end=_at(8, 12),
            fuel_uses=[{"consumer_type": "GALLEY", "fuel_type": "HFO", "fuel_ton": Decimal("1")}],
        )


# ── 수정 ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_moving_end_before_start_is_rejected(session, vessel_id):
    """한쪽만 보내는 것이 정상이라 **기존 행과 합쳐 봐야** 순서를 알 수 있다."""
    period = await _create(session, vessel_id, start=_at(8, 10), end=_at(8, 12))
    with pytest.raises(ValidationError):
        await update_period(session, uuid_of(period), ended_at=_at(8, 9))


@pytest.mark.asyncio
async def test_reopening_a_closed_period(session, vessel_id):
    """``ended_at``의 명시적 null은 클리어가 아니라 「다시 진행 중」이다."""
    period = await _create(session, vessel_id, start=_at(8, 10), end=_at(8, 12))
    reopened = await update_period(session, uuid_of(period), ended_at=None)
    assert reopened["ended_at"] is None


@pytest.mark.asyncio
async def test_clearing_a_not_null_column_is_422(session, vessel_id):
    """NOT NULL 열의 null은 「클리어」가 아니라 잘못된 입력이다 — 500이 아니라 422."""
    period = await _create(session, vessel_id, start=_at(8, 10), end=_at(8, 12))
    with pytest.raises(ValidationError):
        await update_period(session, uuid_of(period), started_at=None)


@pytest.mark.asyncio
async def test_moving_a_period_into_another_year_moves_its_regulation_year(session, vessel_id):
    """시각이 바뀌면 귀속 연도도 따라 옮긴다 — 아니면 집계에서 사라진다."""
    period = await _create(session, vessel_id, start=_at(8, 10), end=_at(8, 12))
    moved = await update_period(
        session,
        uuid_of(period),
        started_at=datetime(2027, 3, 1, tzinfo=UTC),
        ended_at=datetime(2027, 3, 2, tzinfo=UTC),
    )
    assert moved["regulation_year"] == 2027


# ── 삭제 ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_is_soft_and_leaves_the_row(session, vessel_id):
    """지운 구간이 사라지면 같은 연도를 다시 계산할 때 값이 조용히 달라진다."""
    period = await _create(session, vessel_id, start=_at(8, 10), end=_at(8, 12))
    await delete_period(session, uuid_of(period))

    assert await list_periods(session, vessel_id) == []
    row = await nu_repo.get_period(session, uuid_of(period))
    assert row is not None and row.is_deleted is True


@pytest.mark.asyncio
async def test_deleted_period_frees_its_time_range(session, vessel_id):
    """삭제한 구간은 집계에서 빠지므로 겹침 판정에서도 빠져야 한다."""
    period = await _create(session, vessel_id, start=_at(8, 10), end=_at(8, 12))
    await delete_period(session, uuid_of(period))
    again = await _create(session, vessel_id, start=_at(8, 10), end=_at(8, 12))
    assert again["id"] != period["id"]


@pytest.mark.asyncio
async def test_deleted_period_is_404_not_409(session, vessel_id):
    """소프트 삭제는 내부 사정이다 — 사용자에게는 없는 것과 같다."""
    period = await _create(session, vessel_id, start=_at(8, 10), end=_at(8, 12))
    await delete_period(session, uuid_of(period))
    with pytest.raises(NotFoundError):
        await update_period(session, uuid_of(period), port_name="Ulsan")


@pytest.mark.asyncio
async def test_fuel_use_of_another_period_cannot_be_deleted(session, vessel_id):
    """자식 ID만 받으면 URL을 바꿔 남의 구간을 지울 수 있고, CII 값이 조용히 바뀐다."""
    a = await _create(
        session,
        vessel_id,
        start=_at(8, 10),
        end=_at(8, 12),
        fuel_uses=[{"consumer_type": "AUX_ENGINE", "fuel_type": "HFO", "fuel_ton": Decimal("3")}],
    )
    b = await _create(session, vessel_id, start=_at(9, 1), end=_at(9, 2))

    with pytest.raises(NotFoundError):
        await delete_fuel_use(session, uuid_of(b), uuid_of(a["fuel_uses"][0]))


# ── 목록 ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_list_is_not_an_error(session, vessel_id):
    """정박 기록이 없는 선박은 정상 상태다."""
    assert await list_periods(session, vessel_id) == []


@pytest.mark.asyncio
async def test_unknown_vessel_is_404(session):
    with pytest.raises(NotFoundError):
        await list_periods(session, uuid4())


@pytest.mark.asyncio
async def test_list_is_newest_first(session, vessel_id):
    """계산은 시간순으로 훑고, 입력 화면은 방금 넣은 것부터 본다."""
    await _create(session, vessel_id, start=_at(7, 1), end=_at(7, 2))
    await _create(session, vessel_id, start=_at(8, 1), end=_at(8, 2))
    rows = await list_periods(session, vessel_id)
    assert [r["started_at"][:10] for r in rows] == ["2026-08-01", "2026-07-01"]


@pytest.mark.asyncio
async def test_list_carries_fuel_uses(session, vessel_id):
    """목록이 연료를 함께 준다 — 구간마다 다시 부르면 N+1이다."""
    await _create(
        session,
        vessel_id,
        start=_at(8, 10),
        end=_at(8, 12),
        fuel_uses=[
            {"consumer_type": "AUX_ENGINE", "fuel_type": "HFO", "fuel_ton": Decimal("3")},
            {
                "consumer_type": "OIL_FIRED_BOILER",
                "fuel_type": "HFO",
                "fuel_ton": Decimal("12"),
            },
        ],
    )
    rows = await list_periods(session, vessel_id)
    assert len(rows[0]["fuel_uses"]) == 2


# ── 계산과의 연결 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_created_fuel_reaches_the_ytd_aggregate(session, vessel_id):
    """**이 이슈의 존재 이유다.** 넣은 연료가 #353의 집계에 실제로 도달해야 한다.

    도달하지 않으면 M이 늘지 않아 「정박해도 등급이 안 떨어지는」 상태 그대로다.
    """
    await _create(
        session,
        vessel_id,
        start=_at(8, 10),
        end=_at(8, 12),
        fuel_uses=[
            {
                "consumer_type": "OIL_FIRED_BOILER",
                "fuel_type": "HFO",
                "fuel_ton": Decimal("12"),
            }
        ],
    )
    totals = await nu_repo.sum_fuel_by_type(session, vessel_id=vessel_id, regulation_year=YEAR)
    assert [(t.fuel_type, t.fuel_ton) for t in totals] == [("HFO", Decimal("12.00"))]


@pytest.mark.asyncio
async def test_created_distance_reaches_the_denominator(session, vessel_id):
    """운하 통과 거리는 CII 분모 ``Dt``에 더해진다(MEPC.412(84) §4.2)."""
    await _create(
        session,
        vessel_id,
        start=_at(8, 10),
        end=_at(8, 12),
        period_type="CANAL_TRANSIT",
        distance_nm=Decimal("80"),
    )
    total = await nu_repo.sum_distance(session, vessel_id=vessel_id, regulation_year=YEAR)
    assert total == Decimal("80.00")


@pytest.mark.asyncio
async def test_deleted_period_leaves_the_aggregate(session, vessel_id):
    """소프트 삭제한 구간은 집계에서 **즉시** 빠져야 한다."""
    period = await _create(
        session,
        vessel_id,
        start=_at(8, 10),
        end=_at(8, 12),
        fuel_uses=[
            {
                "consumer_type": "OIL_FIRED_BOILER",
                "fuel_type": "HFO",
                "fuel_ton": Decimal("12"),
            }
        ],
    )
    await delete_period(session, uuid_of(period))
    totals = await nu_repo.sum_fuel_by_type(session, vessel_id=vessel_id, regulation_year=YEAR)
    assert totals == []


@pytest.mark.asyncio
async def test_deliberate_year_survives_a_time_edit(session, vessel_id):
    """연말을 걸친 구간에서 **일부러 고른** 연도는 시각을 고쳐도 뒤집히지 않는다.

    무조건 다시 계산하면 사용자의 선택이 조용히 사라진다. 기존 연도가 새 범위에
    여전히 유효하면 그대로 둔다.
    """
    period = await _create(
        session,
        vessel_id,
        start=datetime(2026, 12, 30, tzinfo=UTC),
        end=datetime(2027, 1, 2, tzinfo=UTC),
        regulation_year=2027,
    )
    assert period["regulation_year"] == 2027

    edited = await update_period(
        session, uuid_of(period), ended_at=datetime(2027, 1, 3, tzinfo=UTC)
    )
    assert edited["regulation_year"] == 2027
