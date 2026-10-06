"""Layer 1 Decimal 컨텍스트 계약 잠금 (#37 · #179).

TECH_SPEC §1.2.1(작업 정밀도 = 정본 자릿수 + 최소 20 · ROUND_HALF_UP)과 §5.4 7항
(Layer 1 bit-exact는 재현성 계약의 전제조건)을 지키는지 확인한다.

#179에서 계약이 하나 바뀌었다 — **작업 정밀도는 전역에 걸지 않는다.** 적용 지점은
``@layer1_context`` 하나이며, 전역 ``prec``을 넓히면 Layer 1 밖 연산까지 영향을 받는다.

핵심은 **워커 스레드에서** 단언하는 것이다. :func:`decimal.getcontext`가 thread-local
이라 메인 스레드에서만 확인하면, 지금 고치려는 결함이 그대로 재발해도 CI가 통과한다.
"""

import itertools
import threading
from datetime import UTC, datetime
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    getcontext,
    localcontext,
    setcontext,
)
from fractions import Fraction
from types import SimpleNamespace

import pytest

from cii_platform.calc.cii_engine import FuelUse, calculate_voyage_co2
from cii_platform.calc.precision import (
    LAYER1_ROUNDING,
    LAYER1_WORKING_PRECISION,
    layer1_context,
)

TRAPPED_SIGNALS = (DivisionByZero, InvalidOperation, Overflow)


def _snapshot() -> dict:
    ctx = getcontext()
    return {
        "prec": ctx.prec,
        "rounding": ctx.rounding,
        "traps": {sig.__name__: bool(ctx.traps[sig]) for sig in TRAPPED_SIGNALS},
    }


@layer1_context
def _snapshot_inside_layer1() -> dict:
    return _snapshot()


def _run_in_thread(fn):
    """워커 스레드에서 ``fn``을 실행하고 반환값을 돌려준다."""
    box = {}

    def target():
        box["value"] = fn()

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    return box["value"]


def test_layer1_context_in_worker_thread():
    """워커 스레드에서 Layer 1 컨텍스트가 prec·rounding·traps 전부 성립한다."""
    snapshot = _run_in_thread(_snapshot_inside_layer1)

    assert snapshot["prec"] == LAYER1_WORKING_PRECISION == 50
    assert snapshot["rounding"] == LAYER1_ROUNDING == ROUND_HALF_UP
    # traps는 정본이 명시하지 않은 기본값 의존이라, 누가 끄면 여기서 잡는다.
    assert snapshot["traps"] == {
        "DivisionByZero": True,
        "InvalidOperation": True,
        "Overflow": True,
    }


def test_layer1_context_overrides_clobbered_thread_context():
    """호출 스레드 컨텍스트가 교체돼 있어도 진입점에서 다시 고정된다.

    DefaultContext 설정이 닿지 않는 경로(이미 생성된 스레드, 명시적 setcontext)를 덮는
    것이 데코레이터의 존재 이유다.
    """

    def worker():
        setcontext(Context(prec=9, rounding=ROUND_HALF_EVEN))
        inside = _snapshot_inside_layer1()
        return inside, _snapshot()

    inside, after = _run_in_thread(worker)

    assert inside["prec"] == LAYER1_WORKING_PRECISION
    assert inside["rounding"] == ROUND_HALF_UP
    # 데코레이터를 벗어나면 원래 컨텍스트로 복원된다(전역 오염 없음).
    assert after["prec"] == 9
    assert after["rounding"] == ROUND_HALF_EVEN


def test_layer1_working_precision_is_not_global():
    """작업 정밀도는 전역 기본값을 오염시키지 않는다 (#179).

    종전에는 ``apply_default_context()``가 ``DefaultContext.prec``을 Layer 1 값으로
    올려 새 스레드가 그것을 상속했다. 작업 정밀도를 50으로 올리면서 그 구조를 두면
    ``calc`` import 이후의 **Layer 1 밖 Decimal 연산까지** 50이 된다.

    rounding은 표시 반올림(PRD §9.3)까지 걸리는 공통 정책이라 계속 맞춘다.
    """
    snapshot = _run_in_thread(_snapshot)

    assert snapshot["prec"] != LAYER1_WORKING_PRECISION
    assert snapshot["rounding"] == LAYER1_ROUNDING


