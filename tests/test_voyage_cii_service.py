"""기능① 서비스 계층 검증 (#55) — **DB 없이 돈다.**

세 층위를 나눠 본다.

1. **Layer 1 계산** — 정본 픽스처(``tests/fixtures/cii/``)와 30자리 대조
2. **직렬화** — API_SPEC §4.1 계약 예시와 문자열 대조
3. **응답 조립** — 필드 존재·JSON 타입·오류 코드

1은 ``calc``가 이미 검증하지만, **서비스가 그것을 올바른 순서·컨텍스트로 부르는지**는
여기서만 드러난다. 특히 ``ratio_to_required``는 분모를 확정값으로 바꾸면 조용히
``…580``이 되고 계산 함수 테스트로는 잡히지 않는다.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from cii_platform.calc.cii_engine import FuelUse
from cii_platform.calc.precision import publish_layer1_canonical
from cii_platform.calc.rating_engine import DVector
from cii_platform.services import voyage_cii as svc

_FIXTURE = Path(__file__).parent / "fixtures" / "cii" / "bulk_50000_hfo_2026.json"


@pytest.fixture(scope="module")
def canonical() -> dict[str, str]:
    """정본 픽스처의 기대값 (#45 · 30자리)."""
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))["expected"]


@pytest.fixture
def layer1():
    """Fixture 1과 같은 조건으로 Layer 1 전 구간을 계산한다."""
    return svc._compute_layer1(
        fuel_uses=[FuelUse(fuel_code="HFO", fuel_ton=Decimal("80"), cf_value=Decimal("3.114"))],
        transport_capacity=Decimal("50000"),
        reference_capacity=Decimal("50000"),
        distance_nm=Decimal("1000"),
        a_decimal=Decimal("4745"),
        c=Decimal("0.622"),
        z_factor_percent=Decimal("11"),
        d_vector=DVector(
            d1=Decimal("0.86"), d2=Decimal("0.94"), d3=Decimal("1.06"), d4=Decimal("1.18")
        ),
    )


# --- 1. Layer 1 계산 ----------------------------------------------------------------


class TestLayer1MatchesCanonicalFixture:
    """서비스의 계산 결과가 **정본 픽스처와 30자리까지** 같다."""

    def test_cii_ref(self, layer1, canonical):
        assert str(publish_layer1_canonical(layer1.cii_ref)) == canonical["cii_ref"]

    def test_required_cii(self, layer1, canonical):
        assert str(publish_layer1_canonical(layer1.required_cii)) == canonical["required_cii"]

    def test_ratio_to_required_uses_unpublished_denominator(self, layer1, canonical):
        """⚠️ **이 파일에서 가장 중요한 단언이다.**

        분모를 확정값(30자리)으로 바꾸면 ``…012580``이 나오고 정본은 ``…012581``이다.
        `#179`가 실측으로 남긴 함정이며, ``calc`` 단위 테스트로는 잡히지 않는다 —
        서비스가 어떤 값을 분모로 넘기는지가 결함의 소재이기 때문이다.
        """
        assert (
            str(publish_layer1_canonical(layer1.ratio_to_required))
            == canonical["ratio_to_required"]
        )

    def test_published_denominator_gives_a_different_value(self, layer1):
        """**반대로도 확인한다** — 확정값을 분모로 쓰면 반드시 달라야 한다.

        두 경로가 같은 값을 낸다면 위 테스트는 통과하면서도 아무것도 검사하지 않는다
        (#45가 같은 기법을 썼다).
        """
        from cii_platform.calc.precision import layer1_context

        @layer1_context
        def _wrong() -> Decimal:
            return layer1.attained_cii / publish_layer1_canonical(layer1.required_cii)

        assert publish_layer1_canonical(_wrong()) != publish_layer1_canonical(
            layer1.ratio_to_required
        )

    def test_rating_and_risk(self, layer1, canonical):
        assert layer1.rating == canonical["estimated_rating"] == "C"
        assert layer1.risk_level == canonical["risk_level"] == "MEDIUM"

    @pytest.mark.parametrize(
        "key",
        ["superior_boundary", "lower_boundary", "upper_boundary", "inferior_boundary"],
    )
    def test_boundaries(self, layer1, canonical, key):
        """등급 경계 4개가 정본과 30자리까지 같다.

        ``RatingResult.boundaries``의 키는 ``superior``가 아니라 ``superior_boundary``다
        (``NEXT_WORSE_BOUNDARY_KEY``와 같은 이름). 픽스처의 키와도 그대로 맞는다.
        """
        assert str(publish_layer1_canonical(layer1.boundaries[key])) == canonical[key]


# --- 2. 직렬화 ----------------------------------------------------------------------


class TestSerializationMatchesApiSpec:
    """응답 문자열이 API_SPEC §4.1 계약 예시와 같다.

    **필드마다 자릿수가 다르다.** 하나로 묶으면 계약과 어긋나므로 전건을 적어 둔다.
    """

    @pytest.mark.parametrize(
        ("attr", "digits_key", "expected"),
        [
            ("attained_cii", "attained_cii", "4.982400"),
            ("required_cii", "required_cii", "5.045066"),
            ("ratio_to_required", "ratio_to_required", "0.98758"),
            ("margin", "margin", "0.365370"),
            ("margin_ratio", "margin_ratio", "0.0724"),
            ("total_co2_t", "co2_ton", "249.12"),
            ("fuel_total_ton", "fuel_ton", "80.00"),
            ("fuel_total_ton", "detail_fuel_ton", "80.0"),
        ],
    )
    def test_field(self, layer1, attr, digits_key, expected):
        value = getattr(layer1, attr)
        assert svc._publish(value, svc.SERIALIZATION_DIGITS[digits_key]) == expected


