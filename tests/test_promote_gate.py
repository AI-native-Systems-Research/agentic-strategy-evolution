"""Tests for #224 v1: deterministic promote_gate decision logic.

Pure-Python tests with synthesized inputs. No LLM, no SDK. Each test
sets up the relevant on-disk artifacts (findings.json,
brief_amendments.jsonl, applied_amendments.jsonl) for a given iteration
and asserts the decision dict.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.promote_gate import (
    VALID_DECISIONS,
    evaluate_promote_gate,
)


def _write_findings(iter_dir: Path, *, valid: bool = True) -> None:
    iter_dir.mkdir(parents=True, exist_ok=True)
    (iter_dir / "findings.json").write_text(json.dumps({
        "iteration": 1,
        "bundle_ref": "runs/iter-1/bundle.yaml",
        "experiment_valid": valid,
        "arms": [
            {"arm_type": "h-main",
             "predicted": "p", "observed": "o", "status": "CONFIRMED",
             "error_type": None, "diagnostic_note": "n"},
        ],
    }))


def _write_amendments(iter_dir: Path, rows: list[dict]) -> None:
    inputs = iter_dir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    (inputs / "brief_amendments.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n"
    )


def _write_applied(work_dir: Path, ids: list[str]) -> None:
    (work_dir / "applied_amendments.jsonl").write_text(
        "\n".join(json.dumps({"id": i}) for i in ids) + "\n"
    )


# ─── promote: clean iter, no blockers ─────────────────────────────────────


class TestPromote:
    def test_clean_findings_no_amendments(self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        _write_findings(wd / "runs" / "iter-1", valid=True)
        result = evaluate_promote_gate(wd, 1)
        assert result["decision"] == "promote"
        assert result["blocking_amendments"] == []
        assert result["feasibility_check"]["passed"] is True

    def test_clean_findings_with_non_blocking_amendments(
            self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        _write_findings(wd / "runs" / "iter-1", valid=True)
        _write_amendments(wd / "runs" / "iter-1", [
            {"id": "BA-1", "brief_section": "x", "problem": "p",
             "fix": "f", "priority": "HIGH"},
            {"id": "BA-2", "brief_section": "y", "problem": "p",
             "fix": "f", "priority": "MEDIUM"},
        ])
        result = evaluate_promote_gate(wd, 1)
        assert result["decision"] == "promote"
        assert result["blocking_amendments"] == []

    def test_blocking_amendment_already_applied(self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        _write_findings(wd / "runs" / "iter-1", valid=True)
        _write_amendments(wd / "runs" / "iter-1", [
            {"id": "BA-1", "brief_section": "x", "problem": "p",
             "fix": "f", "priority": "BLOCKING"},
        ])
        _write_applied(wd, ["BA-1"])
        result = evaluate_promote_gate(wd, 1)
        assert result["decision"] == "promote"
        assert "BA-1" in result["applied_amendments"]


# ─── revise: BLOCKING amendments not yet applied ──────────────────────────


class TestRevise:
    def test_one_blocking_unapplied(self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        _write_findings(wd / "runs" / "iter-1", valid=True)
        _write_amendments(wd / "runs" / "iter-1", [
            {"id": "BA-2", "brief_section": "x", "problem": "p",
             "fix": "f", "priority": "BLOCKING"},
        ])
        result = evaluate_promote_gate(wd, 1)
        assert result["decision"] == "revise"
        assert result["blocking_amendments"] == ["BA-2"]
        assert "BA-2" in result["reasoning"]

    def test_multiple_blocking_some_applied(self, tmp_path: Path) -> None:
        """Mixed state: 3 BLOCKING amendments, 1 applied → still revise
        because 2 remain."""
        wd = tmp_path / "campaign"
        _write_findings(wd / "runs" / "iter-1", valid=True)
        _write_amendments(wd / "runs" / "iter-1", [
            {"id": "BA-1", "brief_section": "x", "problem": "p",
             "fix": "f", "priority": "BLOCKING"},
            {"id": "BA-2", "brief_section": "x", "problem": "p",
             "fix": "f", "priority": "BLOCKING"},
            {"id": "BA-3", "brief_section": "x", "problem": "p",
             "fix": "f", "priority": "BLOCKING"},
        ])
        _write_applied(wd, ["BA-1"])
        result = evaluate_promote_gate(wd, 1)
        assert result["decision"] == "revise"
        assert sorted(result["blocking_amendments"]) == ["BA-2", "BA-3"]


# ─── abort: apparatus failure ─────────────────────────────────────────────


class TestAbort:
    def test_findings_missing(self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        # No findings.json
        (wd / "runs" / "iter-1").mkdir(parents=True)
        result = evaluate_promote_gate(wd, 1)
        assert result["decision"] == "abort"
        assert "findings.json" in result["reasoning"]
        assert result["feasibility_check"]["passed"] is False

    def test_findings_invalid(self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        _write_findings(wd / "runs" / "iter-1", valid=False)
        result = evaluate_promote_gate(wd, 1)
        assert result["decision"] == "abort"
        assert "experiment_valid=false" in result["reasoning"]
        assert result["feasibility_check"]["passed"] is False

    def test_findings_missing_takes_priority_over_amendments(
            self, tmp_path: Path) -> None:
        """When findings is missing, decision is abort regardless of
        amendments — there's no point reviewing amendments for an
        iter that didn't produce data."""
        wd = tmp_path / "campaign"
        (wd / "runs" / "iter-1").mkdir(parents=True)
        _write_amendments(wd / "runs" / "iter-1", [
            {"id": "BA-1", "brief_section": "x", "problem": "p",
             "fix": "f", "priority": "BLOCKING"},
        ])
        result = evaluate_promote_gate(wd, 1)
        assert result["decision"] == "abort"


