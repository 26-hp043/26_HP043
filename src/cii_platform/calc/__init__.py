"""계산 엔진 레이어 — CII 수학 계산.

TECH_SPEC의 이중 정밀도 엔진(Layer 1: Decimal 결정론, Layer 2: Monte Carlo
float64), 기상 보정, 해싱 등 순수 계산 로직만 담는다. DB 접근(``db``)이나
HTTP(``api``)에 의존하지 않으며, 비즈니스 흐름(``services``)도 여기 두지 않는다.

계층 규칙은 TECH_SPEC §16 참조. 계산 명세는 TECH_SPEC §1~§9 참조.
"""

from decimal import ROUND_HALF_UP, getcontext

# TECH_SPEC §1.2.1 — Layer 1 결정론 계산용 Decimal 컨텍스트.
# calc 패키지 import 시 1회 설정되어 하위 모듈(imo_parser 등)이 상속한다.
# ⚠️ getcontext()는 thread-local이라 별도 워커 스레드(uvicorn 등)는 이 설정을
#    상속하지 않는다. #36 값은 무해(prec 28에서도 정확)하나, 스레드 안전 방식
#    (DefaultContext 또는 localcontext)은 #37~#40 착수 전 별도 결정 대상이다.
getcontext().prec = 30
getcontext().rounding = ROUND_HALF_UP
