"""Health check 라우트 (API_SPEC §10).

로드 밸런서·모니터링용 엔드포인트. 인증 불필요. 응답은 §10의 ``data`` envelope를
따르며, §1.3.1의 ``meta``(request_id/timestamp)는 §10 규정상 포함하지 않는다.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

import numpy
from fastapi import APIRouter

router = APIRouter(tags=["health"])


def _app_version() -> str:
    """설치된 패키지 메타데이터에서 앱 버전을 읽는다(pyproject 단일 소스)."""
    try:
        return _pkg_version("cii-platform")
    except PackageNotFoundError:  # pragma: no cover - 설치 전 방어
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