# ─── shape contracts ──────────────────────────────────────────────────────


class TestResultShape:
    def test_decision_in_valid_set(self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        _write_findings(wd / "runs" / "iter-1", valid=True)
        result = evaluate_promote_gate(wd, 1)
        assert result["decision"] in VALID_DECISIONS

    def test_required_keys(self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        _write_findings(wd / "runs" / "iter-1", valid=True)
        result = evaluate_promote_gate(wd, 1)
        for k in ("decision", "reasoning", "blocking_amendments",
                  "applied_amendments", "feasibility_check",
                  "malformed_amendment_lines"):
            assert k in result, f"missing key {k} in result"
        assert "passed" in result["feasibility_check"]
        assert isinstance(result["malformed_amendment_lines"], int)

    def test_reasoning_is_human_readable(self, tmp_path: Path) -> None:
        """Smoke test that reasoning text is non-empty and references
        the iteration — operators reading the JSON output can act
        without parsing internal flags."""
        wd = tmp_path / "campaign"
        _write_findings(wd / "runs" / "iter-1", valid=True)
        result = evaluate_promote_gate(wd, 1)
        assert "iter-1" in result["reasoning"]
        assert len(result["reasoning"]) > 30


# ─── degenerate inputs ────────────────────────────────────────────────────


class TestDegenerate:
    def test_no_iter_dir(self, tmp_path: Path) -> None:
        """No runs/iter-N dir at all → abort (treat same as missing findings)."""
        wd = tmp_path / "campaign"
        result = evaluate_promote_gate(wd, 1)
        assert result["decision"] == "abort"

    def test_malformed_findings_treated_as_missing(self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        iter_dir = wd / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        (iter_dir / "findings.json").write_text("not json {")
        result = evaluate_promote_gate(wd, 1)
        assert result["decision"] == "abort"

    def test_malformed_amendments_downgrade_to_revise(self, tmp_path: Path) -> None:
        """A malformed line in brief_amendments.jsonl could have been a
        BLOCKING amendment — silently letting it through risks a false
        promote. Asymmetric-risk: we choose revise instead, surfacing
        the malformed_amendment_lines count for operator inspection."""
        wd = tmp_path / "campaign"
        _write_findings(wd / "runs" / "iter-1", valid=True)
        inputs = wd / "runs" / "iter-1" / "inputs"
        inputs.mkdir(parents=True)
        (inputs / "brief_amendments.jsonl").write_text(
            json.dumps({"id": "BA-1", "brief_section": "x", "problem": "p",
                        "fix": "f", "priority": "HIGH"}) + "\n"
            + "not valid json {\n"
        )
        # The valid row is HIGH (no BLOCKING) but the malformed line
        # could have been anything — we cannot rule out a hidden
        # BLOCKING. Decision: revise.
        result = evaluate_promote_gate(wd, 1)
        assert result["decision"] == "revise", (
            f"asymmetric-risk: malformed amendment lines should "
            f"trigger revise, not silent promote. Got {result!r}"
        )
        assert result["malformed_amendment_lines"] == 1
        assert "malformed" in result["reasoning"].lower()

    def test_clean_amendments_no_malformed_lines(self, tmp_path: Path) -> None:
        """Sanity: no malformed lines → malformed_amendment_lines is 0."""
        wd = tmp_path / "campaign"
        _write_findings(wd / "runs" / "iter-1", valid=True)
        result = evaluate_promote_gate(wd, 1)
        assert result["decision"] == "promote"
        assert result["malformed_amendment_lines"] == 0

    def test_blocking_takes_priority_over_malformed(self, tmp_path: Path) -> None:
        """When both a BLOCKING amendment AND a malformed line exist,
        the BLOCKING-amendment decision wins (still revise — but the
        reasoning should cite the BLOCKING IDs first)."""
        wd = tmp_path / "campaign"
        _write_findings(wd / "runs" / "iter-1", valid=True)
        inputs = wd / "runs" / "iter-1" / "inputs"
        inputs.mkdir(parents=True)
        (inputs / "brief_amendments.jsonl").write_text(
            json.dumps({"id": "BA-1", "brief_section": "x", "problem": "p",
                        "fix": "f", "priority": "BLOCKING"}) + "\n"
            + "garbage {\n"
        )
        result = evaluate_promote_gate(wd, 1)
        assert result["decision"] == "revise"
        assert "BA-1" in result["blocking_amendments"]
        assert result["malformed_amendment_lines"] == 1
