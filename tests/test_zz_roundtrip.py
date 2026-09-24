"""이슈 #82 롤백/재현성 통합 검증 (전역 스키마 변형 테스트 격리).

이 파일의 테스트는 ``alembic downgrade``로 전역 DB 스키마를 파괴·재구성한다.
async ``conn`` fixture를 쓰는 다른 테스트와 실행이 섞이면 빈 스키마를 보게 되어
플래키한 실패가 난다. 이를 막기 위해 두 가지를 적용한다.

- **격리**: 파일명을 ``test_zz_*``로 두어 pytest 기본 수집 순서상 마지막에 실행되게 한다.
- **복원**: 각 테스트는 성공/실패와 무관하게 ``try/finally``에서 ``upgrade head``로
  스키마를 복원하여, 도중에 죽더라도 후속 테스트를 오염시키지 않는다.

원래 ``test_voyage_migrations.py``와 ``test_calculation_migrations.py``에 각각
동일 내용으로 존재하던 ``test_downgrade_upgrade_roundtrip``을 여기로 합쳤다
(둘 다 ``downgrade base → upgrade head``로 전체 체인을 한 번에 왕복하므로 중복).
"""

import asyncio
import importlib.util
import re
import sys
import types
import warnings
from pathlib import Path

import pytest
from conftest import TEST_DATABASE_URL, insert_returning_id, run_alembic
from db_target import is_disposable, skip_reason
from sqlalchemy import pool, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

# sha256: + 64 hex — chk_input_hash_format를 통과하는 유효 해시.
VALID_HASH = "sha256:" + "a" * 64

_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
_CREATE_TRIGGER = re.compile(r"CREATE\s+TRIGGER\s+(\w+)", re.IGNORECASE)
_DROP_TRIGGER = re.compile(r"DROP\s+TRIGGER\s+(\w+)", re.IGNORECASE)

#
# 개발 DB를 파괴하지 않는다 (#507).
#
# 이 파일의 모든 테스트가 `alembic downgrade base`로 스키마를 드롭한다. 대상이
# 개발 DB면 **사람이 가입한 계정이 사라지고 되돌릴 수 없다** — 실제로 그렇게
# 없어졌다. 이름이 `_test`로 끝나는 DB에서만 돌린다. 자세한 근거는 `db_target.py`.
#
# 파일 전체에 거는 이유 — 여섯 테스트가 전부 같은 조작을 한다. 하나씩 붙이면
# 새 테스트를 더할 때 빠뜨린다.
#
pytestmark = pytest.mark.skipif(
    not is_disposable(TEST_DATABASE_URL),
    reason=skip_reason(TEST_DATABASE_URL),
)


def _restore_to_head() -> None:
    """finally에서 스키마를 head로 복원한다 (#95 문제 2).

    try 블록이 이미 예외로 중단된 상태(``sys.exc_info()``가 진행 중 예외를 가리킴)에서
    복원까지 실패할 때, assert로 새 예외를 던지면 원래 실패 원인이 가려진다(finally의
    예외가 try의 예외를 대체하기 때문). 이 경우엔 ``warnings.warn``으로 원래 예외를
    보존하고, try가 정상 종료된 경우(진행 중 예외 없음)에만 복원 실패를
    ``AssertionError``로 올려 후속 테스트 스키마 오염을 드러낸다.
    """
    restore = run_alembic("upgrade", "head")
    if restore.returncode == 0:
        return
    detail = f"{restore.stdout}\n{restore.stderr}"
    if sys.exc_info()[0] is None:
        # try 성공 → 복원 실패는 테스트 실패로 올린다(오염 방지).
        raise AssertionError(f"restore(upgrade head) 실패: {detail}")
    # try가 이미 실패한 상태 → 원래 예외를 가리지 않도록 경고만 남긴다.
    warnings.warn(f"restore(upgrade head)도 실패 — 원래 예외 유지: {detail}", stacklevel=2)


async def _clear_demo_data() -> None:
    """스키마 롤백 전에 데모 데이터를 치운다 (#451).

    **데모 데이터는 스키마가 아니다.** 남아 있으면 ``downgrade 016``이
    ``fk_voyage_fuel_use_fuel_type``에 막히는데(데모 연료 실적이 HFO를 참조한다), 그것을
    스키마 마이그레이션이 치우게 만들면 「마이그레이션이 사용자 데이터를 지우는」 선례가
    된다. 그래서 seed를 넣은 쪽이 치운다.
    """
    from cii_platform.db.demo_seed import clear_demo

    engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            await clear_demo(connection)
    finally:
        await engine.dispose()


