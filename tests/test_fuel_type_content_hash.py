"""이슈 #154 · 마이그레이션 031이 채운 ``fuel_type.content_hash`` 검증.

**이 파일의 검증이 성립하는 이유는 경로가 둘로 갈려 있기 때문이다.**

마이그레이션 031은 해시를 **리터럴**로 담는다 — 마이그레이션이 ``src/``의 해시
함수를 import하면 규약이 바뀔 때 과거 마이그레이션의 동작이 소급 변경되기 때문이다
(PR #147 구현 결정 2 · 017이 세운 원칙). 이 테스트는 반대로 **``src/``의 살아 있는
규약으로 재계산**해 DB 값과 대조한다. 두 경로가 독립적이라 대조가 실질적인 검증이
된다 — 누군가 ``canonical_json``이나 ``_decimal_to_canonical_str``을 바꾸면 여기서
깨져 드리프트가 드러난다.

규칙은 ``DB_SCHEMA`` §8.3.1이 소유한다. 요지는 **행 단위** · 대상 필드 ``{code, cf}``
(``TECH_SPEC`` §5.2.1의 ``parameters_used.fuel_types[]`` 원소 스키마와 동일)다.

downgrade로 NULL이 복원되는지는 전역 스키마를 변형하므로 test_zz_roundtrip.py가
검증한다 (#82의 격리 정책 — 017 seed의 downgrade 검증과 같은 자리).
"""

from decimal import Decimal

from sqlalchemy import text

from cii_platform.calc.hash import canonical_json, compute_parameter_hash

# 컬럼 폭 VARCHAR(71) = "sha256:"(7) + hex(64). 컬럼이 이 규약을 전제하고 설계됐다.
EXPECTED_HASH_LENGTH = 71


async def test_all_rows_have_content_hash(conn):
    """8행 전부 채워졌다 — 031 이전의 NULL 상태가 아니다."""
    nulls = (
        await conn.execute(text("SELECT COUNT(*) FROM fuel_type WHERE content_hash IS NULL"))
    ).scalar_one()
    assert nulls == 0

    total = (await conn.execute(text("SELECT COUNT(*) FROM fuel_type"))).scalar_one()
    assert total == 8


async def test_content_hash_matches_live_convention(conn):
    """DB 값이 ``src/`` 규약으로 재계산한 값과 일치한다 (DB_SCHEMA §8.3.1).

    **이것이 이 파일의 핵심 단언이다.** 031의 리터럴과 살아 있는 해시 함수가
    갈라지면 여기서 잡힌다.
    """
    rows = (await conn.execute(text("SELECT code, cf, content_hash FROM fuel_type"))).all()
    assert len(rows) == 8

    for row in rows:
        # §8.3.1 대상 필드 — code와 cf만. version·source_ref·display_name은 들어가지 않는다.
        expected = compute_parameter_hash({"code": row.code, "cf": Decimal(row.cf)})
        assert row.content_hash == expected, (
            f"{row.code}: DB={row.content_hash} != 재계산={expected}. "
            "031의 리터럴과 src/ 규약이 갈라졌다 — DB_SCHEMA §8.3.1 확인 필요."
        )


async def test_content_hash_format(conn):
    """접두사와 길이가 컬럼 폭 규약과 맞는다."""
    hashes = (await conn.execute(text("SELECT content_hash FROM fuel_type"))).scalars().all()
    for h in hashes:
        assert h.startswith("sha256:")
        assert len(h) == EXPECTED_HASH_LENGTH


async def test_content_hash_is_unique_per_row(conn):
    """행마다 다른 값이다 — 집합 해시였다면 8행이 같은 값을 가졌을 것이다.

    §8.3.1이 「행 단위」를 택한 것을 코드로 고정한다. 8종의 CF가 서로 다르므로
    (3.206 · 3.151 · 3.114 · 3.000 · 3.030 · 2.750 · 1.375 · 1.913) 해시도 전부
    달라야 한다.
    """
    distinct = (
        await conn.execute(text("SELECT COUNT(DISTINCT content_hash) FROM fuel_type"))
    ).scalar_one()
    assert distinct == 8


async def test_canonical_json_shape():
    """canonical 직렬화가 §8.3.1이 적은 모양 그대로다 (DB 불필요).

    키 정렬(``cf`` < ``code``)·공백 없음·Decimal 문자열화·trailing zero 제거를
    한 번에 고정한다. §8.3.1 본문의 예시와 같은 문자열이어야 한다.
    """
    assert canonical_json({"code": "HFO", "cf": Decimal("3.114000")}) == (
        '{"cf":"3.114","code":"HFO"}'
    )

    # 3.000000 → "3". normalize()가 정수로 펴는 것은 [ORACLE-C-2]가 정한 동작이며,
    # 같은 값이 표기에 따라 다른 해시를 내지 않게 하는 것이 그 규칙의 목적이다.
    assert canonical_json({"code": "LPG_PROPANE", "cf": Decimal("3.000000")}) == (
        '{"cf":"3","code":"LPG_PROPANE"}'
    )


async def test_hash_changes_when_cf_changes():
    """CF가 바뀌면 해시가 바뀐다 — 이 컬럼의 존재 이유를 고정한다.

    §8.3.1이 잡으려는 것은 ``version`` 갱신 없이 ``cf``만 UPDATE되는 드리프트다.
    """
    before = compute_parameter_hash({"code": "HFO", "cf": Decimal("3.114000")})
    after = compute_parameter_hash({"code": "HFO", "cf": Decimal("3.115000")})
    assert before != after


async def test_hash_ignores_representation_of_same_value():
    """같은 값의 다른 표기는 같은 해시를 낸다 ([ORACLE-C-2]).

    NUMERIC(10,6)에서 읽으면 ``3.114000``이지만 정본 표기는 ``3.114``다. 표기 차이로
    해시가 갈리면 이 컬럼은 값 변경이 아니라 저장 형식을 추적하게 된다.
    """
    assert compute_parameter_hash({"code": "HFO", "cf": Decimal("3.114000")}) == (
        compute_parameter_hash({"code": "HFO", "cf": Decimal("3.114")})
    )
