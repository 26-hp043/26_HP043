"""픽스처 로더와 Layer 1 비교 — `TEST_PLAN §1.6` · `§9.1` 구현 (#45).

로더를 `conftest.py`가 아니라 별도 모듈에 두는 이유는, 현재 `conftest.py`가
**PostgreSQL 연결을 전제**하기 때문이다. 픽스처 비교는 DB 없이 성립해야 한다.
`conftest.py`가 `load_fixture` pytest fixture를 여기서 가져다 노출한다.

**비교는 항상 수치 비교다.** 표기 자릿수(`249120000` vs `249120000.000`)는
비교 결과에 영향을 주지 않는다 (`TECH_SPEC §1.2.1` 픽스처 표기 조항 2).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from cii_platform.calc.precision import publish_layer1_canonical

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

_CACHE: dict[str, Any] = {}


def load_fixture(rel_path: str) -> Any:
    """`tests/fixtures/` 아래의 JSON 픽스처를 읽는다 (세션 내 캐싱).

    :param rel_path: `fixtures/` 기준 상대 경로 (예: ``"cii/bulk_50000_hfo_2026.json"``)
    """
    if rel_path not in _CACHE:
        with open(FIXTURE_DIR / rel_path, encoding="utf-8") as f:
            _CACHE[rel_path] = json.load(f)
    return _CACHE[rel_path]


def assert_layer1_equal(actual: str, expected: str, decimal_places: int | None = None) -> None:
    """Layer 1 값을 `TEST_PLAN §9.1`대로 비교한다.

    정수값은 bit-exact. 소수값은 **공표 자릿수로 확정한 뒤 정확 일치**를 본다.

    ``actual``은 서비스가 반환한 **작업 정밀도 원값**이고 ``expected``는 픽스처의
    **정본값 30자리**다. 두 값은 자릿수가 다르므로 그대로 비교하면 항상 어긋난다.
    확정을 이 함수가 수행하는 이유는, 호출부마다 확정 시점이 달라지면
    `TECH_SPEC §1.2.1`이 금지하는 중간 확정이 테스트 코드에 섞이기 때문이다.

    ``decimal_places``를 넘기면 그 소수 자릿수로 완화 비교한다.
    **정본값 필드에는 쓰지 않는다** — 표시값처럼 자릿수가 규정된 값 전용이다.
    """
    actual_dec = Decimal(actual)
    expected_dec = Decimal(expected)

    if (
        actual_dec == actual_dec.to_integral_value()
        and expected_dec == expected_dec.to_integral_value()
    ):
        assert actual_dec == expected_dec, f"Layer 1 integer mismatch: {actual} != {expected}"
        return

    if decimal_places is not None:
        quantizer = Decimal(f"1e-{decimal_places}")
        assert actual_dec.quantize(quantizer) == expected_dec.quantize(quantizer), (
            f"Layer 1 decimal mismatch at {decimal_places} decimal places: {actual} != {expected}"
        )
        return

    published = publish_layer1_canonical(actual_dec)
    assert published == expected_dec, (
        f"Layer 1 canonical mismatch: {published} != {expected_dec} (raw actual: {actual})"
    )
