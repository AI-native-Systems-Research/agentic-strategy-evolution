"""Tests for fast-fail rules."""
from orchestrator.fastfail import check_fast_fail, FastFailAction


class TestFastFail:
    def test_h_main_refuted_skips_to_extraction(self):
        findings = {
            "arms": [
                {"arm_type": "h-main", "status": "REFUTED"},
                {"arm_type": "h-control-negative", "status": "CONFIRMED"},
            ]
        }
        assert check_fast_fail(findings) == FastFailAction.SKIP_TO_EXTRACTION

    def test_control_negative_fails_redesign(self):
        findings = {
            "arms": [
                {"arm_type": "h-main", "status": "CONFIRMED"},
                {"arm_type": "h-control-negative", "status": "REFUTED"},
            ]
        }
        assert check_fast_fail(findings) == FastFailAction.REDESIGN

    def test_all_confirmed_continues(self):
        findings = {
            "arms": [
                {"arm_type": "h-main", "status": "CONFIRMED"},
                {"arm_type": "h-control-negative", "status": "CONFIRMED"},
                {"arm_type": "h-robustness", "status": "CONFIRMED"},
            ]
        }
        assert check_fast_fail(findings) == FastFailAction.CONTINUE

    def test_h_main_refuted_takes_priority(self):
        findings = {
            "arms": [
                {"arm_type": "h-main", "status": "REFUTED"},
                {"arm_type": "h-control-negative", "status": "REFUTED"},
            ]
        }
        assert check_fast_fail(findings) == FastFailAction.SKIP_TO_EXTRACTION

    def test_single_dominant_component_simplifies(self):
        findings = {
            "arms": [
                {"arm_type": "h-main", "status": "CONFIRMED"},
                {"arm_type": "h-control-negative", "status": "CONFIRMED"},
            ],
            "dominant_component_pct": 85.0,
        }
        assert check_fast_fail(findings) == FastFailAction.SIMPLIFY

    def test_no_dominant_component_continues(self):
        findings = {
            "arms": [
                {"arm_type": "h-main", "status": "CONFIRMED"},
                {"arm_type": "h-control-negative", "status": "CONFIRMED"},
            ],
            "dominant_component_pct": 60.0,
        }
        assert check_fast_fail(findings) == FastFailAction.CONTINUE

    def test_no_dominant_key_continues(self):
        findings = {
            "arms": [
                {"arm_type": "h-main", "status": "CONFIRMED"},
            ]
        }
        assert check_fast_fail(findings) == FastFailAction.CONTINUE

    def test_exactly_80_does_not_simplify(self):
        findings = {
            "arms": [{"arm_type": "h-main", "status": "CONFIRMED"}],
            "dominant_component_pct": 80.0,
        }
        assert check_fast_fail(findings) == FastFailAction.CONTINUE

    def test_missing_h_main_arm_continues(self):
        findings = {
            "arms": [{"arm_type": "h-control-negative", "status": "CONFIRMED"}],
        }
        assert check_fast_fail(findings) == FastFailAction.CONTINUE
