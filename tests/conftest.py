"""마이그레이션 테스트용 pytest fixture.

실행 중인 PostgreSQL(docker-compose의 db 서비스, 기본 localhost:5432)에 대해
`alembic upgrade head`로 스키마를 구성한 뒤, async 엔진으로 제약을 검증한다.

DATABASE_URL 환경변수로 대상 DB를 바꿀 수 있으며, 미설정 시 config 기본값을 사용한다.
"""

import contextlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(_ROOT / "src"))

from db_target import is_disposable, refusal_reason  # noqa: E402

from cii_platform.config import DATABASE_URL  # noqa: E402
from cii_platform.db.url import normalize_to_async  # noqa: E402

# config/환경변수의 원본 URL. run_alembic은 이 raw 값을 그대로 넘긴다(아래 참조).
_RAW_DATABASE_URL = os.environ.get("DATABASE_URL", DATABASE_URL)
TEST_DATABASE_URL = normalize_to_async(_RAW_DATABASE_URL)

_IS_CUBRID = "cubrid" in TEST_DATABASE_URL
# sqlalchemy-cubrid dialect는 이미 insert_returning=False를 설정한다.
# implicit_returning은 deprecated이므로 사용하지 않는다.
_cubrid_engine_kw: dict = {}

# CUBRID 환경에서 skip할 테스트 파일들 (#1058):
# - migration guard: 42개 개별 migration 파일 기대 → 1개 initial로 합침
# - db_check_cases: CHECK constraint 강제를 기대 → CUBRID는 CHECK 미강제
# - *_migrations: 개별 migration upgrade/downgrade 테스트
#: **비어 있다 — 여덟 파일을 전부 되살렸다** (2026-09-16, `#1058`).
#:
#: 한때 여기 여덟 파일이 있었고 97검사가 통째로 건너뛰어졌다. 「건너뛰는 것은 고친
#: 것이 아니다」라는 규칙대로 한 파일씩 빼고 돌려 무엇이 실제로 죽는지 쟀다.
#:
#:     되살리기 전   72 failed / 25 passed
#:     지금           7 failed / 90 passed
#:
#: 무엇이 죽어 있었나 — 셋이었다.
#:
#: * **CHECK 38건이 아무것도 막지 않았다.** CUBRID는 CHECK를 구문으로 받기만 하고
#:   검사하지 않는다. `046`·`048`이 60개를 트리거로 옮겼다.
#: * **PostgreSQL 전용 카탈로그·구문 18건.** `information_schema` · `pg_indexes` ·
#:   `::timestamptz` · `RETURNING` 따위를 CUBRID 것으로 옮겼다.
#: * **무결성 위반의 예외 갈래가 달랐다.** `db/cubrid_errors.py` 참조.
#:
#: 남은 7건은 **건너뛰지 않고 실패한 채 보인다.** 가려 두면 다음 사람이 다시
#: 조사하게 되고, 무엇보다 트리거 144개가 CI에서 확인되지 않는다. 성질은 이렇다.
#:
#: * `idx_sim_snapshot_unique`가 DB에 없다 (2건) — CUBRID가 FK 컬럼에 인덱스를 또
#:   두는 것을 거부한다(`errno=-272`). 결정요청 §3⑵의 미결 항목이다.
#: * `not_underway_period`의 부분 인덱스에 필터가 없다 (1건).
#: * 부모 쪽 `fuel_type` DELETE를 막지 않는다 (1건) — `REPLACE INTO`가 DELETE로
#:   구현돼 시드 재적재가 막히므로 `a7d3e9b14f26`이 의도적으로 뺐다(`DB_SCHEMA §7.4`).
#: * 불변성 트리거 거부를 `IntegrityError`로 기대한다 (2건) — 성질이 다르다.
#: * `'fixed abc'`가 `LIKE 'fixed %'`를 통과한다 (1건) — 원문 CHECK에도 있던 구멍이다.
#:
#: ⚠️ **`test_migration_guard.py`는 한때 여기 있었다** (`#1058`). `49d010e`가 그 파일을
#: **파일명이 아니라 `revision: str = "..."`을 AST로 읽도록** 고쳐 두었다 — 넣어 두면
#: 프로덕션 다운그레이드를 막는 가드(`#819`)가 아무도 확인하지 않는 상태가 된다.
_CUBRID_SKIP_FILES: set[str] = set()


