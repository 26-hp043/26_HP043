"""구조화 로그 (#827 ⑵ · 결정요청 v9 회신 E-2 「나」) — 로그에 비밀이 없는가.

잠그는 것 세 가지:

1. **쿼리스트링이 로그에 없다** — ``verify-email?token=…``의 토큰이 로그로 새는
   것이 이 이슈 ⑵의 실측 결함이었다(#827 본문 「로그 위생」).
2. **요청 본문이 로그에 없다** — 로그인 비밀번호가 파일에落ち는 경로를 원천적으로
   막는다. 접근 로그는 요약(method·path·status·duration·request_id)만 싣는다.
3. **JSON 형태가 약속대로다** — 사후 되짚기(grep·jq)에 필요한 키가 매 줄에 있다.
   예외 기록은 ``exc`` 키에 스택이 들어간다.

로그 캡처는 로거에 핸들러를 직접 붙인다 — 파일로 남기는 건 프로덕션 배선
(``LOG_FILE``)이고 검사는 형태를 보는 것이므로 파일이 필요 없다.


⚠️ **파일 이름에 ``_db``가 붙어 있다** (`#1350`). 이 파일의 검사 하나
(:func:`test_request_body_never_reaches_the_log`)가 ``/api/v1/auth/login``을 실제로
불러 **DB를 쓴다.** 접미사가 없던 동안 「DB 없이 돌리는 묶음」에 섞여
``ConnectionRefusedError``로 혼자 실패했다 — 그 실패는 **코드가 아니라 실행 방식**을
가리키는데, 이름이 그 사실을 말하지 않았다.
"""

from __future__ import annotations

import json
import logging
import logging.handlers

import pytest
from fastapi.testclient import TestClient

from cii_platform.api.main import app
from cii_platform.log_config import ACCESS_LOGGER, JsonFormatter


class _Capture(logging.Handler):
    """포매터를 거친 최종 문자열을 모은다 — 파일 핸들러와 같은 위치에서 본다."""

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


@pytest.fixture
def access_lines():
    logger = logging.getLogger(ACCESS_LOGGER)
    capture = _Capture()
    logger.addHandler(capture)
    try:
        with TestClient(app, base_url="https://testserver") as client:
            yield client, capture.lines
    finally:
        logger.removeHandler(capture)


def _json_lines(lines: list[str]) -> list[dict]:
    return [json.loads(line) for line in lines]


def test_access_log_is_json_with_the_promised_keys(access_lines):
    """요약 한 줄이 JSON으로 — ts·level·request_id·method·path·status·duration."""
    client, lines = access_lines
    client.get("/api/v1/health")

    records = [r for r in _json_lines(lines) if r.get("path") == "/api/v1/health"]
    assert records, "접근 로그가 나오지 않았다"
    record = records[-1]
    assert record["status"] == 200
    assert record["method"] == "GET"
    assert isinstance(record["request_id"], str) and record["request_id"]
    assert isinstance(record["duration_ms"], (int, float))


def test_query_string_never_reaches_the_log(access_lines):
    """⑵의 실측 결함 — 토큰이 쿼리로 와도 로그에는 path만 남는다."""
    client, lines = access_lines
    secret = "ae_SUPER_SECRET_TOKEN_VALUE"
    client.get(f"/api/v1/auth/verify-email?token={secret}", follow_redirects=False)

    for raw in lines:
        assert secret not in raw, "쿼리스트링 값이 로그에 나왔다"
    for record in _json_lines(lines):
        assert "?" not in record.get("path", ""), "path에 쿼리스트링이 붙었다"


def test_request_body_never_reaches_the_log(access_lines):
    """로그인 비밀번호가 본문에 있어도 로그는 요약만 — 값이 파일로 흐르지 않는다."""
    client, lines = access_lines
    password = "correct-horse-battery-staple-DO-NOT-LOG"
    client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": password},
    )

    for line in lines:
        assert password not in line, "요청 본문이 로그에 나왔다"


def test_5xx_access_line_is_error_level():
    """5xx 접근은 ERROR — 장애 되짚기 때 level로 먼저 거른다.

    본앱(main.app)에 부운 라우트를 얹으면 인증 미들웨어가 먼저 401을 내린다
    (PUBLIC_PATHS는 exact match). 그래서 **미들웨어만** 갖춘 작은 앱으로 본다 —
    관찰 대상은 RequestContextMiddleware의 접근 로그다.
    """
    from fastapi import FastAPI
    from starlette.testclient import TestClient as _Client

    from cii_platform.api.middleware import RequestContextMiddleware

    def boom() -> None:
        raise RuntimeError("boom-for-log-test")

    small = FastAPI()
    small.add_api_route("/api/v1/health", lambda: {"ok": True})
    small.add_api_route("/api/v1/boom", boom)
    small.add_middleware(RequestContextMiddleware)

    # 본앱은 register_exception_handlers가 Exception catch-all을 등록한다 —
    # 그래야 예외가 RequestContextMiddleware **안쪽**에서 500 응답으로 바뀌고
    # 접근 로그가 남는다(미들웨어 스택: ServerError > 사용자 미들웨어 > Exception).
    from starlette.responses import JSONResponse

    small.add_exception_handler(
        Exception, lambda req, exc: JSONResponse({"detail": "boom"}, status_code=500)
    )

    logger = logging.getLogger(ACCESS_LOGGER)
    capture = _Capture()
    logger.addHandler(capture)
    try:
        with _Client(small, base_url="https://testserver", raise_server_exceptions=False) as c:
            assert c.get("/api/v1/health").status_code == 200
            assert c.get("/api/v1/boom").status_code == 500
    finally:
        logger.removeHandler(capture)

    records = {r["path"]: r for r in _json_lines(capture.lines)}
    assert records["/api/v1/health"]["level"] == "INFO"
    assert records["/api/v1/boom"]["status"] == 500
    assert records["/api/v1/boom"]["level"] == "ERROR"


def test_exception_records_carry_the_stack():
    """예외 기록은 exc 키에 스택 — 사후 원인 파악의 핵심 (단위 · HTTP 불필요)."""
    formatter = JsonFormatter()
    record: logging.LogRecord | None = None
    try:
        raise ValueError("boom-stack")
    except ValueError:
        record = logging.LogRecord(
            "cii_platform.test",
            logging.ERROR,
            __file__,
            1,
            "unhandled",
            None,
            __import__("sys").exc_info(),
        )
    assert record is not None
    payload = json.loads(formatter.format(record))
    assert "boom-stack" in payload["exc"]
    assert "Traceback" in payload["exc"]


def test_uvicorn_access_logger_is_demoted():
    """uvicorn 접근 로그는 우리 것과 중복 — WARNING으로 내려져 있다(setup_logging)."""
    assert logging.getLogger("uvicorn.access").level >= logging.WARNING


def test_unwritable_log_file_does_not_kill_the_app(monkeypatch):
    """🔴 관측이 서비스를 죽이면 본말이 전도된다 — 파일을 못 열면 콘솔만 쓰고 산다.

    실측 배경: 볼륨이 root 소유로 마운트돼 앱이 PermissionError 재시작 루프에 빠졌다
    (CI docker 잡). 이미지 chown이 1차 방어, 이 경로가 2차 방어다.
    """
    from cii_platform.log_config import setup_logging

    monkeypatch.setenv("LOG_FILE", "/proc/cannot/exist/api.jsonl")
    try:
        setup_logging()  # 예외 없이 콘솔만으로 돌아간다
    finally:
        root = logging.getLogger()
        assert not any(
            isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers
        ), "열 수 없는 파일의 핸들러가 붙어 있다"
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
