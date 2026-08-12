"""PCG64DXSM 기반 난수 생성기 (#43).

TECH_SPEC §2.5 재현성 계약의 핵심 부품. NumPy ``default_rng()``는 NumPy 버전에
따라 다른 BitGenerator를 생성할 수 있어 쓰지 못한다 — 본 프로젝트의 재현성
계약(TECH_SPEC §5.4)이 RNG의 bit-exact 재현을 전제하므로, 알고리즘을
**명시적으로 PCG64DXSM으로 고정**한다 [ORACLE-C-1].

TECH_SPEC §2.5.1 canonical vector는 NumPy 2.1.0 + PCG64DXSM(seed=12345) 실측값을
고정한 것이며, :func:`validate_rng`가 이 값이 재현되는지 검증한다. 환경 핀닝
(TECH_SPEC §2.5.2)은 ``pyproject.toml``의 ``numpy==2.1.0``으로 유지된다.
"""

from __future__ import annotations

import numpy as np

#: TECH_SPEC §2.5.1 — canonical vector 산출에 쓴 seed.
CANONICAL_SEED = 12345

#: TECH_SPEC §2.5.1 — NumPy 2.1.0 + PCG64DXSM(seed=12345) 첫 5개 uniform 실측값.
#:
#: 이 값은 환경 핀닝(TECH_SPEC §2.5.2, ``numpy==2.1.0``) 아래에서 재현되어야 한다.
#: 값이 바뀌면 NumPy 버전이나 플랫폼이 바뀐 것이므로 재현성 계약(§5.4) 위반이다.
EXPECTED_UNIFORM_5: tuple[float, ...] = (
    0.9320816903198763,
    0.3375056011176768,
    0.21698197019501064,
    0.3527062497665462,
    0.5501051021142127,
)

#: BitGenerator 이름 — TECH_SPEC §2.5 · §2.5.1 [ORACLE-C-1].
RNG_ALGORITHM = "PCG64DXSM"


def create_rng(seed: int) -> np.random.Generator:
    """PCG64DXSM BitGenerator를 명시적으로 생성한 ``Generator``를 반환한다 (#43).

    ``np.random.default_rng(seed)``는 NumPy 버전에 따라 PCG64 / PCG64DXSM / 다른
    알고리즘을 생성할 수 있어 재현성 계약(TECH_SPEC §5.4)을 위반한다 [ORACLE-C-1].
    따라서 ``default_rng``는 프로젝트 전역에서 금지된다 (``pyproject.toml`` TID251).
    """
    return np.random.Generator(np.random.PCG64DXSM(seed))


def validate_rng() -> None:
    """canonical vector(TECH_SPEC §2.5.1) 재현을 검증한다 (#43).

    5개 uniform 값이 :data:`EXPECTED_UNIFORM_5`와 ``1e-15`` 이내로 일치하는지
    확인한다. 일치하지 않으면 NumPy 버전이나 플랫폼이 바뀐 것이므로 재현성
    계약 위반 — 그대로 두면 Monte Carlo 결과가 환경마다 달라진다.
    """
    rng = create_rng(CANONICAL_SEED)
    for i, expected in enumerate(EXPECTED_UNIFORM_5):
        actual = float(rng.random())
        assert abs(actual - expected) < 1e-15, (
            f"RNG mismatch at index {i}: {actual} != {expected}. "
            f"NumPy version or platform may have changed."
        )
