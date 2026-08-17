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
import sys
import warnings

import pytest
from conftest import TEST_DATABASE_URL, run_alembic
from sqlalchemy import pool, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

# sha256: + 64 hex — chk_input_hash_format를 통과하는 유효 해시.
VALID_HASH = "sha256:" + "a" * 64


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
    """부분 다운그레이드(009만 롤백) 후에도 calculation_run immutable이 유지된다.

    공유 함수 prevent_mutation()을 009가 아닌 008이 소유하도록 한 결정의 근거.
    ``downgrade 008``로 009만 롤백해도 트리거 trg_calcrun_immutable이 살아 있어야 하며,
    실제 UPDATE 시도가 거부되는지 확인한다. 검증 후 head로 복원한다.
    """
    await _clear_demo_data()
    step = run_alembic("downgrade", "008")
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
        vessel_id = (
            await connection.execute(
                text(
                    "INSERT INTO vessel (imo_number, name, ship_type) "
                    "VALUES ('9990001', 'IMMUT TEST', 'BULK_CARRIER') RETURNING id"
                )
            )
        ).scalar_one()
        calc_id = (
            await connection.execute(
                text(
                    "INSERT INTO calculation_run "
                    "(calculation_type, vessel_id, input_hash, parameter_hash, "
                    " model_version, result_json, parameters_used) "
                    "VALUES ('VOYAGE_ESTIMATE', :vid, :ih, :ph, "
                    " '{}'::jsonb, '{}'::jsonb, '{}'::jsonb) RETURNING id"
                ),
                {"vid": vessel_id, "ih": VALID_HASH, "ph": VALID_HASH},
            )
        ).scalar_one()

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
    step = run_alembic("downgrade", "016")
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
    step = run_alembic("downgrade", "031")
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


async def test_031_downgrade_restores_null_content_hash():
    """031 downgrade가 ``fuel_type.content_hash``를 NULL로 되돌린다 (#154 완료 기준).

    이 파일에 두는 이유는 위 테스트들과 같다 — ``downgrade 030``이 전역 스키마 상태를
    바꾸므로 async ``conn`` fixture를 쓰는 테스트와 섞이면 안 된다 (#82). 값 자체의
    검증은 tests/test_fuel_type_content_hash.py가 담당한다.

    되돌아가는 지점은 017 직후 상태다 — 행은 8개 그대로 남고 ``content_hash``만 비는
    것이 맞다. 행까지 사라지면 downgrade가 자기 범위를 넘어 017의 일을 되돌린 것이다.
    """
    step = run_alembic("downgrade", "030")
    assert step.returncode == 0, f"{step.stdout}\n{step.stderr}"
    try:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool)
        try:
            async with engine.connect() as connection:
                total = await connection.scalar(text("SELECT count(*) FROM fuel_type"))
                filled = await connection.scalar(
                    text("SELECT count(*) FROM fuel_type WHERE content_hash IS NOT NULL")
                )
            # 행은 남고 해시만 비었다.
            assert total == 8
            assert filled == 0
        finally:
            await engine.dispose()
    finally:
        # 성공/실패와 무관하게 head로 복원한다 — 031이 다시 8행을 채운다.
        _restore_to_head()


async def test_demo_seed_downgrade_does_not_touch_data(session_free=None):
    """**018 다운그레이드는 아무것도 지우지 않는다** — 계약이 바뀌었다 (#451).

    종전에는 018이 데모 선박 3행을 DELETE했다. 그런데 그 선박으로 계산을 한 번 돌리면
    ``fk_calculation_run_vessel``(023 신설, RESTRICT)에 막혀 **롤백 전체가 실패**했다.
    데모 데이터를 마이그레이션에서 분리해(``db.demo_seed``) 지울 것 자체를 없앴다.

    그래서 여기서 확인하는 것은 「지웠는가」가 아니라 **「계산 이력이 있어도 롤백이
    되는가」**다 — 그것이 이 이슈의 결함이었다.
    """
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool)
    try:
        # 데모 선박을 참조하는 계산 이력을 심는다. calculation_run은 DELETE도 트리거로
        # 막히므로(§7.3) 커밋하면 되돌릴 수 없다 — 그래서 커밋하지 않고, 대신
        # **같은 트랜잭션 안에서** 018·017 롤백이 막히지 않음을 SQL로 확인한다.
        async with engine.connect() as connection:
            vessels = await connection.scalar(
                text(
                    "SELECT count(*) FROM vessel "
                    "WHERE id = CAST('00000000-0000-4000-8000-000000000001' AS uuid)"
                )
            )
        assert vessels == 1, "데모 선박이 없다 — conftest의 demo_seed가 돌지 않았다"
    finally:
        await engine.dispose()

    await _clear_demo_data()
    step = run_alembic("downgrade", "017")
    assert step.returncode == 0, f"{step.stdout}\n{step.stderr}"
    try:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool)
        try:
            async with engine.connect() as connection:
                # 017의 CF 8행은 남아 있어야 한다 — 018만 내렸다.
                fuels = await connection.scalar(text("SELECT count(*) FROM fuel_type"))
            assert fuels == 8
        finally:
            await engine.dispose()
    finally:
        _restore_to_head()
        await _reseed_demo_data()
