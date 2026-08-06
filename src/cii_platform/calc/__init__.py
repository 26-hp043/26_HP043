"""계산 엔진 레이어 — CII 수학 계산.

TECH_SPEC의 이중 정밀도 엔진(Layer 1: Decimal 결정론, Layer 2: Monte Carlo
float64), 기상 보정, 해싱 등 순수 계산 로직만 담는다. DB 접근(``db``)이나
HTTP(``api``)에 의존하지 않으며, 비즈니스 흐름(``services``)도 여기 두지 않는다.

계층 규칙은 TECH_SPEC §16 참조. 계산 명세는 TECH_SPEC §1~§9 참조.
"""

from decimal import getcontext

from cii_platform.calc.precision import (
    LAYER1_ROUNDING,
    apply_default_rounding,
)

# TECH_SPEC §1.2.1 — Layer 1 작업 정밀도는 전역에 걸지 않는다 (#179).
# 적용 지점은 @layer1_context 하나이며, 전역 prec을 작업 정밀도로 올리면 calc import
# 이후의 Layer 1 밖 Decimal 연산까지 영향을 받는다.
#
# rounding만 맞춘다. ROUND_HALF_UP은 표시 반올림(PRD §9.3)까지 걸리는 공통 정책이라
# 기본값(ROUND_HALF_EVEN)으로 두면 Layer 1 밖 quantize가 조용히 은행가 반올림을 쓴다.
# 아래 한 줄이 import 스레드를, apply_default_rounding()이 이후 생성되는 스레드를 덮는다.
getcontext().rounding = LAYER1_ROUNDING
apply_default_rounding()
