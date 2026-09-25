"""공적 재항 기록 저장·수집 (`#1197` B단계) — ``DB_SCHEMA §2.25``.

여기서 보는 것은 「받은 기록을 어떻게 남기는가」다.

* 원문(``raw``)과 신고 목록이 **그대로** 남는가 — 파싱 규칙을 고쳐도 다시 읽을 수 있어야 한다
* 같은 기항을 다시 받으면 **한 행을 갱신**하는가 — 공적 기록이 ``최초`` → ``최종``으로 정정된다
* (선박, 항만청) 한 쌍의 실패가 **다른 쌍을 막지 않는가** (``PRD §16.2``)
* 호출부호가 없는 배는 묻지 않는가 — 선박명으로 잇지 않는다(``PRD §15.1`` 제약 ⑵)
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest_asyncio
from conftest import insert_returning_id
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.db.repositories import port_call as port_call_repo
from cii_platform.port_calls.authorities import PORT_AUTHORITIES, authority_for_port
from cii_platform.port_calls.collect import collect
from cii_platform.port_calls.mof_vessel_ops import PortCallApiError, parse_response
from cii_platform.port_calls.provider import (
    KIND_ARRIVAL,
    KIND_DEPARTURE,
    REQUEST_FINAL,
    PortCall,
    PortCallReport,
)

FIXTURES = Path(__file__).parent / "fixtures" / "port_calls"
FETCHED = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def session(conn):
    """``conn``의 트랜잭션에 올라타는 세션 — 테스트 종료 시 함께 롤백된다."""
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


def _call(seq: str, *, sign: str = "TSTV1", arrival_hour: int = 14) -> PortCall:
    return PortCall(
        source="MOF_VESSEL_OPS",
        port_authority_code="020",
        call_year=2026,
        call_seq=seq,
        call_sign=sign,
        vessel_name="스타 스키퍼",
        reports=(
            PortCallReport(
                kind=KIND_ARRIVAL,
                request=REQUEST_FINAL,
                at=datetime(2026, 8, 8, arrival_hour, 20, tzinfo=UTC),
            ),
            PortCallReport(
                kind=KIND_DEPARTURE,
                request=REQUEST_FINAL,
                at=datetime(2026, 8, 9, 10, 0, tzinfo=UTC),
            ),
        ),
        raw=f"<item><etryptCo>{seq}</etryptCo></item>",
    )


async def _rows(session: AsyncSession) -> list[tuple]:
    result = await session.execute(
        text(
            "SELECT call_seq, arrival_at, raw, reports FROM port_call_record "
            "WHERE call_sign IN ('TSTV1', 'TSTD2') ORDER BY call_seq"
        )
    )
    return list(result.all())


async def _insert_vessel(session: AsyncSession, imo: str, call_sign: str | None) -> str:
    sign = "NULL" if call_sign is None else f"'{call_sign}'"
    return await insert_returning_id(
        session,
        "INSERT INTO vessel (imo_number, name, ship_type, gross_tonnage, deadweight, call_sign) "
        f"VALUES ('{imo}', 'PORT CALL {imo}', 'CONTAINER_SHIP', 9520, 12979, {sign}) RETURNING id",
        {},
    )


def test_parse_keeps_raw_item_xml():
    """원문 ``<item>`` 한 덩어리가 기항마다 따라온다 — 저장 표가 그대로 보관한다."""
    calls, _ = parse_response((FIXTURES / "mof_V7UJ2_busan_202608.xml").read_bytes())

    assert calls
    for call in calls:
        assert call.raw is not None
        assert call.raw.startswith("<item>")
        assert f"<etryptCo>{call.call_seq}</etryptCo>" in call.raw
    # 원문은 같은 기항인지 가리는 데 쓰지 않는다 — 원문만 다르면 같은 기항이다.
    first = calls[0]
    assert first == PortCall(**{**first.__dict__, "raw": "<item/>"})


def test_port_names_map_only_verified_authorities():
    """항만청 이름이 곧 항구 이름인 곳만 잇는다 — 모르는 이름은 대조 불가(``None``)."""
    assert authority_for_port("BUSAN") == "020"
    assert authority_for_port(" busan ") == "020"
    assert authority_for_port("부산 항") == "020"
    assert authority_for_port("KRPUS") == "020"
    assert authority_for_port("울산") == "820"
    # 관할이 정황뿐인 항구 · 해외 항구 · 빈 값
    assert authority_for_port("GWANGYANG") is None
    assert authority_for_port("PYEONGTAEK") is None
    assert authority_for_port("SINGAPORE") is None
    assert authority_for_port(None) is None
    assert authority_for_port("") is None
    # 이은 코드는 모두 실제로 응답을 받은 11개 안에 있다
    for name in ("BUSAN", "INCHEON", "DONGHAE", "DAESAN", "GUNSAN", "MOKPO", "YEOSU"):
        assert authority_for_port(name) in PORT_AUTHORITIES
    for name in ("MASAN", "ULSAN", "JEJU"):
        assert authority_for_port(name) in PORT_AUTHORITIES


async def test_upsert_inserts_once_then_updates_same_call(session):
    """같은 기항을 다시 받으면 한 행을 갱신한다 — 공적 기록 쪽 정정을 따라간다."""
    assert await port_call_repo.upsert_port_call(session, _call("9014"), fetched_at=FETCHED)
    # 다시 받았더니 입항 시각이 정정됐다
    assert not await port_call_repo.upsert_port_call(
        session, _call("9014", arrival_hour=15), fetched_at=FETCHED
    )

    rows = await _rows(session)
    assert len(rows) == 1
    seq, arrival_at, raw, reports = rows[0]
    assert seq == "9014"
    assert arrival_at.hour == 15
    assert raw == "<item><etryptCo>9014</etryptCo></item>"
    assert '"request": "FINAL"' in reports


async def test_list_for_call_signs_reads_only_those_signs(session):
    await port_call_repo.upsert_port_call(session, _call("9014"), fetched_at=FETCHED)
    await port_call_repo.upsert_port_call(session, _call("9015", sign="TSTD2"), fetched_at=FETCHED)

    rows = await port_call_repo.list_for_call_signs(session, ["TSTD2"])

    assert [row.call_sign for row in rows] == ["TSTD2"]
    assert rows[0].reports[0]["kind"] == KIND_ARRIVAL
    assert await port_call_repo.list_for_call_signs(session, []) == []


class _FakeProvider:
    """부산은 기록을 주고, 울산은 장애, 인천은 다른 배를 섞어 준다."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str]] = []

    async def fetch(self, *, call_sign: str, port_authority_code: str, start: date, end: date):
        self.asked.append((call_sign, port_authority_code))
        if not call_sign.startswith("TST"):
            return []  # 데모 시드의 실존 두 척(#1197 시연 표본) — 이 테스트의 대상이 아니다
        if port_authority_code == "820":
            raise PortCallApiError("99", "장애")
        if port_authority_code == "030":
            return [_call("9900", sign="OTHER1")]
        return [_call("9014", sign=call_sign)]


