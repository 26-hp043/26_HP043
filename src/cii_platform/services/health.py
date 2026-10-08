"""계산 코어의 RNG 진단을 HTTP와 분리한 호출 경계 (TECH_SPEC §16.3 · #2101)."""

from cii_platform.calc import rng


def validate_rng() -> None:
    """기존 canonical vector 검증을 호출한다. 캐시·응답 처리는 라우트가 맡는다."""
    rng.validate_rng()
