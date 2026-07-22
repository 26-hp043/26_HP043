"""이슈 #103 파라미터 테이블 마이그레이션 검증 (010~012).

대상: cii_reference_line(010), cii_rating_boundary(011), weather_model_parameter(012).

완료 기준(이슈 #103):
- 각 테이블의 CHECK·UNIQUE 인덱스가 DB_SCHEMA §2.10~§2.12와 일치
- INSERT 정상 동작, 제약 위반 거부

주의: 마이그레이션은 스키마만 만들고 값은 넣지 않는다(seed는 #33·#35, 파서 #36 선행).
여기 테스트 값은 제약 동작 검증용 임의 값이며 정본 §3의 규제값이 아니다.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


async def _insert_refline(
    conn,
    ship_type="BULK_CARRIER",
    condition_expr="all",
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
    condition_expr="all",
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
            "INSERT INTO weather_model_parameter (model_version, key, value) "
            "VALUES (:mv, :k, '1.0')"
        ),
        {"mv": model_version, "k": key},
    )


# --- cii_reference_line (010) ---


async def test_refline_insert_ok(conn):
    await _insert_refline(conn)
    await _insert_refline(conn, ship_type="LNG_CARRIER", capacity_rule="fixed 279000")
    count = await conn.execute(text("SELECT count(*) FROM cii_reference_line"))
    assert count.scalar_one() == 2


async def test_refline_allows_zero_c(conn):
    # LNG_CARRIER DWT >= 100000은 c = 0(고정 CII_ref)이 정상 (§2.10 [Oracle 관찰]).
    await _insert_refline(conn, ship_type="LNG_CARRIER", c="0")


async def test_refline_rejects_nonpositive_a_decimal(conn):
    with pytest.raises(IntegrityError, match="chk_a_decimal_positive"):
        await _insert_refline(conn, a_decimal="0")


async def test_refline_rejects_negative_c(conn):
    with pytest.raises(IntegrityError, match="chk_c_positive"):
        await _insert_refline(conn, c="-0.1")


async def test_refline_capacity_rule_rejects_invalid(conn):
    # [M-7]: 'fixed' 뒤에 숫자만 허용.
    with pytest.raises(IntegrityError, match="chk_capacity_rule"):
        await _insert_refline(conn, capacity_rule="fixed abc")


async def test_refline_unique_rejects_duplicate(conn):
    await _insert_refline(conn)
    with pytest.raises(IntegrityError, match="idx_refline_unique"):
        await _insert_refline(conn)


# --- cii_rating_boundary (011) ---


async def test_boundary_insert_ok(conn):
    await _insert_boundary(conn)


async def test_boundary_d_order_rejects_disorder(conn):
    # [M-3]: d1 < d2 < d3 < d4 위반 (d2 < d1).
    with pytest.raises(IntegrityError, match="chk_d_order"):
        await _insert_boundary(conn, d1="0.94", d2="0.86")


async def test_boundary_unique_rejects_duplicate(conn):
    await _insert_boundary(conn)
    with pytest.raises(IntegrityError, match="idx_boundary_unique"):
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
