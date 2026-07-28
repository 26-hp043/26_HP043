"""Capacity 규칙 단위 테스트 (#41).

TEST_PLAN §2.3 [EXT-P0-1] 중 본 이슈 범위: UT-CAP-001~005 · 007 · 009 · 010.
(006은 ``CII_ref = 9.827`` 검증, 008은 W 오차율 검증이라 #38의 CII_ref 계산이 필요하다)

추가분: seed 축 대조 · 구간 완전성 · 경계값 6개 · 파서 문법.
"""

from decimal import Decimal

import pytest

from cii_platform.calc.capacity import (
    DWT_BASED_SHIP_TYPES,
    GT_BASED_SHIP_TYPES,
    capacity_axis,
    evaluate_condition,
    resolve_reference_capacity,
    resolve_transport_capacity,
    select_reference_line,
)
from cii_platform.db.seed import SEED_REFERENCE_LINES


class FakeVessel:
    """선박 더블. ORM ``Vessel``은 이 세 필드만 이 모듈에 노출한다."""

    def __init__(self, ship_type: str, *, deadweight=None, gross_tonnage=None):
        self.ship_type = ship_type
        self.deadweight = deadweight
        self.gross_tonnage = gross_tonnage


def get_reference_line(ship_type: str, condition_expr: str):
    """TEST_PLAN §2.3 예제의 픽스처 헬퍼 — 특정 행을 조건식으로 집어온다.

    계산 함수가 아니라 테스트 편의 함수이므로 ``calc``에 두지 않는다.
    """
    for line in SEED_REFERENCE_LINES:
        if line.ship_type == ship_type and line.condition_expr == condition_expr:
            return line
    raise AssertionError(f"seed에 없는 행: {ship_type} / {condition_expr}")


# --- TEST_PLAN §2.3 UT-CAP ------------------------------------------------------


def test_ut_cap_001_002_transport_and_reference_differ_for_large_bulk():
    """UT-CAP-001 · 002 — 벌크 300k: transport=실제 DWT, reference=fixed 279k.

    본 이슈의 목적이 두 capacity의 분리이므로 한 테스트에서 함께 확인한다.
    함수를 따로 검증하면 둘을 혼용하는 실수가 드러나지 않는다.
    """
    vessel = FakeVessel("BULK_CARRIER", deadweight=300000)
    ref_line = select_reference_line(vessel, SEED_REFERENCE_LINES)

    assert ref_line.condition_expr == "DWT >= 279000"
    assert ref_line.capacity_rule == "fixed 279000"
    assert resolve_transport_capacity(vessel) == Decimal("300000")
    assert resolve_reference_capacity(vessel, ref_line) == Decimal("279000")


def test_ut_cap_003_small_bulk_uses_same_capacity_for_both():
    """UT-CAP-003 — 벌크 < 279k: transport = reference = 실제 DWT."""
    vessel = FakeVessel("BULK_CARRIER", deadweight=50000)
    ref_line = select_reference_line(vessel, SEED_REFERENCE_LINES)

    assert ref_line.capacity_rule == "DWT"
    assert resolve_transport_capacity(vessel) == Decimal("50000")
    assert resolve_reference_capacity(vessel, ref_line) == Decimal("50000")


def test_ut_cap_004_005_small_lng():
    """UT-CAP-004 · 005 — LNG < 65k: transport=실제 DWT, reference=fixed 65k."""
    vessel = FakeVessel("LNG_CARRIER", deadweight=50000)
    ref_line = select_reference_line(vessel, SEED_REFERENCE_LINES)

    assert ref_line.capacity_rule == "fixed 65000"
    assert resolve_transport_capacity(vessel) == Decimal("50000")
    assert resolve_reference_capacity(vessel, ref_line) == Decimal("65000")


