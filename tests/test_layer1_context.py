"""Layer 1 Decimal 컨텍스트 계약 잠금 (#37).

TECH_SPEC §1.2.1(prec=30 · ROUND_HALF_UP)과 §5.4 7항(Layer 1 bit-exact는 재현성 계약의
전제조건)을 지키는지 확인한다.

핵심은 **워커 스레드에서** 단언하는 것이다. :func:`decimal.getcontext`가 thread-local
이라 메인 스레드에서만 확인하면, 지금 고치려는 결함이 그대로 재발해도 CI가 통과한다.
"""

import threading
from decimal import (
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    getcontext,
    setcontext,
)

import pytest

from cii_platform.calc.cii_engine import FuelUse, calculate_voyage_co2
from cii_platform.calc.precision import (
    LAYER1_PRECISION,
    LAYER1_ROUNDING,
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

    assert snapshot["prec"] == LAYER1_PRECISION == 30
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

    assert inside["prec"] == 30
    assert inside["rounding"] == ROUND_HALF_UP
    # 데코레이터를 벗어나면 원래 컨텍스트로 복원된다(전역 오염 없음).
    assert after["prec"] == 9
    assert after["rounding"] == ROUND_HALF_EVEN


def test_new_thread_inherits_default_context():
    """calc import 이후 생성된 스레드는 DefaultContext를 통해 기본값이 맞다."""
    snapshot = _run_in_thread(_snapshot)

    assert snapshot["prec"] == LAYER1_PRECISION
    assert snapshot["rounding"] == LAYER1_ROUNDING


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