class TestPlainSerialization:
    """``_plain()`` — 확정·반올림 대상이 아닌 값."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (Decimal("50000.00"), "50000"),
            (Decimal("50000"), "50000"),
            (Decimal("4745.000000"), "4745"),
            (Decimal("0.622000"), "0.622"),
            (Decimal("11.0000"), "11"),
            (Decimal("0.8600"), "0.86"),
        ],
    )
    def test_no_exponent_notation(self, value, expected):
        """``Decimal("50000.00").normalize()``는 ``5E+4``가 된다.

        계약 예시는 ``"50000"``이므로 지수 표기가 나가면 안 된다.
        """
        assert svc._plain(value) == expected


# --- 3. 등급 E 경계 ------------------------------------------------------------------


class TestGradeE:
    """등급 E는 악화 방향 경계가 없어 ``null``이 나가야 한다 (#171 결론)."""

    @pytest.fixture
    def layer1_e(self):
        # 연료를 크게 올려 E 구간으로 보낸다.
        return svc._compute_layer1(
            fuel_uses=[
                FuelUse(fuel_code="HFO", fuel_ton=Decimal("200"), cf_value=Decimal("3.114"))
            ],
            transport_capacity=Decimal("50000"),
            reference_capacity=Decimal("50000"),
            distance_nm=Decimal("1000"),
            a_decimal=Decimal("4745"),
            c=Decimal("0.622"),
            z_factor_percent=Decimal("11"),
            d_vector=DVector(
                d1=Decimal("0.86"), d2=Decimal("0.94"), d3=Decimal("1.06"), d4=Decimal("1.18")
            ),
        )

    def test_rating_is_e(self, layer1_e):
        assert layer1_e.rating == "E"

    def test_margin_is_none(self, layer1_e):
        """``select_next_worse_boundary``가 E에 ``None``을 반환한다 (#40)."""
        assert layer1_e.next_worse_boundary is None
        assert layer1_e.margin is None
        assert layer1_e.margin_ratio is None

    def test_risk_is_critical(self, layer1_e):
        """PRD §9.4.1 — E는 여유율과 무관하게 CRITICAL이다."""
        assert layer1_e.risk_level == "CRITICAL"


# --- 4. warning 판정 ----------------------------------------------------------------


class TestWarnings:
    """API_SPEC §1.6 warning 코드."""

    def test_reference_only_always_present(self):
        from fakes import FakeVessel

        assert svc.WARNING_REFERENCE_ONLY in svc._build_warnings(FakeVessel())

    def test_non_cii_vessel_when_gt_below_threshold(self):
        from fakes import FakeVessel

        vessel = FakeVessel(gross_tonnage=Decimal("4999.99"))
        assert svc.WARNING_NON_CII_VESSEL in svc._build_warnings(vessel)

    def test_no_warning_at_exactly_threshold(self):
        """5,000 **이상**이 적용 대상이다. 경계값은 경고 대상이 아니다."""
        from fakes import FakeVessel

        vessel = FakeVessel(gross_tonnage=Decimal("5000"))
        assert svc.WARNING_NON_CII_VESSEL not in svc._build_warnings(vessel)

    def test_gt_unknown_is_not_called_non_applicable(self):
        """GT를 모르면 **「적용 대상이 아니다」라고 단정하지 않는다.**

        seed의 실선 2척이 이 경우다(GT 미회신). 근거 없이 경고를 붙이면 사용자가
        확인된 사실로 읽는다.
        """
        from fakes import FakeVessel

        vessel = FakeVessel(gross_tonnage=None)
        assert svc.WARNING_NON_CII_VESSEL not in svc._build_warnings(vessel)

    def test_gt_unknown_says_it_could_not_judge(self):
        """**단정하지 않는 것과 아무 말도 하지 않는 것은 다르다** (`#653`).

        종전에는 GT가 NULL이면 경고가 하나도 붙지 않아, 규제상 무의미할 수 있는
        계산 결과가 아무 표시 없이 나갔다 — 데모의 실선 2척이 그 상태였다.
        """
        from fakes import FakeVessel

        vessel = FakeVessel(gross_tonnage=None)
        assert svc._build_warnings(vessel) == [
            svc.WARNING_REFERENCE_ONLY,
            svc.WARNING_CII_APPLICABILITY_UNKNOWN,
        ]

    def test_applicable_vessel_gets_no_applicability_warning(self):
        """정상 상태에는 경고를 붙이지 않는다 — 붙이면 진짜 예외가 묻힌다."""
        from fakes import FakeVessel

        assert svc._build_warnings(FakeVessel()) == [svc.WARNING_REFERENCE_ONLY]


class TestPercentSerialization:
    """``_percent()`` — Z계수는 소수 자릿수를 최소 1자리 유지한다.

    ``_plain()``을 그대로 쓰면 ``NUMERIC(8,4)``의 ``11.0000``이 ``"11"``이 되는데,
    프론트엔드 고정표와 `#132` 계약은 ``"11.0"``을 쓴다.
    """

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (Decimal("11.0000"), "11.0"),
            (Decimal("11"), "11.0"),
            (Decimal("11.5000"), "11.5"),
            (Decimal("0.5000"), "0.5"),
            (Decimal("12.3456"), "12.3456"),
        ],
    )
    def test_percent(self, value, expected):
        assert svc._percent(value) == expected