def test_ut_cap_007_roro_vehicle_uses_fixed_gt():
    """UT-CAP-007 — Ro-Ro Vehicle GT ≥ 57.7k: reference = fixed 57700."""
    vessel = FakeVessel("RO_RO_CARGO_VEHICLE", gross_tonnage=70000)
    ref_line = select_reference_line(vessel, SEED_REFERENCE_LINES)

    assert ref_line.capacity_rule == "fixed 57700"
    assert resolve_transport_capacity(vessel) == Decimal("70000")
    assert resolve_reference_capacity(vessel, ref_line) == Decimal("57700")


def test_ut_cap_009_exact_boundary_279000_uses_fixed():
    """UT-CAP-009 [ORACLE-S-7] — DWT=279,000은 'DWT >= 279000'을 만족한다."""
    vessel = FakeVessel("BULK_CARRIER", deadweight=279000)
    ref_line = get_reference_line("BULK_CARRIER", "DWT >= 279000")

    assert select_reference_line(vessel, SEED_REFERENCE_LINES) is ref_line
    assert resolve_transport_capacity(vessel) == Decimal("279000")
    assert resolve_reference_capacity(vessel, ref_line) == Decimal("279000")


def test_ut_cap_010_just_below_boundary_278999_uses_actual():
    """UT-CAP-010 [EXT-P1-4] — DWT=278,999는 'DWT < 279000' 행을 선택한다."""
    vessel = FakeVessel("BULK_CARRIER", deadweight=278999)
    ref_line = select_reference_line(vessel, SEED_REFERENCE_LINES)

    assert ref_line.condition_expr == "DWT < 279000"
    assert ref_line.capacity_rule == "DWT"
    assert resolve_reference_capacity(vessel, ref_line) == Decimal("278999")


# --- 축 상수 ---------------------------------------------------------------------


def test_capacity_axis_constants_match_seed():
    """상수(G1 축)가 seed(G2 축)와 어긋나지 않는지 확인한다.

    ⚠️ **이 테스트가 통과한다고 해서 G1 축이 규제상 옳다는 뜻은 아니다.**
    확인되는 것은 "G1 축을 G2 기준선 표의 축과 동일하게 놓았다"는 전제가 코드 안에서
    일관되게 유지되고 있다는 사실뿐이다. 그 전제 자체(attained CII 분모의 capacity가
    선종별로 기준선 표와 같은 축을 쓰는가)는 IMO 원문 확인이 필요한 미확인 사항이며,
    별도 확인 항목으로 관리 중이다. 확정되면 이 docstring과 상수 근거를 갱신한다.

    따라서 이 테스트의 역할은 검증이 아니라 **전제 고정(회귀 방지)** 이다.
    """
    for line in SEED_REFERENCE_LINES:
        if line.condition_expr == "all":
            seed_axis = line.capacity_rule  # 'all' 행은 capacity_rule이 곧 축이다
        else:
            seed_axis = "DWT" if "DWT" in line.condition_expr else "GT"

        assert seed_axis in ("DWT", "GT"), f"축을 알 수 없는 행: {line}"
        assert capacity_axis(line.ship_type) == seed_axis, (
            f"{line.ship_type}: 상수는 {capacity_axis(line.ship_type)}, "
            f"seed는 {seed_axis} ({line.condition_expr} / {line.capacity_rule})"
        )


def test_capacity_axis_sets_cover_seed_ship_types_without_overlap():
    """두 집합이 seed 13종을 정확히 덮고 서로 겹치지 않는지 확인한다."""
    seed_types = {line.ship_type for line in SEED_REFERENCE_LINES}

    assert seed_types == DWT_BASED_SHIP_TYPES | GT_BASED_SHIP_TYPES
    assert not (DWT_BASED_SHIP_TYPES & GT_BASED_SHIP_TYPES)
    assert len(DWT_BASED_SHIP_TYPES) == 8
    assert len(GT_BASED_SHIP_TYPES) == 5