async def _reseed_demo_data() -> None:
    """복원 뒤 데모 데이터를 다시 넣는다 — 세션 fixture가 넣어 둔 상태로 되돌린다."""
    from cii_platform.db.demo_seed import seed_demo

    engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            await seed_demo(connection)
    finally:
        await engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# 0. head의 트리거 집합 — 왕복을 돌리기 전에 지금 상태부터 본다 (#1373 · D-20)
# ─────────────────────────────────────────────────────────────────────────────
#
# CUBRID는 같은 이름의 트리거를 두 번 만드는 것을 막지 않고, 중복이 생기면 이름으로는
# 어느 쪽도 지울 수 없다(`DROP TRIGGER` → -503). 그 상태에서는 아래 왕복 검사가 `048`
# 근처에서 끊기고 DB가 그 리비전에 갇힌다. 마이그레이션 쪽은 `db/trigger_ddl.py`가
# 「있으면 만들지 않고, 없으면 지우지 않는다」로 막는데, 그 관용은 중복을 「없음」으로
# 읽을 수 있어 **중복이 없다는 것을 따로 세어야** 한다. 두 검사가 그것이다 — 중복 0건,
# 그리고 head의 트리거 이름 집합이 마이그레이션이 만든다고 적은 집합과 같은가.


class _CountingOp:
    """``op.execute``의 SQL에서 트리거 생성·삭제만 집계하고 나머지 연산은 삼킨다.

    `tests/test_dbschema_head_sync.py`와 같은 스텁이다 — `tests/`는 패키지가 아니라
    가져올 수 없어 여기 다시 둔다.
    """

    def __init__(self) -> None:
        self.created: list[str] = []
        self.dropped: list[str] = []

    def execute(self, sql, *args, **kwargs) -> None:
        text_ = str(sql)
        self.created.extend(_CREATE_TRIGGER.findall(text_))
        self.dropped.extend(_DROP_TRIGGER.findall(text_))

    def get_bind(self):
        return _NullBind()

    def __getattr__(self, name: str):
        return lambda *args, **kwargs: None


class _NullResult:
    def scalar(self):
        return 0

    scalar_one = scalar

    def fetchall(self):
        return []

    all = fetchall

    def first(self):
        return None


class _NullBind:
    dialect = types.SimpleNamespace(name="cubrid")

    def execute(self, *args, **kwargs):
        return _NullResult()


