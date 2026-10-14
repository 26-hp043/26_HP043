"""NUL 문자 입력 거절 (#2501).

DB 드라이버(pycubrid)는 NUL(``\\x00``)이 든 문자열 파라미터를 ``ProgrammingError``로
거부한다. 어디서도 잡지 않으면 **500**이 나고, 이메일 형식 검사도 NUL을 통과시킨다.
필드마다 막으면 새 필드가 생길 때마다 구멍이 되므로, **요청이 라우트에 닿기 전 한 곳에서**
JSON 본문·쿼리 문자열·경로의 NUL을 422 ``VALIDATION_ERROR``로 거절한다.

## 범위

* JSON 본문(``application/json``)만 본다. multipart·CSV·바이너리(아바타)는 건드리지 않는다 —
  본문이 NUL을 정당하게 담는 형식이고, CSV 셀은 각 import 파서가 행 오류로 돌린다
  (``voyage_import.reject_nul_cells``).
* 파싱할 수 없는 JSON은 그대로 통과시킨다 — 기존 ``json_invalid`` 422가 처리한다.
* 인증 미들웨어보다 **안쪽**에 둔다. 비로그인 요청이 보호 경로에서 NUL 때문에 422가 되어
  401의 우선순위를 흐리지 않게 하려는 것이다(공개 경로인 로그인·가입은 여기까지 온다).
"""

from __future__ import annotations

import json
from urllib.parse import parse_qsl, unquote_to_bytes

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from cii_platform.api.error_handlers import to_error_response
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.errors import ERROR_HTTP_STATUS
from cii_platform.validation.field_labels import field_label_for_route

#: 오류 문구. 정본 문구는 아니다 — 필드 라벨은 ``details``에 따로 실린다.
NUL_MESSAGE = "입력에 쓸 수 없는 문자(NUL)가 들어 있습니다."

#: JSON에서 NUL이 취할 수 있는 표기는 ``\u0000`` 하나다(숫자가 모두 0이라 대소문자 무관).
_JSON_NUL_ESCAPE = b"\\u0000"


def _find_nul(value: object, path: str = "") -> str | None:
    """JSON 값 안에서 NUL이 든 첫 문자열의 필드 경로를 돌려준다. 없으면 ``None``.

    경로는 ``fuel_uses[0].fuel_type``처럼 :func:`error_handlers._field_path`와 같은 모양이다.
    키에 NUL이 있으면 그 키가 속한 객체의 경로를 돌려준다(키 이름 자체를 노출하지 않는다).
    """
    if isinstance(value, str):
        return path if "\x00" in value else None
    if isinstance(value, dict):
        for key, item in value.items():
            if "\x00" in key:
                return path
            found = _find_nul(item, f"{path}.{key}" if path else key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found = _find_nul(item, f"{path}[{index}]")
            if found is not None:
                return found
    return None


def _is_json(scope: Scope) -> bool:
    """FastAPI가 JSON으로 읽는 본문인가 — ``application/json``과 ``+json`` 계열 모두.

    접두사만 보면 ``application/problem+json``·``application/vnd.api+json``이 빠지는데,
    FastAPI는 그 형태도 JSON으로 파싱해 라우트까지 보낸다 — 가드를 우회해 500이 났다
    (머지 전 검토에서 재현). 파라미터(``; charset=…``)는 떼고 소문자로 비교한다.
    """
    for name, value in scope["headers"]:
        if name == b"content-type":
            media = value.split(b";", 1)[0].strip().lower()
            return media == b"application/json" or (
                media.startswith(b"application/") and media.endswith(b"+json")
            )
    return False


class NulGuardMiddleware:
    """JSON 본문·쿼리·경로의 NUL을 라우트 앞에서 422로 거절한다 (순수 ASGI)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        field = self._nul_in_url(scope)
        if field is None and _is_json(scope):
            body, receive = await self._buffer_body(receive)
            if _JSON_NUL_ESCAPE in body or b"\x00" in body:
                field = self._nul_in_body(body)

        if field is None:
            await self.app(scope, receive, send)
            return
        await self._reject(scope, field)(scope, receive, send)

    @staticmethod
    def _nul_in_url(scope: Scope) -> str | None:
        """경로·쿼리 문자열의 NUL. 걸린 쿼리 파라미터 이름(경로면 빈 문자열)을 돌려준다."""
        if "\x00" in scope.get("path", ""):
            return ""
        query = scope.get("query_string", b"")
        if b"%00" not in query.lower() and b"\x00" not in query:
            return None
        for name, value in parse_qsl(
            unquote_to_bytes(query).decode("latin-1"), keep_blank_values=True
        ):
            if "\x00" in name or "\x00" in value:
                return "" if "\x00" in name else name
        return None

    @staticmethod
    def _nul_in_body(body: bytes) -> str | None:
        """파싱되는 JSON이면 NUL이 든 필드 경로를, 아니면 ``None``(검증기에 맡긴다)."""
        try:
            return _find_nul(json.loads(body))
        except (ValueError, RecursionError):
            # 깨진 JSON은 검증기(`json_invalid` 422)에, 지나치게 깊은 중첩도 검증기에 맡긴다.
            return None

    @staticmethod
    async def _buffer_body(receive: Receive) -> tuple[bytes, Receive]:
        """본문을 끝까지 받아 두고, 같은 내용을 다시 내주는 ``receive``를 만든다."""
        chunks: list[bytes] = []
        while True:
            message = await receive()
            if message["type"] != "http.request":
                # 본문 도중 연결이 끊겼다 — 받은 것 없이 그 메시지를 그대로 되먹인다.
                return b"", _replay(message, receive)
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        return body, _replay({"type": "http.request", "body": body, "more_body": False}, receive)

    @staticmethod
    def _reject(scope: Scope, field: str) -> JSONResponse:
        state = scope.get("state") or {}
        path = scope.get("path", "")
        # 필드를 특정하지 못하면(본문 최상위 · 경로) 라벨은 생략하지 않고 「요청」으로 둔다.
        label = field_label_for_route(path, field) if field else "요청 본문"
        body = to_error_response(
            "VALIDATION_ERROR",
            NUL_MESSAGE,
            details=[{"field": field, "field_label": label, "message": NUL_MESSAGE}],
            request_id=state.get("request_id"),
            timestamp=state.get("timestamp") or iso_utc_now(),
        )
        return JSONResponse(status_code=ERROR_HTTP_STATUS["VALIDATION_ERROR"], content=body)


def _replay(first: Message, receive: Receive) -> Receive:
    """``first``를 한 번 내주고 이후는 원래 ``receive``에 맡긴다(연결 끊김 통지 보존)."""
    pending: list[Message] = [first]

    async def replay() -> Message:
        if pending:
            return pending.pop()
        return await receive()

    return replay
