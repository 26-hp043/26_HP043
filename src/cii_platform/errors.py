"""애플리케이션 공통 예외 계층 (레이어 중립).

이 모듈은 어떤 레이어(``calc``/``services``/``db``/``api``)에도 속하지 않는
최상위 위치에 둔다. 이유: 예외를 발생시키는 주체는 하위 레이어(계산 엔진,
저장소, 서비스)인데, 만약 base 예외를 ``api`` 패키지에 두면 하위 레이어가
상위 레이어(``api``)를 import하는 역방향 의존이 생겨 서비스 레이어 규칙
(TECH_SPEC §16)을 스스로 위반하게 된다. 따라서 base 예외는 여기(레이어 중립
위치)에 정의하고, ``api/error_handlers.py``가 이 모듈을 import하여 HTTP
응답으로 변환한다.

구체 예외 클래스(``ValidationError`` 등 TECH_SPEC §12.1의 6종)는 각 계산·검증
로직을 구현하는 후행 이슈에서 ``AppError``를 상속해 정의한다. 본 이슈(#100)는
공통 base와 HTTP status 매핑까지만 확정한다.

참조:
- TECH_SPEC §12.1 오류 분류, §12.2 오류 전파 규칙
- API_SPEC §1.3.2 오류 응답 포맷, §1.4 HTTP Status Code 매핑
"""

from __future__ import annotations

# 오류 코드 → HTTP status 매핑.
# 값은 TECH_SPEC §12.1과 API_SPEC §1.4 표에서 그대로 복사한다. 임의 재작성 금지.
ERROR_HTTP_STATUS: dict[str, int] = {
    "BAD_REQUEST": 400,  # API_SPEC §1.4: JSON 파싱 오류, 잘못된 Content-Type
    "NOT_FOUND": 404,  # API_SPEC §1.4: 존재하지 않는 리소스 ID
    "PARAMETER_ERROR": 409,  # TECH_SPEC §12.1: 규정 파라미터 누락/불일치
    "VALIDATION_ERROR": 422,  # TECH_SPEC §12.1: VAL-001~010 위반
    "CALCULATION_ERROR": 422,  # TECH_SPEC §12.1: 분모 0, overflow, 유효하지 않은 결과
    "MODEL_BREAKDOWN_ERROR": 422,  # TECH_SPEC §12.1: BN > 8, ΔV/V ≥ 100%
    "STATE_TRANSITION_ERROR": 422,  # API_SPEC §1.4: 허용되지 않은 상태 전환 (PRD §8.1.1)
    "WEATHER_FETCH_ERROR": 422,  # TECH_SPEC §12.1: 기상 API 실패 + 사용자가 NONE fallback 거부
    "RATE_LIMIT_EXCEEDED": 429,  # API_SPEC §1.4: 분당 요청 한도 초과
    "INTERNAL_ERROR": 500,  # API_SPEC §1.4: 서버 내부 오류
    "REPRODUCIBILITY_ERROR": 500,  # TECH_SPEC §12.1: canonical test vector 불일치
}

# 매핑에 없는 코드의 기본 HTTP status.
DEFAULT_HTTP_STATUS = 500


class AppError(Exception):
    """모든 애플리케이션 도메인 예외의 base 클래스.

    하위 레이어에서 발생한 오류를 API 계층이 표준 에러 응답(API_SPEC §1.3.2)으로
    일관되게 변환할 수 있도록, 오류 코드와 사용자 메시지를 예외에 담는다.

    Args:
        code: API_SPEC §1.4의 오류 코드 문자열 (예: ``"VALIDATION_ERROR"``).
        message: 사용자에게 노출할 한국어 메시지.
        details: 필드별 상세 오류 목록. API_SPEC §1.3.2의 ``error.details`` 형식을
            따르는 dict 리스트. 필드 검증 오류가 아니면 ``None``.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: list[dict[str, object]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    @property
    def http_status(self) -> int:
        """이 오류에 대응하는 HTTP status code."""
        return ERROR_HTTP_STATUS.get(self.code, DEFAULT_HTTP_STATUS)
