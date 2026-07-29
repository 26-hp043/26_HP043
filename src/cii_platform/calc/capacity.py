"""선종별 capacity 결정 규칙 (#41).

IMO G1과 G2는 서로 다른 capacity 개념을 쓴다 (TECH_SPEC §1.2.4 [EXT-P0-1]).

* **transport capacity (G1)** — attained CII의 분모 ``W = capacity × distance``에 쓴다.
  항상 선박의 실제 DWT 또는 GT이며, ``fixed`` override가 없다.
* **reference capacity (G2)** — ``CII_ref = a × Capacity^(-c)``에 쓴다.
  ``cii_reference_line.capacity_rule``에 따라 고정값을 쓸 수 있다.

둘을 혼용하면 값이 조용히 틀린다. TECH_SPEC §1.2.4의 예시대로 300,000 DWT 벌크캐리어에서
``fixed 279000``을 W에 잘못 적용하면 attained CII가 +7.5% 과대 산정된다.

**DB 접근을 하지 않는다.** 이슈 본문은 ``select_reference_line()``이 테이블을 직접 조회하도록
적고 있으나, TECH_SPEC §16.3은 ``calc`` 계층의 DB 접근을 금지한다(#100 확정). 후보 행을
인자로 받는 순수 함수로 두고, 조회는 첫 호출자 시점에 ``db/repositories``가 담당한다.

선종별 축(DWT/GT)은 PRD §3.4.3 = DB_SCHEMA §3.3 = ``db/seed.py``(20행 · 13종) 세 문서를
행 단위로 대조해 확정했다. 다만 그 대조가 보증하는 것은 **G2 기준선 표의 축**이며,
여기서 G1에도 같은 축을 쓴다고 전제한 부분은 아직 확인되지 않았다
(``tests/test_capacity_rules.py::test_capacity_axis_constants_match_seed`` 참조).
"""

import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

#: DWT를 capacity 축으로 쓰는 선종 (PRD §3.4.3, 8종).
#: 이름은 TECH_SPEC §1.2.4 코드 블록의 참조명을 그대로 따른다.
DWT_BASED_SHIP_TYPES: frozenset[str] = frozenset(
    {
        "BULK_CARRIER",
        "GAS_CARRIER",
        "TANKER",
        "CONTAINER_SHIP",
        "GENERAL_CARGO_SHIP",
        "REFRIGERATED_CARGO_CARRIER",
        "COMBINATION_CARRIER",
        "LNG_CARRIER",
    }
)

#: GT를 capacity 축으로 쓰는 선종 (PRD §3.4.3, 5종).
GT_BASED_SHIP_TYPES: frozenset[str] = frozenset(
    {
        "RO_RO_CARGO_VEHICLE",
        "RO_RO_CARGO",
        "RO_RO_PASSENGER",
        "RO_RO_PASSENGER_HSC",
        "CRUISE_PASSENGER",
    }
)

# condition_expr 문법 3종 (DB_SCHEMA §3.3 전 20행에서 확인).
#   1) "all"
#   2) "DWT >= 279000" / "GT < 30000"
#   3) "65000 <= DWT < 100000" / "30000 <= GT < 57700"
_CONDITION_ALL = "all"
_CONDITION_SIMPLE = re.compile(r"^(DWT|GT)\s*(>=|<)\s*(\d+)$")
_CONDITION_RANGE = re.compile(r"^(\d+)\s*<=\s*(DWT|GT)\s*<\s*(\d+)$")

# capacity_rule 의 fixed 형태. DB CHECK 제약 chk_capacity_rule 과 같은 패턴이다
# (DB_SCHEMA §2.10 [M-7]: capacity_rule IN ('DWT','GT') OR capacity_rule ~ '^fixed \d+$').
_CAPACITY_RULE_FIXED = re.compile(r"^fixed (\d+)$")


class _Vessel(Protocol):
    """이 모듈이 선박에서 읽는 값. ORM 모델과 테스트 더블 양쪽을 받기 위한 구조적 타입."""

    ship_type: str
    deadweight: object
    gross_tonnage: object


class _ReferenceLine(Protocol):
    """이 모듈이 기준선 행에서 읽는 값."""

    ship_type: str
    condition_expr: str
    capacity_rule: str


def capacity_axis(ship_type: str) -> str:
    """선종의 capacity 축을 ``"DWT"`` 또는 ``"GT"``로 반환한다 (PRD §3.4.3).

    어느 집합에도 없는 선종은 :class:`ValueError`로 막는다. ``vessel.ship_type``이
    ``String(50)``이고 DB에 enum 제약이 없어, 오타 선종을 조용히 DWT로 처리하면
    잘못된 CII가 산출되고도 드러나지 않는다.
    """
    if ship_type in DWT_BASED_SHIP_TYPES:
        return "DWT"
    if ship_type in GT_BASED_SHIP_TYPES:
        return "GT"
    raise ValueError(
        f"Unknown ship_type for capacity axis: {ship_type!r}. "
        f"PRD §3.4.3에 정의된 13개 선종만 지원한다."
    )