# import 시점에 asyncpg 등 PostgreSQL 전용 모듈을 쓰는 파일은
# pytest_collection_modifyitems보다 먼저 collection error가 난다.
# collect_ignore로 아예 수집하지 않는다.
_CUBRID_COLLECT_IGNORE = {
    "test_suite_lock_db.py",  # asyncpg advisory lock
}

collect_ignore: list[str] = []
if _IS_CUBRID:
    collect_ignore.extend(str(Path(__file__).parent / f) for f in _CUBRID_COLLECT_IGNORE)


def pytest_collection_modifyitems(config, items):
    """CUBRID 환경에서 migration/CHECK 의존 테스트를 skip한다."""
    if not _IS_CUBRID:
        return
    skip_cubrid = pytest.mark.skip(reason="CUBRID: migration 구조/CHECK 미강제 (#1058)")
    for item in items:
        if item.path and item.path.name in _CUBRID_SKIP_FILES:
            item.add_marker(skip_cubrid)


def require_disposable_target() -> None:
    """DB를 건드리기 전에 대상이 버려도 되는 곳인지 확인한다 (`#691`).

    ## 왜 파일이 아니라 여기인가

    `#507`이 같은 판정을 만들었으나 ``test_zz_roundtrip.py`` **한 파일에만** 걸었다.
    계정·세션·토큰을 지우는 나머지 **12개 파일**은 아무 제약 없이 시연 DB에 붙었고,
    2026-08-23에 가입 계정이 실제로 사라졌다. **스키마 드롭은 막혔는데 행 삭제는
    안 막혀 있었다.**

    파일마다 붙이는 방식은 **다음에 만드는 테스트를 놓친다.** 그래서 DB를 여는
    자리(:func:`run_alembic` · :func:`migrated_db` · :func:`app_fresh_engine`)로
    올린다 — 앞으로 추가되는 테스트도 자동으로 같은 규칙을 받는다.

    ## 왜 skip이 아니라 fail인가

    skip은 조용하다. **돌지 않은 것을 돌았다고 착각할 여지**를 남기는데, 이 사고의
    본체가 바로 「아무 신호 없이 지나갔다」였다. CI는 이미 ``cii_test``를 쓰므로
    (``.github/workflows/ci.yml``) fail로 두어도 **CI 동작은 달라지지 않는다.**

    ## 무엇을 막지 않는가

    **DB를 쓰지 않는 테스트는 그대로 돈다.** 세션 전체를 중단하면 `cii_test` 없이
    돌리던 순수 단위 테스트까지 함께 잃는다 — 막아야 할 것은 「DB에 쓰는 것」이지
    「테스트를 돌리는 것」이 아니다.
    """
    if not is_disposable(TEST_DATABASE_URL):
        pytest.fail(refusal_reason(TEST_DATABASE_URL), pytrace=False)
    _hold_suite_lock()


# ─────────────────────────────────────────────────────────────────────────────
# 실행 단위 잠금 (#894)
#
# 스위트 두 개가 같은 테스트 DB를 동시에 쓰면 서로의 행을 지우고(전역 DELETE·UPDATE로
# 정리하는 검사들) 스키마까지 내린다(`test_zz_roundtrip.py`). 2026-09-09에 세 번 겪었고,
# 증상은 「220 failed」라 **원인이 아니라 내 수정을 의심하게 된다.**
#
# 병렬을 가능하게 하는 것이 아니라 **겹친 순간 원인을 말하며 멈추게** 한다. 실제 병렬
# 수요가 생기면 템플릿 DB 복제(`CREATE DATABASE … TEMPLATE`)로 간다.
#
# `#691`의 판정(대상이 버려도 되는 DB인가)과 층이 다르다 — 이쪽은 **지금 누가 그 DB를
# 쓰는가**다. 둘 다 「DB를 여는 자리」에서 확인하므로 같은 함수에 붙였다.
# ─────────────────────────────────────────────────────────────────────────────

