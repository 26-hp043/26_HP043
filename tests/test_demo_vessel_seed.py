"""이슈 #34 데모용 샘플 선박 seed 마이그레이션(018) + #347 확장(027) 검증.

**기대값은 이 파일에 독립 전사한다.** 018의 ``SEED_VESSELS``를 import해서 대조하면
비교가 항상 참이 되어 검증이 무의미해진다 (tests/test_fuel_type_seed.py와 같은 기법).

``COUNT(*) = 4``을 단언할 수 있는 근거: 저장소에서 ``vessel``에 행을 커밋하는 지점은
018(3척, DWT축)과 027(1척, GT축 #347) 뿐이다. ``conn`` fixture는 함수 단위
트랜잭션을 롤백하며, downgrade로 스키마를 변형하는 테스트(test_zz_roundtrip.py)는
``_restore_to_head()``로 head를 복원한다.

downgrade 시 행이 지워지는지는 전역 스키마를 변형하므로 test_zz_roundtrip.py가
검증한다 (#82의 격리 정책). 027의 항차·not under way 샘플 검증은
tests/test_dashboard_seed.py가 담당한다.
"""

from decimal import Decimal

import pytest
from sqlalchemy import text

# --- 기대값 독립 전사 -------------------------------------------------------------
#
# UUID는 #132 계약 코멘트에서, 실선 2척의 제원은 2026-08-07 제원 조사 회신(sty2581)에서,
# 1번 선박의 제원은 PRD §13.1 + tests/fixtures/cii/bulk_50000_hfo_2026.json에서,
# 4번 선박(GT축)은 027의 설계값(#347 · #207 잔여분)에서 각각 옮겨 적었다.

# ⚠️ ``id``는 ``uuid`` 컬럼이라 문자열 바인드를 그대로 비교할 수 없다.
# ``operator does not exist: uuid = character varying``가 난다 — PostgreSQL은 두 타입을
# 암묵 캐스팅하지 않는다. 아래 조회들은 ``CAST(:vid AS uuid)``로 명시한다.
VESSEL_ID_BULK = "00000000-0000-4000-8000-000000000001"
VESSEL_ID_CONTAINER = "00000000-0000-4000-8000-000000000002"
VESSEL_ID_GENERAL_CARGO = "00000000-0000-4000-8000-000000000003"
VESSEL_ID_RO_RO = "00000000-0000-4000-8000-000000000004"