def _capacity_for_axis(vessel: _Vessel, axis: str) -> Decimal:
    """축에 해당하는 실제 capacity를 Decimal로 반환한다.

    ``Vessel.deadweight``·``gross_tonnage``는 둘 다 nullable이라 ``None``이 들어올 수
    있다. 그대로 두면 ``Decimal(str(None))``이 ``InvalidOperation``으로 터져 원인을
    알기 어려우므로 여기서 막는다.
    """
    raw = vessel.deadweight if axis == "DWT" else vessel.gross_tonnage
    if raw is None:
        raise ValueError(
            f"{'deadweight' if axis == 'DWT' else 'gross_tonnage'} is required for "
            f"ship_type {vessel.ship_type!r} ({axis} 기준) but was None"
        )
    value = Decimal(str(raw))
    if value <= 0:
        raise ValueError(
            f"{'deadweight' if axis == 'DWT' else 'gross_tonnage'} must be > 0: got {value}"
        )
    return value


def resolve_transport_capacity(vessel: _Vessel) -> Decimal:
    """G1 (transport work) capacity — 항상 실제 DWT 또는 GT (TECH_SPEC §1.2.4).

    ``fixed`` override를 적용하지 않는다. 기준선 행을 인자로 받지 않는 것도 같은
    이유이며, 이 함수는 선종만 보고 축을 정한다.
    """
    return _capacity_for_axis(vessel, capacity_axis(vessel.ship_type))


def resolve_reference_capacity(vessel: _Vessel, reference_line: _ReferenceLine) -> Decimal:
    """G2 (CII_ref) capacity — ``capacity_rule``에 따라 고정값일 수 있다 (TECH_SPEC §1.2.4).

    ``capacity_rule``이 축을 직접 지정하므로(``"DWT"`` / ``"GT"`` / ``"fixed N"``)
    선종 상수를 다시 보지 않는다.
    """
    rule = reference_line.capacity_rule
    if rule in ("DWT", "GT"):
        return _capacity_for_axis(vessel, rule)

    fixed = _CAPACITY_RULE_FIXED.match(rule)
    if fixed:
        return Decimal(fixed.group(1))

    raise ValueError(f"Unknown capacity_rule: {rule!r}")


def evaluate_condition(condition_expr: str, vessel: _Vessel) -> bool:
    """``condition_expr``이 선박에 성립하는지 판정한다 (DB_SCHEMA §3.3).

    비교에 쓰는 값은 조건식이 지정한 축(``DWT`` / ``GT``)의 실제 capacity다.

    문법 3종 중 어디에도 맞지 않으면 ``False``가 아니라 :class:`ValueError`를 낸다.
    ``False``를 반환하면 해당 행이 조용히 후보에서 빠져 "매칭 0건" 또는 "잘못된 행
    1건 매칭"으로 이어지고, 원인이 파서에 있다는 사실이 드러나지 않는다.
    """
    if condition_expr == _CONDITION_ALL:
        return True

    simple = _CONDITION_SIMPLE.match(condition_expr)
    if simple:
        axis, operator, threshold = simple.groups()
        capacity = _capacity_for_axis(vessel, axis)
        limit = Decimal(threshold)
        return capacity >= limit if operator == ">=" else capacity < limit

    ranged = _CONDITION_RANGE.match(condition_expr)
    if ranged:
        lower, axis, upper = ranged.groups()
        capacity = _capacity_for_axis(vessel, axis)
        return Decimal(lower) <= capacity < Decimal(upper)

    raise ValueError(f"Unsupported condition_expr: {condition_expr!r}")


def select_reference_line(
    vessel: _Vessel,
    reference_lines: Sequence[_ReferenceLine],
) -> _ReferenceLine:
    """선박에 해당하는 기준선 행 1건을 고른다 (TECH_SPEC §1.2.4).

    ``reference_lines``는 걸러지지 않은 전체 목록이어도 된다 — 선종 필터링을 이 함수
    안에서 수행하므로, 호출자가 "해당 선종 행만 넘겨야 한다"는 암묵 계약을 지킬 필요가
    없다.

    매칭이 0건이거나 2건 이상이면 :class:`ValueError`를 낸다. 후자는 seed의 구간이
    겹쳤다는 뜻이므로 임의로 하나를 고르지 않는다.
    """
    candidates = [line for line in reference_lines if line.ship_type == vessel.ship_type]
    if not candidates:
        raise ValueError(f"No reference line for ship_type {vessel.ship_type!r}")

    matched = [line for line in candidates if evaluate_condition(line.condition_expr, vessel)]
    if not matched:
        # 선종은 있는데 어느 구간에도 안 걸린 경우 — seed에 빈틈이 생겼다는 뜻이다.
        # 현재 seed 13종은 구간이 완전하므로 도달하지 않는다
        # (tests/test_capacity_rules.py::test_seed_intervals_are_exhaustive_and_disjoint).
        # 도달하는 날에는 이 메시지가 혼자서 원인을 말해야 하므로 capacity 값과 후보
        # 조건식을 함께 싣는다. vessel 필드를 그대로 찍기만 하고 _capacity_for_axis를
        # 다시 부르지는 않는다 — None인 축에서 새 예외가 나면 원인이 가려진다.
        exprs = ", ".join(repr(line.condition_expr) for line in candidates)
        raise ValueError(
            f"No reference line condition matched for ship_type {vessel.ship_type!r} "
            f"(DWT={vessel.deadweight}, GT={vessel.gross_tonnage}; 후보 조건 {exprs}). "
            f"seed 구간에 빈틈이 있을 수 있다."
        )
    if len(matched) > 1:
        exprs = ", ".join(repr(line.condition_expr) for line in matched)
        raise ValueError(f"Ambiguous reference line for ship_type {vessel.ship_type!r}: {exprs}")
    return matched[0]
