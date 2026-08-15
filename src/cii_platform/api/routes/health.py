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

from cii_platform.calc.rng import validate_rng

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


@lru_cache(maxsize=1)
def _rng_canonical_test() -> str:
    """canonical vector 재현 결과를 ``"passed"`` / ``"failed"``로 반환한다 (#400).

    :func:`cii_platform.calc.rng.validate_rng`가 PCG64DXSM(seed=12345)의 첫 5개
    uniform 값을 ``TECH_SPEC §2.5.1``의 실측값과 ``1e-15`` 이내로 대조한다 (#43).

    **프로세스당 한 번만 계산한다.** canonical vector는 NumPy 버전과 플랫폼에서
    결정되며 둘 다 프로세스 수명 동안 바뀌지 않는다 — 요청마다 난수를 뽑는 것은
    비용만 든다. health는 로드 밸런서가 주기적으로 호출한다.

    ``AssertionError``만이 아니라 모든 예외를 ``"failed"``로 옮긴다. 이 필드 하나
    때문에 health가 500이 되면 **오케스트레이터가 컨테이너를 죽인다** — 재현성
    문제를 보고하려다 가용성을 깎는다.
    """
    try:
        validate_rng()
    except Exception:  # noqa: BLE001 — 진단 필드가 엔드포인트를 죽이지 않게 한다
        return "failed"
    return "passed"


@router.get("/health")
async def health() -> dict[str, dict[str, str]]:
    """서비스 상태를 반환한다 (API_SPEC §10).

    ``rng_canonical_test``가 ``"failed"``여도 ``status``는 ``"ok"``를 유지한다 (#400).

    두 필드는 서로 다른 것을 본다. ``status``는 **liveness** — 루트 ``Dockerfile``의
    HEALTHCHECK가 "컨테이너가 살아 있지만 응답하지 않는 상태"를 감지하는 데 쓴다.
    RNG canonical 불일치는 프로세스가 살아 있고 응답도 하는 상태이며, **재시작으로
    해결되지 않는다** — NumPy 버전은 이미지에 고정돼 있다. ``status``를 내리면
    오케스트레이터가 무한 재시작 루프에 빠지면서 원인은 그대로 남는다.

    신호는 필드가 전달한다. 모니터링이 이 값을 보고 알람을 걸어야 한다.
    """
    return {
        "data": {
            "status": "ok",
            "version": _app_version(),
            "numpy_version": numpy.__version__,
            "rng_canonical_test": _rng_canonical_test(),
        }
    }