# (id, imo_number, name, ship_type, gross_tonnage, deadweight, hint)
EXPECTED_VESSELS: tuple[tuple[str, str, str, str, Decimal | None, Decimal | None, bool], ...] = (
    (
        VESSEL_ID_BULK,
        "0000012",
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
    (
        VESSEL_ID_RO_RO,
        "0000024",
        "샘플 로로 여객선 (25,000 GT)",
        "RO_RO_PASSENGER",
        Decimal("25000.00"),
        None,
        True,
    ),
)

# GT >= 5000 이면 공식 CII 적용 대상 (PRD §7 · DB_SCHEMA §2.1).
CII_APPLICABLE_GT_THRESHOLD = Decimal("5000")


async def test_seed_row_count(conn):
    """upgrade head 후 vessel이 정확히 4행이다 (018 DWT축 3척 + 027 GT축 1척)."""
    count = await conn.scalar(text("SELECT count(*) FROM vessel"))
    assert count == len(EXPECTED_VESSELS) == 4


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
    assert ids == [
        VESSEL_ID_BULK,
        VESSEL_ID_CONTAINER,
        VESSEL_ID_GENERAL_CARGO,
        VESSEL_ID_RO_RO,
    ]


async def test_frontend_reference_vessel_exists(conn):
    """계약 fixture(#132)가 쓰는 선박이 DB에 있다.

    이 단언이 깨지면 실 API 전환 시 **첫 요청이 404로 떨어진다.**
    """
    row = (
        await conn.execute(
            text(
                "SELECT ship_type, deadweight FROM vessel WHERE id = CAST(:vid AS uuid)"
            ).bindparams(vid=VESSEL_ID_BULK)
        )
    ).one_or_none()
    assert row is not None
    assert row.ship_type == "BULK_CARRIER"
    assert row.deadweight == Decimal("50000.00")


async def test_default_fuel_type_is_null(conn):
    """4척 모두 ``default_fuel_type``이 NULL이다.

    연료 종류는 화면에서 사용자가 고르는 것으로 확정됐다(2026-08-07).
    값을 넣으면 ``fk_vessel_default_fuel_type``이 걸려 **017의 downgrade가 막힌다**
    (PR #147 검증 3a). NULL로 두는 것이 그 성질을 유지한다. 027의 4번 선박도 같은
    이유로 NULL이다.
    """
    count = await conn.scalar(
        text("SELECT count(*) FROM vessel WHERE default_fuel_type IS NOT NULL")
    )
    assert count == 0


async def test_bulk_reference_specs_match_the_canonical_fixture(conn):
    """샘플 벌크선의 기준 제원이 정본 픽스처에서 역산한 값과 같다 (#587).

    두 값은 지어낸 것이 아니라 ``tests/fixtures/cii/bulk_50000_hfo_2026.json``에서
    ``TECH_SPEC §4.1`` 식으로 역산한 것이다. 픽스처가 바뀌면 이 단언이 함께
    갱신을 강제한다 — 그러지 않으면 **시드와 계약 픽스처가 조용히 갈린다.**

        distance 1,000nm · speed 12.0kn · fuel 80.0t · weather NONE
        v = v_ref 이면 speed_factor = 1 이므로
        base_foc_per_day = 80.0 × 12.0 × 24 / 1,000 = 23.04
    """
    row = (
        await conn.execute(
            text(
                "SELECT reference_speed_kn, reference_daily_foc_ton FROM vessel "
                "WHERE id = CAST(:vid AS uuid)"
            ).bindparams(vid=VESSEL_ID_BULK)
        )
    ).one()
    assert row.reference_speed_kn == Decimal("12.00")
    assert row.reference_daily_foc_ton == Decimal("23.04")


async def test_real_vessels_have_no_daily_foc(conn):
    """실존 선박 2척의 ``reference_daily_foc_ton``은 NULL이다 (#587).

    일일 연료소모량은 **선사 내부 운항 데이터**라 공개 자료로 확보할 수 없다.
    2026-08-07·2026-08-22 두 차례 제원 조사 회신(조사: ``sty2581``) 모두
    「알 수 없음」이었고, 출처가 전부 회사 홈페이지였다.

    **임의값을 넣으면 실존 선박에 대한 허위 제원이 된다.** ``TECH_SPEC``의 시계
    경계 처리표도 *「기본값을 넣으면 화면이 근거 없는 연료를 표시한다」*로 같은
    판단을 적고 있다. 회신이 오면 이 단언이 함께 갱신을 강제한다.
    """
    count = await conn.scalar(
        text(
            "SELECT count(*) FROM vessel "
            "WHERE imo_number IN ('9448839', '9633862') "
            "AND reference_daily_foc_ton IS NOT NULL"
        )
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
    """4척 모두 ``chk_imo_format``(7자리 숫자)을 만족한다.

    DB가 이미 강제하므로 INSERT가 성공한 것 자체가 증거지만, **합성 IMO가 실선
    대역과 겹치지 않는다는 것**은 별도 성질이라 함께 확인한다. 합성은 2개다 —
    1번(벌크선, 018)과 4번(로로 여객선, 027).
    """
    rows = (await conn.execute(text("SELECT imo_number FROM vessel ORDER BY id"))).all()
    for row in rows:
        assert len(row.imo_number) == 7
        assert row.imo_number.isdigit()

    # 합성 IMO 2개(0000012·0000024)는 실선 대역(5,000,000~)과 겹치지 않는 0 시작이며,
    # **IMO 체크섬도 만족한다**(#525). 종전 0000001·0000002는 대역만 지키고 체크섬은
    # 고려하지 않아, 시연에서 「샘플이 규격을 안 지킨다」는 지적이 가능했다.
    synthetics = [row.imo_number for row in rows if row.imo_number.startswith("0")]
    assert synthetics == ["0000012", "0000024"], "합성 IMO는 실선 대역과 겹치지 않아야 한다"


async def test_vessel_axes_are_dwt_and_gt(conn):
    """DWT축 3척 + GT축 1척 — **#347이 #207 잔여분(GT축 선박)을 채웠다는 고정.**

    종전 ``test_all_seeded_vessels_are_dwt_axis``는 GT축 선박 부재를 고정하는
    테스트였으며, 이 갱신이 곧 이슈의 완료 시점이었다(이슈 #347 체크리스트).
    """
    from cii_platform.calc.capacity import capacity_axis

    rows = (await conn.execute(text("SELECT id::text, ship_type FROM vessel ORDER BY id"))).all()
    axes = {row[0]: capacity_axis(row.ship_type) for row in rows}
    assert axes == {
        VESSEL_ID_BULK: "DWT",
        VESSEL_ID_CONTAINER: "DWT",
        VESSEL_ID_GENERAL_CARGO: "DWT",
        VESSEL_ID_RO_RO: "GT",
    }


@pytest.mark.parametrize(
    "vessel_id",
    [VESSEL_ID_BULK, VESSEL_ID_CONTAINER, VESSEL_ID_GENERAL_CARGO, VESSEL_ID_RO_RO],
)
async def test_seeded_ship_types_have_reference_lines(conn, vessel_id):
    """네 선종 모두 ``cii_reference_line``에 대응 행이 있다.

    없으면 ``select_reference_line()``이 ``ValueError``를 던져 **계산 API가 그 선박에
    대해 항상 실패한다.** 선박만 넣고 기준선을 확인하지 않으면 드러나지 않는 결함이다.

    규제 파라미터는 마이그레이션이 아니라 ``scripts/seed.py``가 넣는다(#127이 승격을
    다룬다). 적재 전이면 이 테스트는 건너뛴다 — seed 미실행은 이 이슈의 결함이 아니다.
    """
    ship_type = await conn.scalar(
        text("SELECT ship_type FROM vessel WHERE id = CAST(:vid AS uuid)").bindparams(vid=vessel_id)
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


def imo_checksum_ok(imo: str) -> bool:
    """IMO 체크섬 (#525).

    앞 6자리에 ``7·6·5·4·3·2``를 곱한 합의 **1의 자리**가 7번째 자리와 같아야 한다.
    """
    digits = [int(c) for c in imo]
    return sum(digits[i] * (7 - i) for i in range(6)) % 10 == digits[6]


def test_imo_checksum_계산이_맞다() -> None:
    """검산 함수 자신을 먼저 잠근다 — 틀리면 아래 검사가 조용히 통과한다.

    실선 2척(제원 조사 회신분)이 참이고, 종전 합성값 2개가 거짓이어야 한다.
    """
    assert imo_checksum_ok("9448839")  # STAR SKIPPER
    assert imo_checksum_ok("9633862")  # DONGJIN ENDURANCE
    assert not imo_checksum_ok("0000001")  # 종전 합성값
    assert not imo_checksum_ok("0000002")  # 종전 합성값


def test_모든_데모_선박의_imo가_체크섬을_만족한다() -> None:
    """`#525`의 완료 기준이다.

    합성값이라도 규격은 지킨다 — 시연·심사에서 「샘플이 IMO 규격을 안 지킨다」는
    지적을 받을 이유가 없다. 0으로 시작하면서 체크섬이 맞는 7자리는 10만 개 있어
    **「실선 대역 밖」과 「체크섬 유효」를 함께 만족할 수 있다.**
    """
    # 소스를 import하지 않는다 — 이 파일의 기대값은 **독립 전사**다(파일 머리 주석).
    # demo_seed를 읽어 검사하면 「소스가 소스와 같다」를 확인하게 된다.
    imos = [row[1] for row in EXPECTED_VESSELS]
    assert imos, "EXPECTED_VESSELS가 비어 있다 — 아래 검사가 공허하게 참이 된다"

    invalid = [imo for imo in imos if not imo_checksum_ok(imo)]

    assert invalid == [], (
        f"체크섬을 만족하지 않는 IMO: {invalid}. "
        "합성값이라면 0으로 시작하면서 체크섬이 맞는 값을 고르세요 (#525)."
    )


async def test_ro_ro_daily_foc_is_derived_from_its_own_voyage(conn):
    """샘플 로로의 ``reference_daily_foc_ton``은 **역산값**이다 (#587).

    벌크선(`23.04`)과 같은 식으로 이 배의 2026 항차에서 냈다.

        62.0t × 18.0kn × 24h ÷ 450nm = 59.52

    **지어낸 값이 아니다** — 시드가 이미 갖고 있는 항차와 앞뒤가 맞는 유일한 값이다.
    항차를 고치면 이 단언이 함께 갱신을 강제한다.
    """
    from cii_platform.db.demo_seed import VESSEL_ID_RO_RO

    row = (
        await conn.execute(
            text(
                "SELECT v.reference_speed_kn, v.reference_daily_foc_ton, "
                "       y.planned_distance_nm, f.planned_fuel_ton "
                "FROM vessel v "
                "JOIN voyage y ON y.vessel_id = v.id AND y.voyage_no = '2026-01' "
                "JOIN voyage_fuel_use f ON f.voyage_id = y.id "
                "WHERE v.id = CAST(:vid AS uuid)"
            ).bindparams(vid=VESSEL_ID_RO_RO)
        )
    ).one()

    assert row.reference_daily_foc_ton == Decimal("59.52")
    # 역산이 실제로 맞는지 항차에서 다시 낸다 — 상수를 전사만 하면 항차가 바뀌어도
    # 통과한다.
    derived = row.planned_fuel_ton * row.reference_speed_kn * 24 / row.planned_distance_nm
    assert derived == Decimal("59.52")


async def test_seeded_specs_are_actually_in_the_database(conn):
    """시드가 값을 갖는 제원이 **DB에도 있다** (#587).

    ``demo_seed``는 ``ON CONFLICT DO NOTHING``이라 **기존 행을 갱신하지 않는다.**
    시드에 제원을 새로 채워도 볼륨을 유지한 환경에는 들어가지 않고, 그 상태는
    오류가 아니라 **화면의 `—`로만** 드러난다 — `#587`이 보고한 증상이다.

    ``demo_up.sh``가 같은 함수로 시연 전에 경고한다.
    """
    from cii_platform.db.demo_seed import missing_seeded_specs

    drifted = await missing_seeded_specs(conn)

    assert drifted == [], (
        "시드에는 있는데 테스트 DB에 없는 제원입니다: "
        + " · ".join(f"{name}.{column}" for name, column in drifted)
        + "\n  demo_seed는 ON CONFLICT DO NOTHING이라 기존 행을 갱신하지 않습니다."
        + "\n  테스트 DB를 다시 만드십시오: DROP DATABASE cii_test; CREATE DATABASE cii_test;"
    )


async def test_missing_spec_detector_actually_detects(conn):
    """감지기가 **정말 잡는지** 본다.

    위 단언만 두면 감지기가 늘 빈 목록을 돌려줘도 통과한다. 값을 지워 확인한다
    (테스트 트랜잭션은 롤백되므로 DB에 남지 않는다).
    """
    from cii_platform.db.demo_seed import VESSEL_ID_RO_RO, missing_seeded_specs

    await conn.execute(
        text(
            "UPDATE vessel SET reference_daily_foc_ton = NULL WHERE id = CAST(:vid AS uuid)"
        ).bindparams(vid=VESSEL_ID_RO_RO)
    )

    drifted = await missing_seeded_specs(conn)

    assert ("샘플 로로 여객선 (25,000 GT)", "reference_daily_foc_ton") in drifted


async def test_detector_ignores_specs_the_seed_leaves_empty(conn):
    """시드가 **비워 둔** 값은 어긋남이 아니다.

    실존 2척의 ``reference_daily_foc_ton``은 회신 대기라 NULL이 정상이다. 감지기가
    그것까지 잡으면 **시연 때마다 무시해야 하는 경고**가 되고, 무시하는 경고는 진짜
    경고도 함께 묻는다.
    """
    from cii_platform.db.demo_seed import missing_seeded_specs

    drifted = await missing_seeded_specs(conn)
    names = {name for name, _ in drifted}

    assert "STAR SKIPPER" not in names
    assert "DONGJIN ENDURANCE" not in names