async def test_collect_isolates_failures_and_skips_unsigned_vessels(session):
    """울산 장애가 부산 기록을 막지 않는다 · 호출부호 없는 배는 묻지 않는다 · 다른 배는 버린다."""
    await _insert_vessel(session, "7319701", "TSTV1")
    await _insert_vessel(session, "7319702", None)
    provider = _FakeProvider()

    result = await collect(
        session,
        provider,
        start=date(2026, 8, 1),
        end=date(2026, 8, 31),
        authorities=("020", "820", "030"),
        fetched_at=FETCHED,
    )

    # 호출부호 없는 배(7319702)는 묻지 않는다 — 시드의 실존 두 척은 이 테스트와 무관해 거른다.
    assert {sign for sign, _ in provider.asked if sign.startswith("TST")} == {"TSTV1"}
    assert result.inserted == 1
    assert result.updated == 0
    assert result.failures == [("TSTV1", "820", "선박운항정보 API 오류 99: 장애")]
    rows = await _rows(session)
    assert [row[0] for row in rows] == ["9014"]
    other = await session.execute(
        text("SELECT COUNT(*) FROM port_call_record WHERE call_sign = 'OTHER1'")
    )
    assert other.scalar_one() == 0


async def test_collect_call_sign_filter(session):
    """``--call-sign``을 주면 그 배만 묻는다."""
    await _insert_vessel(session, "7319701", "TSTV1")
    await _insert_vessel(session, "7319702", "TSTD2")
    provider = _FakeProvider()

    await collect(
        session,
        provider,
        start=date(2026, 8, 1),
        end=date(2026, 8, 31),
        authorities=("020",),
        call_signs=["tstd2"],
        fetched_at=FETCHED,
    )

    assert provider.asked == [("TSTD2", "020")]
