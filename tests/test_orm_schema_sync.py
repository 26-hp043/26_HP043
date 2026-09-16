"""ORM 모델 ↔ 실제 DB 스키마 동기화(zero drift) 검증 (#101).

Alembic autogenerate의 비교 엔진(compare_metadata)으로 두 방향을 검증한다:

1. zero drift — ``Base.metadata``(ORM 모델)와 마이그레이션이 만든 실제 DB가
   일치하여 diff가 비어 있어야 한다. 이후 누군가 모델만 고치고 마이그레이션을
   만들지 않으면(또는 그 반대) 이 테스트가 CI에서 실패한다.
2. 감지 능력 — 비교 엔진이 실제로 차이를 감지하는지 canary 테이블로 확인한다.
   (1번이 "diff 없음"만 보므로, 비교가 아예 동작하지 않아도 통과하는 위양성을
   차단한다. 이슈 #101 체크리스트의 "일부러 컬럼 추가 후 감지 확인"을 CI에서
   상시 실행 가능한 형태로 옮긴 것.)

읽기 전용 비교만 수행하며 DDL은 실행하지 않는다.
"""

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

# CUBRID용 Alembic DDL 구현을 **등록**한다 (`#1058`). import 자체가 부작용으로
# alembic의 방언→impl 표에 `cubrid`를 넣는다. 없으면 `MigrationContext.configure()`가
# `KeyError: 'cubrid'`로 선다 — `alembic/env.py`가 같은 import를 하고 있어서
# 마이그레이션 경로만 돌고 **이 검사만** 죽었다.
#
# `noqa: F401`은 「쓰지 않는 import」가 아니라 **등록이 목적인 import**라는 표시다.
from sqlalchemy_cubrid.alembic_impl import CubridImpl  # noqa: F401

from cii_platform.db.models import Base

#: CUBRID에서 **길이 없는 문자열**의 정밀도. ``STRING``·``VARCHAR``·
#: ``VARCHAR(1073741823)``이 전부 같은 타입이다 — 빈 표로 확인했다 (`#1058`)::
#:
#:     CREATE TABLE _strchk (a STRING, b VARCHAR(1073741823), c VARCHAR)
#:     SELECT attr_name, data_type, prec FROM db_attribute WHERE class_name = '_strchk'
#:       a  STRING  1073741823
#:       b  STRING  1073741823
#:       c  STRING  1073741823
#:
#: ORM의 ``sa.Text``(그리고 그것을 감싼 ``JSONText``)는 이 방언에서 ``STRING``으로
#: 컴파일되는데, 카탈로그를 반영하면 ``VARCHAR(1073741823)``으로 온다. **같은 타입의
#: 다른 표기**라 ``modify_type`` 10건이 계속 떠 있었다.
_CUBRID_UNBOUNDED_STRING = 1073741823

#: ``sa.text(...)``으로 적은 인덱스 — 반영과 대조되지 않는다.
#:
#: alembic이 그때마다 경고를 낸다: 「Generating approximate signature for index …
#: The dialect implementation should either skip expression indexes or provide a custom
#: implementation.」 그래서 모델의 ``sa.text("created_at DESC")``와 반영된 ``Column``이
#: 늘 다르게 보여 ``remove_index`` + ``add_index`` 쌍이 났다.
#:
#: 🔴 **``sa.desc(컬럼)``으로 적은 것은 여기 없다.** 둘을 재 보면 차이가 분명하다 —
#: ``sa.desc``는 ``UnaryExpression``이고 그 **열이 ``index.columns``에 남아** 있어
#: alembic이 대조한다(``idx_calc_vessel``·``idx_weather_cache``가 그 형태이고 drift에
#: 나오지 않았다). ``sa.text``는 ``TextClause``라 열이 ``index.columns``에서 빠진다.
#: 그래서 새 내림차순 인덱스는 **``sa.text``가 아니라 ``sa.desc``로 적는 쪽이 낫다** —
#: 이 목록에 추가하지 않아도 비교가 된다.
#:
#: ⚠️ **이름을 하나씩 적는다.** 「표현식이면 건너뛴다」로 두면 새로 생긴 표현식 인덱스가
#: 조용히 비교 밖으로 나간다. 아래 ``test_the_skipped_index_list_is_exactly_the_expression_indexes``
#: 가 이 목록이 실제 표현식 인덱스 집합과 **정확히 같은지** 대조한다.
_EXPRESSION_INDEXES: frozenset[str] = frozenset(
    {
        "idx_chat_session_user",
        "idx_fleet_reduction_plan_created",
        "idx_session_user",
        "idx_vessel_position_snapshot_vessel_observed",
    }
)


def _is_unbounded_string(type_: object) -> bool:
    """CUBRID에서 길이 없는 문자열인가 (``STRING`` = ``VARCHAR(1073741823)``)."""
    if not isinstance(type_, sa.String):
        return False
    return type_.length in (None, _CUBRID_UNBOUNDED_STRING)


