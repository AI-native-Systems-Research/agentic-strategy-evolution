"""Tests for fast-fail rules."""
import pytest

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


class TestFastFailValidation:
    def test_missing_h_main_arm_raises(self):
        findings = {
            "arms": [{"arm_type": "h-control-negative", "status": "CONFIRMED"}],
        }
        with pytest.raises(ValueError, match="missing required 'h-main' arm"):
            check_fast_fail(findings)

    def test_missing_arms_key_raises(self):
        with pytest.raises(ValueError, match="missing required 'arms' key"):
            check_fast_fail({"iteration": 1})

    def test_empty_arms_raises(self):
        with pytest.raises(ValueError, match="missing required 'h-main' arm"):
            check_fast_fail({"arms": []})

    def test_h_main_missing_status_raises(self):
        findings = {
            "arms": [{"arm_type": "h-main"}],
        }
        with pytest.raises(ValueError, match="missing required 'status' field"):
            check_fast_fail(findings)

    def test_dominant_component_pct_string_raises(self):
        findings = {
            "arms": [{"arm_type": "h-main", "status": "CONFIRMED"}],
            "dominant_component_pct": "85%",
        }
        with pytest.raises(TypeError, match="must be numeric"):
            check_fast_fail(findings)

    def test_duplicate_arm_type_raises(self):
        findings = {
            "arms": [
                {"arm_type": "h-main", "status": "CONFIRMED"},
                {"arm_type": "h-main", "status": "REFUTED"},
            ]
        }
        with pytest.raises(ValueError, match="Duplicate arm_type"):
            check_fast_fail(findings)

    def test_missing_arm_type_key_raises(self):
        findings = {
            "arms": [
                {"status": "CONFIRMED"},  # no arm_type
            ]
        }
        with pytest.raises(ValueError, match="missing required 'arm_type' key"):
            check_fast_fail(findings)