def test_unknown_ship_type_rejected():
    """오타 선종이 조용히 DWT로 처리되지 않는다."""
    with pytest.raises(ValueError, match="Unknown ship_type"):
        capacity_axis("BULK_CARIER")
    with pytest.raises(ValueError, match="Unknown ship_type"):
        resolve_transport_capacity(FakeVessel("BULK_CARIER", deadweight=50000))


# --- seed 구간 -------------------------------------------------------------------


def test_seed_intervals_are_exhaustive_and_disjoint():
    """선종별로 capacity를 훑을 때 항상 정확히 1행만 매칭되는지 확인한다.

    seed 자체의 성질을 잠그는 회귀 방지용이며, 축 전제와는 무관하다.
    ``all`` 행과 조건부 행이 같은 선종에 공존하면 매칭이 2건이 되는데, 그것을 막는
    제약이 DB에도 코드에도 없다.
    """
    # 0은 넣지 않는다 — DB CHECK(chk_dwt_positive / chk_gt_positive)가 양수만 허용하므로
    # capacity 0은 애초에 존재할 수 없고, 입력 가드가 먼저 ValueError를 낸다.
    probes = [
        1,
        19999,
        20000,
        29999,
        30000,
        57699,
        57700,
        64999,
        65000,
        99999,
        100000,
        278999,
        279000,
        400000,
    ]
    for ship_type in {line.ship_type for line in SEED_REFERENCE_LINES}:
        axis = capacity_axis(ship_type)
        for probe in probes:
            kwargs = {"deadweight": probe} if axis == "DWT" else {"gross_tonnage": probe}
            vessel = FakeVessel(ship_type, **kwargs)
            matched = [
                line
                for line in SEED_REFERENCE_LINES
                if line.ship_type == ship_type and evaluate_condition(line.condition_expr, vessel)
            ]
            assert len(matched) == 1, f"{ship_type} @ {axis}={probe}: {len(matched)}건 매칭"


@pytest.mark.parametrize(
    ("ship_type", "boundary", "expected_at", "expected_below"),
    [
        ("GENERAL_CARGO_SHIP", 20000, "DWT >= 20000", "DWT < 20000"),
        ("RO_RO_CARGO_VEHICLE", 30000, "30000 <= GT < 57700", "GT < 30000"),
        ("RO_RO_CARGO_VEHICLE", 57700, "GT >= 57700", "30000 <= GT < 57700"),
        ("GAS_CARRIER", 65000, "DWT >= 65000", "DWT < 65000"),
        ("LNG_CARRIER", 65000, "65000 <= DWT < 100000", "DWT < 65000"),
        ("LNG_CARRIER", 100000, "DWT >= 100000", "65000 <= DWT < 100000"),
        ("BULK_CARRIER", 279000, "DWT >= 279000", "DWT < 279000"),
    ],
)
def test_boundary_values_select_expected_row(ship_type, boundary, expected_at, expected_below):
    """경계값의 정확한 값과 −1에서 어느 행이 선택되는지 확인한다.

    부등호 방향(``>=`` vs ``<``)은 IMO 표를 그대로 옮긴 것이라 off-by-one이 곧 규제
    오적용이 된다.
    """
    axis = capacity_axis(ship_type)
    field = "deadweight" if axis == "DWT" else "gross_tonnage"

    at = select_reference_line(FakeVessel(ship_type, **{field: boundary}), SEED_REFERENCE_LINES)
    below = select_reference_line(
        FakeVessel(ship_type, **{field: boundary - 1}), SEED_REFERENCE_LINES
    )

    assert at.condition_expr == expected_at
    assert below.condition_expr == expected_below


# --- condition_expr 파서 ---------------------------------------------------------