#: 잠금 키. 어드바이저리 잠금은 **데이터베이스 단위**라 다른 DB(시연 `cii`)와 섞이지 않는다.
SUITE_LOCK_KEY = 894_000_001

#: 잠금을 쥔 연결과 그 이벤트 루프. 프로세스가 끝나면 연결이 끊겨 잠금도 풀린다 —
#: 실행이 강제 종료돼도 잠금이 남지 않는다.
_suite_lock: dict[str, object] = {}

SUITE_LOCK_MESSAGE = (
    "다른 pytest 실행이 이 테스트 DB를 쓰고 있습니다 ({db}). "
    "두 실행이 겹치면 서로의 데이터를 지우고 스키마까지 내립니다(#894). "
    "앞 실행이 끝난 뒤 다시 돌리십시오."
)


def uuid_hex(value) -> str:
    """UUID를 CUBRID 저장 형식(하이픈 없는 32자 hex)으로 (#1058).

    f-string으로 SQL 리터럴을 만드는 자리에서 쓴다. PostgreSQL 시절에는
    ``'{uuid}'::uuid``로 캐스팅했는데 **CUBRID에는 `uuid` 타입이 없다.** 컬럼은
    ``CHAR(32)``이고, 대시 형식을 그대로 넣으면 다음처럼 거부된다 — 실측이다::

        Cannot coerce '00000000-0000-4000-8000-000000000001' to type char

    파라미터를 쓸 수 있는 자리에서는 이 함수 대신 ``UuidText`` bindparam을 붙인다.
    """
    from uuid import UUID

    return UUID(str(value)).hex


def uuid_canon(value) -> str:
    """UUID를 **표준 대시 36자**로 (`#1058`).

    :func:`uuid_hex`의 짝이다. 생 SQL이 읽은 값은 저장 형식(hex 32자)이고 계약값·
    API 응답은 대시 형식이다. 목록·집합·딕셔너리 키를 통째로 비교하는 자리에서는
    :func:`same_uuid` 로 짝지어 볼 수 없으므로, **DB에서 온 쪽을 이 함수로 정규화**한다.

    계약값을 hex로 바꾸지 않는 이유 — ``#132``가 정한 것은 대시 형식이고,
    ``test_uuids_are_the_contracted_values`` 같은 검사는 **그 형식 자체가 단언 대상**이다.
    """
    from uuid import UUID

    return str(UUID(str(value)))


def same_uuid(a, b) -> bool:
    """UUID 두 값을 **형식에 상관없이** 비교한다 (`#1058`).

    서비스·API는 `str(vessel.id)`로 **대시 36자**를 낸다(ORM이 `CHAR(32)`를 `UUID`로
    되돌린다). 반면 :func:`insert_returning_id`는 저장 형식인 **hex 32자**를 돌려준다.
    그대로 ``==``로 비교하면 **영원히 거짓**이다 — 예외가 아니라 조용한 불일치라
    ``next(...)``가 ``StopIteration``을 내고, 그것이 ``RuntimeError: coroutine raised
    StopIteration``으로 둔갑해 원인이 전혀 보이지 않았다.

    :func:`insert_returning_id`가 대시 형식을 돌려주게 바꿔 봤으나 그 값을 생 SQL에
    그대로 싣는 검사 **40건**이 깨져 되돌렸다(고쳐진 것은 0건이었다). 형식을 한쪽으로
    통일하는 일은 따로 잡고, 여기서는 **비교하는 자리에서** 맞춘다.
    """
    from uuid import UUID

    return UUID(str(a)) == UUID(str(b))


