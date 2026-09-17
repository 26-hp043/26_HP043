"""데모 데이터 적재·삭제의 **행 수 보고**가 사실인지 본다 (#481).

**막으려는 것은 적재 실패가 아니라, 적재 결과를 알 수 없는 상태다.**

``seed_demo``·``clear_demo``가 돌려주는 숫자는 그대로 콘솔에 찍히고
(``python -m cii_platform.db.demo_seed``), 운영자는 그 숫자로 **「이번에 들어갔는가,
이미 있었는가」**를 판단한다. 2026-08-17 시점의 출력은 다음과 같았다.

.. code-block:: text

    vessel: -1행 신규 적재
    voyage: -1행 신규 적재

``rowcount``를 그대로 쓴 결과다 — executemany 경로의 asyncpg는 ``-1``을 돌려주고,
``-1 or 0``은 ``-1``이다. **첫 실행과 두 번째 실행이 같은 값으로 보인다.**

그래서 여기서는 세 가지를 잠근다.

1. 값이 **음수가 아니다** — 회귀의 직접 신호
2. 이미 적재된 상태에서 다시 부르면 **전부 0** — 멱등성이 숫자로 보인다
3. 비운 뒤 부르면 **실제 데이터 건수와 정확히 같다** — 「뭔가 됐다」가 아니라 몇 건인지

`clear_demo`의 삭제 건수도 같은 근거로 함께 본다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from cii_platform.db.demo_seed import (
    SEED_PERIOD_FUELS,
    SEED_PERIODS,
    SEED_VESSEL_GT_AXIS,
    SEED_VESSEL_WATCH,
    SEED_VESSELS,
    SEED_VOYAGE_FUELS,
    SEED_VOYAGES,
    SEED_VOYAGES_WATCH,
    clear_demo,
    seed_demo,
)

#: 테이블별 seed 정의 건수. **코드의 상수에서 세며 여기 숫자를 적지 않는다** —
#: 적어 두면 seed가 늘 때 이 파일이 조용히 낡는다.
EXPECTED_ROWS: dict[str, int] = {
    "vessel": len(SEED_VESSELS) + len(SEED_VESSEL_GT_AXIS) + len(SEED_VESSEL_WATCH),
    "voyage": len(SEED_VOYAGES) + len(SEED_VOYAGES_WATCH),
    "voyage_fuel_use": len(SEED_VOYAGE_FUELS),
    "not_underway_period": len(SEED_PERIODS),
    "not_underway_fuel_use": len(SEED_PERIOD_FUELS),
}


def _seeded_tables(counts: dict[str, int]) -> dict[str, int]:
    """``EXPECTED_ROWS``가 다루는 테이블만 남긴다.

    ``seed_demo``는 시연 계정도 넣지만(``app_user`` · `#692`) **``clear_demo``는 계정을
    지우지 않는다.** 그것이 의도다 — 이 프로젝트에서 계정을 지우는 일은 `#691`이
    막으려던 바로 그 사고이고, 데모 계정을 지우는 것은 스키마 롤백에 필요하지도 않다.

    그래서 「지운 수 = 다시 들어간 수」 항등식에 ``app_user``를 넣을 수 없다. 계정
    자체의 계약은 ``tests/test_demo_user_seed.py``가 본다.
    """
    return {name: value for name, value in counts.items() if name in EXPECTED_ROWS}


#: ``seed_demo``가 보고하는 **전체** 키. ``app_user``는 `#692`가 더했다.
#: 키 집합까지 함께 보면 「보고에서 조용히 빠진 테이블」도 드러난다.
REPORTED_KEYS: tuple[str, ...] = (*EXPECTED_ROWS, "app_user")


@pytest.mark.asyncio
async def test_reseed_on_already_seeded_db_reports_zero(conn: AsyncConnection):
    """**이 이슈의 핵심 계약**이다 — 이미 있으면 0이라고 말해야 한다.

    세션 fixture(``migrated_db``)가 이미 데모 데이터를 넣어 둔 상태에서 다시 부른다.
    ``-1``이 새어 나오던 자리다.
    """
    counts = await seed_demo(conn)

    assert counts == dict.fromkeys(REPORTED_KEYS, 0), (
        "이미 적재된 DB에서 신규 적재 수가 0이 아니다. "
        "행이 늘었거나(멱등성 위반), 행 수를 잘못 세고 있다. "
        "키가 다르면 보고에서 빠지거나 새로 늘어난 테이블이 있다는 뜻이다."
    )


@pytest.mark.asyncio
async def test_counts_are_never_negative(conn: AsyncConnection):
    """음수는 「셀 수 없었다」는 뜻이고, 출력에 그대로 실린다."""
    counts = await seed_demo(conn)
    negatives = {name: value for name, value in counts.items() if value < 0}
    assert not negatives, f"행 수가 음수다(드라이버 rowcount 유출): {negatives}"


@pytest.mark.asyncio
async def test_seed_after_clear_reports_the_actual_row_count(conn: AsyncConnection):
    """비운 뒤 넣으면 **지운 만큼** 들어갔다고 말해야 한다.

    0과 실제 건수가 구분되는지를 여기서 확인한다 — 위 테스트만 있으면 「항상 0을
    돌려주는 구현」도 통과한다.

    ``EXPECTED_ROWS``와 직접 비교하지 않는 이유는 **계산 이력이 참조하는 행은 지워지지
    않기 때문**이다(`clear_demo` docstring). 같은 DB를 쓰는 다른 테스트가 데모 선박으로
    계산을 한 번 돌리면 그 선박은 남고, 그러면 다시 넣을 것도 그만큼 줄어든다 —
    **그것은 결함이 아니라 설계**다. 그래서 「지운 수 = 다시 들어간 수」로 본다.
    """
    cleared = await clear_demo(conn)

    counts = await seed_demo(conn)

    assert _seeded_tables(counts) == {name: cleared[name] for name in EXPECTED_ROWS}
    if cleared["kept_vessel"] == 0 and cleared["kept_voyage"] == 0:
        # 아무것도 남지 않았다면 전량이 돌아와야 한다.
        assert _seeded_tables(counts) == EXPECTED_ROWS


@pytest.mark.asyncio
async def test_clear_reports_the_actual_deleted_count(conn: AsyncConnection):
    """삭제 건수도 같은 규칙을 따른다.

    ``kept_voyage``·``kept_vessel``이 이 값에서 파생되므로(``len(ids) - 지운 수``),
    **삭제 수가 틀리면 남긴 수까지 함께 틀린다.** 그래서 항등식으로 본다 —
    **지운 수 + 남긴 수 = seed 정의 수**. 계산 이력이 걸린 행은 남는 것이 정상이므로
    (`clear_demo` docstring) 「전부 지워졌는가」로 보면 다른 테스트가 남긴 이력에
    이 검사가 흔들린다.
    """
    counts = await clear_demo(conn)

    assert counts["vessel"] + counts["kept_vessel"] == EXPECTED_ROWS["vessel"]
    assert counts["voyage"] + counts["kept_voyage"] == EXPECTED_ROWS["voyage"]
    # 정박 구간 쪽은 참조 제약이 없어 언제나 전량이다.
    for name in ("not_underway_period", "not_underway_fuel_use"):
        assert counts[name] == EXPECTED_ROWS[name], f"{name} 삭제 건수가 seed 정의와 다르다"

    # 🔴 **항차 연료는 「언제나 전량」이 아니다** (`#1088`). 계산 이력으로 남긴 항차의
    # 연료는 **남는다** — 종전에는 전량을 지워 그 항차가 연료 0 항차가 됐다. 남긴
    # 항차가 없을 때만 전량과 같다.
    if counts["kept_voyage"] == 0:
        assert counts["voyage_fuel_use"] == EXPECTED_ROWS["voyage_fuel_use"]
    else:
        assert counts["voyage_fuel_use"] <= EXPECTED_ROWS["voyage_fuel_use"]


@pytest.mark.asyncio
async def test_reported_count_matches_the_table(conn: AsyncConnection):
    """보고한 수와 **실제 테이블 상태**가 일치한다.

    앞의 테스트들은 모두 함수의 반환값끼리 비교한다. 반환값이 일관되게 틀릴 수도
    있으므로, 한 번은 DB를 직접 세어 대조한다.
    """
    await clear_demo(conn)
    before = await _count(conn, "vessel")

    counts = await seed_demo(conn)

    after = await _count(conn, "vessel")
    assert after - before == counts["vessel"]


async def _count(conn: AsyncConnection, table: str) -> int:
    result = await conn.execute(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
    return int(result.scalar_one())


# ─────────────────────────────────────────────────────────────────────────────
# 지울 수 없는 것을 지우려 들지 않는다 (#1088)
# ─────────────────────────────────────────────────────────────────────────────

VALID_HASH = "sha256:" + "a" * 64


def _hex(seed_id: object) -> str:
    """시드 정의의 **대시 36자**를 저장 형식인 ``CHAR(32)`` hex로.

    시드 상수는 사람이 읽는 대시 형식(또는 ``UUID`` 객체)이고 DB는 hex 32자로
    담는다(``UuidText``).
    raw SQL에는 그 변환이 걸리지 않으므로 여기서 직접 맞춘다 — 어긋나면
    ``Cannot coerce … to type char``로 즉시 드러난다 (`#1058`).
    """
    return str(seed_id).replace("-", "")


@pytest.mark.asyncio
async def test_user_data_on_a_demo_vessel_does_not_sink_the_whole_clear(conn: AsyncConnection):
    """데모 선박에 **위치 스냅샷**이 하나 쌓여 있어도 전체가 실패하지 않는다.

    ``vessel_position_snapshot.vessel_id``는 ``RESTRICT``다. 종전 구현은
    ``calculation_run``만 걸러 내고 ``DELETE FROM vessel``을 바로 쐈으므로 FK 위반이
    났고, 호출자가 트랜잭션을 쥐고 있어 **한 척 때문에 전체가 롤백**됐다 — 그러면
    이미 지운 항차·연료까지 되살아나고, 운영자는 「지웠다」는 보고를 받지 못한다.

    `clear_demo` docstring이 약속한 것은 **「막히는 것은 억지로 지우지 않고 남긴 수를
    돌려준다」**이다. 그 약속을 여기서 잠근다.
    """
    demo_vessel_id = SEED_VESSELS[0]["id"]

    await conn.execute(
        text(
            "INSERT INTO vessel_position_snapshot "
            "(id, vessel_id, source, lat, lon, observed_at) "
            "VALUES (:sid, :vid, 'MANUAL', 35.1, 129.0, :obs)"
        ),
        {
            "sid": uuid.uuid4().hex,
            "vid": _hex(demo_vessel_id),
            "obs": datetime(2026, 5, 1, tzinfo=UTC),
        },
    )

    # 종전에는 여기서 FK 위반이 터졌다.
    counts = await clear_demo(conn)

    assert counts["kept_vessel"] >= 1, "참조가 남은 선박은 남긴 수로 세어져야 한다"
    assert counts["vessel"] + counts["kept_vessel"] == EXPECTED_ROWS["vessel"]

    rows = await conn.execute(
        text("SELECT COUNT(*) FROM vessel WHERE id = :vid"), {"vid": _hex(demo_vessel_id)}
    )
    assert rows.scalar_one() == 1, "참조가 남은 선박은 지워지지 않고 남아야 한다"


@pytest.mark.asyncio
async def test_fuel_of_a_voyage_kept_for_calculation_history_survives(conn: AsyncConnection):
    """계산 이력 때문에 남긴 항차의 **연료 기록은 지우지 않는다.**

    계산 이력을 남기는 이유는 「그때 무슨 데이터로 계산했나」에 답하기 위해서다.
    그런데 종전 구현은 항차를 남기면서 **그 답의 재료인 연료를 지웠다** — 남은
    항차는 연료 0 항차가 되고, 그 항차로 다시 계산하면 분자가 비어 값이 달라진다.
    """
    demo_voyage = SEED_VOYAGES[0]
    voyage_id = demo_voyage["id"]
    vessel_id = demo_voyage["vessel_id"]

    before = await conn.execute(
        text("SELECT COUNT(*) FROM voyage_fuel_use WHERE voyage_id = :vid"),
        {"vid": _hex(voyage_id)},
    )
    fuel_before = before.scalar_one()
    assert fuel_before > 0, "전제가 깨졌다 — 이 항차에 연료 seed가 있어야 한다"

    # 이 항차를 가리키는 계산 이력을 만든다 — 그래서 항차가 남는다.
    await conn.execute(
        text(
            "INSERT INTO calculation_run "
            "(id, calculation_type, vessel_id, voyage_id, input_hash, parameter_hash, "
            " model_version, result_json, parameters_used) "
            "VALUES (:cid, 'VOYAGE_ESTIMATE', :vsl, :vid, :ih, :ih, "
            " '{}'::jsonb, '{}'::jsonb, '{}'::jsonb)"
        ),
        {
            "cid": uuid.uuid4().hex,
            "vsl": _hex(vessel_id),
            "vid": _hex(voyage_id),
            "ih": VALID_HASH,
        },
    )

    counts = await clear_demo(conn)

    assert counts["kept_voyage"] >= 1

    still_there = await conn.execute(
        text("SELECT COUNT(*) FROM voyage WHERE id = :vid"), {"vid": _hex(voyage_id)}
    )
    assert still_there.scalar_one() == 1, "계산 이력이 가리키는 항차는 남아야 한다"

    fuel = await conn.execute(
        text("SELECT COUNT(*) FROM voyage_fuel_use WHERE voyage_id = :vid"),
        {"vid": _hex(voyage_id)},
    )
    assert fuel.scalar_one() == fuel_before, (
        "남긴 항차의 연료가 지워졌다 — 그 항차로 다시 계산하면 분자가 비어 값이 달라진다"
    )
