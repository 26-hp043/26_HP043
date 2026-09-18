"""구조화 로그 설정 (#827 ⑵ · 결정요청 v9 회신 E-2 「나」).

## 무엇을 넣고 무엇을 안 넣는가 (결정 범위)

**구조화(JSON) 로그만 넣고 외부 전송은 하지 않는다.** 알림을 받아 대응할 상시
운영자가 없는 제품(10/10 뒤 개발 없음 · `API_SPEC §1.9`)에서 외부 전송은 관측성이
아니라 소음이다. 필요한 것은 「시연 중 화면이 이상했을 때 **사후에 되짚을 기록**」이고,
그것은 파일로 남는 JSON 한 줄이다. 나중에 전송만 붙이면 「가」(에러 추적)로 확장된다.

## 로그에 없는 것 — 비밀값

- **요청 본문을 남기지 않는다.** 접근 로그는 요약(method·path·status·duration·
  request_id·client)만 싣는다 — 로그인 비밀번호가 파일에落ち는 경로를 원천적으로
  없앤다.
- **쿼리스트링을 남기지 않는다.** ``verify-email?token=…`` 토큰이 로그로 새는 것이
  이슈 ⑵의 실측 결함이었다. path만 남긴다.
- :func:`tests` — 이 두 성질은 ``tests/test_structured_logs.py``가 잠근다.

## 파일 회전

``LOG_FILE`` 환경변수가 있을 때만 파일로 남긴다(프로덕션 compose가 설정한다).
``RotatingFileHandler`` — 10MB × 5개. 미설정이면 콘솔만(개발·검사 환경).

## uvicorn 접근 로그와의 관계

uvicorn 자체 접근 로그(``uvicorn.access``)는 **쿼리스트링이 없는 우리 접근 로그와
중복**이므로 WARNING으로 내린다. uvicorn이 자기 로거를 구성하는 시점은 앱 모듈
임포트(**이 함수가 부르는 자리**)보다 앞이므로, 여기서 내린 수준이 이긴다.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: 접근 로그가 찍히는 로거. 미들웨어가 이 이름으로 낸다 — OPERATIONS.md가 이 이름을 안내한다.
ACCESS_LOGGER = "cii_platform.access"

#: 파일 회전 — 10MB × 5개. 50MB를 넘지 않는다 (#827 ⑵ 체크리스트 「회전」).
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5


class JsonFormatter(logging.Formatter):
    """한 사건을 JSON 한 줄로 — 사람이 읽는 콘솔과 분리해 **그냥(grep·jq)으로 되짚기 위한** 형태.

    스택 트레이스(``exc_info``)는 ``exc`` 키에 문자열로 들어간다 — 예외 핸들러가
    남긴 기록에서 원인을 찾는 것이 이 파일의 주 용도다.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # 미들웨어가 extra로 싣는 접근 요약 — 있으면 펴서 담는다.
        for key in ("request_id", "method", "path", "status", "duration_ms", "client"):
            if (value := getattr(record, key, None)) is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    """루트 로깅을 구성한다 — ``cii_platform.api.main`` 임포트 시점에 한 번 부른다.

    - 콘솔: 짧은 텍스트(개발 가독성 — uvicorn 기본 출력과 같은 자리)
    - 파일(``LOG_FILE`` 설정 시): JSON 한 줄 · 회전 — **장애 대응은 이 파일을 본다**
    - ``uvicorn.access``는 WARNING으로 — 접근 로그는 우리 미들웨어가 쿼리스트링
      없이 남긴다 (위 모듈 docstring 참조)
    """
    level = os.environ.get("LOG_LEVEL", "INFO").upper()

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handlers: list[logging.Handler] = [console]

    log_file = os.environ.get("LOG_FILE")
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(JsonFormatter())
        handlers.append(file_handler)

    logging.basicConfig(level=level, handlers=handlers, force=True)

    # 쿼리스트링 없는 우리 접근 로그와 중복되는 uvicorn 접근 로그를 내린다.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