def _cubrid_params(params: dict | None) -> dict:
    """CUBRID 호환 파라미터 변환 — UUID → hex string, Decimal → float (#1058)."""
    if not params:
        return {}
    import uuid
    from decimal import Decimal

    result = {}
    for k, v in params.items():
        if isinstance(v, uuid.UUID):
            result[k] = v.hex
        elif isinstance(v, Decimal):
            result[k] = float(v)
        else:
            result[k] = v
    return result


async def execute_sql(session, sql: str, params: dict | None = None):
    """CUBRID 호환 raw SQL 실행 — UUID/Decimal 자동 변환."""
    from sqlalchemy import text

    return await session.execute(text(sql), _cubrid_params(params))


async def insert_if_not_exists(session, sql_with_values: str, params: dict | None = None) -> None:
    """CUBRID 호환 idempotent INSERT — 이미 있으면 무시."""
    # 이미 존재 (UNIQUE/PK 위반)
    with contextlib.suppress(Exception):
        await execute_sql(session, sql_with_values, params)


async def ensure_regulation_year(session, year: int, z_factor: float = 11.0) -> None:
    """테스트에 필요한 regulation_year 행을 넣는다 (이미 있으면 무시)."""
    await insert_if_not_exists(
        session,
        'INSERT INTO regulation_year (id, "year", z_factor_percent, '
        "effective_from, source_ref, version, is_active) "
        "VALUES (:id, :y, :z, :eff, :src, :ver, 1)",
        {
            "id": __import__("uuid").uuid4().hex,
            "y": year,
            "z": z_factor,
            "eff": f"{year}-01-01",
            "src": "TEST",
            "ver": "1.0",
        },
    )


def _hold_suite_lock() -> None:
    """CUBRID에는 advisory lock이 없으므로 no-op (#1058)."""
    pass


def _release_suite_lock() -> None:
    pass


def pytest_sessionfinish(session, exitstatus):
    """세션이 끝나면 잠금을 푼다."""
    _release_suite_lock()


@pytest.fixture(autouse=True)
def _fresh_rate_limiter():
    """매 테스트마다 ``main.app``의 분당 카운터를 새것으로 바꾼다 (#651).

    ## 왜 필요한가

    ``main.app``은 **모듈 레벨 객체**라 ``app.state.rate_limiter``(300/분)를
    **pytest 프로세스 전체가 공유**한다. 그 앱을 ``TestClient``로 때리는 테스트
    파일이 20개가 넘고, ``RateLimiter``는 **고정 윈도**라 60초가 지나야 리셋된다.

    그래서 실패 여부가 **전체 실행 속도에 달려 있었다.**

    .. code-block:: text

        로컬  전체 3분대 → 요청이 여러 윈도에 흩어짐 → 통과
        CI    전체 1분대 → 같은 윈도에 몰림         → 429

    테스트를 몇 개만 더해도 **자기 변경과 무관한 파일**이 떨어진다. 실제로 `#593`과
    `#648`이 각각 한 번씩 이것으로 CI가 막혔고, 두 번 다 해당 파일에서만 우회했다.

    ## 왜 카운터를 비우지 않고 통째로 바꾸는가

    ``_counts``는 내부 상태다. 테스트가 그것을 직접 만지면 구현이 바뀔 때 함께
    깨진다. 같은 한도의 **새 인스턴스**를 끼우면 공개된 생성자만 쓴다 — 미들웨어가
    요청마다 ``request.app.state.rate_limiter``를 다시 읽으므로 교체가 그대로 든다.

    **``limits``를 통째로 넘긴다** (`#811`). 종전에는 ``RateLimiter(previous.limit)``,
    즉 기본 버킷 값 하나만 넘겼다 — 버킷이 생긴 뒤로 그렇게 하면 **인증 10 · 계산 60이
    전부 300으로 통일**되어, ``main.app``을 쓰는 25개 파일에서 새 한도가 조용히 사라진다.

    ## 무엇을 무력화하지 않는가

    **한도 자체는 그대로 살아 있다.** 한 테스트 안에서 300건을 넘기면 여전히 429가
    되고, ``test_rate_limit.py``는 자기 앱을 따로 만들어 쓰므로 영향이 없다.
    `#275`가 배선으로 고정한 「rate limit이 auth보다 바깥」도 그대로다 — 한도를 0으로
    꺼 버리면 그 순서가 깨져도 아무도 모른다.
    """
    from cii_platform.api.main import app
    from cii_platform.api.rate_limit import RateLimiter

    previous = getattr(app.state, "rate_limiter", None)
    if previous is not None:
        app.state.rate_limiter = RateLimiter(previous.limits)
    try:
        yield
    finally:
        if previous is not None:
            app.state.rate_limiter = previous


