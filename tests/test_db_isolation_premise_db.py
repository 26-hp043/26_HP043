"""CUBRID 격리 수준 전제 가드 (TEST_PLAN §5.10, #1796 · #1631).

## 왜 남기는가

저장소의 동시성 방어 세 갈래가 전부 **한 전제** 위에 서 있다 — 「READ COMMITTED에서
커밋되지 않은 변경은 다른 연결에 보이지 않고, 읽기를 막지도 않는다」.

- `#1079` 조건부 UPDATE(`WHERE status = 'DRAFT'`)가 최신 버전으로 재평가된다
- `#1630` 부모 행 `FOR UPDATE`가 범위 검사 → INSERT를 직렬화한다
- `#1631` 유니크 인덱스가 앞 트랜잭션의 커밋까지 기다렸다가 위반으로 떨어진다
- `#1860`·`#1868` 잠금 순서(선박 → 항차)가 「FK 검사는 부모 행 S 잠금을 요구한다」에 기댄다

서버 설정(`cubrid.conf` `isolation_level` · `lock_timeout`) · 드라이버 인자 · CUBRID
판올림으로 이 전제가 바뀌어도 지금은 어느 검사도 알려 주지 않는다. `#1796`이 실측한
다섯 현상을 그대로 잠근다 — 값이 아니라 **동작**을 단언하므로 CUBRID를 갈아도 전제가
같으면 통과하고, 다르면 여기서 먼저 드러난다.

## 어떻게 재는가

앱이 쓰는 세션 팩토리(`get_sessionmaker` · `app_fresh_engine`이 NullPool로 갈아끼운 것)로
세션 둘을 교차시킨다. B 쪽은 `SET TRANSACTION LOCK TIMEOUT 1`(초)로 걸어 두어 대기 여부를
시간으로 판정한다 — 0.5초 안에 끝나면 「대기 없음」, 잠금에 걸리면 1초 뒤 `errno=-75`.
앱 기본은 `-1`(무한 대기)이라 실제 API는 오류 대신 기다린다 — 여기서는 시험을 빨리
끝내려고 줄일 뿐이다.

표는 전부 `probe_iso_*`이며 이 파일이 만들고 지운다. 저장소 표는 건드리지 않는다.
실측 스크립트 원본은 `#1796` 코멘트(2026-09-24 06시 KST)에 있다.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

#: A가 커밋 전에 머무는 시간. B의 대기가 이보다 짧으면 「기다리지 않았다」로 읽는다.
HOLD_SEC = 1.0
#: B의 잠금 대기 한도(초). `#1796`은 2초로 쟀고 여기서는 1초 — 판정에는 충분하다.
LOCK_TIMEOUT_SEC = 1
#: 이보다 빨리 끝나면 「대기 없음」.
NO_WAIT_SEC = 0.5

_TABLES: tuple[str, ...] = (
    "probe_iso_row",
    "probe_iso_period",
    # FK 자식은 부모보다 먼저 지운다 — 부모를 먼저 지우면 FK가 막는다.
    "probe_iso_fkchild",
    "probe_iso_parent",
    "probe_iso_uq",
    "probe_iso_voy",
)
_DDL: tuple[str, ...] = (
    "CREATE TABLE probe_iso_row (id INT PRIMARY KEY, val VARCHAR(20))",
    "CREATE TABLE probe_iso_parent (id INT PRIMARY KEY)",
    "CREATE TABLE probe_iso_period (id INT PRIMARY KEY, parent_id INT NOT NULL, "
    "started_at DATETIME NOT NULL, ended_at DATETIME)",
    "CREATE INDEX idx_probe_iso_period_parent ON probe_iso_period (parent_id, started_at)",
    "CREATE TABLE probe_iso_uq (id INT PRIMARY KEY, k VARCHAR(7))",
    "CREATE UNIQUE INDEX uq_probe_iso_k ON probe_iso_uq (k)",
    "CREATE TABLE probe_iso_voy (id INT PRIMARY KEY, status VARCHAR(16))",
    "INSERT INTO probe_iso_parent (id) VALUES (1)",
    # FK 자식 (`#1868`) — 부모 1을 가리키는 행 하나와, 대조군용 부모 2를 가리키는 행 하나.
    "INSERT INTO probe_iso_parent (id) VALUES (2)",
    "CREATE TABLE probe_iso_fkchild (id INT PRIMARY KEY, parent_id INT NOT NULL, "
    "val VARCHAR(20), CONSTRAINT fk_probe_iso_fkchild FOREIGN KEY (parent_id) "
    "REFERENCES probe_iso_parent (id))",
    "INSERT INTO probe_iso_fkchild (id, parent_id, val) VALUES (10, 1, 'c')",
    "INSERT INTO probe_iso_fkchild (id, parent_id, val) VALUES (20, 2, 'c')",
)


async def _drop_all(engine) -> None:
    for name in _TABLES:
        try:
            async with engine.begin() as c:
                await c.execute(text(f"DROP TABLE {name}"))
        except DBAPIError:
            pass


@pytest_asyncio.fixture
async def probe_tables(app_fresh_engine):
    """`probe_iso_*` 표를 만들고 끝에 지운다. 남은 표가 없는지도 확인한다."""
    await _drop_all(app_fresh_engine)
    async with app_fresh_engine.begin() as c:
        for sql in _DDL:
            await c.execute(text(sql))
    try:
        yield app_fresh_engine
    finally:
        await _drop_all(app_fresh_engine)
        async with app_fresh_engine.connect() as c:
            left = (
                await c.execute(
                    text("SELECT class_name FROM db_class WHERE class_name LIKE 'probe_iso%'")
                )
            ).fetchall()
        assert left == [], f"probe_iso 표가 남았다: {left}"


def _maker():
    from cii_platform.db.session import get_sessionmaker

    return get_sessionmaker()


async def _set_lock_timeout(session) -> None:
    await session.execute(text(f"SET TRANSACTION LOCK TIMEOUT {LOCK_TIMEOUT_SEC}"))


async def _timed(coro) -> tuple[object, float, Exception | None]:
    """오류도 결과다 — 다만 취소·인터럽트(``BaseException``)는 삼키지 않는다."""
    t0 = time.perf_counter()
    try:
        return await coro, time.perf_counter() - t0, None
    except Exception as exc:  # noqa: BLE001
        return None, time.perf_counter() - t0, exc


# ─────────────────────────────────────────────────────────────────────────────
# ⑴ 미커밋 INSERT — 보이지 않고, 기다리지도 않는다
# ─────────────────────────────────────────────────────────────────────────────


async def test_uncommitted_insert_is_invisible_and_does_not_block_readers(probe_tables):
    """DB-ISO-001 — A가 넣고 커밋하지 않은 행을 B는 **못 보고**, 읽기가 **막히지도** 않는다.

    이것이 `#1631`의 트리거·사전 조회가 중복을 못 막은 이유이고, `#1629`의 「CUBRID가
    미커밋 INSERT의 읽기를 막는다」(정황)가 성립하지 않는 근거다.
    """
    maker = _maker()
    a_inserted = asyncio.Event()
    b_done = asyncio.Event()
    seen: dict[str, object] = {}

    async def a() -> None:
        async with maker() as s:
            await s.execute(text("INSERT INTO probe_iso_row (id, val) VALUES (1, 'uncommitted')"))
            a_inserted.set()
            await b_done.wait()
            await s.commit()

    async def b() -> None:
        await a_inserted.wait()
        async with maker() as s:
            await _set_lock_timeout(s)
            rows, elapsed, err = await _timed(
                s.execute(text("SELECT id FROM probe_iso_row WHERE id = 1"))
            )
            seen["plain"] = (rows.fetchall() if err is None else None, elapsed, err)
            # 없는 행에는 잠금이 걸리지 않는다 — FOR UPDATE도 같다
            rows, elapsed2, err2 = await _timed(
                s.execute(text("SELECT id FROM probe_iso_row WHERE id = 1 FOR UPDATE"))
            )
            seen["for_update"] = (rows.fetchall() if err2 is None else None, elapsed2, err2)
            await s.rollback()
        b_done.set()

    await asyncio.gather(a(), b())

    for key in ("plain", "for_update"):
        rows, elapsed, err = seen[key]
        assert err is None, f"{key}: 읽기가 막혔다 — {err}"
        assert rows == [], f"{key}: 미커밋 행이 보였다 — {rows}"
        assert elapsed < NO_WAIT_SEC, f"{key}: 읽기가 {elapsed:.2f}s 기다렸다"


# ─────────────────────────────────────────────────────────────────────────────
# ⑵ 미커밋 UPDATE — 옛 값이 보이고, 기다리지 않는다
# ─────────────────────────────────────────────────────────────────────────────


async def test_uncommitted_update_shows_the_old_value_without_blocking(probe_tables):
    """DB-ISO-002 — A가 바꾸고 커밋하지 않은 행을 B는 **옛 값으로** 읽고 기다리지 않는다.

    같은 행을 `FOR UPDATE`로 읽으면 그때는 잠금에 걸린다(lock_timeout 뒤 `errno=-75`) —
    「읽기는 안 막지만 쓰기 잠금은 실재한다」는 것이 `#1630` 부모 행 잠금의 전제다.
    """
    maker = _maker()
    async with probe_tables.begin() as c:
        await c.execute(text("INSERT INTO probe_iso_row (id, val) VALUES (2, 'old')"))
    a_updated = asyncio.Event()
    b_done = asyncio.Event()
    seen: dict[str, object] = {}

    async def a() -> None:
        async with maker() as s:
            await s.execute(text("UPDATE probe_iso_row SET val = 'new' WHERE id = 2"))
            a_updated.set()
            await b_done.wait()
            await s.commit()

    async def b() -> None:
        await a_updated.wait()
        async with maker() as s:
            await _set_lock_timeout(s)
            rows, elapsed, err = await _timed(
                s.execute(text("SELECT val FROM probe_iso_row WHERE id = 2"))
            )
            seen["plain"] = (rows.scalar() if err is None else None, elapsed, err)
            rows, elapsed2, err2 = await _timed(
                s.execute(text("SELECT val FROM probe_iso_row WHERE id = 2 FOR UPDATE"))
            )
            seen["for_update"] = (None if err2 else rows.scalar(), elapsed2, err2)
            await s.rollback()
        b_done.set()

    await asyncio.gather(a(), b())

    value, elapsed, err = seen["plain"]
    assert err is None and value == "old", (value, err)
    assert elapsed < NO_WAIT_SEC, f"일반 읽기가 {elapsed:.2f}s 기다렸다"
    _, elapsed2, err2 = seen["for_update"]
    assert err2 is not None, "같은 행의 FOR UPDATE가 잠금에 걸리지 않았다 — 쓰기 잠금이 사라졌다"
    assert "errno=-75" in str(err2), str(err2)[:200]
    assert elapsed2 >= LOCK_TIMEOUT_SEC * 0.8, f"잠금 대기가 {elapsed2:.2f}s로 짧다"

    async with probe_tables.connect() as c:
        assert (
            await c.execute(text("SELECT val FROM probe_iso_row WHERE id = 2"))
        ).scalar() == "new"


# ─────────────────────────────────────────────────────────────────────────────
# ⑶ 범위 SELECT → INSERT 교차 — 잠금 없이는 2건, 부모 행 FOR UPDATE면 1건
# ─────────────────────────────────────────────────────────────────────────────

_OVERLAP = text(
    "SELECT id FROM probe_iso_period WHERE parent_id = 1 "
    "AND (ended_at IS NULL OR ended_at > :s) AND started_at < :e ORDER BY started_at LIMIT 1"
)
_WINDOW = {"s": "2026-03-01 00:00:00", "e": "2026-03-05 00:00:00"}


async def _interleave(lock_parent: bool, next_id: int) -> int:
    """A select → B select → A insert → B insert → A commit → B commit.

    남은 구간 행 수를 돌려준다.
    """
    maker = _maker()
    a_selected = asyncio.Event()
    b_selected = asyncio.Event()
    a_inserted = asyncio.Event()

    async def insert(s, row_id: int) -> None:
        await s.execute(
            text(
                "INSERT INTO probe_iso_period (id, parent_id, started_at, ended_at) "
                "VALUES (:id, 1, :s, :e)"
            ),
            {"id": row_id, **_WINDOW},
        )

    async def a() -> None:
        async with maker() as s:
            if lock_parent:
                await s.execute(text("SELECT id FROM probe_iso_parent WHERE id = 1 FOR UPDATE"))
            assert (await s.execute(_OVERLAP, _WINDOW)).scalar() is None
            a_selected.set()
            # 잠금이 있으면 B는 FOR UPDATE에서 기다리고 있어 신호가 오지 않는다 — 시간으로 넘어간다.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(b_selected.wait(), timeout=HOLD_SEC)
            await insert(s, next_id)
            a_inserted.set()
            await asyncio.sleep(HOLD_SEC if lock_parent else 0)
            await s.commit()

    async def b() -> None:
        await a_selected.wait()
        async with maker() as s:
            # 잠금 갈래는 A가 HOLD_SEC 뒤 커밋하므로 그보다 길게 기다린다.
            await s.execute(
                text(f"SET TRANSACTION LOCK TIMEOUT {int(HOLD_SEC * 3) + LOCK_TIMEOUT_SEC}")
            )
            if lock_parent:
                await s.execute(text("SELECT id FROM probe_iso_parent WHERE id = 1 FOR UPDATE"))
            clash = (await s.execute(_OVERLAP, _WINDOW)).scalar()
            b_selected.set()
            if not lock_parent:
                await a_inserted.wait()
            if clash is None:
                await insert(s, next_id + 1)
                await s.commit()
            else:
                await s.rollback()  # 겹침 검출 — 409 경로

    await asyncio.gather(a(), b())
    async with _maker()() as s:
        return int(
            (
                await s.execute(text("SELECT count(*) FROM probe_iso_period WHERE parent_id = 1"))
            ).scalar_one()
        )


async def test_range_check_then_insert_interleaves_unless_the_parent_row_is_locked(probe_tables):
    """DB-ISO-003 — `#1629` 형태. 잠금 없이는 둘 다 「겹침 없음」을 읽고 **2건**이 남는다.

    부모 행을 `FOR UPDATE`로 잡으면 B가 A의 커밋까지 기다린 뒤 A의 행을 보고 물러나
    **1건**이다 — `F-8` 결정(부모 행 잠금)이 유효한 근거. 두 갈래를 한 함수에서 재는 것은
    「경합이 실재한다」와 「잠금이 그것을 막는다」가 서로의 대조군이기 때문이다.
    """
    assert await _interleave(lock_parent=False, next_id=100) == 2, (
        "잠금 없이도 직렬화됐다 — 전제가 바뀌었다"
    )
    async with probe_tables.begin() as c:
        await c.execute(text("DELETE FROM probe_iso_period"))
    assert await _interleave(lock_parent=True, next_id=200) == 1, (
        "부모 행 잠금이 교차를 막지 못했다"
    )


# ─────────────────────────────────────────────────────────────────────────────
# ⑸ 유니크 인덱스 — 뒤 INSERT가 앞 커밋까지 기다렸다가 IntegrityError
# ─────────────────────────────────────────────────────────────────────────────


async def test_unique_index_makes_the_second_insert_wait_then_fail(probe_tables):
    """DB-ISO-004 — `#1631`이 기대는 성질. B의 INSERT는 A의 커밋까지 **대기**한 뒤
    `IntegrityError`(`errno=-670`)로 떨어지고, 같은 키 행은 하나만 남는다.

    A가 롤백하면 B가 성공하는 형태라 「하나만 남는다」를 DB가 보장한다.
    """
    maker = _maker()
    a_inserted = asyncio.Event()
    outcome: dict[str, object] = {}

    async def a() -> None:
        async with maker() as s:
            await s.execute(text("INSERT INTO probe_iso_uq (id, k) VALUES (1, 'K1')"))
            a_inserted.set()
            await asyncio.sleep(HOLD_SEC)
            await s.commit()

    async def b() -> None:
        await a_inserted.wait()
        async with maker() as s:
            await s.execute(text(f"SET TRANSACTION LOCK TIMEOUT {int(HOLD_SEC * 3)}"))
            _, elapsed, err = await _timed(
                s.execute(text("INSERT INTO probe_iso_uq (id, k) VALUES (2, 'K1')"))
            )
            outcome["b"] = (elapsed, err)
            await s.rollback()

    await asyncio.gather(a(), b())

    elapsed, err = outcome["b"]
    assert isinstance(err, IntegrityError), (
        f"유니크 위반이 IntegrityError가 아니다 — {type(err).__name__}: {err}"
    )
    assert "errno=-670" in str(err.orig), str(err.orig)[:200]
    assert elapsed >= HOLD_SEC * 0.8, f"B가 A의 커밋을 기다리지 않았다({elapsed:.2f}s)"
    async with probe_tables.connect() as c:
        assert (
            await c.execute(text("SELECT count(*) FROM probe_iso_uq WHERE k = 'K1'"))
        ).scalar() == 1


# ─────────────────────────────────────────────────────────────────────────────
# ⑹ 조건부 UPDATE — 앞 커밋 뒤 최신 버전으로 재평가돼 rowcount 0
# ─────────────────────────────────────────────────────────────────────────────


async def test_conditional_update_is_reevaluated_after_the_holder_commits(probe_tables):
    """DB-ISO-005 — `#1079`/`#1628` 형태. `WHERE status = 'DRAFT'`를 단 UPDATE는 A의 커밋을
    기다린 뒤 **최신 값으로 다시 평가**돼 `rowcount = 0`이다. 조건 없는 UPDATE(ORM 기본)는
    `rowcount = 1`로 마지막 쓰기가 이긴다 — 조건부가 방어인 이유다.
    """
    maker = _maker()

    async def run(conditional: bool) -> tuple[int, tuple[str, ...]]:
        async with probe_tables.begin() as c:
            await c.execute(text("DELETE FROM probe_iso_voy"))
            await c.execute(text("INSERT INTO probe_iso_voy (id, status) VALUES (1, 'DRAFT')"))
        a_updated = asyncio.Event()
        rowcount: dict[str, int] = {}

        async def a() -> None:
            async with maker() as s:
                r = await s.execute(
                    text(
                        "UPDATE probe_iso_voy SET status = 'CONFIRMED' "
                        "WHERE id = 1 AND status = 'DRAFT'"
                    )
                )
                assert r.rowcount == 1
                a_updated.set()
                await asyncio.sleep(HOLD_SEC)
                await s.commit()

        async def b() -> None:
            await a_updated.wait()
            async with maker() as s:
                await s.execute(text(f"SET TRANSACTION LOCK TIMEOUT {int(HOLD_SEC * 3)}"))
                sql = (
                    "UPDATE probe_iso_voy SET status = 'CANCELLED' "
                    "WHERE id = 1 AND status = 'DRAFT'"
                    if conditional
                    else "UPDATE probe_iso_voy SET status = 'CANCELLED' WHERE id = 1"
                )
                r = await s.execute(text(sql))
                rowcount["b"] = r.rowcount
                await s.commit()

        await asyncio.gather(a(), b())
        async with probe_tables.connect() as c:
            final = (
                await c.execute(text("SELECT status FROM probe_iso_voy WHERE id = 1"))
            ).scalar()
        return rowcount["b"], (final,)

    assert await run(conditional=True) == (0, ("CONFIRMED",)), (
        "조건부 UPDATE가 옛 버전 기준으로 통과했다"
    )
    assert await run(conditional=False) == (1, ("CANCELLED",)), (
        "무조건 UPDATE가 마지막 쓰기로 이기지 않았다"
    )


# ─────────────────────────────────────────────────────────────────────────────
# ⑹ FK 검사는 부모 행 S 잠금을 요구한다 (#1860 · #1868)
# ─────────────────────────────────────────────────────────────────────────────


async def _b_waits(a_sql: str, b_sql: str) -> tuple[float, Exception | None]:
    """A가 ``a_sql`` 뒤 커밋 전에 머무는 동안 B의 ``b_sql``이 걸린 시간과 오류.

    B는 lock timeout 1초 — 걸리면 약 1초 뒤 ``errno=-75``, 안 걸리면 곧바로 끝난다.
    """
    maker = _maker()
    a_ready = asyncio.Event()
    b_done = asyncio.Event()
    seen: dict[str, object] = {}

    async def a() -> None:
        async with maker() as s:
            await s.execute(text(a_sql))
            a_ready.set()
            await b_done.wait()
            await s.rollback()

    async def b() -> None:
        await a_ready.wait()
        async with maker() as s:
            await _set_lock_timeout(s)
            _rows, elapsed, err = await _timed(s.execute(text(b_sql)))
            seen["r"] = (elapsed, err)
            await s.rollback()
        b_done.set()

    await asyncio.gather(a(), b())
    return seen["r"]  # type: ignore[return-value]


def _waited_on_parent(err: Exception | None) -> bool:
    """잠금 대기 한도에 걸렸고, 그 대상이 **부모 표**였는가 — 문구가 표 이름을 싣는다."""
    return err is not None and "probe_iso_parent" in str(err) and "-75" in str(err)


_LOCK_PARENT = "SELECT id FROM probe_iso_parent WHERE id = 1 FOR UPDATE"


async def test_child_insert_waits_for_the_parent_row_x_lock(probe_tables):
    """DB-ISO-006 — 부모 X 보유 중 자식 INSERT는 부모 행의 **S 잠금**을 기다린다 (`#1860` ⑻).

    채택 `CREATE_NEW_VOYAGE`와 정박 구간 경로의 잠금 순서(선박 → 항차)가 이 성질에서 나왔다.
    """
    elapsed, err = await _b_waits(
        _LOCK_PARENT, "INSERT INTO probe_iso_fkchild (id, parent_id, val) VALUES (11, 1, 'x')"
    )
    assert _waited_on_parent(err), f"자식 INSERT가 부모 잠금을 기다리지 않았다 — {err}"
    assert "S_LOCK" in str(err), err
    assert elapsed >= NO_WAIT_SEC


async def test_child_insert_holds_the_parent_s_lock_until_commit(probe_tables):
    """DB-ISO-007 — 자식 INSERT가 얻은 부모 S는 문장 뒤가 아니라 **커밋까지** 남는다 (`#1868` ⑽-a).

    READ COMMITTED의 일반 SELECT는 S를 문장 뒤에 푼다. FK 검사의 S는 그렇지 않아서, 자식을
    넣고 커밋 전에 머무는 세션이 있으면 그 부모의 `FOR UPDATE`가 기다린다.
    """
    elapsed, err = await _b_waits(
        "INSERT INTO probe_iso_fkchild (id, parent_id, val) VALUES (12, 1, 'x')", _LOCK_PARENT
    )
    assert _waited_on_parent(err), f"부모 FOR UPDATE가 기다리지 않았다 — S가 풀려 있었다: {err}"
    assert elapsed >= NO_WAIT_SEC


async def test_child_update_rechecks_the_fk_even_when_it_does_not_change(probe_tables):
    """DB-ISO-008 — FK 열을 바꾸지 않는 자식 UPDATE도 부모 S를 기다린다 (`#1868` ⑽-b).

    이것 때문에 항차 X를 쥔 채 `voyage`를 UPDATE하는 다섯 경로가 전부 선박 S를 요구했고,
    `#1877`이 그 다섯을 선박 → 항차 순으로 맞췄다. 대조군 — **다른 부모**의 자식 UPDATE는
    기다리지 않는다(잠금이 부모 행 단위라는 것, 표 잠금이 아니라는 것).
    """
    elapsed, err = await _b_waits(
        _LOCK_PARENT, "UPDATE probe_iso_fkchild SET val = 'y' WHERE id = 10"
    )
    assert _waited_on_parent(err), f"비-FK 열 UPDATE가 부모 잠금을 기다리지 않았다 — {err}"
    assert elapsed >= NO_WAIT_SEC

    elapsed, err = await _b_waits(
        _LOCK_PARENT, "UPDATE probe_iso_fkchild SET val = 'y' WHERE id = 20"
    )
    assert err is None, f"다른 부모의 자식 UPDATE가 막혔다 — {err}"
    assert elapsed < NO_WAIT_SEC, f"다른 부모의 자식 UPDATE가 {elapsed:.2f}s 기다렸다"
