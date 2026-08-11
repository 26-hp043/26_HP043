"""API 계층 오류 처리 (에러 핸들러 등록 진입점).

하위 레이어에서 발생한 :class:`~cii_platform.errors.AppError`를 API_SPEC §1.3.2
표준 오류 응답으로 변환한다. 이 모듈은 ``errors`` 모듈을 import하지만, 하위
레이어(``calc``/``services``/``db``)는 이 모듈을 import하지 않는다(계층 방향 준수,
TECH_SPEC §16).

#100이 변환 함수 :func:`to_error_response`와 base 예외 핸들러를, #49가 FastAPI ``app``
배선을 맡았다. **#116이 남은 두 경로를 채운다** — Pydantic 검증 실패
(``RequestValidationError``)와 어디에도 잡히지 않은 예외(catch-all).

이 둘이 없으면 다음이 깨진다.

- FastAPI 기본 422 응답은 ``{"detail": [...]}`` 형태다. **API_SPEC §1.3.2와 구조가
  다르므로** 화면이 필드별 메시지를 꺼낼 수 없다.
- 잡히지 않은 예외는 Starlette 기본 500 HTML을 낸다. JSON을 기대하는 클라이언트가
  파싱에 실패하고, **traceback이 응답에 실릴 수 있다.**

참조:
- API_SPEC §1.3.2 오류 응답 포맷, §1.4 HTTP Status Code 매핑, §11 검증 규칙
- TECH_SPEC §12.1 오류 분류, §12.2 오류 전파 규칙
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from cii_platform.api.field_labels import field_label
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.errors import ERROR_HTTP_STATUS, AppError

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

logger = logging.getLogger(__name__)


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

    API_SPEC §1.3.2 예시는 meta 값이 문자열임을 전제하므로, 값이 없는
    meta 키는 null로 내리지 않고 생략한다.
    """
    error: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    meta: dict[str, object] = {}
    if request_id is not None:
        meta["request_id"] = request_id
    if timestamp is not None:
        meta["timestamp"] = timestamp
    return {"error": error, "meta": meta}


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """:class:`AppError`(및 하위 클래스)를 표준 오류 응답으로 변환하는 핸들러.

    HTTP status는 :attr:`AppError.http_status`(= TECH_SPEC §12.1 매핑)에서 가져온다.
    """
    state = getattr(request, "state", None)
    request_id = getattr(state, "request_id", None)
    # 미들웨어(#49)가 주입한 값을 우선하되, 없으면 동일 포맷 헬퍼로 채운다.
    # API_SPEC §1.3.2가 timestamp를 ISO8601 문자열로 전제하므로 null로 내리지 않는다.
    timestamp = getattr(state, "timestamp", None) or iso_utc_now()
    body = to_error_response(
        exc.code,
        exc.message,
        details=exc.details,
        request_id=request_id,
        timestamp=timestamp,
    )
    return JSONResponse(status_code=exc.http_status, content=body)


# --- #116: Pydantic 검증 실패 -------------------------------------------------------

#: ``RequestValidationError``의 HTTP status. API_SPEC §1.4 ``VALIDATION_ERROR`` 행.
#: 값을 여기 박지 않고 매핑에서 가져온다 — 두 곳에 적으면 갈린다.
_VALIDATION_STATUS = ERROR_HTTP_STATUS["VALIDATION_ERROR"]

#: 본문 필드 오류의 ``loc``은 ``("body", "distance_nm")``처럼 시작한다.
#: 앞의 출처 표시는 필드 경로가 아니므로 떼어 낸다.
_LOC_PREFIXES = frozenset({"body", "query", "path", "header", "cookie"})


def _field_path(loc: tuple[object, ...]) -> str:
    """Pydantic ``loc`` 튜플을 요청 본문 기준 필드 경로로 만든다.

    ``("body", "fuel_uses", 0, "fuel_ton")`` → ``"fuel_uses[0].fuel_ton"``

    **배열 인덱스를 대괄호로 적는 이유**: 화면이 이 경로를 그대로 입력창에 매핑한다
    (#135 ``VoyageCiiError.field``). 점 표기(``fuel_uses.0.fuel_ton``)로 내려보내면
    화면 쪽에 변환 규칙이 하나 더 생긴다.
    """
    parts = list(loc)
    if parts and isinstance(parts[0], str) and parts[0] in _LOC_PREFIXES:
        parts = parts[1:]
    if not parts:
        return ""

    path = str(parts[0])
    for part in parts[1:]:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path