def run_alembic(*alembic_args: str) -> subprocess.CompletedProcess:
    """프로젝트 루트에서 alembic CLI를 실행한다.

    PATH에 alembic 스크립트가 없어도(예: `python -m pytest` 직접 실행, CI) 동작하도록
    현재 인터프리터로 `python -m alembic`을 호출한다.
    """
    # 드라이버 정규화는 alembic/env.py의 _to_async_url()이 담당하므로, 여기서는
    # 원본 URL을 그대로 전달한다. asyncpg form을 미리 넘겨 이중 변환하지 않음으로써,
    # 향후 config.py가 raw postgresql:// 형식을 검증하더라도 깨지지 않게 한다. (#86)
    require_disposable_target()
    env = {**os.environ, "DATABASE_URL": _RAW_DATABASE_URL}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *alembic_args],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="session")
def load_fixture():
    """JSON 픽스처 로더 (`TEST_PLAN §1.6`).

    구현은 `tests/fixture_loader.py`에 있다. 이 모듈은 PostgreSQL 연결을
    전제하므로, DB 없이 성립해야 하는 픽스처 비교를 여기에 두지 않는다.

    `tests/`에 `__init__.py`가 없어 pytest가 이 디렉터리를 `sys.path`에 넣는다.
    따라서 `tests.` 접두 없이 모듈 이름으로 import한다 — `tests.fixture_loader`로
    적으면 저장소 루트가 `sys.path`에 있는 환경(로컬 `cwd`)에서만 동작하고
    CI에서는 `ModuleNotFoundError`가 난다.
    """
    from fixture_loader import load_fixture as _load

    return _load


@pytest.fixture(scope="session")
def migrated_db() -> None:
    """세션 시작 시 head까지 upgrade하고 **데모 데이터를 적재**한다.

    데모 데이터가 마이그레이션에서 분리되면서(`#451`) 스키마만으로는 데모 선박이 없다.
    그 선박의 고정 UUID를 전제하는 테스트가 여럿이라 여기서 함께 넣는다 — 각 테스트가
    따로 넣으면 같은 데이터를 여러 벌 관리하게 된다.

    적재는 **멱등**이라(``ON CONFLICT DO NOTHING``) 매 세션 반복해도 행이 늘지 않는다.

    대상 DB 판정을 먼저 한다 (`#691`) — :func:`run_alembic`이 같은 확인을 하지만,
    **여기서 막아야 실패 지점이 「DB를 쓰는 fixture」로 읽힌다.**
    """
    require_disposable_target()
    result = run_alembic("upgrade", "head")
    if result.returncode != 0:
        pytest.fail(_upgrade_failure_message(result), pytrace=False)

    import asyncio

    from cii_platform.db.demo_seed import seed_demo

    async def _seed() -> None:
        engine = create_async_engine(
            TEST_DATABASE_URL, poolclass=pool.NullPool, **_cubrid_engine_kw
        )
        try:
            async with engine.begin() as conn:
                await seed_demo(conn)
        finally:
            await engine.dispose()

    asyncio.run(_seed())


