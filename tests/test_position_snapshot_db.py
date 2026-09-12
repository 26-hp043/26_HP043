"""선박 위치 스냅샷 · AIS 수집 (#764) — `PRD §21` 「AIS 연동」.

케이스: IT-POS-001 ~ IT-POS-008 (`TEST_PLAN §3.15`)

**AIS 제공자는 아직 없다.** 데모 선박 5척의 IMO가 합성값이라(마이그레이션 `036`)
어떤 출처도 이 배들의 위치를 주지 않는다. 그래서 여기서 보는 것은 「AIS가 맞는
값을 주는가」가 아니라 **받은 것을 우리가 어떻게 다루는가**다:

* 재전송·중복 관측을 한 행으로 접는가 (AIS는 같은 관측을 여러 번 보낸다)
* **늦게 도착한 오래된 관측**이 현재 위치를 뒤로 돌리지 않는가
* 위치가 오지 않은 선박의 마지막 위치를 지우지 않는가
* 모르는 항행 상태를 「정박」으로 단정하지 않는가

이 넷이 틀리면 화면에서 배가 사라지거나 뒤로 간다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.ais.provider import (
    NOT_UNDER_WAY,
    SOURCE_AIS,
    SOURCE_MANUAL,
    UNDER_WAY,
    AisError,
    AisPosition,
    state_pair_from,
)
from cii_platform.db.repositories import position_snapshot as snapshot_repo
from cii_platform.services.position_snapshot import (
    ingest_ais_positions,
    position_age_seconds,
    record_manual_position,
)

OBSERVED = datetime(2026, 9, 12, 3, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def session(conn):
    """``conn``의 트랜잭션에 올라타는 세션 — 테스트 종료 시 함께 롤백된다."""
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _insert_vessel(session, imo: str) -> str:
    row = await session.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type, gross_tonnage, deadweight) "
            f"VALUES ('{imo}', 'AIS TEST {imo}', 'BULK_CARRIER', 30000, 50000) RETURNING id"
        )
    )
    return str(row.scalar_one())


class _FakeProvider:
    """받은 것만 돌려주는 제공자 대역. 바깥으로 나가지 않는다."""

    def __init__(self, positions: list[AisPosition], *, error: str | None = None) -> None:
        self._positions = positions
        self._error = error
        self.asked: list[str] = []

    async def fetch_positions(self, *, imo_numbers: list[str]) -> list[AisPosition]:
        self.asked = list(imo_numbers)
        if self._error is not None:
            raise AisError(self._error)
        return self._positions


def _position(imo: str, *, lat: str, lon: str, observed_at: datetime, **extra) -> AisPosition:
    return AisPosition(
        mmsi="440000000",
        imo_number=imo,
        lat=Decimal(lat),
        lon=Decimal(lon),
        observed_at=observed_at,
        **extra,
    )


@pytest.mark.asyncio
async def test_manual_position_leaves_a_track(session):
    """IT-POS-001 — 사람이 넣은 위치도 스냅샷으로 남는다.

    `vessel.current_lat/lon`은 덮어쓰는 한 칸이라 직전 값이 사라진다. AIS가 붙기
    전에도 항적이 쌓이려면 이 경로가 유일한 문이다.
    """
    vessel_id = await _insert_vessel(session, "7300101")

    assert await record_manual_position(
        session,
        vessel_id=vessel_id,
        lat=Decimal("35.100000"),
        lon=Decimal("129.040000"),
        observed_at=OBSERVED,
    )

    latest = await snapshot_repo.latest_for_vessel(session, vessel_id=vessel_id)
    assert latest is not None
    assert latest.source == SOURCE_MANUAL
    assert latest.lat == Decimal("35.100000")


@pytest.mark.asyncio
async def test_the_same_observation_is_one_row(session):
    """IT-POS-002 — 같은 `(선박·출처·관측 시각)`은 한 행이다.

    AIS는 **같은 관측을 여러 번 보내는 것이 정상**이다(재전송·구독 중복). 중복을
    그대로 쌓으면 항적이 같은 점에서 여러 번 꺾인 것처럼 보인다.
    """
    vessel_id = await _insert_vessel(session, "7300102")

    first = await record_manual_position(
        session, vessel_id=vessel_id, lat=Decimal("1"), lon=Decimal("2"), observed_at=OBSERVED
    )
    second = await record_manual_position(
        session, vessel_id=vessel_id, lat=Decimal("1"), lon=Decimal("2"), observed_at=OBSERVED
    )

    assert first is True
    assert second is False  # 넣지 않았다는 사실을 돌려준다 — 조용히 삼키지 않는다
    rows = await snapshot_repo.list_track(session, vessel_id=vessel_id)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_ais_positions_are_recorded_and_applied(session):
    """IT-POS-003 — AIS가 준 위치가 스냅샷과 선박 현재 위치에 함께 들어간다."""
    vessel_id = await _insert_vessel(session, "7300103")
    provider = _FakeProvider(
        [
            _position(
                "7300103",
                lat="35.500000",
                lon="129.500000",
                observed_at=OBSERVED,
                sog_kn=Decimal("12.30"),
                cog_deg=Decimal("95.00"),
                nav_status=0,
            )
        ]
    )

    result = await ingest_ais_positions(session, provider=provider)

    assert result["received"] == 1
    assert result["recorded"] == 1
    # 선대 전체를 한 번에 묻는다 — 척마다 따로 물으면 제공자 상한(구독 3 × MMSI 200)에
    # 금방 닿는다. 시드 선박이 함께 들어 있으므로 포함 여부로 본다.
    assert "7300103" in provider.asked

    latest = await snapshot_repo.latest_for_vessel(session, vessel_id=vessel_id)
    assert latest is not None
    assert latest.source == SOURCE_AIS
    assert latest.nav_status == 0
    assert latest.sog_kn == Decimal("12.30")

    row = await session.execute(
        text(
            "SELECT current_lat, underway_state, detail_status, position_updated_at "
            f"FROM vessel WHERE id = '{vessel_id}'::uuid"
        )
    )
    current_lat, underway_state, detail_status, updated_at = row.one()
    assert current_lat == Decimal("35.500000")
    # **두 축을 함께** 적는다 — 026 `chk_vessel_state_pair`가 한쪽만 바뀐 상태를 거부한다.
    assert (underway_state, detail_status) == (UNDER_WAY, "SAILING")
    # 현재 위치의 시각은 **관측 시각**이다 — 수신 시각으로 적으면 신선도가 부풀려진다.
    assert updated_at == OBSERVED


@pytest.mark.asyncio
async def test_a_late_older_observation_does_not_move_the_ship_back(session):
    """IT-POS-004 — 늦게 도착한 **오래된** 관측은 현재 위치를 덮지 않는다.

    배치가 겹쳐 돌거나 재전송이 섞이면 오래된 관측이 뒤에 도착한다. 그대로 쓰면
    **배가 뒤로 간다.** 스냅샷에는 남기되 현재 위치는 건드리지 않는다.
    """
    vessel_id = await _insert_vessel(session, "7300104")
    await ingest_ais_positions(
        session,
        provider=_FakeProvider(
            [_position("7300104", lat="35.500000", lon="129.500000", observed_at=OBSERVED)]
        ),
    )

    older = OBSERVED - timedelta(hours=2)
    await ingest_ais_positions(
        session,
        provider=_FakeProvider(
            [_position("7300104", lat="10.000000", lon="10.000000", observed_at=older)]
        ),
    )

    row = await session.execute(
        text(f"SELECT current_lat, position_updated_at FROM vessel WHERE id = '{vessel_id}'::uuid")
    )
    current_lat, updated_at = row.one()
    assert current_lat == Decimal("35.500000")
    assert updated_at == OBSERVED
    # 그래도 **항적에는 남는다** — 지나온 자리를 버리지 않는다.
    assert len(await snapshot_repo.list_track(session, vessel_id=vessel_id)) == 2


@pytest.mark.asyncio
async def test_a_vessel_without_a_position_keeps_its_last_one(session):
    """IT-POS-005 — 위치가 오지 않은 선박은 건드리지 않는다.

    AIS는 수신 범위 밖이면 아무것도 주지 않는 것이 정상이다. 그것을 「좌표 없음」으로
    적으면 **화면에서 배가 사라진다.**
    """
    vessel_id = await _insert_vessel(session, "7300105")
    await record_manual_position(
        session,
        vessel_id=vessel_id,
        lat=Decimal("20.000000"),
        lon=Decimal("20.000000"),
        observed_at=OBSERVED,
    )
    await session.execute(
        text(
            "UPDATE vessel SET current_lat = 20.0, current_lon = 20.0, "
            f"position_updated_at = '{OBSERVED.isoformat()}' WHERE id = '{vessel_id}'::uuid"
        )
    )

    result = await ingest_ais_positions(session, provider=_FakeProvider([]))

    assert result["received"] == 0
    row = await session.execute(
        text(f"SELECT current_lat FROM vessel WHERE id = '{vessel_id}'::uuid")
    )
    assert row.scalar_one() == Decimal("20.000000")


@pytest.mark.asyncio
async def test_an_unknown_imo_is_counted_not_stored(session):
    """IT-POS-006 — 우리 선대에 없는 IMO는 세기만 하고 저장하지 않는다.

    구독에 남의 배가 섞여 들어올 수 있다. 저장하면 **없는 선박의 항적**이 생긴다.
    """
    await _insert_vessel(session, "7300106")

    result = await ingest_ais_positions(
        session,
        provider=_FakeProvider(
            [_position("9999999", lat="1.000000", lon="1.000000", observed_at=OBSERVED)]
        ),
    )

    assert result["unmatched"] == 1
    assert result["recorded"] == 0


@pytest.mark.asyncio
async def test_a_lookup_failure_is_reported_not_swallowed(session):
    """IT-POS-007 — 조회 실패는 **사유와 함께 돌려준다.** 배치를 죽이지도 않는다."""
    await _insert_vessel(session, "7300107")

    result = await ingest_ais_positions(
        session, provider=_FakeProvider([], error="구독이 끊겼습니다")
    )

    assert result["errors"] == ["구독이 끊겼습니다"]
    assert result["recorded"] == 0


@pytest.mark.asyncio
async def test_freshness_is_measured_from_the_observation(session):
    """IT-POS-008 — 신선도는 **관측 시각**으로 잰다. 수신 시각이 아니다.

    수신 시각으로 재면 「30분 전 위치를 방금 받았다」가 최신으로 읽히고, 그것이
    정확히 AIS에서 일어나는 일이다(지연·재전송).

    ⚠️ **임계값은 여기서 정하지 않는다** — `DESIGN_SYSTEM §16` 항목 14가 미결이다.
    """
    vessel_id = await _insert_vessel(session, "7300108")
    await record_manual_position(
        session,
        vessel_id=vessel_id,
        lat=Decimal("1"),
        lon=Decimal("2"),
        observed_at=OBSERVED,
    )
    latest = await snapshot_repo.latest_for_vessel(session, vessel_id=vessel_id)
    assert latest is not None

    age = position_age_seconds(latest, at=OBSERVED + timedelta(minutes=30))

    assert age == pytest.approx(1800.0)


def test_unknown_nav_status_is_not_a_judgement():
    """IT-POS-008 보조 — 모르는 항행 상태를 「정박」으로 단정하지 않는다.

    판정은 **쌍**으로 돌려준다 — 026 `chk_vessel_state_pair`가 두 축을 함께
    요구하므로, 한쪽만 옮기면 저장이 거부된다.

    옮길 수 없는 코드는 `None`이다. `NOT_UNDER_WAY`로 적으면 정박하지 않은 배가
    정박한 것으로 기록되고 `not_underway_period`와 어긋난다.
    """
    assert state_pair_from(0) == (UNDER_WAY, "SAILING")  # under way using engine
    assert state_pair_from(8) == (UNDER_WAY, "SAILING")  # under way sailing
    assert state_pair_from(1) == (NOT_UNDER_WAY, "AT_ANCHOR")  # at anchor
    assert state_pair_from(5) == (NOT_UNDER_WAY, "IN_PORT")  # moored
    # 조종 제한(3)·좌초(6)·미정의(15)는 우리 세부 상태 6종 중 어느 것도 아니다.
    assert state_pair_from(3) is None
    assert state_pair_from(6) is None
    assert state_pair_from(15) is None
    assert state_pair_from(None) is None