def _expected_head_triggers(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    """마이그레이션이 head에 남긴다고 적은 트리거 이름 집합 — DB 없이 센다.

    `upgrade()`가 내는 `CREATE TRIGGER` 누적에서 `DROP TRIGGER`를 뺀 것이다(`050`·`051`·
    `057`이 지우고 다시 만든다). `alembic`을 세는 스텁으로 갈아 끼우고 리비전 사슬
    순서로 `upgrade()`를 부른다 — `db/trigger_ddl.py`가 카탈로그를 스텁에 물으면 빈
    집합이 오므로 만드는 쪽은 전부 실행되고 지우는 쪽은 전부 건너뛰는데, 집합으로 세므로
    결과는 같다.
    """
    op = _CountingOp()
    fake = types.ModuleType("alembic")
    fake.op = op  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "alembic", fake)
    monkeypatch.setitem(sys.modules, "alembic.op", op)

    modules: list[types.ModuleType] = []
    for path in sorted(_VERSIONS.glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"_zz_roundtrip_{path.stem}", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    by_down = {m.down_revision: m for m in modules}

    live: set[str] = set()
    rev = None
    walked = 0
    while rev in by_down:
        module = by_down[rev]
        op.created.clear()
        op.dropped.clear()
        module.upgrade()
        live -= set(op.dropped)
        live |= set(op.created)
        rev = module.revision
        walked += 1
    assert walked == len(modules), "리비전 사슬이 한 줄이 아니다 — 분기가 생겼다"
    return live


async def _db_trigger_rows(sql: str) -> list:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            return list((await connection.execute(text(sql))).all())
    finally:
        await engine.dispose()


async def test_head_has_no_duplicate_trigger_names():
    """같은 이름의 트리거가 둘 이상 없다 (#1373).

    있으면 그 이름은 `DROP TRIGGER`로 지울 수 없고(-503), 뒤의 왕복 검사가 거기서 끊긴다.
    `db/trigger_ddl.drop_trigger`는 그 -503을 넘어가므로 **여기서 세지 않으면 조용하다.**
    """
    up = run_alembic("upgrade", "head")
    assert up.returncode == 0, f"{up.stdout}\n{up.stderr}"

    duplicated = await _db_trigger_rows(
        "SELECT name, count(*) FROM db_trigger GROUP BY name HAVING count(*) > 1"
    )
    assert duplicated == [], (
        f"같은 이름의 트리거가 둘 이상이다 — 이름으로는 지울 수 없다. README 「테스트 DB 복구」로 "
        f"다시 만들 것: {duplicated}"
    )


async def test_head_trigger_set_matches_migrations(monkeypatch: pytest.MonkeyPatch):
    """`upgrade head` 뒤 DB의 트리거 이름 집합 = 마이그레이션이 만든다고 적은 집합 (#1373).

    합계(160)는 `test_dbschema_head_sync`가 `DB_SCHEMA §7.4`와 대조한다. 여기서는 **이름
    하나하나**를 실제 DB와 대조한다 — 수가 같아도 남은 것 하나와 빠진 것 하나가 상쇄되면
    합계는 그대로다.
    """
    up = run_alembic("upgrade", "head")
    assert up.returncode == 0, f"{up.stdout}\n{up.stderr}"

    expected = _expected_head_triggers(monkeypatch)
    assert expected, "마이그레이션에서 트리거를 하나도 세지 못했다 — 이 검사가 헛돌고 있다"

    actual = {row[0] for row in await _db_trigger_rows("SELECT name FROM db_trigger")}
    assert actual == expected, (
        f"DB에만 있다: {sorted(actual - expected)} · "
        f"마이그레이션에만 있다: {sorted(expected - actual)}"
    )


def test_downgrade_upgrade_roundtrip():
    """downgrade base → upgrade head 왕복이 성공한다 (§8.1 롤백 안전성).

    전체 마이그레이션 체인을 base까지 내렸다가 head로 되올려, voyage 그룹(§8.1)과
    008이 만든 공유 함수 prevent_mutation()의 드롭·재생성까지 한 번에 검증한다.
    실패하더라도 finally에서 head로 복원한다.
    """
    asyncio.run(_clear_demo_data())
    try:
        down = run_alembic("downgrade", "base")
        assert down.returncode == 0, f"{down.stdout}\n{down.stderr}"
        up = run_alembic("upgrade", "head")
        assert up.returncode == 0, f"{up.stdout}\n{up.stderr}"
    finally:
        # 성공/실패와 무관하게 head로 복원한다(happy path에서는 no-op).
        _restore_to_head()
        asyncio.run(_reseed_demo_data())


async def test_partial_downgrade_preserves_immutability():
    """부분 다운그레이드 뒤에도 calculation_run immutable이 유지된다.

    ``downgrade 008``로 009만 내리던 검사였다. CUBRID 전환이 001~042를
    ``1c444a5c4819`` 하나로 합치면서 **그 두 리비전이 사라졌다** (`#1058`).

    검사의 뜻은 「**한 단계만 내려도** 불변성 보호가 함께 내려가지 않는다」이므로
    지금 그래프에서 같은 뜻을 갖는 자리로 옮긴다 — ``downgrade 043``은 `044`만
    되돌리고, 불변성 트리거를 소유한 ``a7d3e9b14f26``은 그대로 남는다.

        base → 1c444a5c4819 → 6c7496c4d122 → a7d3e9b14f26 → 043 → 044
    """
    await _clear_demo_data()
    step = run_alembic("downgrade", "043")
    assert step.returncode == 0, f"{step.stdout}\n{step.stderr}"
    try:
        await _assert_calculation_run_immutable()
    finally:
        # 부분 롤백 상태에서 head로 복원한다(실패해도 후속 테스트 오염 방지).
        _restore_to_head()
        await _reseed_demo_data()


async def _assert_calculation_run_immutable() -> None:
    """리비전 008 상태에서 calculation_run이 UPDATE 거부(immutable)됨을 실제로 확인한다.

    트랜잭션 안에서 vessel + calculation_run을 INSERT하고 UPDATE를 시도하여
    'immutable' 에러가 나는지 검증한 뒤, 전체를 롤백하여 행을 남기지 않는다.
    """
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool)
    connection = await engine.connect()
    trans = await connection.begin()
    try:
        vessel_id = await insert_returning_id(
            connection,
            "INSERT INTO vessel (imo_number, name, ship_type) "
            "VALUES ('9990001', 'IMMUT TEST', 'BULK_CARRIER') RETURNING id",
            {},
        )
        calc_id = await insert_returning_id(
            connection,
            "INSERT INTO calculation_run "
            "(calculation_type, vessel_id, input_hash, parameter_hash, "
            " model_version, result_json, parameters_used) "
            "VALUES ('VOYAGE_ESTIMATE', :vid, :ih, :ph, "
            # `::jsonb`는 CUBRID에 없다. 컬럼이 TEXT(`JSONText`)라 문자열 그대로 넣는다.
            # 이 헬퍼는 `conftest`의 `before_cursor_execute` 셈이 걸리지 않은 **직접
            # 엔진**을 쓰므로 구문이 자동으로 걷히지 않는다 (`#1058`).
            " '{}', '{}', '{}') RETURNING id",
            {"vid": vessel_id, "ih": VALID_HASH, "ph": VALID_HASH},
        )

        with pytest.raises(DBAPIError) as exc:
            await connection.execute(
                text("UPDATE calculation_run SET calculation_type = 'SCENARIO' WHERE id = :id"),
                {"id": calc_id},
            )
        assert "immutable" in str(exc.value).lower()
    finally:
        await trans.rollback()
        await connection.close()
        await engine.dispose()