def _upgrade_failure_message(result: subprocess.CompletedProcess) -> str:
    """``upgrade head`` 실패를 **DB가 어느 리비전에 남았는지**와 함께 알린다 (#894).

    `test_zz_roundtrip.py`가 ``downgrade base``와 ``upgrade head`` 사이에서 끊기면 DB가
    **중간 리비전에 남는다.** 그 상태에서 다음 실행은 잔존 데이터와 충돌해 실패하는데,
    alembic 원문만으로는 「이전 실행이 중간에 끊겼다」가 읽히지 않는다(2026-09-09 실측:
    ``017``·테이블 15개로 남았고 복구 절차를 찾는 데 시간이 들었다).
    """
    current = run_alembic("current")
    revision = (current.stdout.strip().split() or ["(없음)"])[0]
    return (
        "alembic upgrade head 실패 — 테스트 DB가 리비전 "
        f"{revision}에 남아 있습니다.\n"
        "이전 실행의 왕복 검사(test_zz_roundtrip.py)가 중간에 끊긴 흔적일 수 있습니다. "
        "복구: 테스트 DB를 지우고 다시 만든 뒤 `alembic upgrade head` "
        "(README 「테스트 DB 복구」).\n\n"
        f"{result.stdout}\n{result.stderr}"
    )