def test_layer1_context_restores_outer_precision():
    """데코레이터를 벗어나면 바깥 정밀도가 그대로 돌아온다.

    전역을 넓히지 않으므로, 작업 정밀도가 새는 유일한 경로가 이 복원 실패다.
    """

    def worker():
        before = _snapshot()["prec"]
        _snapshot_inside_layer1()
        return before, _snapshot()["prec"]

    before, after = _run_in_thread(worker)

    assert before == after
    assert after != LAYER1_WORKING_PRECISION


def test_rounding_mode_is_observable():
    """prec만 맞추고 rounding을 놓치면 표시 반올림 지점에서 값이 갈린다.

    TECH_SPEC §1.2.1이 ROUND_HALF_UP을 지정한 근거가 "화면 표시 반올림과 일관성"이며,
    PRD §13.1 화면 표시 기대값이 정확히 이 자릿수다.
    """
    assert Decimal("4.9825").quantize(Decimal("0.001")) == Decimal("4.983")


def test_engine_result_is_stable_across_threads():
    """같은 입력이 메인 스레드와 워커 스레드에서 동일한 값을 낸다."""
    fuel_uses = [FuelUse("HFO", Decimal("80"), Decimal("3.114"))]

    def worker():
        setcontext(Context(prec=9, rounding=ROUND_HALF_EVEN))
        return calculate_voyage_co2(fuel_uses)[0]

    assert _run_in_thread(worker) == calculate_voyage_co2(fuel_uses)[0]


def test_division_by_zero_is_trapped():
    """traps 기본값 의존을 잠근다 (§1.2.5 가드가 예외를 전제로 한다)."""
    with pytest.raises(DivisionByZero):
        Decimal(1) / Decimal(0)
    with pytest.raises(InvalidOperation):
        Decimal(0) / Decimal(0)


# ── 파생값도 적용 지점 안에서 낸다 (`#1372`) ────────────────────────────────────
#
# `TECH_SPEC §1.2.1`이 *「Layer 1 값에서 새 값을 만드는 코드는 반드시 진입점 안에 둔다」*로
# 정한 자리다. 밖에서 나누면 기본 정밀도(prec=28)로 잘려 27번째 자리부터 갈린다 —
# 실측 `…012600`(밖) vs `…012581`(정본). 응답 자릿수에서는 드러나지 않으므로 **값이
# 아니라 계산 시점의 정밀도**를 본다.


def test_year_end_projection_derives_inside_the_context(monkeypatch):
    """⑶ 연말 예상의 `ratio_to_required`가 작업 정밀도 안에서 나온다 (`#1372`)."""
    from cii_platform.services import cii_current

    seen: dict[str, int] = {}

    class _Deterministic:
        attained_cii = Decimal("4.9824")
        rating = "E"
        boundaries: dict[str, Decimal] = {}

    def _spy(**_kwargs):
        seen["prec"] = getcontext().prec
        return _Deterministic()

    monkeypatch.setattr(cii_current, "project_deterministic", _spy)

    class _Context:
        transport_capacity = Decimal("50000")
        required_cii = Decimal("5.04506633249618206053073653978")
        d_vector = None

    class _Inputs:
        completed = ()
        remaining = ()

    _deterministic, ratio, _risk = cii_current._project_layer1(_Context(), _Inputs())

    assert seen["prec"] == LAYER1_WORKING_PRECISION == 50
    # 컨텍스트 안에서 나눈 값과 같아야 한다 — 밖에서 나누면 prec=28로 잘린다.
    with localcontext() as ctx:
        ctx.prec, ctx.rounding = LAYER1_WORKING_PRECISION, LAYER1_ROUNDING
        expected = _Deterministic.attained_cii / _Context.required_cii
    assert ratio == expected

    with localcontext() as ctx:
        ctx.prec, ctx.rounding = 28, LAYER1_ROUNDING
        outside = _Deterministic.attained_cii / _Context.required_cii
    assert ratio != outside, "prec=28로 계산해도 같은 값이면 이 검사는 아무것도 잠그지 않는다"


