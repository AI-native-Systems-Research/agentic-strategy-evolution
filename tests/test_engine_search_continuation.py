"""Behavioral tests for engine search-continuation past REFUTE (issue #169).

Auditing the inference-sim ledgers (May 2026): mech-design-kvtime,
fp-delay-frontier, sgsf-unification all REFUTED at iter-1 and walked
away producing nothing deployable. The engine itself doesn't have a
REFUTE → DONE shortcut, but the conventional flow today emits no
constraint principles either, so the next iteration's designer
gets no help avoiding the dead end.

This commit closes both halves:
  * Regression: assert the state machine has no REFUTE-driven path
    to DONE (only HUMAN_FINDINGS_GATE → DONE via human approval).
  * Generation: deterministic Python that turns each REFUTED arm
    into a category=meta constraint principle, recorded in
    principles.json so the next DESIGN reads it.

Test contract:
  - Engine transition map continues to allow HUMAN_FINDINGS_GATE →
    EXECUTE_ANALYZE (the redesign loop), NOT a direct DONE for REFUTE.
  - make_constraints_from_findings produces one constraint per REFUTED
    arm, zero for CONFIRMED/PARTIALLY_CONFIRMED.
  - apply_refute_constraints reads runs/iter-N/findings.json and
    writes constraints into principles.json atomically. Idempotent
    when re-run on the same findings.
  - All emitted principles carry category=meta and a clear
    "Refuted: ..." statement plus an applicability_bounds capturing
    where it failed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.engine import TRANSITIONS
from orchestrator.refute_constraints import (
    apply_refute_constraints,
    make_constraints_from_findings,
)


def _arm(arm_type: str, status: str, **extra) -> dict:
    return {
        "arm_type": arm_type,
        "predicted": extra.get("predicted", "p"),
        "observed": extra.get("observed", "o"),
        "status": status,
        "error_type": None,
        "diagnostic_note": "n",
        "metadata": extra.get("metadata", {}),
    }


def _findings(arms: list[dict], iteration: int = 1) -> dict:
    return {
        "iteration": iteration,
        "bundle_ref": f"runs/iter-{iteration}/bundle.yaml",
        "arms": arms,
        "experiment_valid": True,
        "discrepancy_analysis": "",
    }


def _write_iter(work_dir: Path, iteration: int, findings: dict) -> None:
    iter_dir = work_dir / "runs" / f"iter-{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    (iter_dir / "findings.json").write_text(json.dumps(findings))


def _write_principles(work_dir: Path, principles: list) -> None:
    (work_dir / "principles.json").write_text(
        json.dumps({"principles": principles}),
    )


# ─── Engine state-machine regression ──────────────────────────────────────


class TestEngineDoesNotAutoTerminateOnRefute:
    def test_human_findings_gate_can_loop_back_to_execute_analyze(self) -> None:
        """The redesign loop is intact — REFUTE flows back through this path."""
        assert "EXECUTE_ANALYZE" in TRANSITIONS["HUMAN_FINDINGS_GATE"]

    def test_human_findings_gate_can_reach_done(self) -> None:
        """DONE remains reachable from HUMAN_FINDINGS_GATE — the human
        gate exists precisely so a human can end the campaign. The
        important property is that REFUTE doesn't bypass that gate."""
        assert "DONE" in TRANSITIONS["HUMAN_FINDINGS_GATE"]

    def test_no_state_offers_a_direct_path_to_done_other_than_findings_gate(
        self,
    ) -> None:
        """Audit: the only state allowed to transition to DONE is
        HUMAN_FINDINGS_GATE. No automatic short-circuit."""
        states_with_done = {
            from_state for from_state, dests in TRANSITIONS.items()
            if "DONE" in dests
        }
        assert states_with_done == {"HUMAN_FINDINGS_GATE"}


# ─── make_constraints_from_findings: pure function ────────────────────────


