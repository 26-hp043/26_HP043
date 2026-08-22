"""항차 CSV 가져오기 (API_SPEC §8.2, #60).

**데이터를 넣을 경로가 하나 열린다.** 지금 서비스는 시드 데이터로만 도는데,
`PRD §6.2 SCR-007`이 대량 입력을 CSV로 설계해 두고 그 CSV가 없었다.

여기서 잠그는 것은 셋이다.

1. **수식 주입이 값으로 들어가지 않는다** — 문자 열은 `'` prefix, 숫자 열은 parser가
   거부. 두 방향을 다 막지 않으면 한쪽으로 새어 나간다
2. **틀린 행이 파일 전체를 되돌리지 않는다** — 1,000행에서 3행이 틀렸을 때 전부
   거부하면 사용자는 어느 3행인지 알아내려고 같은 업로드를 반복한다
3. **CSV로 들어왔다고 연간 집계에 바로 들어가지 않는다** — 상태는 수기 생성과 같은
   `DRAFT`/`EXCLUDE`다. 출처(`created_from`)만 다르다

케이스 (`TEST_PLAN §14.5`):
    IT-CSV-001 · IT-CSV-002 · IT-CSV-003 · IT-CSV-004 · IT-CSV-005 · IT-CSV-006 · IT-CSV-007
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.errors import ValidationError
from cii_platform.services.voyage_import import (
    MAX_ROWS,
    import_voyages,
    read_rows,
)

FIXTURE = Path(__file__).parent / "fixtures" / "csv" / "voyage_import_sample.csv"

HEADER = (
    "voyage_no,departure_port_name,arrival_port_name,"
    "planned_distance_nm,planned_speed_kn,fuel_type,planned_fuel_ton"
)


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


@pytest_asyncio.fixture
async def vessel_id(session) -> UUID:
    new_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight) "
            "VALUES (:id, :imo, 'IMPORT TEST', 'BULK_CARRIER', 50000)"
        ),
        {"id": new_id, "imo": f"9{new_id.int % 1000000:06d}"},
    )
    return new_id


def csv_bytes(*rows: str, header: str = HEADER) -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode("utf-8")


async def _stored(session, vessel_id: UUID) -> list:
    result = await session.execute(
        text(
            "SELECT voyage_no, status, annual_inclusion_policy, created_from, "
            "       planned_distance_nm, planned_speed_kn "
            "FROM voyage WHERE vessel_id = :vid ORDER BY voyage_no"
        ),
        {"vid": vessel_id},
    )
    return list(result)


# ─────────────────────────────────────────────────────────────────────────────
# 정상 경로
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sample_fixture_imports_every_row(session, vessel_id):
    """`TEST_PLAN §1.5` Fixture 4를 그대로 넣는다 — 정상 5행 + 주입 4행."""
    result = await import_voyages(session, vessel_id, content=FIXTURE.read_bytes())

    assert result["imported_count"] == 9
    assert result["skipped_count"] == 0
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_imported_voyage_starts_as_draft_and_excluded(session, vessel_id):
    """**CSV로 들어왔다는 이유로 연간 집계에 바로 들어가면 안 된다.**

    집계 편입은 상태 전환(`API_SPEC §3.5`)이 결정한다. 출처만 다르게 남긴다.
    """
    await import_voyages(session, vessel_id, content=csv_bytes("V-1,Busan,Tokyo,1000,13.5,HFO,80"))

    (row,) = await _stored(session, vessel_id)
    assert row.status == "DRAFT"
    assert row.annual_inclusion_policy == "EXCLUDE"
    assert row.created_from == "IMPORT"


@pytest.mark.asyncio
async def test_numbers_keep_their_precision(session, vessel_id):
    """`float`을 거치면 `13.5`가 `13.499999…`로 들어간다 — `Decimal`로 옮긴다."""
    await import_voyages(
        session, vessel_id, content=csv_bytes("V-1,Busan,Tokyo,1234.56,13.5,HFO,80.25")
    )

    (row,) = await _stored(session, vessel_id)
    assert row.planned_distance_nm == Decimal("1234.56")
    assert row.planned_speed_kn == Decimal("13.50")


@pytest.mark.asyncio
async def test_bom_is_accepted(session, vessel_id):
    """IT-CSV-004 — Excel이 저장한 CSV는 BOM을 붙인다.

    벗기지 않으면 **첫 컬럼명이 `\\ufeffvoyage_no`가 되어 「필수 컬럼 없음」으로
    거부된다** — 사용자는 컬럼이 멀쩡히 보이는데 거부당한다.
    """
    content = b"\xef\xbb\xbf" + csv_bytes("V-1,Busan,Tokyo,1000,13.5,HFO,80")

    result = await import_voyages(session, vessel_id, content=content)

    assert result["imported_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 수식 주입 — IT-CSV-005 · 006 · 007
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "cell"),
    [
        ("IT-CSV-001", '=CMD("calc")'),
        ("IT-CSV-005", "+1-1=2"),
        ("IT-CSV-006", "-1+1"),
        ("IT-CSV-007", "@SUM(A1)"),
    ],
)
async def test_formula_prefix_is_escaped_in_text_columns(session, vessel_id, case, cell):
    """네 prefix 모두 `'`가 앞에 붙어 저장된다 (`API_SPEC §8.2` 보안 표).

    **행을 버리지 않고 escape한다.** 버리면 정상 항명(`-`로 시작하는 사내 코드 등)까지
    사라지고, 사용자는 왜 빠졌는지 알 수 없다.
    """
    await import_voyages(
        session, vessel_id, content=csv_bytes(f"{cell},Busan,Tokyo,1000,13.5,HFO,80")
    )

    (row,) = await _stored(session, vessel_id)
    assert row.voyage_no == f"'{cell}", case


@pytest.mark.asyncio
async def test_formula_in_numeric_column_is_rejected_not_escaped(session, vessel_id):
    """IT-CSV-002 — 숫자 열은 **escape가 아니라 거부**다 (`API_SPEC §8.2`).

    `'=1+1`을 거리로 저장하면 계산이 그 값을 만나고, 거기서는 고칠 방법이 없다.
    """
    result = await import_voyages(
        session, vessel_id, content=csv_bytes("V-1,Busan,Tokyo,=1+1,13.5,HFO,80")
    )

    assert result["imported_count"] == 0
    assert result["skipped_count"] == 1
    assert result["errors"][0]["field"] == "planned_distance_nm"
    assert await _stored(session, vessel_id) == []


# ─────────────────────────────────────────────────────────────────────────────
# 행 단위 오류 — 부분 성공
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bad_row_does_not_stop_the_good_ones(session, vessel_id):
    """**틀린 행 하나가 파일 전체를 되돌리지 않는다** (`API_SPEC §8.2` 응답 계약)."""
    result = await import_voyages(
        session,
        vessel_id,
        content=csv_bytes(
            "V-1,Busan,Tokyo,1000,13.5,HFO,80",
            "V-2,Busan,Tokyo,0,13.5,HFO,80",
            "V-3,Busan,Tokyo,1000,13.5,HFO,80",
        ),
    )

    assert result["imported_count"] == 2
    assert result["skipped_count"] == 1
    assert [row.voyage_no for row in await _stored(session, vessel_id)] == ["V-1", "V-3"]


@pytest.mark.asyncio
async def test_error_points_at_the_row_the_user_sees(session, vessel_id):
    """행 번호는 **파일에서 보이는 번호**다 — 헤더가 1행이므로 첫 데이터가 2행.

    0부터 세면 사용자가 엉뚱한 줄을 고친다.
    """
    result = await import_voyages(
        session,
        vessel_id,
        content=csv_bytes(
            "V-1,Busan,Tokyo,1000,13.5,HFO,80",
            "V-2,Busan,Tokyo,-5,13.5,HFO,80",
        ),
    )

    assert result["errors"] == [
        {"row": 3, "field": "planned_distance_nm", "message": "0보다 커야 합니다."}
    ]


@pytest.mark.asyncio
async def test_speed_below_one_knot_is_rejected(session, vessel_id):
    """VAL-009 — `0보다 큼`만 보면 0.5kn이 통과한다 (`PRD §9.1`)."""
    result = await import_voyages(
        session, vessel_id, content=csv_bytes("V-1,Busan,Tokyo,1000,0.5,HFO,80")
    )

    assert result["errors"][0]["field"] == "planned_speed_kn"


@pytest.mark.asyncio
async def test_unknown_fuel_is_reported_with_its_row(session, vessel_id):
    """VAL-006 — 연료 검증을 `create_voyage`에 맡기면 **어느 행인지가 사라진다.**"""
    result = await import_voyages(
        session, vessel_id, content=csv_bytes("V-1,Busan,Tokyo,1000,13.5,PLUTONIUM,80")
    )

    assert result["errors"] == [
        {"row": 2, "field": "fuel_type", "message": "지원하지 않는 연료입니다: PLUTONIUM"}
    ]


@pytest.mark.asyncio
async def test_empty_required_cell_is_a_row_error(session, vessel_id):
    result = await import_voyages(
        session, vessel_id, content=csv_bytes(",Busan,Tokyo,1000,13.5,HFO,80")
    )

    assert result["errors"][0]["field"] == "voyage_no"


# ─────────────────────────────────────────────────────────────────────────────
# 파일 단위 거부 — 한 행도 읽지 않는다
# ─────────────────────────────────────────────────────────────────────────────


def test_missing_required_column_rejects_the_file():
    """필수 컬럼 7종 (`API_SPEC §8.2`). 없으면 행을 보기 전에 끊는다."""
    content = b"voyage_no,departure_port_name\nV-1,Busan\n"

    with pytest.raises(ValidationError) as exc:
        read_rows(content)

    assert "planned_distance_nm" in str(exc.value)


def test_wrong_content_type_is_rejected():
    """`API_SPEC §8.2` — `text/csv`·`application/vnd.ms-excel`만 받는다."""
    with pytest.raises(ValidationError):
        read_rows(csv_bytes("V-1,Busan,Tokyo,1000,13.5,HFO,80"), content_type="image/png")


def test_content_type_parameters_do_not_break_the_check():
    """`text/csv; charset=utf-8`도 `text/csv`다 — 파라미터를 떼고 본다."""
    rows, truncated = read_rows(
        csv_bytes("V-1,Busan,Tokyo,1000,13.5,HFO,80"),
        content_type="text/csv; charset=utf-8",
    )

    assert len(rows) == 1
    assert truncated == 0


def test_row_limit_truncates_instead_of_rejecting():
    """`TEST_PLAN` IT-CSV-003 — 「1000행까지만 처리, 초과분 skip」.

    파일을 통째로 거부하지 않는다. 1,001행을 올린 사용자에게 「1,000행까지만 됩니다」로
    답하면 **어느 행이 빠졌는지 스스로 세어야 한다.**
    """
    rows = [f"V-{i},Busan,Tokyo,1000,13.5,HFO,80" for i in range(MAX_ROWS + 3)]

    parsed, truncated = read_rows(csv_bytes(*rows))

    assert len(parsed) == MAX_ROWS
    assert truncated == 3


def test_truncation_is_reported_not_silent():
    """**잘랐다는 사실이 응답에 남는다.**

    개수만 맞추고 말하지 않으면 사용자는 「전부 들어갔다」로 읽는다. 오늘 이 저장소가
    반복해서 고친 형태가 그것이다 — 규칙은 지켜졌고 그 사실이 보이지 않았다.
    """
    rows = [f"V-{i},Busan,Tokyo,1000,13.5,HFO,80" for i in range(MAX_ROWS + 2)]

    _, truncated = read_rows(csv_bytes(*rows))

    assert truncated == 2


def test_non_utf8_file_is_rejected_with_a_readable_message():
    """CP949로 저장한 파일을 그대로 던지면 `UnicodeDecodeError`가 500이 된다."""
    content = ("voyage_no\n한글\n").encode("cp949")

    with pytest.raises(ValidationError) as exc:
        read_rows(content)

    assert "UTF-8" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────────────
# dry-run
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dry_run_creates_nothing(session, vessel_id):
    """**올리기 전에 몇 행이 걸리는지 먼저 볼 수 있어야 한다.**

    그 확인이 없으면 부분 성공 상태에서 무엇을 고쳐 다시 올려야 하는지 사용자가
    계산해야 한다.
    """
    result = await import_voyages(
        session,
        vessel_id,
        content=csv_bytes(
            "V-1,Busan,Tokyo,1000,13.5,HFO,80",
            "V-2,Busan,Tokyo,0,13.5,HFO,80",
        ),
        dry_run=True,
    )

    assert result["imported_count"] == 1
    assert result["skipped_count"] == 1
    assert result["dry_run"] is True
    assert await _stored(session, vessel_id) == []


@pytest.mark.asyncio
async def test_dry_run_and_real_run_agree(session, vessel_id):
    """검증 결과가 실제 결과와 다르면 dry-run이 쓸모없다."""
    content = csv_bytes(
        "V-1,Busan,Tokyo,1000,13.5,HFO,80",
        "V-2,Busan,Tokyo,1000,13.5,PLUTONIUM,80",
    )

    preview = await import_voyages(session, vessel_id, content=content, dry_run=True)
    actual = await import_voyages(session, vessel_id, content=content)

    assert preview["imported_count"] == actual["imported_count"]
    assert preview["errors"] == actual["errors"]


def test_the_route_is_registered():
    """서비스가 있어도 **라우트를 잊으면 아무도 부를 수 없다.**"""
    from cii_platform.api.main import app

    assert "post" in app.openapi()["paths"]["/api/v1/vessels/{vessel_id}/import"]


# ─────────────────────────────────────────────────────────────────────────────
# 커서 페이지네이션 (#627)
#
# **가져오기 뒤에 두는 이유** — 이 결함이 드러나는 조건이 「한 선박에 항차가 페이지
# 크기보다 많다」이고, 그 상태를 실제로 만드는 것이 CSV 가져오기다(`#625`).
#
# 이 검사는 **DB에 붙어야 한다.** 결함이 파이썬 쪽 오류가 아니라 SQL 타입 불일치였다 —
# 커서의 `created_at`이 `str`이라 `timestamptz` 컬럼과 비교되지 않았다.
#
#     operator does not exist: timestamp with time zone > character varying
#
# 서버는 커서를 발급하면서 **자기가 발급한 커서를 읽지 못했다.** 화면 두 곳이
# `meta.next_cursor`를 버려 왔기 때문에 아무도 밟지 않았다.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cursor_reaches_the_rows_past_the_first_page(session, vessel_id):
    """페이지 크기를 넘는 항차에 커서로 도달한다.

    `#625`가 한 번에 1,000행을 넣을 수 있게 만든 뒤, 목록이 첫 페이지에서 멈추면
    **그 뒤 항차는 화면에서 도달할 방법이 없다.**
    """
    from cii_platform.services.voyage import list_voyages

    rows = [f"V-{i:03d},BUSAN,SINGAPORE,1000,12.0,HFO,80.0" for i in range(1, 8)]
    await import_voyages(session, vessel_id, content=csv_bytes(*rows))

    seen: list[str] = []
    cursor = None
    for _ in range(10):  # 무한 루프 방지 — 7건이면 3페이지에 끝난다
        page, meta = await list_voyages(session, vessel_id=vessel_id, limit=3, cursor=cursor)
        seen.extend(str(v["voyage_no"]) for v in page)
        if not meta["has_more"]:
            break
        cursor = meta["next_cursor"]
        assert isinstance(cursor, str) and cursor != ""

    assert len(seen) == 7, seen
    assert len(set(seen)) == 7, "같은 행이 두 페이지에 나오면 안 된다"
    assert set(seen) == {f"V-{i:03d}" for i in range(1, 8)}


@pytest.mark.asyncio
async def test_the_server_can_read_the_cursor_it_issued(session, vessel_id):
    """**발급한 커서를 그대로 되돌려 준다.**

    종전에는 여기서 `UndefinedFunctionError`(`timestamptz > varchar`)로 500이 났다.
    커서를 만드는 쪽과 읽는 쪽이 같은 타입을 쓰는지 보는 것이 이 테스트의 전부다.
    """
    from cii_platform.services.voyage import list_voyages

    rows = [f"W-{i:03d},BUSAN,SINGAPORE,1000,12.0,HFO,80.0" for i in range(1, 4)]
    await import_voyages(session, vessel_id, content=csv_bytes(*rows))

    first, meta = await list_voyages(session, vessel_id=vessel_id, limit=1)
    issued = meta["next_cursor"]
    assert isinstance(issued, str)

    second, _ = await list_voyages(session, vessel_id=vessel_id, limit=1, cursor=issued)

    assert len(second) == 1
    # **어느 행이 먼저인지는 단언하지 않는다.** `created_at`의 기본값이 `now()`이고
    # PostgreSQL의 `now()`는 **트랜잭션 시작 시각**이라 한 번에 넣은 행들의 시각이
    # 전부 같다. 정렬은 그때 `id`(UUID)로 갈리므로 `voyage_no` 순서와 무관하다.
    # 여기서 볼 것은 **커서가 전진했는가**뿐이다 — 종전에는 그 앞에서 500이 났다.
    assert second[0]["voyage_no"] != first[0]["voyage_no"]


@pytest.mark.asyncio
async def test_broken_cursor_is_422_not_500(session, vessel_id):
    """깨진 커서는 사용자가 URL을 손댄 경우가 대부분이다 — 500이 나가면 안 된다.

    시각·UUID **둘 다** 검증한다. base64가 정상이어도 안의 값이 형식에 맞지 않으면
    쿼리 바인딩 단계에서 거절돼 500이 된다(선박 쪽 `#233`과 같은 경로).
    """
    import base64

    from cii_platform.services.voyage import list_voyages

    def token(raw: str) -> str:
        return base64.urlsafe_b64encode(raw.encode()).decode("ascii")

    broken = [
        "not-base64!!",
        token("구분자없음"),
        token("2026-08-22T00:00:00+00:00\x00uuid가아님"),
        token("시각이아님\x00" + str(uuid4())),
    ]
    for value in broken:
        with pytest.raises(ValidationError):
            await list_voyages(session, vessel_id=vessel_id, limit=3, cursor=value)