def test_days_to_target_derives_inside_the_context():
    """「D등급 진입까지 n일」의 누적면적(`attained × Dt`)이 작업 정밀도 안에서 나온다 (`#1372`)."""
    from cii_platform.services.fleet_summary import _days_to_target_arithmetic

    seen: dict[str, int] = {}

    class _Past:
        data_available = True
        total_distance_nm = Decimal("1000")

        @property
        def attained_cii(self) -> Decimal:
            # 이 속성은 곱셈 직전에 읽힌다 — 읽히는 순간의 정밀도가 곧 계산 정밀도다.
            seen["prec"] = getcontext().prec
            return Decimal("4.9")

    result = _days_to_target_arithmetic(
        attained_now=Decimal("5.0"),
        distance_now=Decimal("2000"),
        past=_Past(),
        boundary=Decimal("5.34777031244595298416258073217"),
        window_days=30,
    )

    assert seen["prec"] == LAYER1_WORKING_PRECISION == 50
    # 값 자체는 이 검사의 관심이 아니다 — 산식은 `test_fleet_summary.py`가 본다.
    assert result is not None


# ── 진행 중 항차의 연료 분배도 적용 지점 안에서 한다 (`#2097`) ──────────────────
#
# 시뮬레이션 시계가 넘기는 진행 연료는 작업 정밀도(50자리) 값이다. 그것을 유종별로
# 나누는 `_split_fuel`이 기본 컨텍스트(prec=28)에서 돌아, 단일 유종(몫 1)에서도
# `총량 − 0` 한 번으로 28자리가 됐다. 구간 CII가 전송 자릿수 경계에 놓이는 입력에서
# 그 차이가 응답에 드러난다 — 참값 `8477/1250 = 6.7816`인데 전송값이 `6.781599`였다.

_SEGMENT_INPUT = {
    "planned_distance_nm": Decimal("2300"),
    "speed_kn": Decimal("14"),
    "reference_speed_kn": Decimal("12"),
    "daily_foc_ton": Decimal("23.04"),
}
_SEGMENT_CAPACITY = Decimal("50000")
_SEGMENT_CF = Decimal("3.114")


def _segment_cii_exact(inputs: dict[str, Decimal] = _SEGMENT_INPUT) -> Fraction:
    """항차 구간 CII를 **분수로** 낸다 — 반올림·절단된 값을 입력으로 쓰지 않는다.

    ``연료 = 소모율 × (v / v_ref)³ × (거리 / v) / 24`` (`TECH_SPEC §4.1`),
    ``CII = 연료 × CF × 10⁶ / (capacity × 거리)`` (`PRD §3.3.1`).
    """
    speed = Fraction(inputs["speed_kn"])
    distance = Fraction(inputs["planned_distance_nm"])
    fuel_ton = (
        Fraction(inputs["daily_foc_ton"])
        * (speed / Fraction(inputs["reference_speed_kn"])) ** 3
        * (distance / speed)
        / 24
    )
    return fuel_ton * Fraction(_SEGMENT_CF) * 10**6 / (Fraction(_SEGMENT_CAPACITY) * distance)


def _truncated_6(value: Fraction) -> str:
    """분수를 소수 6자리로 **절사**한 문자열 (`API_SPEC §1.7`). 정수 나눗셈만 쓴다."""
    scaled = value.numerator * 10**6 // value.denominator
    return f"{scaled // 10**6}.{scaled % 10**6:06d}"


