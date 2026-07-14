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

import pytest
from conftest import TEST_DATABASE_URL, run_alembic
from sqlalchemy import pool, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

# sha256: + 64 hex — chk_input_hash_format를 통과하는 유효 해시.
VALID_HASH = "sha256:" + "a" * 64


def test_downgrade_upgrade_roundtrip():
    """downgrade base → upgrade head 왕복이 성공한다 (§8.1 롤백 안전성).

    전체 마이그레이션 체인을 base까지 내렸다가 head로 되올려, voyage 그룹(§8.1)과
    008이 만든 공유 함수 prevent_mutation()의 드롭·재생성까지 한 번에 검증한다.
    실패하더라도 finally에서 head로 복원한다.
    """
    try:
        down = run_alembic("downgrade", "base")
        assert down.returncode == 0, f"{down.stdout}\n{down.stderr}"
        up = run_alembic("upgrade", "head")
        assert up.returncode == 0, f"{up.stdout}\n{up.stderr}"
    finally:
        # 성공/실패와 무관하게 head로 복원한다(happy path에서는 no-op).
        run_alembic("upgrade", "head")


def test_partial_downgrade_preserves_immutability():
    """부분 다운그레이드(009만 롤백) 후에도 calculation_run immutable이 유지된다.

    공유 함수 prevent_mutation()을 009가 아닌 008이 소유하도록 한 결정의 근거.
    ``downgrade 008``로 009만 롤백해도 트리거 trg_calcrun_immutable이 살아 있어야 하며,
    실제 UPDATE 시도가 거부되는지 확인한다. 검증 후 head로 복원한다.
    """
    step = run_alembic("downgrade", "008")
    assert step.returncode == 0, f"{step.stdout}\n{step.stderr}"
    try:
        asyncio.run(_assert_calculation_run_immutable())
    finally:
        # 부분 롤백 상태에서 head로 복원한다(실패해도 후속 테스트 오염 방지).
        run_alembic("upgrade", "head")


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
