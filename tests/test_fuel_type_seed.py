"""이슈 #83 fuel_type CF seed 마이그레이션(017) 검증.

**정본 값은 이 파일에 독립 전사한다.** 017의 ``SEED_FUEL_TYPES``를 import해서 대조하면
비교가 항상 참이 되어 검증이 무의미해진다. DB_SCHEMA.md §3.2 표를 사람이 다시 옮겨
적고 DB 조회 결과와 맞춰야 전사 오류를 실제로 잡는다 (#33이 ``a_raw``/``a_decimal``에
쓴 것과 같은 기법 — tests/test_seed_data.py 참조).

``COUNT(*) = 8``을 단언할 수 있는 근거: #83 이후 저장소에서 ``fuel_type``에 행을
커밋하는 지점이 없다. 유일한 삽입 지점이던 test_voyage_migrations.py의
``_insert_fuel_type`` 헬퍼는 seed와 ``uq_fuel_type_code``가 충돌하여 이 이슈에서
제거했고, ``conn`` fixture는 함수 단위 트랜잭션을 롤백하며, downgrade로 스키마를
변형하는 테스트(test_zz_roundtrip.py)는 ``_restore_to_head()``로 head를 복원한다.

downgrade 시 8행이 지워지는지는 전역 스키마를 변형하므로 test_zz_roundtrip.py가
검증한다 (#82의 격리 정책).
"""

from decimal import Decimal

from sqlalchemy import text

# --- 정본 독립 전사 (DB_SCHEMA.md §3.2) -----------------------------------------
# | code | display_name | cf | source_ref |
# source_ref는 "값이 인쇄된 문서"를 적는다 — CF 값표는 MEPC.364(79) §2.2.1에 있다
# (§3.2 각주 [#87 정정] · AGENTS.md §2.2). MEPC.352(78) G1에는 CF 표가 없다.
EXPECTED_SOURCE_REF = "MEPC.364(79)"

EXPECTED_FUEL_TYPES: tuple[tuple[str, str, Decimal], ...] = (
    ("DIESEL_GAS_OIL", "Diesel/Gas Oil", Decimal("3.206000")),
    ("LFO", "Light Fuel Oil", Decimal("3.151000")),
    ("HFO", "Heavy Fuel Oil", Decimal("3.114000")),
    ("LPG_PROPANE", "LPG Propane", Decimal("3.000000")),
    ("LPG_BUTANE", "LPG Butane", Decimal("3.030000")),
    ("LNG", "Liquefied Natural Gas", Decimal("2.750000")),
    ("METHANOL", "Methanol", Decimal("1.375000")),
    ("ETHANOL", "Ethanol", Decimal("1.913000")),
)


async def test_seed_row_count(conn):
    """upgrade head 후 fuel_type이 정확히 8행이다 (이슈 #83 완료 기준)."""
    count = await conn.scalar(text("SELECT count(*) FROM fuel_type"))
    assert count == len(EXPECTED_FUEL_TYPES) == 8


async def test_seed_values_match_db_schema(conn):
    """code · display_name · cf가 정본 §3.2와 전건 일치한다 — 오전사 검출."""
    rows = (
        await conn.execute(text("SELECT code, display_name, cf FROM fuel_type ORDER BY code"))
    ).all()
    actual = [(row.code, row.display_name, row.cf) for row in rows]
    expected = sorted(EXPECTED_FUEL_TYPES, key=lambda row: row[0])
    assert actual == expected


async def test_seed_source_ref_is_value_printed_document(conn):
    """8행 모두 source_ref가 MEPC.364(79)다 (§3.2 각주 · #87/#140 정정 반영).

    이슈 #83 본문의 "MEPC.352(78) G1 기준"은 정정 이전 표기다. G1에는 CF 표가 없어
    그 문서로는 값 대조 자체가 불가능하다.
    """
    refs = (await conn.execute(text("SELECT DISTINCT source_ref FROM fuel_type"))).scalars().all()
    assert refs == [EXPECTED_SOURCE_REF]


async def test_seed_column_defaults(conn):
    """명시 삽입값과 server_default 위임값이 의도대로 들어갔다 (DB_SCHEMA §2.9 · §8.3).

    content_hash는 NULL이 정상이다 — 해싱 규칙이 #42에서 확정된 뒤 별도 마이그레이션이
    채운다. effective_from은 8종 CF가 연도 스코프 없는 상시 적용값이라 NULL이다.
    """
    rows = (
        await conn.execute(
            text("SELECT unit, version, is_active, content_hash, effective_from FROM fuel_type")
        )
    ).all()
    assert len(rows) == 8
    for row in rows:
        assert row.unit == "tCO₂/tFuel"
        assert row.version == "1.0"
        assert row.is_active is True
        assert row.content_hash is None
        assert row.effective_from is None