def _compare_type(_ctx, _insp_col, _meta_col, inspected_type, metadata_type):
    """``False``면 「차이 없음」, ``None``이면 alembic의 기본 판단에 맡긴다."""
    if _is_unbounded_string(inspected_type) and _is_unbounded_string(
        metadata_type.impl if isinstance(metadata_type, sa.types.TypeDecorator) else metadata_type
    ):
        return False
    return None


def _include_object(_obj, name, type_, _reflected, _compare_to) -> bool:
    return not (type_ == "index" and name in _EXPRESSION_INDEXES)


def _compare(sync_conn, metadata: sa.MetaData) -> list:
    """현재 DB와 metadata를 비교해 autogenerate diff 목록을 반환한다.

    빼는 것은 **표기 차이 둘뿐**이다(위 두 상수의 근거 참조). 제약·인덱스·열의 존재와
    이름은 그대로 비교한다 — 오탐을 빼려고 실물 drift까지 가리면 이 검사가 무의미해진다.
    """
    ctx = MigrationContext.configure(
        sync_conn,
        # 타입 변경도 감지한다. server_default는 텍스트 표기 차이(now() 등)로
        # 오탐이 잦아 비교에서 제외한다(기본값). — 2단계 결정 2-A.
        opts={
            "compare_type": _compare_type,
            "include_object": _include_object,
        },
    )
    return compare_metadata(ctx, metadata)


async def test_orm_models_match_db_zero_drift(conn):
    """8개 테이블 ORM 모델이 마이그레이션 결과 DB와 일치한다.

    server_default는 비교에서 제외한다(_compare 참조 — 텍스트 표기 차이 오탐).
    그 외 테이블·컬럼·타입·제약·인덱스는 diff 0을 요구한다.
    """
    diffs = await conn.run_sync(_compare, Base.metadata)
    assert diffs == [], f"ORM 모델과 DB 스키마가 불일치:\n{diffs}"


def test_the_skipped_index_list_is_exactly_the_textual_indexes():
    """비교에서 뺀 인덱스 목록이 **실제 ``sa.text`` 인덱스 집합과 같다** (`#1058`).

    한쪽으로 어긋나면 각각 다른 사고다.
    - 목록에 있는데 표현식이 아니다 → **실물 drift가 가려진다.**
    - 표현식인데 목록에 없다 → 이 검사가 영원히 빨갛다(그건 곧 끄게 된다).
    """
    actual = {
        index.name
        for table in Base.metadata.tables.values()
        for index in table.indexes
        if any(isinstance(expr, sa.TextClause) for expr in index.expressions)
    }
    assert actual == _EXPRESSION_INDEXES, (
        f"`sa.text` 인덱스가 바뀌었다 — 실제 {sorted(actual)} ≠ 목록 "
        f"{sorted(_EXPRESSION_INDEXES)}. 내림차순이 필요하면 `sa.desc(컬럼)`으로 적으면 "
        "비교 대상으로 남는다(위 상수 주석)."
    )


def test_desc_indexes_are_not_skipped():
    """``sa.desc``로 적은 내림차순 인덱스는 **비교 대상에 남아 있다.**

    이 검사가 없으면 위 목록을 「내림차순이면 다 뺀다」로 넓혀도 아무도 모른다 —
    그러면 내림차순 인덱스의 실물 drift가 통째로 가려진다.
    """
    desc_indexes = {
        index.name
        for table in Base.metadata.tables.values()
        for index in table.indexes
        if any(isinstance(expr, sa.UnaryExpression) for expr in index.expressions)
    }
    assert desc_indexes, "sa.desc로 적은 인덱스가 하나도 없다 — 전제가 바뀌었다"
    assert desc_indexes & _EXPRESSION_INDEXES == set(), (
        f"sa.desc 인덱스가 비교에서 빠졌다: {sorted(desc_indexes & _EXPRESSION_INDEXES)}"
    )


def test_unbounded_string_equivalence_is_narrow():
    """길이 없는 문자열만 같게 본다 — 길이가 있는 ``VARCHAR``는 그대로 비교된다.

    넓게 잡으면 ``VARCHAR(50)``을 ``VARCHAR(200)``으로 바꿔도 drift가 안 보인다.
    """
    assert _is_unbounded_string(sa.String())
    assert _is_unbounded_string(sa.String(_CUBRID_UNBOUNDED_STRING))
    assert _is_unbounded_string(sa.Text())
    assert not _is_unbounded_string(sa.String(50))
    assert not _is_unbounded_string(sa.Integer())


async def test_compare_engine_detects_drift(conn):
    """비교 엔진이 모델↔DB 차이를 실제로 감지한다 (canary 테이블)."""
    canary_metadata = sa.MetaData()
    sa.Table(
        "orm_drift_canary",
        canary_metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    diffs = await conn.run_sync(_compare, canary_metadata)
    # canary는 DB에 없으므로 add_table diff가 나와야 한다.
    added = [d for d in diffs if d[0] == "add_table" and d[1].name == "orm_drift_canary"]
    assert added, f"비교 엔진이 canary 테이블 추가를 감지하지 못함:\n{diffs}"
