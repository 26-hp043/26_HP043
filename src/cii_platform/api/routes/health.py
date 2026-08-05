"""Health check 라우트 (API_SPEC §10).

로드 밸런서·모니터링용 엔드포인트. 인증 불필요. 응답은 §10의 ``data`` envelope를
따르며, §1.3.1의 ``meta``(request_id/timestamp)는 §10 규정상 포함하지 않는다.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

import numpy
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@lru_cache(maxsize=1)
def _app_version() -> str:
    """앱 배포 패키지 버전을 반환한다 (pyproject 단일 소스).

    1순위는 설치된 dist metadata다. 미설치 환경(``tests/conftest.py``가 ``sys.path``에
    ``src/``를 넣어 설치 없이도 실행되는 경우)에서는 저장소의 ``pyproject.toml``을
    직접 읽어 폴백한다. 둘 다 실패하면 ``"unknown"``을 반환한다.

    폴백 실패 시에도 예외를 던지지 않는다 — health 엔드포인트가 버전 조회 때문에
    500이 되는 것을 막는다.

    ``lru_cache``로 프로세스당 한 번만 계산한다. health는 로드 밸런서가 주기적으로
    호출하므로 매 요청 파일 I/O를 하지 않는다.
    """
    try:
        return _pkg_version("cii-platform")
    except PackageNotFoundError:
        pass

    # 이 파일 기준 상위 4단계가 저장소 루트다:
    # src/cii_platform/api/routes/health.py → routes → api → cii_platform → src → 루트
    # 컨테이너에서도 성립한다(Dockerfile이 pyproject.toml을 /app에 복사).
    pyproject = Path(__file__).resolve().parents[4] / "pyproject.toml"
    try:
        with pyproject.open("rb") as fh:
            return str(tomllib.load(fh)["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"


@router.get("/health")
async def health() -> dict[str, dict[str, str]]:
    """서비스 상태를 반환한다 (API_SPEC §10)."""
    return {
        "data": {
            "status": "ok",
            "version": _app_version(),
            "numpy_version": numpy.__version__,
            # TODO(#43): rng_canonical_test 필드 추가 (§10). PCG64DXSM canonical
            # vector 검증이 #43 범위라 미구현이므로, 거짓 "passed"를 내지 않기 위해
            # 지금은 생략한다. #43 착수 시 이 응답에 필드를 추가할 것.
        }
    }