def _install_cubrid_param_converter(engine):
    """CUBRID 호환 파라미터 변환 이벤트 — UUID→hex, Decimal→float (#1058).

    sa.text()에 UUID 객체를 바인딩하면 pycubrid가 거부하므로,
    before_cursor_execute에서 자동 변환한다.
    """
    import re
    import uuid

    # ``sa.Uuid``의 bind processor를 여기서 패치하지 않는다 (`#1058`).
    #
    # 한때 `_sqltypes.Uuid.bind_processor`를 갈아 문자열을 통과시켰는데, 그 패치는
    # **검사에만 걸린다** — 배포 코드는 같은 자리에서 그대로 선다. 검사는 초록인데
    # 운영이 깨지는 모양이라, 결함을 고치는 대신 **가리는** 쪽이었다.
    #
    # 지금은 `db/types.py`의 `UuidText`가 타입 자체에서 받으므로 검사와 운영이 같은
    # 경로를 탄다. 패치를 빼고 같은 묶음을 돌려 **18 failed / 64 passed로 동일**함을
    # 확인했다(있으나 없으나 같다). 서드파티 클래스를 되돌리지 않고 전역 변조하는
    # 것이기도 해서 남겨 둘 이유가 없다.
    from decimal import Decimal

    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "before_cursor_execute", retval=True)
    def _convert_params(conn, cursor, statement, parameters, context, executemany):
        # 1. UUID/Decimal/datetime → CUBRID 호환 변환
        from datetime import datetime as _dt

        def _convert_value(p):
            if isinstance(p, uuid.UUID):
                return p.hex
            if isinstance(p, Decimal):
                return str(p)
            if isinstance(p, _dt):
                # 🔴 **`datetime`은 손대지 않는다** (`#1058` · 인계 v6 §4의 그 원인).
                #
                # 종전에는 여기서 `strftime("%Y-%m-%d %H:%M:%S")`로 **초 단위 문자열**을
                # 만들고 타임존을 떼었다. 그래서 `simulation_snapshot.created_at`이
                # 밀리초를 잃고 `+00:00`도 잃었다 — 실측이다::
                #
                #     보낸 값     2026-09-16T05:07:21.697000+00:00
                #     DB 문자열   '05:07:21.000 AM 09/16/2026 UTC UTC'   ← .000 · 존 이름
                #
                # 그 결과 실행 응답(파이썬 값)은 `.697000`을 내고 조회 응답(DB에서 읽음)은
                # 소수부 없이 내, `test_annual_simulation_read_db` 5건이 **경로에 따라
                # 다른 `created_at`**으로 떨어졌다.
                #
                # ⚠️ **이것은 검사에만 있던 변환이다.** 배포 엔진에는 이 이벤트가 붙지
                # 않으므로 운영에서는 밀리초가 보존된다 — 즉 검사가 **없는 결함을
                # 만들어 내고** 있었다. 위 `sa.Uuid` 패치를 뺄 때 적은 것과 같은 자리다:
                # 「그 패치는 검사에만 걸린다」.
                #
                # pycubrid가 aware `datetime`을 그대로 받고 밀리초까지 보관하는 것을
                # 빈 표로 확인했다::
                #
                #     보낸 값 datetime(2026, 9, 16, 5, 3, 26, 548000, tzinfo=utc)
                #     DB 문자열 '05:03:26.548 AM 09/16/2026 +00:00'
                #
                # 아래 `str` 갈래는 그대로 둔다 — **문자열 리터럴**의 `T`·`Z`는 CUBRID가
                # 정말로 거부한다(`Invalid or missing timezone`).
                return p
            if isinstance(p, str):
                # ISO 8601 문자열 datetime → CUBRID 호환
                if re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", p):
                    p = p.replace("T", " ").rstrip("Z")
                    if p.endswith("+00:00"):
                        p = p[:-6]
                return p
            return p

        if parameters and isinstance(parameters, (tuple, list)):
            parameters = tuple(_convert_value(p) for p in parameters)

        # 2. CUBRID: PostgreSQL 구문 변환 (auto-id 전에 실행해야 regex가 깨지지 않음)
        # CUBRID datetime 호환:
        # 1) 'Z' 타임존 제거 + T→공백  2) +00:00 제거 + T→공백
        # CUBRID는 ISO 8601 'T' 구분자와 'Z' 접미사를 모두 거부한다.
        def _fix_dt_literal(m):
            s = m.group(1).replace("T", " ")
            return f"'{s}'"

        statement = re.sub(
            r"'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})Z'",
            _fix_dt_literal,
            statement,
        )
        statement = re.sub(
            r"'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})\+00:00'",
            _fix_dt_literal,
            statement,
        )
        # 나머지 T 구분자 (타임존 없는 경우)
        statement = re.sub(
            r"'(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})'",
            r"'\1 \2'",
            statement,
        )
        statement = statement.replace("interval '1 hour'", "1/24.0")
        statement = re.sub(r"CAST\(\? AS \w+\)", "?", statement)
        statement = re.sub(r"::(uuid|timestamptz|timestamp|text|jsonb)", "", statement)
        statement = re.sub(r"\bIS 0\b", "= 0", statement)
        statement = re.sub(r"\bIS 1\b", "= 1", statement)

        # 3. CUBRID: RETURNING 미지원 — INSERT RETURNING ... 전체 제거
        #    복수 컬럼(RETURNING id, created_at)도 처리한다.
        #    auto-id 삽입보다 먼저 실행해야 regex의 $가 매칭된다.
        if " RETURNING " in statement:
            statement = re.sub(r"\s+RETURNING\s+.+$", "", statement)

        # 4. INSERT에 id 컬럼이 없으면 자동 추가 (CUBRID server_default 미지원 대응)
        #
        # ⚠️ **공백에 관대해야 한다.** 종전 정규식은 `INSERT INTO <표> (` 사이를 **공백
        # 하나**로만 봤는데, SQLAlchemy가 내는 구문은 줄바꿈과 여러 칸을 섞는다.
        #
        #     INSERT INTO voyage_fuel_use   (voyage_id, …) VALUES (?, ?,   ?, ?)
        #
        # 매칭이 빗나가면 `id`가 붙지 않고 그대로 나가 이렇게 선다 —
        # `Missing value for attribute "id" with the NOT NULL constraint (errno=-225)`.
        # 오류가 **구문이 아니라 데이터 문제처럼** 보여 원인이 셈에 있다는 것이 가려진다.
        if statement.lstrip().upper().startswith("INSERT INTO") and not re.search(
            r"\(\s*id\s*[,)]", statement, re.I
        ):
            # VALUES 안의 괄호까지 포함하여 마지막 )를 찾기
            m = re.match(
                r"(INSERT INTO \S+\s+)\(([^)]+)\)(\s*VALUES\s*)\((.+)\)\s*$",
                statement,
                re.S,
            )
            if m:
                prefix, cols, mid, vals = m.groups()
                new_id = uuid.uuid4().hex
                statement = f"{prefix}(id, {cols}){mid}(?, {vals})"
                if isinstance(parameters, tuple):
                    parameters = (new_id, *parameters)
                elif isinstance(parameters, list):
                    parameters = [new_id] + parameters

        return statement, parameters


