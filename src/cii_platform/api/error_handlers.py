"""API 계층 오류 처리 (에러 핸들러 등록 진입점).

하위 레이어에서 발생한 :class:`~cii_platform.errors.AppError`를 API_SPEC §1.3.2
표준 오류 응답으로 변환한다. 이 모듈은 ``errors`` 모듈을 import하지만, 하위
레이어(``calc``/``services``/``db``)는 이 모듈을 import하지 않는다(계층 방향 준수,
TECH_SPEC §16).

본 이슈(#100) 범위: 변환 함수 :func:`to_error_response`, base 예외 핸들러,
등록 진입점 :func:`register_exception_handlers`의 골격까지. 실제 FastAPI ``app``에
핸들러를 붙이는 호출은 후행 이슈 #49(FastAPI app 구성)에서 수행한다.

참조:
- API_SPEC §1.3.2 오류 응답 포맷, §1.4 HTTP Status Code 매핑
- TECH_SPEC §12.1 오류 분류, §12.2 오류 전파 규칙
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse

from cii_platform.errors import AppError

if TYPE_CHECKING:
    from fastapi import FastAPI, Request


def to_error_response(
    code: str,
    message: str,
    *,
    details: list[dict[str, object]] | None = None,
    request_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, object]:
    """API_SPEC §1.3.2 형식의 오류 응답 본문(dict)을 생성한다.

    수치·포맷을 임의로 만들지 않고 API_SPEC §1.3.2 구조를 그대로 따른다::

        {"error": {"code", "message", "details"?}, "meta": {"request_id", "timestamp"}}

    Args:
        code: API_SPEC §1.4 오류 코드.
        message: 사용자에게 노출할 한국어 메시지.
        details: 필드별 상세 오류 목록. 없으면 응답에서 생략한다.
        request_id: 요청 추적 ID. 미들웨어에서 주입한다.
        timestamp: 응답 생성 시각(UTC ISO8601). 미들웨어에서 주입한다.

    Returns:
        JSON 직렬화 가능한 오류 응답 dict.
    """
    error: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {
        "error": error,
        "meta": {"request_id": request_id, "timestamp": timestamp},
    }


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """:class:`AppError`(및 하위 클래스)를 표준 오류 응답으로 변환하는 핸들러.

    HTTP status는 :attr:`AppError.http_status`(= TECH_SPEC §12.1 매핑)에서 가져온다.
    """
    request_id = getattr(getattr(request, "state", None), "request_id", None)
    body = to_error_response(
        exc.code,
        exc.message,
        details=exc.details,
        request_id=request_id,
    )
    return JSONResponse(status_code=exc.http_status, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    """FastAPI ``app``에 오류 핸들러를 등록한다.

    후행 이슈 #49(FastAPI app 구성)에서 app 생성 직후 이 함수를 호출한다.
    구체 예외 6종(TECH_SPEC §12.1)은 모두 :class:`AppError`를 상속하므로,
    base 핸들러 하나로 일괄 변환된다. 개별 예외에 특수 처리가 필요해지면 후행
    이슈에서 핸들러를 추가 등록한다.
    """
    app.add_exception_handler(AppError, app_error_handler)