@pytest.mark.parametrize(
    ("condition_expr", "deadweight", "expected"),
    [
        ("all", 1, True),
        ("DWT >= 279000", 279000, True),
        ("DWT >= 279000", 278999, False),
        ("DWT < 279000", 278999, True),
        ("DWT < 279000", 279000, False),
        ("65000 <= DWT < 100000", 65000, True),
        ("65000 <= DWT < 100000", 99999, True),
        ("65000 <= DWT < 100000", 100000, False),
        ("65000 <= DWT < 100000", 64999, False),
    ],
)
def test_condition_grammar(condition_expr, deadweight, expected):
    """문법 3종 판정 (DB_SCHEMA §3.3)."""
    vessel = FakeVessel("BULK_CARRIER", deadweight=deadweight)
    assert evaluate_condition(condition_expr, vessel) is expected


@pytest.mark.parametrize(
    "bad",
    ["DWT > 279000", "DWT >= 279000.5", "dwt >= 279000", "DWT >= ", "279000 <= DWT", ""],
)
def test_unsupported_condition_expr_raises(bad):
    """미지 문법은 False가 아니라 ValueError. 조용히 후보에서 빠지면 원인이 숨는다."""
    vessel = FakeVessel("BULK_CARRIER", deadweight=300000)
    with pytest.raises(ValueError, match="Unsupported condition_expr"):
        evaluate_condition(bad, vessel)


# --- capacity_rule · 입력 가드 ----------------------------------------------------


def test_unknown_capacity_rule_raises():
    line = get_reference_line("BULK_CARRIER", "DWT < 279000")
    bogus = type(line)(
        ship_type=line.ship_type,
        condition_expr=line.condition_expr,
        capacity_rule="fixed",  # 숫자 없음 — DB CHECK도 거부하는 형태
        a_raw=line.a_raw,
        a_decimal=line.a_decimal,
        c=line.c,
    )
    with pytest.raises(ValueError, match="Unknown capacity_rule"):
        resolve_reference_capacity(FakeVessel("BULK_CARRIER", deadweight=50000), bogus)


@pytest.mark.parametrize(
    ("ship_type", "kwargs", "expected"),
    [
        ("BULK_CARRIER", {}, "deadweight is required"),
        ("BULK_CARRIER", {"gross_tonnage": 30000}, "deadweight is required"),
        ("RO_RO_CARGO", {}, "gross_tonnage is required"),
        ("RO_RO_CARGO", {"deadweight": 30000}, "gross_tonnage is required"),
    ],
)
def test_missing_capacity_named_in_error(ship_type, kwargs, expected):
    """nullable 컬럼이라 None이 들어올 수 있다. 어느 값이 없는지 메시지에 남긴다."""
    with pytest.raises(ValueError, match=expected):
        resolve_transport_capacity(FakeVessel(ship_type, **kwargs))


@pytest.mark.parametrize("bad", [0, -1])
def test_non_positive_capacity_rejected(bad):
    with pytest.raises(ValueError, match="must be > 0"):
        resolve_transport_capacity(FakeVessel("BULK_CARRIER", deadweight=bad))


def test_missing_reference_line_for_ship_type():
    """seed에 없는 선종이면 '매칭 0건'과 구분되는 메시지를 낸다."""
    vessel = FakeVessel("TANKER", deadweight=50000)
    with pytest.raises(ValueError, match="No reference line for ship_type"):
        select_reference_line(vessel, [])


def test_ambiguous_reference_line_rejected():
    """구간이 겹치면 임의로 하나를 고르지 않는다."""
    vessel = FakeVessel("BULK_CARRIER", deadweight=300000)
    duplicated = [
        get_reference_line("BULK_CARRIER", "DWT >= 279000"),
        get_reference_line("BULK_CARRIER", "DWT >= 279000"),
    ]
    with pytest.raises(ValueError, match="Ambiguous reference line"):
        select_reference_line(vessel, duplicated)


def test_select_reference_line_filters_ship_type_internally():
    """호출자가 미리 걸러 넘기지 않아도 된다 — seed 전체를 넘겨도 동작한다."""
    vessel = FakeVessel("CONTAINER_SHIP", deadweight=20000)
    line = select_reference_line(vessel, SEED_REFERENCE_LINES)

    assert line.ship_type == "CONTAINER_SHIP"
    assert line.condition_expr == "all"