def _segment_progress(inputs: dict[str, Decimal] = _SEGMENT_INPUT):
    """계획 거리를 넘긴 시점(출항 29일 뒤)의 시계 값 — 거리가 정확히 계획값에서 멎는다."""
    from cii_platform.services.simulation_clock import compute_progress

    return compute_progress(
        as_of=datetime(2026, 6, 30, tzinfo=UTC),
        departure_at=datetime(2026, 6, 1, tzinfo=UTC),
        arrival_at=None,
        planned_arrival_at=None,
        not_underway_periods=[],
        **inputs,
    )


def _segment_cii_sent(inputs: dict[str, Decimal] = _SEGMENT_INPUT) -> str:
    """`current_voyage.attained_cii` 전송값. 시계 → `_split_fuel` → 엔진 → 절사를 다 지난다."""
    from cii_platform.services import cii_current

    progress = _segment_progress(inputs)
    assert progress.distance_nm == inputs["planned_distance_nm"], "상한에 닿지 않았다"
    voyage = SimpleNamespace(
        id="voyage",
        voyage_no="V-2097",
        status="IN_PROGRESS",
        departure_port_name="A",
        arrival_port_name="B",
        planned_distance_nm=inputs["planned_distance_nm"],
    )
    segment = cii_current._voyage_segment(
        voyage=voyage,
        progress=progress,
        transport_capacity=_SEGMENT_CAPACITY,
        cf_by_fuel={"HFO": _SEGMENT_CF},
        fuel_code="HFO",
        fuel_split=(("HFO", Decimal(1)),),
    )
    return segment["attained_cii"]


def test_in_progress_segment_cii_is_the_truncation_of_the_exact_value():
    """⚠️ #2097 — 구간 CII 전송값이 **참값의 절사**와 같다 (`6.781600`).

    참값은 분수로 정확히 ``8477/1250``이다. 종전에는 `_split_fuel`이 50자리 연료를
    28자리로 깎아 CII가 ``6.78159999…``가 됐고, 절사가 그것을 ``6.781599``로 내보냈다.
    """
    exact = _segment_cii_exact()
    # 이 입력이 전송 자릿수 **경계에 정확히 놓인다**는 것이 검사의 전제다 — 경계가
    # 아니면 28자리로 깎여도 6자리 절사는 같아, 결함이 있어도 통과한다.
    assert (exact * 10**6).denominator == 1

    assert _segment_cii_sent() == _truncated_6(exact) == "6.781600"


def test_split_fuel_does_not_shorten_the_working_precision_total():
    """`_split_fuel`을 지난 연료가 **들어온 값 그대로**다 — 단일 유종도, 다유종도 (#2097).

    단일 유종(몫 1)은 곱셈 없이 ``총량 − 0``만 지난다. 그 뺄셈 하나가 기본
    컨텍스트에서는 28자리로 반올림한다 — 「몫이 1이면 값이 종전과 같다」가 깨진 자리다.
    """
    from cii_platform.services.cii_current import _planned_shares, _split_fuel

    total = _segment_progress().fuel_ton
    assert len(total.as_tuple().digits) > 28, "28자리 이하면 이 검사는 아무것도 잠그지 않는다"

    assert _split_fuel(total, (("HFO", Decimal(1)),)) == (("HFO", total),)

    # 다유종 — 몫도 컨텍스트 안에서 나눈 값이어야 하고, 합은 총량과 **정확히** 같다.
    shares = _planned_shares(
        [("DIESEL_GAS_OIL", Decimal("40")), ("HFO", Decimal("50")), ("LNG", Decimal("30"))]
    )
    parts = _split_fuel(total, shares)
    with localcontext(prec=LAYER1_WORKING_PRECISION, rounding=LAYER1_ROUNDING):
        assert shares == (
            ("DIESEL_GAS_OIL", Decimal(40) / Decimal(120)),
            ("HFO", Decimal(50) / Decimal(120)),
            ("LNG", Decimal(30) / Decimal(120)),
        )
        assert parts[0][1] == total * shares[0][1]
        assert sum(ton for _, ton in parts) == total


