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
from datetime import UTC, datetime, timedelta
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
    validate_layer1_result,
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


# ── 공표 확정 **이전**의 산술도 적용 지점 안에서 한다 (`#2212`) ─────────────────
#
# `#2184`는 직렬화 헬퍼에 30자리 공표 확정을 넣었다. 그런데 헬퍼에 **들어가기 전**의 산술 —
# CO₂ g → t 나눗셈, 두 CII의 뺄셈, 완결성 비율 나눗셈 — 이 `@layer1_context` 밖에 있으면
# 호출 스레드의 기본 정밀도(`prec=28`)로 먼저 깎인다. 28자리로 깎인 값은 30자리 확정으로도
# 돌아오지 않는다(`TECH_SPEC §1.2.1` 「파생값 계산도 적용 지점 안에서 한다」).
#
# 아래 입력은 참값이 **유효숫자 30자리 이내**로 떨어지게 골랐다 — 그래서 30자리 공표 확정이
# 값을 바꾸지 않고, 기대 문자열은 참값(분수)의 절사 하나로 정해진다(`AGENTS §5`). 28자리로
# 계산하면 29·30번째 자리가 올림을 일으켜 전송 자릿수 경계를 넘는다. 실제 운항 입력에서
# 나오는 크기가 아니라 **계약을 잠그는 입력**이다.

#: 호출 스레드의 기본 컨텍스트 — uvicorn 워커가 상속하는 값이다 (`TECH_SPEC §1.2.1`).
_DEFAULT_PRECISION = 28


def _truncated(value: Fraction, digits: int) -> str:
    """분수를 소수 ``digits``자리로 **0 방향 절사**한 문자열. 정수 나눗셈만 쓴다."""
    scaled = abs(value.numerator) * 10**digits // value.denominator
    sign = "-" if value < 0 and scaled else ""
    return f"{sign}{scaled // 10**digits}.{scaled % 10**digits:0{digits}d}"


def _significant_digits(exact: Fraction) -> int:
    """유한소수인 분수의 유효숫자 수 — 30 이하여야 「기대값 = 참값의 절사」가 성립한다."""
    scale = next(n for n in range(80) if (exact * 10**n).denominator == 1)
    return len(str(abs((exact * 10**scale).numerator)).rstrip("0"))


#: (CO₂ g, 28자리로 나눴을 때 나가던 문자열). 참값 t는 각각 `12.3499…94` · `0.9999…96`이다.
_CO2_GRAM_CASES = [
    ("12349999.9999999999999999999994", "12.35"),
    ("999999.999999999999999999999996", "1.00"),
]