async def test_seed_downgrade_removes_fuel_type_rows():
    """017 downgrade가 fuel_type seed 8행을 삭제한다 (#83 완료 기준).

    이 파일에 두는 이유는 위 두 테스트와 같다 — ``downgrade 016``이 전역 스키마 상태를
    바꾸므로 async ``conn`` fixture를 쓰는 테스트와 섞이면 안 된다 (#82). 값 자체의
    검증은 tests/test_fuel_type_seed.py가 담당한다.

    여기서는 참조 행이 없으므로 NO ACTION FK에 걸리지 않는다. 참조가 있을 때 DELETE가
    거부되는 경로는 커밋된 데이터가 필요해 테스트가 아니라 수동 검증으로 확인한다
    (PR 본문 실측 결과 참조).
    """
    await _clear_demo_data()
    # `017`은 `1c444a5c4819`에 합쳐졌고 seed는 `6c7496c4d122`가 넣는다 (`#1058`).
    # 그 앞으로 내리는 자리가 종전의 `downgrade 016`에 해당한다.
    step = run_alembic("downgrade", "1c444a5c4819")
    assert step.returncode == 0, f"{step.stdout}\n{step.stderr}"
    try:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool)
        try:
            async with engine.connect() as connection:
                count = await connection.scalar(text("SELECT count(*) FROM fuel_type"))
            assert count == 0
        finally:
            await engine.dispose()
    finally:
        # 성공/실패와 무관하게 head로 복원한다 — seed 8행이 다시 적재된다.
        _restore_to_head()
        await _reseed_demo_data()


async def test_032_downgrade_removes_regulation_parameters():
    """032 downgrade가 규제 파라미터 42행을 지운다 (#127 완료 기준).

    이 파일에 두는 이유는 위 테스트들과 같다 — ``downgrade 031``이 전역 스키마 상태를
    바꾸므로 async ``conn`` fixture를 쓰는 테스트와 섞이면 안 된다 (#82). 값 자체의
    검증은 tests/test_seed_migration.py가 담당한다.

    ⚠️ 참조 중인 행이 있으면 FK에 걸려 실패한다(``calculation_run`` →
    ``regulation_year``). 여기서는 커밋된 계산 이력이 없으므로 걸리지 않는다.
    """
    # 종전 `031`의 자리 — 규제 파라미터를 넣는 `6c7496c4d122` 앞이다 (`#1058`).
    step = run_alembic("downgrade", "1c444a5c4819")
    assert step.returncode == 0, f"{step.stdout}\n{step.stderr}"
    try:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool)
        try:
            async with engine.connect() as connection:
                for table in ("regulation_year", "cii_reference_line", "cii_rating_boundary"):
                    count = await connection.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
                    assert count == 0, f"{table}: downgrade 후에도 {count}행 남음"
        finally:
            await engine.dispose()
    finally:
        # 성공/실패와 무관하게 head로 복원한다 — 032가 다시 42행을 넣는다.
        _restore_to_head()


