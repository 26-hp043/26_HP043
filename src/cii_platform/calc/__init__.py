"""계산 엔진 레이어 — CII 수학 계산.

TECH_SPEC의 이중 정밀도 엔진(Layer 1: Decimal 결정론, Layer 2: Monte Carlo
float64), 기상 보정, 해싱 등 순수 계산 로직만 담는다. DB 접근(``db``)이나
HTTP(``api``)에 의존하지 않으며, 비즈니스 흐름(``services``)도 여기 두지 않는다.

계층 규칙은 TECH_SPEC §16 참조. 계산 명세는 TECH_SPEC §1~§9 참조.
"""

from decimal import getcontext

from cii_platform.calc.precision import (
    LAYER1_PRECISION,
    LAYER1_ROUNDING,
    apply_default_context,
)

# TECH_SPEC §1.2.1 — Layer 1 결정론 계산용 Decimal 컨텍스트.
# getcontext()는 thread-local이라 이 설정은 calc를 import 한 스레드에만 적용된다.
# 스레드 안전 방식(#37에서 결정): 아래 두 줄로 import 스레드를, apply_default_context()로
# 이후 생성되는 스레드를 덮고, Layer 1 공개 함수는 @layer1_context 로 진입 시점에
# 한 번 더 고정한다. 상세는 cii_platform.calc.precision 참조.
getcontext().prec = LAYER1_PRECISION
getcontext().rounding = LAYER1_ROUNDING
apply_default_context()