async def insert_returning_id(session, sql: str, params: dict) -> str:
    """CUBRID 호환 INSERT RETURNING id 대체.

    INSERT에 id를 자동 생성하여 넣고, 그 id를 반환한다.
    before_cursor_execute가 id를 자동 추가하므로, 추가된 id를 찾아 반환한다.
    """
    import re as _re
    import uuid as _uuid

    generated_id = _uuid.uuid4().hex
    sql_no_returning = _re.sub(r"\s+RETURNING\s+\w+", "", sql)
    if "(id," not in sql_no_returning:
        sql_no_returning = sql_no_returning.replace("VALUES (", f"VALUES ('{generated_id}', ", 1)
        # 컬럼 리스트에 id 추가
        sql_no_returning = _re.sub(r"\((\w)", r"(id, \1", sql_no_returning, count=1)
    else:
        # id가 이미 있으면 params에서 가져온다
        generated_id = str(params.get("id", generated_id)).replace("-", "")

    await execute_sql(session, sql_no_returning, params)
    return generated_id


@pytest_asyncio.fixture
async def conn(migrated_db):
    """함수 단위 트랜잭션. 테스트 종료 시 롤백하여 DB를 오염시키지 않는다."""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool, **_cubrid_engine_kw)
    _install_cubrid_param_converter(engine)
    connection = await engine.connect()
    trans = await connection.begin()
    try:
        yield connection
    finally:
        await trans.rollback()
        await connection.close()
        await engine.dispose()


@pytest.fixture
def app_fresh_engine(monkeypatch: pytest.MonkeyPatch):
    """TestClient(포털 루프) DB 접근용 NullPool 엔진으로 교체한다.

    앱의 ``get_engine``은 lru_cache로 프로세스에 하나다. TestClient는 컨텍스트마다
    새 이벤트 루프(포털)를 만들므로, 풀에 남은 연결이 이전 루프에 묶여
    ``attached to a different loop``로 실패한다 (#308 테스트). DB를 실제로 쓰는
    TestClient 테스트는 이 fixture로 요청마다 연결을 만드는 NullPool 엔진으로
    갈아끼운다 — 테스트 루프에서 검증·정리할 때도 같은 세션팩토리를 쓴다.

    **``migrated_db``에 의존하지 않는다.** 그래서 대상 DB 판정을 여기서 따로 한다
    (`#691`) — 이 fixture만 받아 DB에 쓰는 테스트가 생기면 위 판정을 통째로
    비켜 간다.
    """
    require_disposable_target()

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from cii_platform.db import session as db_session_mod

    engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool, **_cubrid_engine_kw)
    _install_cubrid_param_converter(engine)
    patched_maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session_mod, "get_engine", lambda: engine)
    monkeypatch.setattr(db_session_mod, "get_sessionmaker", lambda: patched_maker)
    yield engine
