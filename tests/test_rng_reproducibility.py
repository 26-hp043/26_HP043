"""RNG 재현성 테스트 (#43).

TECH_SPEC §2.5.1 canonical vector 일치(UT-RNG-001)와 동일 seed bit-exact 재현
(UT-RNG-002), seed 민감도(UT-RNG-003), ``default_rng`` canary(UT-RNG-004)를
검증한다. TEST_PLAN §2.4 참조. ``numpy==2.1.0`` 환경 핀닝 아래에서만 통과해야 한다.

UT-RNG-003은 TEST_PLAN이 ``rating_probabilities`` 비교를 규정하나, 그 결과는
Monte Carlo 엔진(#63)이 있어야 산출할 수 있다. #43 시점에서는 **난수 시퀀스 자체**의
상이함으로 검증하고, ``rating_probabilities`` 비교는 #63에서 보강한다.
"""

import numpy as np

from cii_platform.calc.rng import (
    CANONICAL_SEED,
    EXPECTED_UNIFORM_5,
    create_rng,
    validate_rng,
)


def test_ut_rng_001_canonical_vector_matches_pinned_environment() -> None:
    """UT-RNG-001 — PCG64DXSM(seed=12345) 처음 5개 값이 canonical vector와 일치 (#43)."""
    validate_rng()


def test_ut_rng_002_same_seed_yields_bit_exact_sequence() -> None:
    """UT-RNG-002 — 동일 seed로 5000회 생성 → 두 번째 실행과 bit-exact 일치 (#43).

    float64 비트 패턴까지 동일한지 ``tobytes`` 비교로 잡는다 — ``==``는 NaN이나
    부호있는 0을 넘겨버릴 수 있다. 재현성 계약은 값이 아니라 **비트** 단위다.
    """
    n = 5000
    seq1 = np.array([create_rng(CANONICAL_SEED).random() for _ in range(n)])
    seq2 = np.array([create_rng(CANONICAL_SEED).random() for _ in range(n)])
    assert seq1.tobytes() == seq2.tobytes()


def test_ut_rng_003_different_seeds_yield_different_sequences() -> None:
    """UT-RNG-003 — seed 변경 시 난수 시퀀스가 상이하다 (#43).

    rating_probabilities 비교는 #63 (Monte Carlo 엔진)에서 추가한다.
    """
    seq_canonical = [float(create_rng(12345).random()) for _ in range(5)]
    seq_other = [float(create_rng(99999).random()) for _ in range(5)]
    assert seq_canonical != seq_other


def test_ut_rng_004_default_rng_uses_different_bitgenerator() -> None:
    """UT-RNG-004 canary — default_rng()는 PCG64를 생성하므로 PCG64DXSM과 다름 (#43).

    TEST_PLAN §2.4 [ORACLE-M-1] — 정적 lint(``pyproject.toml`` TID251)과 런타임
    canary 양쪽으로 ``default_rng`` 사용을 잠근다. 이 테스트 파일만 TID251 예외
    (``pyproject.toml`` per-file-ignores)를 받아 canary 호출을 허용한다.
    """
    default_seq = [float(np.random.default_rng(CANONICAL_SEED).random()) for _ in range(5)]
    pcg64dxsm_seq = list(EXPECTED_UNIFORM_5)
    assert default_seq != pcg64dxsm_seq
