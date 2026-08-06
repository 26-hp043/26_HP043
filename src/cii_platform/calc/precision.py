"""Layer 1 Decimal 정밀도 계약 (#37).

TECH_SPEC §1.2.1은 Layer 1 결정론 계산을 **작업 정밀도 = 정본 자릿수 + 최소 20**
(``prec=50``) · ``ROUND_HALF_UP``으로 규정하고, 공표 시점에 유효숫자 30자리로
확정하도록 한다. 그런데 :func:`decimal.getcontext`는 thread-local이라 모듈 import 시점의
스레드에만 적용된다. uvicorn 워커처럼 별도 스레드에서 Layer 1 함수가 실행되면 기본
컨텍스트(``prec=28`` · ``ROUND_HALF_EVEN``)를 상속하므로, 같은 입력이 호출 경로에 따라
다른 값을 낼 수 있다. TECH_SPEC §5.4 7항이 "Layer 1 Decimal bit-exact"를 재현성 계약의
전제조건으로 규정한 그 전제가 깨지는 상태다.

**작업 정밀도의 적용 지점은 :func:`layer1_context` 하나다** (#179). 공개 진입점마다
:func:`decimal.localcontext`로 고정하며, 전역 컨텍스트의 ``prec``은 넓히지 않는다.

전역을 작업 정밀도로 올리면 ``calc`` import 이후의 **Layer 1 밖 Decimal 연산까지**
``prec=50``이 된다. 작업 정밀도는 Layer 1 계산 내부의 안정성 계약이지 프로세스의
Decimal 정책이 아니다.

``rounding``만 :func:`apply_default_rounding`으로 전역에 맞춘다. ``ROUND_HALF_UP``은
Layer 1 전용이 아니라 표시 반올림(`PRD §9.3`)까지 걸리는 저장소 공통 정책이고,
기본값 ``ROUND_HALF_EVEN``으로 두면 Layer 1 밖의 ``quantize``가 조용히 은행가 반올림을
쓴다.

``prec``과 ``rounding``은 항상 **쌍으로** 지정한다. :func:`decimal.localcontext`는 호출
스레드의 컨텍스트를 복사한 뒤 인자만 덮어쓰므로, ``prec``만 넘기면 반올림 모드가
호출 스레드 값(기본 ``ROUND_HALF_EVEN``)으로 남는다.
"""

import functools
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal, DefaultContext, localcontext

# TECH_SPEC §1.2.1 표. 값을 바꾸면 재현성 계약(§5.4)이 바뀐다.
#
# 두 값을 구분한다 (#179). 종전 ``LAYER1_PRECISION`` 하나가 두 의미를 겸해
# 작업 정밀도가 공표 자릿수와 같아졌고, 그 결과 ln/exp 체인이 30번째 자리를 틀렸다.
#: 공표 시점에 확정하는 **유효숫자** 자릿수. §1.2.1의 「N자리」는 유효숫자를 뜻한다.
LAYER1_CANONICAL_SIGNIFICANT_DIGITS = 30

#: 계산 중 유지하는 작업 정밀도. §1.2.1이 **정본 자릿수 + 최소 20**을 요구한다.
#:
#: 이 값은 관측치가 아니라 규격에서 온다. BULK 3,620건 스캔에서는 35자리부터
#: 전정밀도 단일 체인과 일치했으나(49자리까지 동일), 자릿수를 근거로 삼으면
#: 표본이 바뀔 때 흔들린다. 판정 기준은 §1.2.1의 불변성 검사다.
LAYER1_WORKING_PRECISION = LAYER1_CANONICAL_SIGNIFICANT_DIGITS + 20

LAYER1_ROUNDING = ROUND_HALF_UP


def apply_default_rounding() -> None:
    """새로 생성되는 스레드의 기본 Decimal 반올림 모드를 맞춘다.

    ``prec``은 건드리지 않는다 (#179). 작업 정밀도는 :func:`layer1_context` 안에서만
    적용하며, 전역으로 넓히면 Layer 1 밖 연산까지 영향을 받는다.

    ``calc`` 패키지 import 시 1회 호출된다(:mod:`cii_platform.calc`). 프로세스 전역
    상태를 바꾸므로 호출 지점을 늘리지 않는다.
    """
    DefaultContext.rounding = LAYER1_ROUNDING


def layer1_context[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Layer 1 계산을 TECH_SPEC §1.2.1 컨텍스트 안에서 실행하는 데코레이터.

    :func:`decimal.localcontext`가 반환하는 컨텍스트 매니저는
    :class:`contextlib.ContextDecorator`를 상속하지 않아 그 자체로는 데코레이터가
    되지 않는다. ``functools.wraps`` 기반으로 감싼다.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        with localcontext(prec=LAYER1_WORKING_PRECISION, rounding=LAYER1_ROUNDING):
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


def publish_layer1_canonical(value: Decimal) -> Decimal:
    """Layer 1 값을 공표 자릿수(유효숫자 30)로 확정한다 (TECH_SPEC §1.2.1, #179).

    **이후 계산 또는 판정에 입력으로 쓰이지 않는 최종 공표값에만 적용한다.**
    체인 중간값(``cii_ref`` · ``required_cii``)과 판정 입력값(``attained_cii``)에
    쓰면 §1.2.1이 금지하는 중간 단계 처리가 되어 결과가 달라진다.

    「30자리」는 **유효숫자**다(§1.2.1 「N자리」 표기 규약). 고정 exponent로
    ``quantize``하면 정수부 자릿수가 다른 값에서 어긋나므로 :meth:`Decimal.adjusted`
    로 지수를 잡는다 — ``5.66…``(정수부 1)과 ``10.09…``(정수부 2)의 소수부 자릿수가
    각각 29·28로 달라야 한다.

    ``quantize``는 결과 자릿수가 컨텍스트 정밀도를 넘으면 :class:`InvalidOperation`을
    낸다. 호출 컨텍스트가 기본값(``prec=28``)일 수 있으므로 여기서 명시적으로 고정한다.

    :param value: Layer 1 산출값. 비유한값은 :func:`validate_layer1_result`가 상류에서
        막지만, 이 함수만 단독으로 쓰는 경로를 위해 여기서도 거부한다.
    :returns: 유효숫자 30자리로 반올림한 ``Decimal``. 문자열 변환은 호출부 책임이며,
        픽스처 파일의 표기 자릿수는 이 함수가 정하지 않는다.
    """
    if not value.is_finite():
        raise ValueError(f"cannot publish non-finite Layer 1 value: {value}")

    with localcontext(prec=LAYER1_WORKING_PRECISION, rounding=LAYER1_ROUNDING):
        if value.is_zero():
            # adjusted()가 0을 특수 처리하므로 지수 계산이 의미를 갖지 않는다.
            # 부호 있는 0을 만들지 않도록 통일한다.
            return Decimal(0)
        exponent = value.adjusted() - LAYER1_CANONICAL_SIGNIFICANT_DIGITS + 1
        return value.quantize(Decimal(1).scaleb(exponent))
