"""Layer 1 Decimal 정밀도 계약 (#37).

TECH_SPEC §1.2.1은 Layer 1 결정론 계산 컨텍스트를 ``prec=30`` · ``ROUND_HALF_UP``으로
규정한다. 그런데 :func:`decimal.getcontext`는 thread-local이라 모듈 import 시점의
스레드에만 적용된다. uvicorn 워커처럼 별도 스레드에서 Layer 1 함수가 실행되면 기본
컨텍스트(``prec=28`` · ``ROUND_HALF_EVEN``)를 상속하므로, 같은 입력이 호출 경로에 따라
다른 값을 낼 수 있다. TECH_SPEC §5.4 7항이 "Layer 1 Decimal bit-exact"를 재현성 계약의
전제조건으로 규정한 그 전제가 깨지는 상태다.

두 겹으로 막는다.

1. :func:`apply_default_context` — :data:`decimal.DefaultContext`를 올려 **이후 생성되는**
   스레드의 초기 컨텍스트를 맞춘다. 이미 생성된 스레드에는 소급되지 않는다.
2. :func:`layer1_context` — Layer 1 공개 진입점마다 컨텍스트를 명시적으로 고정한다.
   1)이 닿지 않는 스레드와, 컨텍스트가 중간에 교체된 경우를 덮는다.

``prec``과 ``rounding``은 항상 **쌍으로** 지정한다. :func:`decimal.localcontext`는 호출
스레드의 컨텍스트를 복사한 뒤 인자만 덮어쓰므로, ``prec``만 넘기면 반올림 모드가
호출 스레드 값(기본 ``ROUND_HALF_EVEN``)으로 남는다.
"""

import functools
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal, DefaultContext, localcontext

# TECH_SPEC §1.2.1 표. 값을 바꾸면 재현성 계약(§5.4)이 바뀐다.
LAYER1_PRECISION = 30
LAYER1_ROUNDING = ROUND_HALF_UP


def apply_default_context() -> None:
    """새로 생성되는 스레드의 초기 Decimal 컨텍스트를 Layer 1 기준으로 맞춘다.

    ``calc`` 패키지 import 시 1회 호출된다(:mod:`cii_platform.calc`). 프로세스 전역
    상태를 바꾸므로 호출 지점을 늘리지 않는다.
    """
    DefaultContext.prec = LAYER1_PRECISION
    DefaultContext.rounding = LAYER1_ROUNDING


def layer1_context[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Layer 1 계산을 TECH_SPEC §1.2.1 컨텍스트 안에서 실행하는 데코레이터.

    :func:`decimal.localcontext`가 반환하는 컨텍스트 매니저는
    :class:`contextlib.ContextDecorator`를 상속하지 않아 그 자체로는 데코레이터가
    되지 않는다. ``functools.wraps`` 기반으로 감싼다.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        with localcontext(prec=LAYER1_PRECISION, rounding=LAYER1_ROUNDING):
            return func(*args, **kwargs)

    return wrapper


def validate_layer1_result(value: Decimal, name: str) -> Decimal:
    """Layer 1 출력값이 finite한지 검증한다 (TECH_SPEC §1.2.5 [ORACLE-MISS-2]).

    비유한값이 그대로 저장되면 후속 등급 판정·직렬화 단계에서야 증상이 드러나므로
    Layer 1 경계에서 막는다.
    """
    if not value.is_finite():
        raise ValueError(
            f"Layer 1 result '{name}' is not finite: {value}. "
            f"Check input parameters for NaN/Infinity propagation."
        )
    return value
