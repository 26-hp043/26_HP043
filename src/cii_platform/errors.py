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
    "UNAUTHORIZED": 401,  # API_SPEC §1.4: 세션 없음·만료·무횜 (#275)
    "CSRF_ERROR": 403,  # API_SPEC §1.4: CSRF 토큰 누락·불일치 (#275)
    "NOT_FOUND": 404,  # API_SPEC §1.4: 존재하지 않는 리소스 ID
    "PARAMETER_ERROR": 409,  # TECH_SPEC §12.1: 규정 파라미터 누락/불일치
    "CONFLICT": 409,  # API_SPEC §1.4: 리소스 중복 (동일 IMO 재등록 등)
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


class ValidationError(AppError):
    """VAL-001~010 위반 (TECH_SPEC §12.1).

    필수값 누락, 범위 초과, NaN/Infinity. HTTP 422.

    ``field``를 받는 이유는 화면이 **해당 입력창 아래에** 메시지를 붙이기 때문이다
    (API_SPEC §1.3.2 ``details[].field``). ``field``가 있으면 ``details`` 한 건을
    자동으로 구성한다 — 호출부마다 dict를 손으로 만들면 형식이 갈린다.

    ``field_label``은 :mod:`cii_platform.api.field_labels`가 아니라 호출부에서
    주입한다. ``errors``는 레이어 중립 모듈이라 ``api`` 패키지를 import할 수 없다
    (TECH_SPEC §16 계층 방향).
    """

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        field_label: str | None = None,
        details: list[dict[str, object]] | None = None,
    ) -> None:
        if details is None and field is not None:
            entry: dict[str, object] = {"field": field, "message": message}
            if field_label is not None:
                entry["field_label"] = field_label
            details = [entry]
        super().__init__("VALIDATION_ERROR", message, details=details)
        self.field = field


class ParameterError(AppError):
    """규정 파라미터 누락·불일치 (TECH_SPEC §12.1). HTTP 409.

    **입력이 아니라 서버 데이터의 문제다.** 사용자가 요청을 고쳐도 해결되지 않으므로
    422가 아니라 409다 — 규정 파라미터 seed(``scripts/seed.py``)가 적재되지 않았거나
    해당 선종·연도의 행이 없는 상태다.
    """

    def __init__(self, message: str, *, details: list[dict[str, object]] | None = None) -> None:
        super().__init__("PARAMETER_ERROR", message, details=details)


class ConflictError(AppError):
    """리소스 중복 (API_SPEC §1.4). HTTP 409.

    ``PARAMETER_ERROR``(규정 파라미터 문제)와 **같은 409지만 다른 code**다.
    클라이언트가 code로 분기할 때 중복 IMO 등록을 파라미터 문제로 오인하지 않게
    분리한다 (#286).
    """

    def __init__(self, message: str, *, details: list[dict[str, object]] | None = None) -> None:
        super().__init__("CONFLICT", message, details=details)


class CalculationError(AppError):
    """분모 0, overflow, 유효하지 않은 결과 (TECH_SPEC §12.1). HTTP 422.

    입력 검증을 통과한 뒤 계산 단계에서 드러나는 문제다. Layer 1 엔진이 던지는
    ``ValueError``를 서비스 계층이 이 예외로 옮긴다 — ``ValueError``가 그대로 위로
    올라가면 500이 되어 「서버 오류」로 보고되지만, 실제로는 입력이 만든 상태다.
    """

    def __init__(self, message: str, *, details: list[dict[str, object]] | None = None) -> None:
        super().__init__("CALCULATION_ERROR", message, details=details)


class NotFoundError(AppError):
    """존재하지 않는 리소스 (API_SPEC §1.4). HTTP 404."""

    def __init__(self, message: str, *, details: list[dict[str, object]] | None = None) -> None:
        super().__init__("NOT_FOUND", message, details=details)


class RateLimitError(AppError):
    """분당 요청 한도 초과 (API_SPEC §1.4 · §13.2). HTTP 429.

    MVP는 인증이 없어 IP 기반으로 적용한다(#238). 인증(#104) 도입 시 user_id 기반으로
    확장한다 — 그때 이 예외의 메시지에 user_id를 포함한다.
    """

    def __init__(self, message: str, *, details: list[dict[str, object]] | None = None) -> None:
        super().__init__("RATE_LIMIT_EXCEEDED", message, details=details)
