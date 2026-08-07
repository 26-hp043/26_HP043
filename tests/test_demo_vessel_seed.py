"""이슈 #34 데모용 샘플 선박 seed 마이그레이션(018) 검증.

**기대값은 이 파일에 독립 전사한다.** 018의 ``SEED_VESSELS``를 import해서 대조하면
비교가 항상 참이 되어 검증이 무의미해진다 (tests/test_fuel_type_seed.py와 같은 기법).

``COUNT(*) = 3``을 단언할 수 있는 근거: 저장소에서 ``vessel``에 행을 커밋하는 지점이
018 하나뿐이다. ``conn`` fixture는 함수 단위 트랜잭션을 롤백하며, downgrade로 스키마를
변형하는 테스트(test_zz_roundtrip.py)는 ``_restore_to_head()``로 head를 복원한다.

downgrade 시 3행이 지워지는지는 전역 스키마를 변형하므로 test_zz_roundtrip.py가
검증한다 (#82의 격리 정책).
"""

from decimal import Decimal

import pytest
from sqlalchemy import text

# --- 기대값 독립 전사 -------------------------------------------------------------
#
# UUID는 #132 계약 코멘트에서, 실선 2척의 제원은 2026-08-07 제원 조사 회신에서,
# 1번 선박의 제원은 PRD §13.1 + tests/fixtures/cii/bulk_50000_hfo_2026.json에서
# 각각 옮겨 적었다.

VESSEL_ID_BULK = "00000000-0000-4000-8000-000000000001"
VESSEL_ID_CONTAINER = "00000000-0000-4000-8000-000000000002"
VESSEL_ID_GENERAL_CARGO = "00000000-0000-4000-8000-000000000003"

# (id, imo_number, name, ship_type, gross_tonnage, deadweight, hint)
EXPECTED_VESSELS: tuple[tuple[str, str, str, str, Decimal | None, Decimal, bool], ...] = (
    (
        VESSEL_ID_BULK,
        "0000001",
        "샘플 벌크선 (50,000 DWT)",
        "BULK_CARRIER",
        Decimal("30000.00"),
        Decimal("50000.00"),
        True,
    ),
    (
        VESSEL_ID_CONTAINER,
        "9448839",
        "STAR SKIPPER",
        "CONTAINER_SHIP",
        None,
        Decimal("9520.00"),
        False,
    ),
    (
        VESSEL_ID_GENERAL_CARGO,
        "9633862",
        "DONGJIN ENDURANCE",
        "GENERAL_CARGO_SHIP",
        None,
        Decimal("6405.77"),
        False,
    ),
)

# GT >= 5000 이면 공식 CII 적용 대상 (PRD §7 · DB_SCHEMA §2.1).
CII_APPLICABLE_GT_THRESHOLD = Decimal("5000")


async def test_seed_row_count(conn):
    """upgrade head 후 vessel이 정확히 3행이다."""
    count = await conn.scalar(text("SELECT count(*) FROM vessel"))
    assert count == len(EXPECTED_VESSELS) == 3


async def test_seed_values_match_expected(conn):
    """전 컬럼이 기대값과 일치한다 — 오전사 검출."""
    rows = (
        await conn.execute(
            text(
                "SELECT id::text, imo_number, name, ship_type, gross_tonnage, "
                "deadweight, is_cii_applicable_hint FROM vessel ORDER BY id"
            )
        )
    ).all()
    actual = [tuple(row) for row in rows]
    expected = sorted(EXPECTED_VESSELS, key=lambda row: row[0])
    assert actual == expected


async def test_uuids_are_the_contracted_values(conn):
    """UUID가 #132 계약값과 정확히 같다.

    **이것이 이 마이그레이션의 존재 이유다.** ``vessel.id``의 server_default는
    ``gen_random_uuid()``라 명시 삽입하지 않으면 환경마다 값이 달라지고,
    프론트엔드 고정표(#134)와 입력 폼(#135)이 참조할 수 없게 된다.
    """
    ids = [
        row[0]
        for row in (await conn.execute(text("SELECT id::text FROM vessel ORDER BY id"))).all()
    ]
    assert ids == [VESSEL_ID_BULK, VESSEL_ID_CONTAINER, VESSEL_ID_GENERAL_CARGO]


async def test_frontend_reference_vessel_exists(conn):
    """프론트엔드 demo provider가 쓰는 선박이 DB에 있다.

    이 단언이 깨지면 실 API 전환 시 **첫 요청이 404로 떨어진다.**
    """
    row = (
        await conn.execute(
            text("SELECT ship_type, deadweight FROM vessel WHERE id = :vid").bindparams(
                vid=VESSEL_ID_BULK
            )
        )
    ).one_or_none()
    assert row is not None
    assert row.ship_type == "BULK_CARRIER"
    assert row.deadweight == Decimal("50000.00")