@pytest.mark.parametrize("offset", [10, 20])
def test_in_progress_segment_cii_is_stable_under_higher_precision(monkeypatch, offset):
    """작업 정밀도 P · P+10 · P+20에서 구간 CII 전송값이 같다 (`TECH_SPEC §1.2.1` 불변성 검사).

    `_split_fuel`이 컨텍스트 밖에 있으면 작업 정밀도를 아무리 올려도 연료가 28자리에서
    멎어 값이 ``6.781599``로 남는다 — 그 상태도 「안정적」이므로, 기준이 참값의 절사와
    맞는지를 함께 본다(안정적이지만 틀린 값을 잡기 위함).
    """
    baseline = _segment_cii_sent()
    assert baseline == _truncated_6(_segment_cii_exact())

    # 데코레이터는 호출 시점에 모듈 상수를 읽는다 — 상수를 바꾸면 전 구간이 그 정밀도로 돈다.
    higher = LAYER1_WORKING_PRECISION + offset
    monkeypatch.setattr("cii_platform.calc.precision.LAYER1_WORKING_PRECISION", higher)
    assert len(_segment_progress().fuel_ton.as_tuple().digits) == higher
    assert _segment_cii_sent() == baseline


# ── 전송값은 30자리 공표 확정을 거친 뒤 절사한다 (`#2184`) ─────────────────────
#
# `TECH_SPEC §1.2.1` 「응답 직렬화의 절사」는 두 단계다 — 공표 확정(유효숫자 30)을 먼저 하고,
# 그 30자리 값을 전송 자릿수로 줄인다. 실시간 CII는 앞 단계 없이 작업 정밀도(50자리) 값을
# 바로 절사해, 참값이 전송 자릿수 경계에 정확히 놓인 입력에서 `…99998` 꼬리가 끝자리를
# 하나 내렸다 — 참값 `519/64 = 8.109375`가 `8.109374`로 나갔다. 같은 한 단계 절사가
# `cii_history` · `annual_simulation` · `fleet_summary` · `fleet_reduction` · `data_quality`에도
# 있었다.

#: (거리 nm · 계획 속도 · 기준 속도 · 일일 소모율) → 참값. 이슈 `#2184` 표의 세 입력이다.
_BOUNDARY_SEGMENT_CASES = [
    (("1000", "8", "8", "25"), Fraction(519, 64)),
    (("1000", "8", "10", "50"), Fraction(1038, 125)),
    (("1000", "16", "12", "23.04"), Fraction(5536, 625)),
]


def _segment_inputs(distance, speed, reference_speed, daily_foc) -> dict[str, Decimal]:
    return {
        "planned_distance_nm": Decimal(distance),
        "speed_kn": Decimal(speed),
        "reference_speed_kn": Decimal(reference_speed),
        "daily_foc_ton": Decimal(daily_foc),
    }


@pytest.mark.parametrize(("raw", "exact_expected"), _BOUNDARY_SEGMENT_CASES)
def test_segment_cii_at_a_transport_boundary_is_published_before_truncation(raw, exact_expected):
    """⚠️ #2184 — 참값이 소수 6자리 경계에 놓인 세 입력에서 전송값이 참값의 절사와 같다.

    종전에는 `_truncate`가 50자리 값을 바로 절사해 `8.109374` · `8.303999` · `8.857599`가
    나갔다. 참값은 분수로 따로 내고, 기대 문자열은 정수 나눗셈으로 만든다(`AGENTS §5`) —
    절단된 값을 입력으로 쓰면 검산이 틀린 값을 확증한다.
    """
    inputs = _segment_inputs(*raw)
    exact = _segment_cii_exact(inputs)
    assert exact == exact_expected
    assert (exact * 10**6).denominator == 1, "경계가 아니면 결함이 있어도 통과한다"

    assert _segment_cii_sent(inputs) == _truncated_6(exact)