@pytest.mark.parametrize(("grams_raw", "narrowed"), _CO2_GRAM_CASES)
def test_data_quality_co2_ton_is_converted_inside_the_layer1_context(grams_raw, narrowed):
    """⚠️ #2212 — 완결성 내역의 CO₂ 톤이 참값의 2자리 절사와 같다.

    종전의 ``_publish_co2_ton``은 데코레이터 없이 ``grams / 1_000_000``을 했다 — 기본
    컨텍스트에서는 28자리로 반올림되어 `12.3499…94`가 `12.35`로 나갔다.
    """
    from cii_platform.services import data_quality

    grams = Decimal(grams_raw)
    exact = Fraction(grams) / 10**6
    assert _significant_digits(exact) == 30
    expected = _truncated(exact, 2)

    with localcontext(prec=_DEFAULT_PRECISION):
        in_default = (grams / Decimal(10**6)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        assert str(in_default) == narrowed
        assert narrowed != expected, "28자리로도 같은 값이 나오는 입력이면 아무것도 잠그지 않는다"
        sent = data_quality._publish_co2_ton(grams)

    assert sent == expected


def test_data_quality_co2_ton_is_published_before_truncation():
    """CO₂ 톤도 **공표 확정 → 절사** 두 단계다 (`#2184`의 규약 · `#2212`에서 맞춘다).

    컨텍스트 안에서 나누기만 하고 바로 절사하면, 경계 바로 아래의 50자리 값(`12.3499…9`)이
    `12.34`로 나간다. 30자리 확정이 그 꼬리를 경계로 되돌린다 — 같은 파일의 ``_publish`` ·
    ``_publish_cii``가 이미 그렇게 한다.
    """
    from cii_platform.services import data_quality

    boundary = Decimal("12.35")
    with localcontext(prec=LAYER1_WORKING_PRECISION, rounding=LAYER1_ROUNDING):
        below_ton = boundary - Decimal(1).scaleb(boundary.adjusted() - LAYER1_WORKING_PRECISION + 1)
        grams = below_ton * Decimal(10**6)
    assert len(below_ton.as_tuple().digits) == LAYER1_WORKING_PRECISION, "50자리여야 전제가 선다"

    with localcontext(prec=_DEFAULT_PRECISION):
        assert data_quality._publish_co2_ton(grams) == "12.35"
        assert data_quality._publish_co2_ton(Decimal(0)) == "0.00"


@pytest.mark.parametrize("sign", [1, -1])
async def test_data_quality_cii_delta_is_subtracted_inside_the_layer1_context(monkeypatch, sign):
    """⚠️ #2212 — ``cii_impact.delta``가 두 CII 참값의 차를 4자리로 절사한 값과 같다.

    ``_impact``는 ``async``라 ``@layer1_context``를 달 수 없고(데코레이터는 코루틴을 **만드는**
    순간만 감싼다), 종전에는 그 안에서 ``base − without``을 바로 했다. 기본 컨텍스트에서는
    차가 28자리로 반올림되어 `0.12339…94`가 `0.1234`로 나갔다. 부호를 뒤집어도 대칭이다.
    """
    from cii_platform.services import data_quality

    high = Decimal("5.123456789012345678901234567891")
    low = Decimal("5.000056789012345678901234567897")
    base_cii, without_cii = (high, low) if sign > 0 else (low, high)
    exact = Fraction(base_cii) - Fraction(without_cii)
    assert abs(exact) == Fraction(Decimal("0.123399999999999999999999999994"))
    assert _significant_digits(exact) == 30
    expected = _truncated(exact, 4)
    assert expected == ("0.1233" if sign > 0 else "-0.1233")

    async def _without(_session, **_kwargs):
        return SimpleNamespace(data_available=True, attained_cii=without_cii, rating="C")

    monkeypatch.setattr(data_quality, "compute_ytd_cii", _without)
    base = SimpleNamespace(data_available=True, attained_cii=base_cii, rating="C")

    with localcontext(prec=_DEFAULT_PRECISION):
        in_default = (base_cii - without_cii).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
        assert str(in_default) != expected, "28자리로도 같은 값이면 아무것도 잠그지 않는다"
        impact, reason = await data_quality._impact(
            None, vessel=SimpleNamespace(id=1), year=2026, base=base, voyage_id=1
        )

    assert reason is None
    assert impact["delta"] == expected


def test_completeness_ratio_is_divided_inside_the_layer1_context():
    """⚠️ #2212 — 완결성 비율이 참값의 4자리 절사와 같다 (이슈 본문 밖 · 같은 응답의 같은 유형).

    ``calc.data_quality.completeness_ratio``는 ``measured / total``을 데코레이터 없이 했다 —
    `TECH_SPEC §1.2.1`이 ``ratio_to_required``로 든 바로 그 형태다. 기본 컨텍스트에서는
    `0.4999…9`(30자리)가 `0.5000`으로 나갔다.
    """
    from cii_platform.calc.data_quality import completeness_ratio
    from cii_platform.services import data_quality

    measured = Decimal("499999999999999999999999999999")
    total = Decimal(10**30)
    exact = Fraction(measured) / Fraction(total)
    assert _significant_digits(exact) == 30
    expected = _truncated(exact, 4)
    assert expected == "0.4999"

    with localcontext(prec=_DEFAULT_PRECISION):
        in_default = (measured / total).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
        assert str(in_default) == "0.5000", "28자리로도 같은 값이면 아무것도 잠그지 않는다"
        sent = data_quality._publish(completeness_ratio(measured, total), 4)

    assert sent == expected


@pytest.mark.parametrize(("grams_raw", "narrowed"), _CO2_GRAM_CASES)
def test_other_services_convert_co2_grams_inside_the_layer1_context(grams_raw, narrowed):
    """같은 g → t 나눗셈을 **직렬화 헬퍼 앞에서** 하던 두 서비스도 참값의 절사를 낸다 (`#2212`).

    ``cii_history._fuel_rows``(연료축의 ``co2_ton``)와 ``cii_current._ytd_to_dict``(⑴의
    ``not_underway_co2_ton``)가 ``_publish(g / 1_000_000, "co2_ton")`` 꼴이었다 — 헬퍼의 공표
    확정은 이미 28자리로 깎인 값을 받는다.
    """
    from cii_platform.services import cii_current, cii_history

    grams = Decimal(grams_raw)
    exact = Fraction(grams) / 10**6
    assert _significant_digits(exact) == 30
    expected = _truncated(exact, 2)
    assert narrowed != expected

    class _Ytd(SimpleNamespace):
        def __getattr__(self, _name):
            return None

    ytd = _Ytd(data_available=True, not_underway_co2_g=grams, substitutions=[])

    with localcontext(prec=_DEFAULT_PRECISION):
        fuel_rows = cii_history._fuel_rows({"HFO": Decimal(4)}, {"HFO": grams})
        ytd_block = cii_current._ytd_to_dict(ytd)

    assert fuel_rows[0]["co2_ton"] == expected
    assert ytd_block["not_underway_co2_ton"] == expected


# --- Layer 1 출력 가드 (`TECH_SPEC §1.2.5` · #2144) ----------------------------------
# CI 커버리지에서 `precision.py`의 거부 줄이 한 번도 실행되지 않았다 — 가드가
# `is_nan()`만 보도록 좁아져 무한대가 저장 단계까지 흘러가도 어느 검사도 깨지지 않았다.


@pytest.mark.parametrize("bad", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_non_finite_layer1_result_is_refused(bad):
    """`[ORACLE-MISS-2]` — 유한하지 않은 값은 저장·전달 전에 막는다. 이름이 문구에 실린다."""
    with pytest.raises(ValueError, match="attained_cii"):
        validate_layer1_result(Decimal(bad), "attained_cii")


@pytest.mark.parametrize(
    "ok", ["0", "-1.5", "4.9824", "1E+40", "1.234567890123456789012345678901234567890"]
)
def test_finite_layer1_result_passes_through_unchanged(ok):
    """유한하면 **그 값 그대로** 돌려준다 — 0도 음수도 가드의 대상이 아니다.

    같은 객체를 돌려주는지 본다. 가드가 값을 다시 만들면(`+value`) 호출 스레드의
    컨텍스트(기본 28자리)로 반올림되어 40자리 값이 깎인다.
    """
    value = Decimal(ok)
    assert validate_layer1_result(value, "x") is value


# ─── #2254 — 서비스 계층에 남아 있던 컨텍스트 밖 산술 ────────────────────────────


def _half_up_significant(exact: Fraction, digits: int) -> Decimal:
    """양의 분수를 유효숫자 ``digits``자리로 ``ROUND_HALF_UP``한 값. 정수 나눗셈만 쓴다."""
    assert exact > 0
    adjusted = len(str(exact.numerator)) - len(str(exact.denominator))
    if Fraction(10) ** adjusted > exact:
        adjusted -= 1
    shift = digits - 1 - adjusted
    scaled = exact * Fraction(10) ** shift
    quotient, remainder = divmod(scaled.numerator, scaled.denominator)
    if 2 * remainder >= scaled.denominator:
        quotient += 1
    # 문자열로 만든다 — ``scaleb``는 호출 컨텍스트의 정밀도로 다시 깎는다.
    return Decimal(f"{quotient}E{-shift}")


def _half_up(exact: Fraction, digits: int) -> str:
    """양의 분수를 소수 ``digits``자리로 ``ROUND_HALF_UP``한 문자열. 정수 나눗셈만 쓴다."""
    assert exact >= 0
    scaled = (2 * exact.numerator * 10**digits + exact.denominator) // (2 * exact.denominator)
    return f"{scaled // 10**digits}.{scaled % 10**digits:0{digits}d}"


#: 1초 — ``1/3600`` h · ``1/86400`` 일은 나누어떨어지지 않아 28자리와 50자리가 반드시 갈린다.
_ONE_SECOND = (datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC))


def test_remaining_days_are_divided_inside_the_layer1_context():
    """⚠️ #2254 — 연말 예상의 잔여 일수(초 ÷ 86400)가 작업 정밀도에서 나온다.

    ``_remaining_days``는 코루틴 ``_project_year_end``가 부른다 — 데코레이터가 없으면 호출
    스레드의 기본 28자리로 나눈 값이 「해가 끝났는가」 판정과 ``assumptions.remaining_days``로
    간다.
    """
    from cii_platform.services import cii_current

    start, _end = _ONE_SECOND
    exact = Fraction(1, 86400)
    expected = _half_up_significant(exact, LAYER1_WORKING_PRECISION)

    with localcontext(prec=_DEFAULT_PRECISION):
        narrowed = Decimal(1) / Decimal(86400)
        assert narrowed != expected, "28자리로도 같은 값이 나오는 입력이면 아무것도 잠그지 않는다"
        days = cii_current._remaining_days(as_of=start, regulation_year=2026)

    assert days == expected


def test_data_quality_sailing_hours_are_divided_inside_the_layer1_context():
    """⚠️ #2254 — 이상치 판정의 분모(출항~도착 시간)가 작업 정밀도에서 나온다.

    ``judge_anomaly``는 적용 지점 안이지만 인자 ``sailing_hours``는 그 밖에서 먼저 만들어졌다.
    """
    from cii_platform.services import data_quality

    start, end = _ONE_SECOND
    expected = _half_up_significant(Fraction(1, 3600), LAYER1_WORKING_PRECISION)
    voyage = SimpleNamespace(actual_departure_at=start, actual_arrival_at=end)

    with localcontext(prec=_DEFAULT_PRECISION):
        assert Decimal(1) / Decimal(3600) != expected
        hours = data_quality._sailing_hours(voyage)

    assert hours == expected


def test_report_elapsed_hours_are_divided_inside_the_layer1_context():
    """⚠️ #2254 — 항차 리포트 실적 행의 소요 시간(초 ÷ 3600)이 작업 정밀도에서 나온다."""
    from cii_platform.services import report

    start, end = _ONE_SECOND
    expected = _half_up_significant(Fraction(1, 3600), LAYER1_WORKING_PRECISION)

    with localcontext(prec=_DEFAULT_PRECISION):
        assert Decimal(1) / Decimal(3600) != expected
        hours = report._elapsed_hours(start, end)

    assert hours == expected


def test_report_voyage_co2_is_summed_inside_the_layer1_context():
    """⚠️ #2254 — 항차 리포트의 「항차 CO₂ 배출량」이 참값의 표시 반올림과 같다.

    ``build_voyage_report``는 코루틴이라 그 안의 ``Σ(t × 10⁶ × CF) ÷ 10⁶``이 기본 28자리에서
    돌았다. 참값 `12.3499…94` t는 1자리 표시가 `12.3`인데, 28자리로 먼저 깎이면 `12.35`가
    되어 `12.4`로 찍힌다.
    """
    from cii_platform.services import report

    ton = Decimal("12.3499999999999999999999999994")
    rows = [SimpleNamespace(actual_fuel_ton=ton, planned_fuel_ton=None, cf_used=Decimal(1))]
    exact = Fraction(ton)
    assert _significant_digits(exact) == 30
    expected = _half_up(exact, 1)
    assert expected == "12.3"

    with localcontext(prec=_DEFAULT_PRECISION, rounding=ROUND_HALF_UP):
        narrowed = ton * Decimal(1_000_000) * Decimal(1) / Decimal(1_000_000)
        assert report._display(narrowed, "co2_ton") == "12.4"
        shown = report._display(report._voyage_co2_ton(rows), "co2_ton")

    assert shown == expected


def test_report_share_is_divided_inside_the_layer1_context():
    """⚠️ #2254 — 「연간 누적에서 차지한 비중」이 참값의 1자리 표시 반올림과 같다.

    참값 `49.9499…9`%는 `49.9`인데, 28자리 나눗셈은 `0.4995`로 올려 `50.0`을 낸다.
    """
    from cii_platform.services import report

    part = Decimal("499499999999999999999999999999")
    whole = Decimal(10**30)
    exact = Fraction(part) / Fraction(whole) * 100
    assert _significant_digits(exact) == 30
    expected = _half_up(exact, 1)
    assert expected == "49.9"

    with localcontext(prec=_DEFAULT_PRECISION, rounding=ROUND_HALF_UP):
        narrowed = (part / whole * 100).quantize(Decimal("0.1"))
        assert str(narrowed) == "50.0", "28자리로도 같은 값이면 아무것도 잠그지 않는다"
        share = report._share_percent(part, whole)

    assert str(share) == expected


def test_report_share_rounds_half_up_whatever_the_caller_context():
    """비중의 반올림은 호출 스레드의 모드가 아니라 표시 규칙(``ROUND_HALF_UP``)이다 (`#2254`).

    종전에는 ``quantize``에 모드를 적지 않아 호출 스레드의 기본 모드에 기댔다. 은행가
    반올림이면 `0.25`%가 `0.2`로 찍힌다(`DESIGN_SYSTEM §4.2` — 절사가 아니라 반올림).
    """
    from cii_platform.services import report

    with localcontext(prec=_DEFAULT_PRECISION, rounding=ROUND_HALF_EVEN):
        assert str((Decimal(1) / Decimal(400) * 100).quantize(Decimal("0.1"))) == "0.2"
        share = report._share_percent(Decimal(1), Decimal(400))

    assert str(share) == _half_up(Fraction(1, 400) * 100, 1) == "0.3"


async def test_scenario_adopt_fuel_shares_are_divided_inside_the_layer1_context(monkeypatch):
    """⚠️ #2254 — 채택이 **저장하는** 유종별 계획 연료가 참값의 4자리 반올림과 같다.

    ``_apply_scenario_fuel``은 코루틴이라 ``총량 × 비중 ÷ 비중 합``이 기본 28자리에서 돌았다.
    참값 `0.49994999…9`는 `0.4999`인데 28자리로는 `0.49995`가 되어 `0.5000`이 저장된다 —
    잔차를 흡수하는 행까지 함께 달라진다.
    """
    from cii_platform.services import scenario_adopt

    weights = [
        Decimal("499949999999999999999999999999"),
        Decimal("500050000000000000000000000001"),
    ]
    total = Decimal(1)
    exact = [Fraction(total) * Fraction(w) / Fraction(sum(map(Fraction, weights))) for w in weights]
    assert all(_significant_digits(share) == 30 for share in exact)
    expected = [_half_up(share, 4) for share in exact]
    assert expected == ["0.4999", "0.5001"]
    assert sum(map(Fraction, expected)) == total, "잔차가 없어야 기대값이 곧 저장값이다"

    rows = [SimpleNamespace(planned_fuel_ton=w, source="MANUAL") for w in weights]

    async def _list_fuel_uses(_session, _voyage_id):
        return rows

    monkeypatch.setattr(scenario_adopt.voyage_repo, "list_fuel_uses", _list_fuel_uses)

    with localcontext(prec=_DEFAULT_PRECISION, rounding=ROUND_HALF_UP):
        narrowed = (total * weights[0] / sum(weights)).quantize(Decimal("0.0001"))
        assert str(narrowed) != expected[0], "28자리로도 같은 값이면 아무것도 잠그지 않는다"
        changed = await scenario_adopt._apply_scenario_fuel(
            None, SimpleNamespace(id=1), SimpleNamespace(fuel_ton=total)
        )

    assert changed is True
    assert [str(row.planned_fuel_ton) for row in rows] == expected


def test_scenario_detour_distance_is_multiplied_inside_the_layer1_context():
    """⚠️ #2254 — 우회 거리 기본값(``직항 × 1.05``)이 참값과 같다.

    곱셈은 두 피연산자의 자릿수 합이 28을 넘을 때만 깎인다 — 30자리 직항 거리로 그 경우를 만든다.
    """
    from cii_platform.services import scenario_compare

    direct = Decimal("1234567890123456789012345678.99")
    exact = Fraction(direct) * Fraction(105, 100)
    assert _significant_digits(exact) <= LAYER1_WORKING_PRECISION
    payload = SimpleNamespace(detour_distance_nm=None)

    with localcontext(prec=_DEFAULT_PRECISION):
        assert Fraction(direct * scenario_compare.DETOUR_DISTANCE_RATIO) != exact
        detour = scenario_compare._resolve_detour_distance(payload, direct, None)

    assert Fraction(detour) == exact


def test_simulation_clock_computes_progress_inside_the_layer1_context():
    """⚠️ #2254 — 시계가 내는 경과 시간과 거리가 작업 정밀도에서 나온다.

    ``compute_progress``의 산출물은 그대로 Layer 1 계산의 입력이다. 경과 시간은 나눗셈
    한 번이라 참값의 50자리 반올림과 정확히 같고, 거리(``속도 × 시간``)는 연산이 둘이라
    참값과 **48자리까지** 같음을 본다 — 28자리 계산은 그 안에 들지 못한다.
    """
    from cii_platform.services.simulation_clock import compute_progress

    start, end = _ONE_SECOND
    speed = Decimal(7)
    exact_hours = Fraction(1, 3600)
    exact_distance = Fraction(speed) * exact_hours
    tolerance = exact_distance / 10**48

    with localcontext(prec=_DEFAULT_PRECISION):
        narrowed = speed * (Decimal(1) / Decimal(3600))
        assert abs(Fraction(narrowed) - exact_distance) > tolerance
        progress = compute_progress(
            as_of=end, departure_at=start, arrival_at=None, speed_kn=speed, daily_foc_ton=None
        )

    assert progress.underway_hours == _half_up_significant(exact_hours, LAYER1_WORKING_PRECISION)
    assert abs(Fraction(progress.distance_nm) - exact_distance) <= tolerance


# (속력 kn · 경과 초) — 진행 거리의 참값이 전송 자릿수(2자리) 경계에 정확히 놓이는 입력.
_PROGRESS_BOUNDARY_CASES = [
    pytest.param("4.14", 3_768_200, id="4.14kn-3768200s"),
    pytest.param("24.00", 4_862_928, id="24.00kn-4862928s"),
]


@pytest.mark.parametrize(("speed_raw", "seconds"), _PROGRESS_BOUNDARY_CASES)
def test_progress_distance_at_a_transport_boundary_is_sent_as_the_exact_value(speed_raw, seconds):
    """⚠️ #2254 — 진행 거리의 참값이 전송 자릿수 경계에 놓여도 전송값이 참값이다.

    실제 저장 범위의 입력이다(속력 2자리 · 경과 시간 초 단위). ``초 ÷ 3600``을 28자리에서
    끊고 속력을 곱하면 ``…29999…``(28자리)가 되고, 30자리 공표 확정은 28자리에서 이미 잃은
    꼬리를 되돌리지 못해 전송값이 한 단위 아래로 나갔다(`#2184` 유형). 직렬화는 실시간 CII
    응답의 ``current_voyage.distance_nm``이 지나는 ``cii_current._publish``를 그대로 부른다.
    """
    from cii_platform.services import cii_current
    from cii_platform.services.simulation_clock import compute_progress

    speed = Decimal(speed_raw)
    departure = datetime(2026, 1, 1, tzinfo=UTC)
    exact = Fraction(speed_raw) * Fraction(seconds, 3600)
    assert exact * 100 == int(exact * 100), "참값이 전송 자릿수 경계에 놓인 입력이어야 한다"
    expected = _truncated(exact, 2)
    one_unit_below = _truncated(exact - Fraction(1, 100), 2)
    arguments = {
        "as_of": departure + timedelta(seconds=seconds),
        "departure_at": departure,
        "arrival_at": None,
        "speed_kn": speed,
        "daily_foc_ton": None,
    }

    # 데코레이터가 감싼 본문 — 데코레이터가 사라지면 함수 자신이 그 본문이다.
    body = getattr(compute_progress, "__wrapped__", compute_progress)

    with localcontext(prec=_DEFAULT_PRECISION, rounding=ROUND_HALF_UP):
        narrowed = body(**arguments)
        assert cii_current._publish(narrowed.distance_nm, "distance_nm") == one_unit_below, (
            "28자리 본문도 참값을 내면 이 입력은 아무것도 잠그지 않는다"
        )
        progress = compute_progress(**arguments)

    assert cii_current._publish(progress.distance_nm, "distance_nm") == expected


# ── YTD 누적이 진행분의 50자리 값을 28자리로 깎지 않는다 (`#2254`) ────────────────
#
# `ytd_cii._aggregate`는 코루틴이라 호출 스레드의 기본 정밀도(28자리)로 돈다. 시계와
# `_split_fuel`이 50자리로 낸 진행분을 거기서 바로 더하면 `_compute_layer1`의 입력이
# 28자리에서 시작한다.


def _stub_ytd_reads(monkeypatch, *, voyages=(), fuel_rows=None, cf=_SEGMENT_CF):
    """`_aggregate`의 조회 다섯을 고정값으로 바꾼다 — 덧셈만 실제 코드가 한다."""
    from cii_platform.services import ytd_cii

    answers = {
        "annual_inclusions": list(voyages),
        "fuel_uses_by_voyages": fuel_rows or {},
        "not_underway_fuel": [],
        "not_underway_distance": Decimal(0),
    }

    async def _cached(_session, key, _load):
        if key[0] == "fuel_types":
            return {code: SimpleNamespace(cf=cf) for code in key[1]}
        return answers[key[0]]

    monkeypatch.setattr(ytd_cii, "cached", _cached)


async def _aggregate_with(contribution):
    from cii_platform.services import ytd_cii

    return await ytd_cii._aggregate(
        None, vessel_id="vessel", regulation_year=2026, as_of=None, in_progress=contribution
    )


async def test_ytd_aggregate_adds_the_in_progress_share_at_working_precision(monkeypatch):
    """⚠️ #2254 — 완료 항차의 합에 진행분을 더한 값이 참값과 같다.

    진행분을 소수 39자리로 둔다 — 합의 유효숫자가 44자리(거리) · 43자리(연료)라 작업
    정밀도에서는 정확하고 28자리에서는 깎인다. 연료는 같은 유종 두 몫으로 넣어 「몫끼리
    모으는 덧셈」과 「완료 항차 묶음에 얹는 덧셈」을 둘 다 지나게 한다.
    """
    from cii_platform.services.ytd_cii import InProgressContribution

    base_distance, base_fuel = Decimal("12345.67"), Decimal("987.6543")
    tail = Decimal("0.123456789012345678901234567890123456789")
    exact_distance = Fraction(base_distance) + Fraction(tail)
    exact_fuel = Fraction(base_fuel) + 2 * Fraction(tail)
    assert _significant_digits(exact_distance) <= LAYER1_WORKING_PRECISION
    assert _significant_digits(exact_fuel) <= LAYER1_WORKING_PRECISION
    _stub_ytd_reads(
        monkeypatch,
        voyages=[SimpleNamespace(id=1, actual_distance_nm=base_distance)],
        fuel_rows={
            1: [SimpleNamespace(actual_fuel_ton=base_fuel, fuel_type="HFO", cf_used=_SEGMENT_CF)]
        },
    )

    with localcontext(prec=_DEFAULT_PRECISION, rounding=ROUND_HALF_UP):
        assert Fraction(base_distance + tail) != exact_distance, "28자리로도 같으면 잠그지 않는다"
        assert Fraction(tail + tail) != 2 * Fraction(tail)
        assert Fraction(base_fuel + tail) != Fraction(base_fuel) + Fraction(tail)
        aggregated = await _aggregate_with(
            InProgressContribution(distance_nm=tail, fuel_uses=(("HFO", tail), ("HFO", tail)))
        )

    assert Fraction(aggregated.underway_distance_nm) == exact_distance
    assert {key: Fraction(ton) for key, ton in aggregated.underway_fuel.items()} == {
        ("HFO", _SEGMENT_CF): exact_fuel
    }


async def test_ytd_cii_at_a_transport_boundary_survives_the_in_progress_sum(monkeypatch):
    """⚠️ #2254 — 진행분만 있는 해의 누적 CII가 전송 자릿수 경계에서 참값으로 나간다.

    실제 저장 범위의 입력이다: 8 kn(기준 속도와 같다) · 일일 25 t · 출항 864,004초 뒤 ·
    capacity 50,000 · CF 3.114. 구간 CII는 시간이 약분돼 ``519/64 = 8.109375``인데, 거리와
    연료를 각각 28자리로 깎으면 그 약분이 깨져 ``8.10937499…``(28번째 자리)가 되고 30자리
    공표 확정이 되돌리지 못한다. 시계 → ``_split_fuel`` → ``_aggregate`` → ``_compute_layer1``
    → ``cii_current._publish``를 그대로 지난다.
    """
    from cii_platform.calc.rating_engine import DVector
    from cii_platform.services import cii_current, ytd_cii
    from cii_platform.services.simulation_clock import compute_progress

    speed, daily_foc, seconds = Decimal("8"), Decimal("25"), 864_004
    hours = Fraction(seconds, 3600)
    exact = (
        (Fraction(daily_foc) * hours / 24)
        * Fraction(_SEGMENT_CF)
        * 10**6
        / (Fraction(_SEGMENT_CAPACITY) * Fraction(speed) * hours)
    )
    assert exact == Fraction(519, 64)
    assert (exact * 10**6).denominator == 1, "경계가 아니면 결함이 있어도 통과한다"
    departure = datetime(2026, 1, 1, tzinfo=UTC)
    progress = compute_progress(
        as_of=departure + timedelta(seconds=seconds),
        departure_at=departure,
        arrival_at=None,
        speed_kn=speed,
        daily_foc_ton=daily_foc,
        reference_speed_kn=speed,
    )
    fuel_uses = cii_current._split_fuel(progress.fuel_ton, (("HFO", Decimal(1)),))
    _stub_ytd_reads(monkeypatch)

    def _sent(distance: Decimal, fuel_ton: Decimal) -> str:
        layer1 = ytd_cii._compute_layer1(
            underway_fuel_uses=[FuelUse(fuel_code="HFO", fuel_ton=fuel_ton, cf_value=_SEGMENT_CF)],
            not_underway_fuel_uses=[],
            transport_capacity=_SEGMENT_CAPACITY,
            reference_capacity=_SEGMENT_CAPACITY,
            underway_distance_nm=distance,
            not_underway_distance_nm=Decimal(0),
            a_decimal=Decimal("4745"),
            c=Decimal("0.622"),
            z_factor_percent=Decimal("11"),
            d_vector=DVector(
                d1=Decimal("0.86"), d2=Decimal("0.94"), d3=Decimal("1.06"), d4=Decimal("1.18")
            ),
        )
        return cii_current._publish(layer1.ytd.attained_cii, "cii")

    with localcontext(prec=_DEFAULT_PRECISION, rounding=ROUND_HALF_UP):
        # 단항 ``+``는 그 문맥의 정밀도로 반올림한다 — 28자리 덧셈(``0 + 값``)이 내던 값이다.
        narrowed = _sent(+progress.distance_nm, +fuel_uses[0][1])
        assert narrowed == _truncated_6(exact - Fraction(1, 10**6)), (
            "28자리 누적도 참값을 내면 이 입력은 아무것도 잠그지 않는다"
        )
        aggregated = await _aggregate_with(
            ytd_cii.InProgressContribution(distance_nm=progress.distance_nm, fuel_uses=fuel_uses)
        )

    (fuel_ton,) = aggregated.underway_fuel.values()
    assert _sent(aggregated.underway_distance_nm, fuel_ton) == _truncated_6(exact) == "8.109375"


# ── `compute_ytd_cii`의 합 셋도 작업 정밀도에서 돈다 (`#2254`) ─────────────────────
#
# `_aggregate`가 모은 값을 응답 필드로 모으는 합 셋 — `fuel_ton_breakdown`(유종별 투입 톤) ·
# `total_fuel_ton` · `total_distance_nm` — 은 코루틴 본문에서 `sum()`·`+`로 돌아 호출
# 스레드의 기본 정밀도(28자리)였다(탐침 실측). 진행분(50자리)이 섞이면 응답의 2자리
# 필드로 가는 합의 꼬리가 거기서 깎인다.

#: 소수 39자리 꼬리 — 저장값(유효숫자 12자리)에 더하면 합이 44자리라 28자리에서 깎인다.
_YTD_TAIL = Decimal("0.123456789012345678901234567890123456789")


def _stub_ytd_output_reads(monkeypatch, aggregated):
    """`compute_ytd_cii`의 조회를 고정값으로 바꾼다 — 합 셋만 실제 코드가 한다.

    거리 또는 연료가 0이면 Layer 1 앞에서 돌아 나가고, 그 응답에도 합 셋이 실린다. 그 갈래를
    지나면 규제 파라미터 조회 없이 **합 셋이 응답으로 나가는 경로**를 그대로 볼 수 있다.
    """
    from cii_platform.services import applicability, ytd_cii

    async def _aggregate(_session, **_kwargs):
        return aggregated

    async def _load_vessel(_session, _vessel_id):
        return SimpleNamespace(ship_type="BULK_CARRIER", dwt=Decimal(50000), gross_tonnage=None)

    async def _cached(_session, _key, _load):
        return []

    monkeypatch.setattr(ytd_cii, "_aggregate", _aggregate)
    monkeypatch.setattr(ytd_cii, "_load_vessel", _load_vessel)
    monkeypatch.setattr(ytd_cii, "_resolve_transport_capacity", lambda _vessel: Decimal(50000))
    monkeypatch.setattr(ytd_cii, "cached", _cached)
    monkeypatch.setattr(applicability, "applicability_warnings", lambda _vessel: [])


def _ytd_aggregated(**overrides):
    from cii_platform.services import ytd_cii

    values = {
        "underway_fuel": {},
        "not_underway_fuel": [],
        "underway_distance_nm": Decimal(0),
        "not_underway_distance_nm": Decimal(0),
        "voyage_count": 0,
        "warnings": [],
        "substitutions": [],
        "unfilled": [],
    }
    values.update(overrides)
    return ytd_cii._Aggregated(**values)


async def test_ytd_fuel_totals_are_summed_inside_the_layer1_context(monkeypatch):
    """⚠️ #2254 — 응답의 유종별 투입 톤과 총 연료가 참값과 같다.

    같은 유종이 CF snapshot 둘로 갈라진 묶음(완료 항차 `NUMERIC(12,4)` + 진행분 50자리)을
    유종 하나로 합치는 덧셈과, 그 유종별 값을 다시 총량으로 모으는 덧셈을 지난다. 거리는
    0으로 두어 Layer 1 앞에서 돌아 나가게 한다 — 그 응답에도 두 합이 그대로 실린다.
    """
    from cii_platform.services import ytd_cii

    base = Decimal("987.6543")
    exact_hfo = Fraction(base) + Fraction(_YTD_TAIL)
    exact_total = exact_hfo + Fraction(_YTD_TAIL)
    assert _significant_digits(exact_total) <= LAYER1_WORKING_PRECISION
    _stub_ytd_output_reads(
        monkeypatch,
        _ytd_aggregated(
            underway_fuel={
                ("HFO", Decimal("3.114")): base,
                ("HFO", Decimal("3.115")): _YTD_TAIL,
                ("MGO", Decimal("3.206")): _YTD_TAIL,
            }
        ),
    )

    with localcontext(prec=_DEFAULT_PRECISION, rounding=ROUND_HALF_UP):
        assert Fraction(base + _YTD_TAIL) != exact_hfo, "28자리로도 같으면 잠그지 않는다"
        out = await ytd_cii.compute_ytd_cii(None, vessel_id="vessel", regulation_year=2026)

    assert out.data_available is False
    assert {code: Fraction(ton) for code, ton in out.fuel_ton_breakdown.items()} == {
        "HFO": exact_hfo,
        "MGO": Fraction(_YTD_TAIL),
    }
    assert Fraction(out.total_fuel_ton) == exact_total


async def test_ytd_total_distance_is_summed_inside_the_layer1_context(monkeypatch):
    """⚠️ #2254 — 응답의 총 거리(항해 중 + not under way)가 참값과 같다.

    항해 중 거리에 진행분 꼬리가 섞인 50자리 값을, 저장된 not under way 거리(`NUMERIC(12,2)`)와
    더하는 자리다. 연료를 비워 Layer 1 앞에서 돌아 나가게 한다 — 그 갈래가 이 합을 응답에
    싣는 유일한 경로다(Layer 1을 지나면 엔진이 낸 거리가 실린다).
    """
    from cii_platform.services import ytd_cii

    # 문자열로 만든다 — 덧셈으로 만들면 이 자리의 문맥(28자리)이 꼬리를 먼저 깎는다.
    underway = Decimal("12345.793456789012345678901234567890123456789")
    not_underway = Decimal("89.01")
    assert Fraction(underway) == Fraction("12345.67") + Fraction(_YTD_TAIL)
    exact = Fraction(underway) + Fraction(not_underway)
    assert _significant_digits(exact) <= LAYER1_WORKING_PRECISION
    _stub_ytd_output_reads(
        monkeypatch,
        _ytd_aggregated(underway_distance_nm=underway, not_underway_distance_nm=not_underway),
    )

    with localcontext(prec=_DEFAULT_PRECISION, rounding=ROUND_HALF_UP):
        assert Fraction(underway + not_underway) != exact, "28자리로도 같으면 잠그지 않는다"
        out = await ytd_cii.compute_ytd_cii(None, vessel_id="vessel", regulation_year=2026)

    assert out.data_available is False
    assert Fraction(out.total_distance_nm) == exact


async def test_ytd_total_fuel_at_a_transport_boundary_is_sent_as_the_exact_value(monkeypatch):
    """⚠️ #2254 — 실제 범위의 입력에서 응답의 ``total_fuel_ton`` 전송값이 참값의 절사다.

    8 kn · 일일 25 t · 출항 3,456초 뒤 → 진행분 연료 참값 ``25 × 3456 / 86400 = 1`` t를
    유종 셋이 1:1:1로 나눈 50자리 몫(``_split_fuel``이 내는 ``0.333…3`` · ``0.333…4``)에
    정박 연료 MGO 3,652.04 t를 더하면 참값은 3653.04다. 28자리 덧셈은 같은 유종의 저장값에
    비종결 몫을 얹을 때 잃는 꼬리가 유종 셋에서 같은 방향으로 쌓여
    ``3653.039999999999999999999999``(28자리)가 되고, 30자리 공표 확정이 그 값을 그대로 두어
    전송값이 ``3653.03``으로 나갔다. 직렬화는 응답이 지나는 ``cii_current._publish``를 그대로
    부른다.
    """
    from cii_platform.services import cii_current, ytd_cii

    third = Decimal("0.33333333333333333333333333333333333333333333333333")
    last = Decimal("0.33333333333333333333333333333333333333333333333334")
    exact = 2 * Fraction(third) + Fraction(last) + Fraction("3652.04")
    assert exact == Fraction("3653.04"), "참값이 전송 자릿수 경계에 놓인 입력이어야 한다"
    aggregated = _ytd_aggregated(
        underway_fuel={
            ("HFO", Decimal("3.114")): third,
            ("MGO", Decimal("3.206")): third,
            ("LNG", Decimal("2.750")): last,
        },
        not_underway_fuel=[
            SimpleNamespace(fuel_type="MGO", fuel_ton=Decimal("3652.04"), cf_used=Decimal("3.206"))
        ],
    )
    _stub_ytd_output_reads(monkeypatch, aggregated)

    with localcontext(prec=_DEFAULT_PRECISION, rounding=ROUND_HALF_UP):
        narrowed = sum((third, third + Decimal("3652.04"), last), Decimal(0))
        assert cii_current._publish(narrowed, "fuel_ton") == "3653.03", (
            "28자리 덧셈도 참값을 내면 이 입력은 아무것도 잠그지 않는다"
        )
        out = await ytd_cii.compute_ytd_cii(None, vessel_id="vessel", regulation_year=2026)

    assert cii_current._publish(out.total_fuel_ton, "fuel_ton") == "3653.04"