async def test_seed_migration_skips_existing_rows():
    """seed migration이 이미 찬 표에서 UNIQUE 위반으로 죽지 않는다 (#1201).

    운영 DB는 2026-09-15 수동 세팅에서 ``python -m cii_platform.db.seed``로 63행을
    받고 ``1c444a5c4819``에 머물러 있었다 — seed를 alembic 경로에 되살린
    ``6c7496c4d122``는 그 뒤에 합쳐졌다. 그래서 2026-09-20 첫 자동 배포의
    ``upgrade head``가 이 리비전을 처음 돌며 ``uq_fuel_type_code``(``DIESEL_GAS_OIL``)에
    걸려 ``deploy-app``이 실패했다.

    이 검사는 그 상태를 재현한다 — **행은 들어와 있고 alembic_version만 직전을
    가리키는** 상태를 만드는 데 ``stamp``를 쓴다(운영의 그 상태와 같은 모양). 그 위에서
    ``upgrade head``가 **성공**하고, 행이 늘지도 줄지도 않는다. 함께 ``METHANOL`` 한 행을
    지워 **없는 행만 다시 들어오는지**도 본다.
    """
    await _clear_demo_data()
    step = run_alembic("downgrade", "1c444a5c4819")
    assert step.returncode == 0, f"{step.stdout}\n{step.stderr}"
    try:
        # seed 63행을 넣은 뒤 alembic_version만 직전으로 되돌린다 — 운영 재현
        seeded = run_alembic("upgrade", "6c7496c4d122")
        assert seeded.returncode == 0, f"{seeded.stdout}\n{seeded.stderr}"
        stamped = run_alembic("stamp", "1c444a5c4819")
        assert stamped.returncode == 0, f"{stamped.stdout}\n{stamped.stderr}"

        engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool)
        try:
            async with engine.begin() as connection:
                await connection.execute(text("DELETE FROM fuel_type WHERE code = 'METHANOL'"))

            up = run_alembic("upgrade", "head")
            assert up.returncode == 0, f"{up.stdout}\n{up.stderr}"

            async with engine.connect() as connection:
                for table, expected in (
                    ("fuel_type", 8),
                    ("regulation_year", 8),
                    ("cii_reference_line", 20),
                    ("cii_rating_boundary", 14),
                    ("weather_model_parameter", 10),
                    ("simulation_parameter", 3),
                ):
                    count = await connection.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
                    assert count == expected, (
                        f"{table}: upgrade 뒤 {count}행 (기대 {expected}) — "
                        "있는 행을 넘기지 못했거나 지운 METHANOL이 돌아오지 않았다"
                    )
        finally:
            await engine.dispose()
    finally:
        # 성공/실패와 무관하게 head로 복원한다.
        _restore_to_head()
        await _reseed_demo_data()


# ─────────────────────────────────────────────────────────────────────────────
# 🔴 지운 검사 둘 — 전제가 사라졌다 (`#1058` · 결정요청 §0-2 · 가)
# ─────────────────────────────────────────────────────────────────────────────
#
# * `test_031_downgrade_restores_null_content_hash`
#     — 「`030`까지 내리면 `fuel_type` 행은 8개 남고 `content_hash`만 NULL이 된다」
# * `test_demo_seed_downgrade_does_not_touch_data`
#     — 「`018`만 내리면 `017`이 적재한 CF 8행은 남는다」
#
# CUBRID 전환이 마이그레이션 `001`~`042`를 `1c444a5c4819` **하나로 합쳤다.** 두 검사가
# 전제하는 「리비전 사이의 구분」이 **존재하지 않는다** — `017`과 `018`, `030`과 `031`이
# 같은 리비전이 되었으므로 「하나만 내린다」가 성립하지 않는다. `downgrade 030`은
# 리비전을 찾지 못하고, `downgrade 1c444a5c4819`는 스키마를 통째로 되돌린다.
#
#     base → 1c444a5c4819 → 6c7496c4d122 → a7d3e9b14f26 → 043 … → 051
#
# `db/migration_guard.py`도 같은 이유로 분류를 셋에서 하나로 줄이며 그 사실을 적었다 —
# 「되돌린다는 것은 스키마 전체를 드롭한다는 뜻이라 나눌 것이 남지 않는다」.
#
# **건너뛰지 않고 지운 이유** — 전제가 사라진 검사를 `skip`으로 남겨 두면 다음 사람이
# 「왜 실패하는지」를 다시 조사한다(`049`가 건너뛰기 목록을 비운 것과 같은 판단).
# 잃은 커버리지는 `DB_SCHEMA §8.1`에 명시했다. 위 `test_downgrade_upgrade_roundtrip`이
# 전체 왕복(`downgrade base` → `upgrade head`)을 그대로 보므로 **롤백 안전성 자체**는
# 덮여 있고, 잃은 것은 **리비전 단위의 경계 검증**이다.