async def test_default_fuel_type_is_null(conn):
    """3척 모두 ``default_fuel_type``이 NULL이다.

    연료 종류는 화면에서 사용자가 고르는 것으로 확정됐다(2026-08-07).
    값을 넣으면 ``fk_vessel_default_fuel_type``이 걸려 **017의 downgrade가 막힌다**
    (PR #147 검증 3a). NULL로 두는 것이 그 성질을 유지한다.
    """
    count = await conn.scalar(
        text("SELECT count(*) FROM vessel WHERE default_fuel_type IS NOT NULL")
    )
    assert count == 0


async def test_cii_applicable_hint_follows_gross_tonnage(conn):
    """``is_cii_applicable_hint``가 GT 기준과 어긋나지 않는다.

    - GT가 있고 5,000 이상 → true
    - GT가 NULL → **false**. 판정 근거가 없으므로 「적용 대상이 아닐 수 있음」쪽으로 둔다

    GT 회신이 와서 컬럼을 채울 때 이 단언이 함께 갱신을 강제한다.
    """
    rows = (
        await conn.execute(text("SELECT name, gross_tonnage, is_cii_applicable_hint FROM vessel"))
    ).all()
    for row in rows:
        if row.gross_tonnage is None:
            assert row.is_cii_applicable_hint is False, f"{row.name}: GT 없음인데 hint=true"
        else:
            expected = row.gross_tonnage >= CII_APPLICABLE_GT_THRESHOLD
            assert row.is_cii_applicable_hint is expected, f"{row.name}: GT 기준 불일치"


async def test_imo_numbers_satisfy_format_constraint(conn):
    """3척 모두 ``chk_imo_format``(7자리 숫자)을 만족한다.

    DB가 이미 강제하므로 INSERT가 성공한 것 자체가 증거지만, **1번 선박의 합성 IMO가
    실선 대역과 겹치지 않는다는 것**은 별도 성질이라 함께 확인한다.
    """
    rows = (await conn.execute(text("SELECT imo_number FROM vessel ORDER BY id"))).all()
    for row in rows:
        assert len(row.imo_number) == 7
        assert row.imo_number.isdigit()

    synthetic = rows[0].imo_number
    # IMO 선박식별번호는 실제로 5,000,000 이상만 발급된다. 0으로 시작하는 값은
    # 어떤 실선과도 충돌하지 않는다.
    assert synthetic.startswith("0"), "1번 선박의 IMO는 실선과 충돌하지 않아야 한다"


async def test_all_seeded_vessels_are_dwt_axis(conn):
    """3척이 전부 DWT 축이다 — **GT 축 선박이 아직 없다는 사실을 고정한다.**

    #34 본문은 3번 선박을 ``CRUISE_PASSENGER``(GT 축)로 지정했으나 제원을 확보하지
    못했다. 이 테스트가 깨지는 시점이 곧 GT 축 선박이 들어온 시점이며, 그때
    후속 이슈를 닫으면 된다.
    """
    from cii_platform.calc.capacity import capacity_axis

    rows = (await conn.execute(text("SELECT ship_type FROM vessel"))).all()
    axes = {capacity_axis(row.ship_type) for row in rows}
    assert axes == {"DWT"}


@pytest.mark.parametrize(
    "vessel_id",
    [VESSEL_ID_BULK, VESSEL_ID_CONTAINER, VESSEL_ID_GENERAL_CARGO],
)
async def test_seeded_ship_types_have_reference_lines(conn, vessel_id):
    """세 선종 모두 ``cii_reference_line``에 대응 행이 있다.

    없으면 ``select_reference_line()``이 ``ValueError``를 던져 **계산 API가 그 선박에
    대해 항상 실패한다.** 선박만 넣고 기준선을 확인하지 않으면 드러나지 않는 결함이다.

    규제 파라미터는 마이그레이션이 아니라 ``scripts/seed.py``가 넣는다(#127이 승격을
    다룬다). 적재 전이면 이 테스트는 건너뛴다 — seed 미실행은 이 이슈의 결함이 아니다.
    """
    ship_type = await conn.scalar(
        text("SELECT ship_type FROM vessel WHERE id = :vid").bindparams(vid=vessel_id)
    )
    total = await conn.scalar(text("SELECT count(*) FROM cii_reference_line"))
    if total == 0:
        pytest.skip("규제 파라미터 seed 미적재 (scripts/seed.py) — #127 참조")

    count = await conn.scalar(
        text("SELECT count(*) FROM cii_reference_line WHERE ship_type = :st").bindparams(
            st=ship_type
        )
    )
    assert count > 0, f"{ship_type}의 기준선이 없다"