def _validation_details(exc: RequestValidationError) -> list[dict[str, object]]:
    """Pydantic 오류를 API_SPEC §1.3.2 ``details[]`` 형식으로 옮긴다.

    ``rule``은 넣지 않는다. §1.3.2 예시에는 있으나 **Pydantic 오류에서 VAL 번호를
    유도할 수 없고**, 임의로 붙이면 근거 없는 규칙 번호가 응답에 실린다. VAL 번호가
    필요한 검증은 서비스 계층이 :class:`~cii_platform.errors.ValidationError`로
    직접 던지며 그쪽에서 ``details``를 구성한다.

    ``field_label``은 :func:`~cii_platform.api.field_labels.field_label`이 채운다.
    미등록 필드는 필드명 원문이 그대로 돌아온다(조회 실패 계약).
    """
    details: list[dict[str, object]] = []
    for error in exc.errors():
        field = _field_path(tuple(error.get("loc", ())))
        entry: dict[str, object] = {
            "field": field,
            "field_label": field_label(field),
            "message": str(error.get("msg", "")),
        }
        details.append(entry)
    return details


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Pydantic 검증 실패를 API_SPEC §1.3.2 응답으로 변환한다 (#116).

    **FastAPI 기본 핸들러를 그대로 두면 안 되는 이유**: 기본 응답은
    ``{"detail": [{"loc": [...], "msg": ..., "type": ...}]}``이고 §1.3.2의
    ``{"error": {...}, "meta": {...}}``와 구조가 다르다. 화면(#135·#138)은 §1.3.2를
    전제로 필드별 메시지를 꺼내므로 기본 응답에서는 아무것도 표시하지 못한다.

    ``message``는 첫 오류 문구를 쓴다 — 여러 필드가 동시에 틀렸을 때 대표 문구가
    필요하고, 전체 목록은 ``details``에 그대로 있다.
    """
    details = _validation_details(exc)
    message = str(details[0]["message"]) if details else "요청 값이 올바르지 않습니다."
    state = getattr(request, "state", None)
    body = to_error_response(
        "VALIDATION_ERROR",
        message,
        details=details,
        request_id=getattr(state, "request_id", None),
        timestamp=getattr(state, "timestamp", None) or iso_utc_now(),
    )
    return JSONResponse(status_code=_VALIDATION_STATUS, content=body)


# --- #116: catch-all ----------------------------------------------------------------

#: 클라이언트에게 보이는 500 문구. **내부 정보를 담지 않는다.**
INTERNAL_ERROR_MESSAGE = "서버 내부 오류가 발생했습니다."


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """어디에도 잡히지 않은 예외를 500 ``INTERNAL_ERROR``로 변환한다 (#116).

    **예외 내용을 응답에 넣지 않는다.** 메시지·traceback에는 파일 경로·SQL·값이
    섞여 있을 수 있고, 그것이 그대로 나가면 정보 노출이 된다. 대신 ``logger.exception``
    으로 서버 로그에 남겨 ``request_id``로 추적할 수 있게 한다.

    이 핸들러가 없으면 Starlette 기본 500 **HTML**이 나가고, JSON을 기대하는
    클라이언트가 파싱 단계에서 실패한다.
    """
    state = getattr(request, "state", None)
    request_id = getattr(state, "request_id", None)
    logger.exception("unhandled error (request_id=%s)", request_id, exc_info=exc)
    body = to_error_response(
        "INTERNAL_ERROR",
        INTERNAL_ERROR_MESSAGE,
        request_id=request_id,
        timestamp=getattr(state, "timestamp", None) or iso_utc_now(),
    )
    return JSONResponse(status_code=ERROR_HTTP_STATUS["INTERNAL_ERROR"], content=body)


# --- #183: HTTPException -----------------------------------------------------------

#: HTTPException의 status → error_code 매핑. API_SPEC §1.4에서 HTTP status ↔ 코드가
#: 1:1인 행만 발췌한다. 422(5개)·500(2개)는 1:1이 아니므로 status만으로 결정할 수
#: 없어 표에 넣지 않는다 — 코드는 status가 아닌 원인에서 유래한다.
#: 405는 #182에서 ``METHOD_NOT_ALLOWED``로 확정됐다 (#183 착수 시점엔 미확정).
_HTTP_EXCEPTION_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "PARAMETER_ERROR",
    429: "RATE_LIMIT_EXCEEDED",
}

#: 미등록 status(403·415 등)에 쓸 범용 코드 (#182 §1.4 신설).
_HTTP_ERROR_CODE = "HTTP_ERROR"

#: 프레임워크가 status phrase로 만든 기본 detail(예: ``"Not Found"``)을 대체할
#: 한국어 문구 (#182 §1.4 정책 노트). 명시적 detail은 이 표를 타지 않는다.
_FRAMEWORK_DEFAULT_MESSAGES: dict[int, str] = {
    404: "요청한 경로를 찾을 수 없습니다.",
    405: "허용되지 않은 HTTP 메서드입니다.",
}

#: 위 표에 없는 status(미등록 status)의 범용 문구 (#182 §1.4 정책 노트).
_HTTP_ERROR_MESSAGE = "요청을 처리할 수 없습니다."


def _resolve_error_code(status: int) -> str:
    """HTTPException의 status를 error_code로 변환한다 (#183).

    §1.4 표에서 1:1인 status만 매핑하고, 그 외(422·500·미등록)는 범용
    ``HTTP_ERROR``로 떨어진다.
    """
    return _HTTP_EXCEPTION_CODES.get(status, _HTTP_ERROR_CODE)


def _status_phrase(status: int) -> str:
    """HTTPStatus를 활용해 프레임워크 기본 detail을 재현한다 (#183).

    Starlette은 ``HTTPException``의 ``detail``이 없으면 status phrase(예: 404 →
    ``'Not Found'``)를 채운다. 응답에 직접 쓰지 않고, 아래 :func:`_is_framework_default`
    에서 프레임워크 기본값 판별에만 사용한다. 비표준 status(예: 499)는 phrase가
    없으므로 빈 문자열을 돌려준다.
    """
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return ""


def _is_framework_default(exc: StarletteHTTPException) -> bool:
    """``detail``이 프레임워크가 status phrase로 만든 기본값인지 판별한다 (#183)."""
    return exc.detail == _status_phrase(exc.status_code)


def _resolve_message(exc: StarletteHTTPException) -> str:
    """HTTPException의 사용자 노출 문구를 결정한다 (#183).

    - 프레임워크가 status phrase로 만든 기본 detail(예: ``'Not Found'``)이면
      #182가 정한 한국어 문구로 바꾼다. 미등록 status는 범용 문구를 쓴다.
    - 라우트가 명시적으로 넣은 detail(예: ``HTTPException(422, "bad")``)은
      그대로 보존한다 — 개발자 작성 문구를 임의로 덮지 않는다.
    """
    if _is_framework_default(exc):
        return _FRAMEWORK_DEFAULT_MESSAGES.get(exc.status_code, _HTTP_ERROR_MESSAGE)
    return str(exc.detail)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Starlette/FastAPI의 ``HTTPException``을 API_SPEC §1.3.2 응답으로 변환한다 (#183).

    프레임워크 404·405와 라우트가 던진 명시적 ``HTTPException``이 그대로
    ``{"detail": ...}``로 나가던 것을 §1.3.2 구조로 고친다. ``status_code``와
    ``headers``(405의 ``Allow``, 401의 ``WWW-Authenticate``)는 **그대로 보존**한다 —
    바꾸면 HTTP 규격과 클라이언트 동작이 틀어진다.
    """
    state = getattr(request, "state", None)
    body = to_error_response(
        _resolve_error_code(exc.status_code),
        _resolve_message(exc),
        request_id=getattr(state, "request_id", None),
        timestamp=getattr(state, "timestamp", None) or iso_utc_now(),
    )
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)


def register_exception_handlers(app: FastAPI) -> None:
    """FastAPI ``app``에 오류 핸들러를 등록한다.

    #49(FastAPI app 구성)가 app 생성 직후 이 함수를 호출한다.

    등록 순서가 아니라 **예외 타입의 구체성**이 우선순위를 정한다. Starlette는
    등록된 핸들러 중 예외의 MRO에서 가장 먼저 일치하는 것을 고르므로,
    :class:`AppError`가 :class:`Exception`보다 앞선다 — catch-all이 도메인 오류를
    가로채지 않는다.

    구체 예외 6종(TECH_SPEC §12.1)은 모두 :class:`AppError`를 상속하므로 base 핸들러
    하나로 일괄 변환된다.
    """
    app.add_exception_handler(AppError, app_error_handler)
    # #183: Starlette 기준 등록 — FastAPI HTTPException이 이를 상속하므로 둘 다 덮는다.
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    # #116: FastAPI 기본 422 응답 형태를 §1.3.2로 교체.
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    # #116: 마지막 안전망. 위 두 핸들러가 잡지 못한 것만 여기로 온다.
    app.add_exception_handler(Exception, unhandled_error_handler)