def test_every_boundary_input_in_the_grid_is_the_truncation_of_the_exact_value():
    """경계 입력 **다수**에서 전송값 = 참값의 6자리 절사 (`#2184` 완료 기준).

    거리 6 × 계획 속도 6 × 기준 속도 6 × 소모율 6 = 1,296 조합 가운데 참값이 소수 6자리에
    정확히 놓이는 것만 센다 — 나머지는 절사 자릿수 아래에서 갈려도 전송값이 같아 아무것도
    잠그지 않는다. 격자는 임의로 정한 것이라 실제 입력에서의 빈도가 아니다. 경계 건수에
    하한을 두는 것은 격자를 바꿔 경계가 사라지면 검사가 비는 것을 막기 위해서다.
    """
    grid = (
        ["1000", "1500", "2000", "2300", "2500", "3000"],
        ["8", "10", "12", "14", "16", "18"],
        ["8", "10", "12", "14", "16", "18"],
        ["20", "23.04", "25", "30", "40", "50"],
    )
    boundary = 0
    mismatched: list[tuple[tuple[str, ...], str, str]] = []
    for raw in itertools.product(*grid):
        inputs = _segment_inputs(*raw)
        exact = _segment_cii_exact(inputs)
        if (exact * 10**6).denominator != 1:
            continue
        boundary += 1
        sent = _segment_cii_sent(inputs)
        if sent != _truncated_6(exact):
            mismatched.append((raw, sent, _truncated_6(exact)))

    assert boundary >= 100, f"경계 입력이 {boundary}건뿐이라 성질 검사가 되지 않는다"
    assert mismatched == []


@pytest.mark.parametrize("boundary", ["8.1094", "4.9824", "10.0001", "0.0002", "123.4567"])
def test_every_service_publishes_the_canonical_value_before_shortening(boundary):
    """경계 바로 아래의 50자리 값을 **모든 직렬화 헬퍼**가 경계 문자열로 내보낸다 (`#2184`).

    `voyage_cii._publish`가 정본 경로(공표 확정 → 절사)다. 같은 한 단계 절사를 쓰던
    `cii_current` · `cii_history` · `annual_simulation` · `fleet_summary` · `fleet_reduction` ·
    `data_quality`가 그와 같은 값을 내는지 본다. 값은 경계에서 작업 정밀도의 마지막 자리
    하나를 뺀 것 — 50자리로는 `…99999`지만 30자리 공표 확정이 경계로 되돌린다. 자릿수가
    다른 종류(비율 5 · 대시보드 CII 4 · 연료 2)도 같은 두 단계를 지난다.
    """
    from cii_platform.services import (
        annual_simulation,
        cii_current,
        cii_history,
        data_quality,
        fleet_reduction,
        fleet_summary,
        voyage_cii,
    )

    exact = Decimal(boundary)
    with localcontext(prec=LAYER1_WORKING_PRECISION, rounding=LAYER1_ROUNDING):
        below = exact - Decimal(1).scaleb(exact.adjusted() - LAYER1_WORKING_PRECISION + 1)
    assert below < exact
    assert len(below.as_tuple().digits) == LAYER1_WORKING_PRECISION, "50자리가 아니면 전제가 없다"

    def expect(digits: int) -> str:
        return str(exact.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_DOWN))

    reference = voyage_cii._publish(below, "attained_cii")
    assert reference == expect(6)
    assert cii_current._publish(below, "cii") == reference
    assert cii_history._publish(below, "cii") == reference
    assert annual_simulation._publish(below, "cii") == reference

    assert voyage_cii._publish(below, "ratio_to_required") == expect(5)
    assert cii_current._publish(below, "ratio") == expect(5)

    assert fleet_summary._publish_cii(below) == expect(4)
    assert fleet_reduction._publish_cii(below) == expect(4)
    assert data_quality._publish_cii(below) == expect(4)
    assert data_quality._publish(below, 4) == expect(4)

    assert voyage_cii._publish(below, "fuel_ton") == expect(2)
    assert cii_current._publish(below, "fuel_ton") == expect(2)
    assert cii_history._publish(below, "fuel_ton") == expect(2)
    assert fleet_reduction._publish_measure(below, 2) == expect(2)