class TestMakeConstraints:
    def test_refuted_arm_produces_one_constraint(self) -> None:
        findings = _findings([_arm("h-main", "REFUTED")])
        constraints = make_constraints_from_findings(
            findings, iteration=1, family="burst-aware-noise-floor",
        )
        assert len(constraints) == 1
        c = constraints[0]
        assert c["category"] == "meta"
        assert c["status"] == "active"
        assert "Refuted" in c["statement"] or "refuted" in c["statement"]
        assert c["extraction_iteration"] == 1
        # Family is captured in the regime / applicability_bounds
        assert "burst-aware-noise-floor" in (c["regime"] + c["applicability_bounds"])

    def test_confirmed_arm_produces_no_constraint(self) -> None:
        findings = _findings([_arm("h-main", "CONFIRMED")])
        constraints = make_constraints_from_findings(
            findings, iteration=1, family="x",
        )
        assert constraints == []

    def test_partially_confirmed_arm_produces_no_constraint(self) -> None:
        """Partial = redirect, not eliminate. Constraints come only from
        full refutations."""
        findings = _findings([_arm("h-main", "PARTIALLY_CONFIRMED")])
        constraints = make_constraints_from_findings(
            findings, iteration=1, family="x",
        )
        assert constraints == []

    def test_multiple_refuted_arms_produce_multiple_constraints(self) -> None:
        findings = _findings([
            _arm("h-main", "REFUTED"),
            _arm("h-ablation", "REFUTED"),
            _arm("h-control-negative", "CONFIRMED"),
        ])
        constraints = make_constraints_from_findings(
            findings, iteration=2, family="x",
        )
        assert len(constraints) == 2
        types = sorted(c["statement"] for c in constraints)
        # Different arms produce distinguishable statements
        assert types[0] != types[1]

    def test_existing_ids_prevent_duplicates(self) -> None:
        """Idempotent: if a constraint with the same id was already
        recorded in a previous run, don't emit it again."""
        findings = _findings([_arm("h-main", "REFUTED")])
        first = make_constraints_from_findings(
            findings, iteration=1, family="x",
        )
        existing = {c["id"] for c in first}
        second = make_constraints_from_findings(
            findings, iteration=1, family="x", existing_ids=existing,
        )
        assert second == []

    def test_all_emitted_constraints_have_category_meta(self) -> None:
        findings = _findings([
            _arm("h-main", "REFUTED"),
            _arm("h-robustness", "REFUTED"),
        ])
        constraints = make_constraints_from_findings(
            findings, iteration=1, family="x",
        )
        for c in constraints:
            assert c["category"] == "meta"


# ─── apply_refute_constraints: end-to-end on disk ─────────────────────────


class TestApplyRefuteConstraints:
    def test_replay_inserts_constraints_into_principles_json(
        self, tmp_path: Path,
    ) -> None:
        """Mirrors a mech-design-kvtime-shaped iter-1: all REFUTED, no
        prior principles. After apply, principles.json has constraint
        rows with category=meta."""
        _write_iter(tmp_path, 1, _findings([
            _arm("h-main", "REFUTED"),
            _arm("h-ablation", "REFUTED"),
        ]))
        _write_principles(tmp_path, [])

        applied = apply_refute_constraints(
            tmp_path, iteration=1, family="kvtime-discrimination",
        )

        on_disk = json.loads((tmp_path / "principles.json").read_text())
        assert len(on_disk["principles"]) == len(applied) == 2
        assert all(p["category"] == "meta" for p in on_disk["principles"])
        assert all("kvtime" in p["regime"] + p["applicability_bounds"]
                   for p in on_disk["principles"])

    def test_replay_preserves_existing_principles(
        self, tmp_path: Path,
    ) -> None:
        """Existing domain principles aren't disturbed by new constraint
        emissions."""
        prior = {
            "id": "RP-1", "statement": "existing", "confidence": "medium",
            "regime": "", "evidence": [], "contradicts": [],
            "extraction_iteration": 0, "mechanism": "",
            "applicability_bounds": "", "superseded_by": None,
            "status": "active", "category": "domain",
        }
        _write_iter(tmp_path, 1, _findings([_arm("h-main", "REFUTED")]))
        _write_principles(tmp_path, [prior])

        apply_refute_constraints(tmp_path, iteration=1, family="x")

        on_disk = json.loads((tmp_path / "principles.json").read_text())
        ids = [p["id"] for p in on_disk["principles"]]
        assert "RP-1" in ids
        assert len(on_disk["principles"]) == 2  # RP-1 + new constraint

    def test_idempotent_replay_does_not_duplicate(
        self, tmp_path: Path,
    ) -> None:
        """Running the same iteration twice produces the same
        principles file — recovery / re-execution must not duplicate."""
        _write_iter(tmp_path, 1, _findings([_arm("h-main", "REFUTED")]))
        _write_principles(tmp_path, [])

        apply_refute_constraints(tmp_path, iteration=1, family="x")
        first = json.loads((tmp_path / "principles.json").read_text())

        apply_refute_constraints(tmp_path, iteration=1, family="x")
        second = json.loads((tmp_path / "principles.json").read_text())

        assert first == second

    def test_no_refuted_arms_no_change_to_principles(
        self, tmp_path: Path,
    ) -> None:
        _write_iter(tmp_path, 1, _findings([_arm("h-main", "CONFIRMED")]))
        _write_principles(tmp_path, [])

        apply_refute_constraints(tmp_path, iteration=1, family="x")

        on_disk = json.loads((tmp_path / "principles.json").read_text())
        assert on_disk["principles"] == []

    def test_missing_findings_is_no_op(self, tmp_path: Path) -> None:
        """No findings.json → don't crash, don't write."""
        _write_principles(tmp_path, [])
        result = apply_refute_constraints(tmp_path, iteration=1, family="x")
        assert result == []

    def test_methodology_prompt_describes_constraint_reading(self) -> None:
        """design.md tells the LLM what to do with category=meta principles
        whose statement starts with 'Refuted'."""
        prompt = (Path(__file__).resolve().parent.parent
                  / "prompts" / "methodology" / "design.md")
        text = prompt.read_text()
        # Either the explicit blurb or some structured guidance about
        # refuted-mechanism constraints must be present.
        assert "Refuted" in text or "refuted" in text
        assert "category=meta" in text or "constraint" in text.lower()
