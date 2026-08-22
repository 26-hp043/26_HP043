"""CII 적용 대상 판정 단일 출처 검증 (#653).

`services/applicability.py`가 세 상태를 가르는 규칙과, 그 결과가 경고 코드로
옮겨지는 규칙을 잠근다.

**여기서 지키려는 것은 「미해당」과 「판정 불가」가 합쳐지지 않는 것**이다. 둘을 한
상태로 뭉치면 총톤수를 넣지 않은 사용자가 「이 배는 규제 대상이 아니다」로 읽는다 —
데모 시드의 실선 2척(`STAR SKIPPER` · `DONGJIN ENDURANCE`)이 정확히 그 경우다.
"""

from decimal import Decimal

from cii_platform.services import applicability as app


class _Vessel:
    """``gross_tonnage``만 읽는 최소 대역."""

    def __init__(self, gross_tonnage):
        self.gross_tonnage = gross_tonnage


class TestState:
    """3상태 판정."""

    def test_at_or_above_threshold_is_applicable(self):
        assert app.applicability_state(Decimal("5000")) == app.STATE_APPLICABLE
        assert app.applicability_state(Decimal("30000")) == app.STATE_APPLICABLE

    def test_below_threshold_is_not_applicable(self):
        """경계는 **5,000 이상**이 적용 대상이다 (`API_SPEC §2.3`)."""
        assert app.applicability_state(Decimal("4999.99")) == app.STATE_NOT_APPLICABLE

    def test_missing_gt_is_unknown_not_not_applicable(self):
        """**이 단언이 이 파일의 핵심이다.**

        GT가 없는 것을 「미해당」으로 접으면 화면이 확정적인 오안내를 한다.
        """
        assert app.applicability_state(None) == app.STATE_UNKNOWN

    def test_float_input_is_accepted(self):
        """응답 경로에 따라 ``float``으로 들어올 수 있다 — 판정이 형에 걸리지 않는다."""
        assert app.applicability_state(4000) == app.STATE_NOT_APPLICABLE


class TestWarnings:
    """상태 → `API_SPEC §1.6` 경고 코드."""

    def test_applicable_vessel_has_no_warning(self):
        assert app.applicability_warnings(_Vessel(Decimal("30000"))) == []

    def test_small_vessel_gets_non_cii_vessel(self):
        assert app.applicability_warnings(_Vessel(Decimal("4999"))) == [app.WARNING_NON_CII_VESSEL]

    def test_unknown_gt_gets_its_own_code(self):
        """두 코드가 **다른 사실**을 말한다 — 하나로 합치지 않는다."""
        assert app.applicability_warnings(_Vessel(None)) == [app.WARNING_CII_APPLICABILITY_UNKNOWN]

    def test_the_two_codes_are_never_emitted_together(self):
        """한 선박이 동시에 「미해당」이면서 「판정 불가」일 수는 없다."""
        for gt in (None, Decimal("4999"), Decimal("5000")):
            codes = app.applicability_warnings(_Vessel(gt))
            assert len(codes) <= 1


class TestThresholdIsNotDuplicated:
    """임계값이 두 곳에 따로 적혀 있지 않다 (`#653`이 정리한 것)."""

    def test_vessel_service_reuses_the_shared_threshold(self):
        from cii_platform.services import vessel as vessel_svc

        assert vessel_svc.CII_APPLICABLE_GT_THRESHOLD is app.CII_APPLICABLE_GT_THRESHOLD

    def test_voyage_cii_reuses_the_shared_threshold(self):
        from cii_platform.services import voyage_cii as voyage_svc

        assert voyage_svc.CII_APPLICABLE_GT_THRESHOLD is app.CII_APPLICABLE_GT_THRESHOLD


class TestReportLabels:
    """리포트 표기 — 3상태 전부에 문구가 있다."""

    def test_every_state_has_a_label(self):
        from cii_platform.reports.labels import APPLICABILITY_LABELS, applicability_label

        for state in (app.STATE_APPLICABLE, app.STATE_NOT_APPLICABLE, app.STATE_UNKNOWN):
            assert state in APPLICABILITY_LABELS
            assert applicability_label(state) != state

    def test_non_applicable_states_say_internal_use_only(self):
        """리포트는 대외로 나간다 — 「내부 분석용」이 빠지면 오해가 그대로 남는다."""
        from cii_platform.reports.labels import applicability_label

        assert "내부 분석용" in applicability_label(app.STATE_NOT_APPLICABLE)
        assert "내부 분석용" in applicability_label(app.STATE_UNKNOWN)
