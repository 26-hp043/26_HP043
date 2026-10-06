"""이슈 #103 파라미터 테이블 마이그레이션 검증 (010~012).

대상: cii_reference_line(010), cii_rating_boundary(011), weather_model_parameter(012).

완료 기준(이슈 #103):
- 각 테이블의 CHECK·UNIQUE 인덱스가 DB_SCHEMA §2.10~§2.12와 일치
- INSERT 정상 동작, 제약 위반 거부

주의: 여기 테스트 값은 제약 동작 검증용 임의 값이며 정본 §3의 규제값이 아니다.

**[#127] 이 테이블들은 더 이상 비어 있지 않다.** data migration 032가 ``upgrade head``
시점에 규제 파라미터 42행을 넣는다. 그래서 아래 두 가지를 지킨다.

- ``condition_expr``에 정본에 없는 sentinel(``__test__``)을 쓴다 — 규제값과 UNIQUE 키가
  겹치지 않게 한다. seed가 늘어나도 계속 성립한다.
- 행 수는 절대값이 아니라 **증가분**으로 단언한다 — seed 행 수에 결합되지 않게 한다.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


async def _insert_refline(
    conn,
    ship_type="BULK_CARRIER",
    condition_expr="__test__",
    capacity_rule="DWT",
    a_raw="4745E3",
    a_decimal="4745000",
    c="0.622",
):
    await conn.execute(
        text(
            "INSERT INTO cii_reference_line "
            "(ship_type, condition_expr, capacity_rule, a_raw, a_decimal, c, source_ref) "
            "VALUES (:st, :ce, :cr, :ar, :ad, :c, 'TEST')"
        ),
        {
            "st": ship_type,
            "ce": condition_expr,
            "cr": capacity_rule,
            "ar": a_raw,
            "ad": a_decimal,
            "c": c,
        },
    )


async def _insert_boundary(
    conn,
    ship_type="BULK_CARRIER",
    condition_expr="__test__",
    d1="0.86",
    d2="0.94",
    d3="1.06",
    d4="1.18",
):
    await conn.execute(
        text(
            "INSERT INTO cii_rating_boundary "
            "(ship_type, condition_expr, capacity_basis, d1, d2, d3, d4, source_ref) "
            "VALUES (:st, :ce, 'DWT', :d1, :d2, :d3, :d4, 'TEST')"
        ),
        {"st": ship_type, "ce": condition_expr, "d1": d1, "d2": d2, "d3": d3, "d4": d4},
    )


async def _insert_weather_param(conn, model_version="TOWNSIN_KWON_ALPHA", key="alpha"):
    await conn.execute(
        text(
            'INSERT INTO weather_model_parameter (model_version, "key", "value") '
            "VALUES (:mv, :k, '1.0')"
        ),
        {"mv": model_version, "k": key},
    )


# --- cii_reference_line (010) ---


async def test_refline_insert_ok(conn):
    before = (await conn.execute(text("SELECT count(*) FROM cii_reference_line"))).scalar_one()
    await _insert_refline(conn)
    await _insert_refline(conn, ship_type="LNG_CARRIER", capacity_rule="fixed 279000")
    after = (await conn.execute(text("SELECT count(*) FROM cii_reference_line"))).scalar_one()
    # 증가분으로 본다 — 032가 넣은 seed 20행에 결합되지 않게 (#127).
    assert after - before == 2


async def test_refline_allows_zero_c(conn):
    # LNG_CARRIER DWT >= 100000은 c = 0(고정 CII_ref)이 정상 (§2.10 [Oracle 관찰]).
    await _insert_refline(conn, ship_type="LNG_CARRIER", c="0")


async def test_refline_rejects_nonpositive_a_decimal(conn):
    # 케이스 DB-CHK-019 (`TEST_PLAN §5.1`)
    with pytest.raises(IntegrityError, match="chk_a_decimal_positive"):
        await _insert_refline(conn, a_decimal="0")


async def test_refline_rejects_negative_c(conn):
    # 케이스 DB-CHK-020 (`TEST_PLAN §5.1`)
    with pytest.raises(IntegrityError, match="chk_c_positive"):
        await _insert_refline(conn, c="-0.1")


async def test_refline_capacity_rule_rejects_invalid(conn):
    # 케이스 DB-CHK-008 (`TEST_PLAN §5.1`)
    # [M-7]: 'fixed' 뒤에 숫자만 허용.
    with pytest.raises(IntegrityError, match="chk_capacity_rule"):
        await _insert_refline(conn, capacity_rule="fixed abc")


async def test_refline_unique_rejects_duplicate(conn):
    # 🔴 054(#673) — 전역 UNIQUE(idx_refline_unique)는 **활성-유니크 트리거**로
    # 바뀌었다. 같은 키의 활성 행 둘은 여전히 거부되나(계산이 읽는 것은 활성 행),
    # 이행 행(is_active=0)은 쌓일 수 있다(DB_SCHEMA §7.2 개정 정책).
    await _insert_refline(conn)
    with pytest.raises(IntegrityError, match="trg_cii_reference_line_active_unique"):
        await _insert_refline(conn)


async def test_refline_history_row_same_key_is_allowed(conn):
    # #673 — 개정은 기존 활성 행을 끄고 새 행을 넣는다. 그 결과 같은 키의
    # 이행 행이 존재하는 것이 **정상 상태**다.
    await _insert_refline(conn)
    await conn.execute(
        text("UPDATE cii_reference_line SET is_active = 0 WHERE condition_expr = '__test__'")
    )
    await _insert_refline(conn)  # 같은 키 · 활성 행은 이제 하나뿐이라 통과


# --- cii_rating_boundary (011) ---


async def test_boundary_insert_ok(conn):
    await _insert_boundary(conn)


async def test_boundary_d_order_rejects_disorder(conn):
    # 케이스 DB-CHK-003 (`TEST_PLAN §5.1`)
    # [M-3]: d1 < d2 < d3 < d4 위반 (d2 < d1).
    with pytest.raises(IntegrityError, match="chk_d_order"):
        await _insert_boundary(conn, d1="0.94", d2="0.86")


async def test_boundary_unique_rejects_duplicate(conn):
    # 🔴 054(#673) — 위 기준선과 같은 변경. 활성 행끼리만 유일하다.
    await _insert_boundary(conn)
    with pytest.raises(IntegrityError, match="trg_cii_rating_boundary_active_unique"):
        await _insert_boundary(conn)


# --- weather_model_parameter (012) ---


async def test_weather_param_insert_ok(conn):
    # unit·source_ref는 NULL 허용 (§2.12).
    await _insert_weather_param(conn)


async def test_weather_param_unique_rejects_duplicate(conn):
    # [S-5]: (model_version, key) 조합 유일.
    await _insert_weather_param(conn)
    with pytest.raises(IntegrityError, match="idx_weather_param_unique"):
        await _insert_weather_param(conn)


async def test_weather_param_same_key_other_model_ok(conn):
    await _insert_weather_param(conn, model_version="SIMPLE_RULE")
    await _insert_weather_param(conn, model_version="TOWNSIN_KWON_ALPHA")


# --- 활성-유니크의 「활성 행끼리만」 (054 → 067, #2104) ---


async def _insert_regulation_year(conn, year=1900, is_active=1, source_ref="TEST"):
    # [#127] 정본에 없는 연도(1900)를 쓴다 — seed의 2023~2030과 키가 겹치지 않게.
    await conn.execute(
        text(
            "INSERT INTO regulation_year "
            '("year", z_factor_percent, effective_from, source_ref, version, is_active) '
            "VALUES (:y, 0, '1900-01-01', :src, '1.0', :act)"
        ),
        {"y": year, "src": source_ref, "act": is_active},
    )


async def _insert_refline_versioned(conn, is_active=1, source_ref="TEST"):
    await conn.execute(
        text(
            "INSERT INTO cii_reference_line "
            "(ship_type, condition_expr, capacity_rule, a_raw, a_decimal, c, source_ref, "
            "version, is_active) "
            "VALUES ('BULK_CARRIER', '__test__', 'DWT', '4745E3', '4745000', '0.622', :src, "
            "'1.0', :act)"
        ),
        {"src": source_ref, "act": is_active},
    )


async def _insert_boundary_versioned(conn, is_active=1, source_ref="TEST"):
    await conn.execute(
        text(
            "INSERT INTO cii_rating_boundary "
            "(ship_type, condition_expr, capacity_basis, d1, d2, d3, d4, source_ref, "
            "version, is_active) "
            "VALUES ('BULK_CARRIER', '__test__', 'DWT', '0.86', '0.94', '1.06', '1.18', :src, "
            "'1.0', :act)"
        ),
        {"src": source_ref, "act": is_active},
    )


#: (테이블, 같은 키 행을 넣는 헬퍼, 검사 행만 고르는 WHERE) — `054`가 트리거를 건 세 표.
_ACTIVE_UNIQUE_TABLES = {
    "regulation_year": (_insert_regulation_year, '"year" = 1900'),
    "cii_reference_line": (_insert_refline_versioned, "condition_expr = '__test__'"),
    "cii_rating_boundary": (_insert_boundary_versioned, "condition_expr = '__test__'"),
}

_tables = pytest.mark.parametrize("table", sorted(_ACTIVE_UNIQUE_TABLES))


async def test_regulation_year_active_duplicate_is_rejected(conn):
    # 054 — `uq_regulation_year_year`를 뺀 자리의 활성-유니크. 두 기준선 표와 같은 계약.
    await _insert_regulation_year(conn)
    with pytest.raises(IntegrityError, match="trg_regulation_year_active_unique"):
        await _insert_regulation_year(conn)


@_tables
async def test_inactive_row_insert_passes_with_active_present(conn, table):
    """활성 행이 있는 키에 **이행 행**(is_active = 0)을 넣을 수 있다 (#2104 · 067).

    `054`의 조건은 `new.is_active`를 보지 않아 활성 행이 하나라도 있으면 비활성 행 INSERT까지
    거부했다 — 「활성 행끼리만 유일」(`DB_SCHEMA §2.10`)이 아니었다.
    """
    insert, where = _ACTIVE_UNIQUE_TABLES[table]
    await insert(conn)
    await insert(conn, is_active=0)
    count = (
        await conn.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"))  # noqa: S608
    ).scalar_one()
    assert count == 2


@_tables
async def test_inactive_row_update_passes_with_active_present(conn, table):
    """활성 행이 있는 키의 **이행 행**은 다른 열을 고칠 수 있다 (#2104 · 067).

    `BEFORE UPDATE` 트리거도 같은 조건이라 `054`에서는 이행 행의 출처 메모 하나도 못 고쳤다.
    """
    insert, where = _ACTIVE_UNIQUE_TABLES[table]
    await insert(conn)
    await insert(conn, is_active=0)
    await conn.execute(
        text(f"UPDATE {table} SET source_ref = 'TEST-FIXED' WHERE {where} AND is_active = 0")  # noqa: S608
    )
    fixed = (
        await conn.execute(
            text(f"SELECT count(*) FROM {table} WHERE {where} AND source_ref = 'TEST-FIXED'")  # noqa: S608
        )
    ).scalar_one()
    assert fixed == 1


@_tables
async def test_reactivating_history_row_beside_active_is_rejected(conn, table):
    """이행 행을 `is_active = 1`로 되살리면 활성 행이 둘이 되므로 거부된다 (`047` ⑥과 같은 판단).

    `067`이 넓힌 것은 **비활성 행의 쓰기**뿐이다 — 활성 행 둘은 INSERT든 UPDATE든 여전히
    막혀야 계산이 읽는 활성 행이 하나로 남는다.
    """
    insert, where = _ACTIVE_UNIQUE_TABLES[table]
    await insert(conn)
    await insert(conn, is_active=0)
    with pytest.raises(IntegrityError, match=f"trg_{table}_active_unique_upd"):
        await conn.execute(
            text(f"UPDATE {table} SET is_active = 1 WHERE {where} AND is_active = 0")  # noqa: S608
        )


def test_067_copies_054_trigger_targets():
    """`067`이 사본으로 가진 (표, 키)·이름 규칙이 `054` 원본과 같다 (`066` 검토 지적과 같은 잠금).

    `alembic/versions`는 패키지가 아니라 `067`이 `054`를 import할 수 없어 사본을 갖는다. 사본이
    원본과 어긋나면 없는 이름을 교체하려다 트리거가 **늘어나거나** 옛 조건이 남는다.
    """
    import importlib.util
    from pathlib import Path

    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"

    def load(pattern: str):
        hits = sorted(versions.glob(pattern))
        assert len(hits) == 1, f"{pattern}: {[h.name for h in hits]}"
        spec = importlib.util.spec_from_file_location(f"migration_{hits[0].stem}", hits[0])
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    m054 = load("054_*.py")
    m067 = load("067_*.py")
    original = tuple((table, keys) for table, _index, keys in m054.ACTIVE_UNIQUE)
    assert original == m067.ACTIVE_UNIQUE
    assert m067._EVENTS == m054._EVENTS
    for table, _keys in m067.ACTIVE_UNIQUE:
        for event in m067._EVENTS:
            assert m067._trigger_name(table, event) == m054._trigger_name(table, event)
    # 되돌리는 조건은 `054`가 건 것과 글자 그대로 같아야 한다 — 왕복 뒤 정의 대조(`#1861`).
    for table, keys in m067.ACTIVE_UNIQUE:
        assert m067._exists(table, keys) == m054._condition(table, keys)
