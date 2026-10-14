"""TECH_SPEC §20의 보안 응답 헤더 (#2111 · CSP #2368).

HTTP 응답 시작만 수정해 CSV·PDF·스트리밍 본문과 여러 Set-Cookie를 보존한다.
ServerErrorMiddleware가 밖에서 만드는 500은 error_handlers가 같은 값을 사용한다.
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # API 응답은 JSON·CSV·PDF라 문서가 아니다 — 아무것도 불러오지 않는 정책이다.
    # 화면용 정책은 frontend/public/_headers가 갖는다 (TECH_SPEC §20).
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}

# 개발 환경에서만 열리는 Swagger UI는 외부 스크립트·인라인 스크립트를 쓴다 (main.py `docs_url`).
# 프로덕션은 이 경로를 만들지 않으므로(#593) 제외해도 운영 응답에는 영향이 없다.
_CSP_EXEMPT_PATHS = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect"})


class SecurityHeadersMiddleware:
    """인증·한도·CORS의 조기 응답도 포함해 HTTP 응답에 정책을 적용한다."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    if name == "Content-Security-Policy" and scope["path"] in _CSP_EXEMPT_PATHS:
                        continue
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)
