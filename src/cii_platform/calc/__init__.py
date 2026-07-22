"""계산 엔진 레이어 — CII 수학 계산.

TECH_SPEC의 이중 정밀도 엔진(Layer 1: Decimal 결정론, Layer 2: Monte Carlo
float64), 기상 보정, 해싱 등 순수 계산 로직만 담는다. DB 접근(``db``)이나
HTTP(``api``)에 의존하지 않으며, 비즈니스 흐름(``services``)도 여기 두지 않는다.

계층 규칙은 TECH_SPEC §16 참조. 계산 명세는 TECH_SPEC §1~§9 참조.
"""
