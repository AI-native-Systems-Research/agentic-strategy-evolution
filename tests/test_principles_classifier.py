"""Behavioral tests for the principles classifier (issue #179).

The sort_bench dry-run on 2026-05-25 surfaced that extracted principles
ship with `empirical_content` and `derivation_type` unset because the
methodology prompt is advisory and the schema treats them as optional.
This module fills the gap with a deterministic post-extraction
classifier (no LLM) plus a validator that warns when residual unset
principles slip through.

Test contract:
  - `classify_principle({statement: ...})` tags `empirical_content` /
    `derivation_type` based on text heuristics.
  - Obvious-empirical statements (iter-N reference + numeric
    measurement) → empirical_content=True, derivation_type='empirical'.
  - Obvious-algebraic statements (`iff`, `identity`, `theorem`,
    `algebraic`) → empirical_content=False, derivation_type='algebraic'.
  - Pre-tagged principles preserved (explicit > heuristic).
  - Neutral statements left None → validator WARN catches them.
  - `validate_principles_have_empirical_content` returns WARN strings
    for category=domain principles with unset fields; meta-category
    principles (constraint principles from #169) are exempt.
  - `classify_principle_updates_in_place(iter_dir)` mutates
    principle_updates.json atomically and is idempotent.
  - End-to-end: `finalize_iteration` calls the classifier before
    `_merge_principles`, so principles.json reflects the tags.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.iteration import finalize_iteration
from orchestrator.principles_classifier import (
    classify_principle,
    classify_principle_updates_in_place,
    classify_principles,
)
from orchestrator.validate import validate_principles_have_empirical_content


def _principle(*, pid: str, statement: str, category: str = "domain", **extra) -> dict:
    p = {
        "id": pid, "statement": statement, "confidence": "medium",
        "regime": "", "evidence": [], "contradicts": [],
        "extraction_iteration": 1, "mechanism": "",
        "applicability_bounds": "", "superseded_by": None,
        "status": "active", "category": category,
    }
    p.update(extra)
    return p


def _campaign() -> dict:
    return {
        "research_question": "q?",
        "run_id": "demo",
        "max_iterations": 1,
        "target_system": {"name": "x", "description": "d"},
        "prompts": {"methodology_layer": "p"},
    }


# ─── Classifier — single-principle heuristics ─────────────────────────────


class TestClassifyPrinciple:
    def test_obvious_empirical_statement_is_tagged(self) -> None:
        """The exact case from sort_bench RP-2: numeric measurements +
        iter-N reference. This must be tagged empirical."""
        p = _principle(
            pid="RP-1",
            statement=(
                "On nearly_sorted (n=200, k=5), timsort uses 460 "
                "comparisons (iter-1)."
            ),
        )
        out = classify_principle(p)
        assert out["empirical_content"] is True
        assert out["derivation_type"] == "empirical"

    def test_obvious_algebraic_statement_is_tagged(self) -> None:
        """The composite-sensitivity-boundary RP-9 case from #84/#86."""
        p = _principle(
            pid="RP-2",
            statement=(
                "CC_RD > 1.0 iff completion_fraction < 1 - 1/sqrt(N) — "
                "algebraic identity."
            ),
        )
        out = classify_principle(p)
        assert out["empirical_content"] is False
        assert out["derivation_type"] == "algebraic"

    def test_definitional_statement_is_tagged(self) -> None:
        p = _principle(
            pid="RP-3",
            statement=(
                "RD is defined as 1 minus the completion fraction — "
                "by definition."
            ),
        )
        out = classify_principle(p)
        assert out["empirical_content"] is False
        assert out["derivation_type"] == "definitional"

    def test_existing_explicit_tags_are_preserved(self) -> None:
        """Heuristic must NOT overwrite a fielded value. Explicit > heuristic
        — even when the heuristic would have classified differently."""
        p = _principle(
            pid="RP-4",
            statement=(
                "Numbers like 460 and iter-1 appear (would normally "
                "classify empirical) but I have already declared this as "
                "definitional."
            ),
            empirical_content=False,
            derivation_type="definitional",
        )
        out = classify_principle(p)
        assert out["empirical_content"] is False
        assert out["derivation_type"] == "definitional"

    def test_partial_existing_tag_fills_only_unset_field(self) -> None:
        """If empirical_content is set but derivation_type is None,
        only the missing field gets filled in."""
        p = _principle(
            pid="RP-5",
            statement="iter-3 measurement: 0.85 ratio",
            empirical_content=True,
            derivation_type=None,
        )
        out = classify_principle(p)
        assert out["empirical_content"] is True
        assert out["derivation_type"] == "empirical"

    def test_neutral_statement_left_unclassified(self) -> None:
        """When neither side fires strongly, leave fields None — the
        validator warning will surface to the human."""
        p = _principle(
            pid="RP-6",
            statement="The system seems to work well in many cases.",
        )
        out = classify_principle(p)
        # Either both None, or at most one classified weakly. The strict
        # contract: empirical_content must NOT be silently True without
        # numeric / iter evidence.
        assert out.get("empirical_content") is None or out.get("empirical_content") is False

    def test_classifier_is_pure(self) -> None:
        """Input dict must not be mutated — caller may rely on it."""
        p = _principle(pid="RP-7", statement="iter-1 obs 42")
        snapshot = json.dumps(p, sort_keys=True)
        classify_principle(p)
        assert json.dumps(p, sort_keys=True) == snapshot


class TestClassifyPrinciplesBatch:
    def test_batch_classifies_each_independently(self) -> None:
        ps = [
            _principle(pid="A", statement="iter-1 measured 460 comparisons"),
            _principle(pid="B", statement="iff CC_RD > 1.0 — algebraic identity"),
        ]
        out = classify_principles(ps)
        assert out[0]["empirical_content"] is True
        assert out[1]["empirical_content"] is False


# ─── In-place file mutation ───────────────────────────────────────────────


class TestClassifyPrincipleUpdatesInPlace:
    def test_rewrites_principle_updates_json_atomically(self, tmp_path: Path) -> None:
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        updates_path = iter_dir / "principle_updates.json"
        updates_path.write_text(json.dumps([
            _principle(pid="X", statement="iter-1: observed 460 comparisons"),
        ]))

        classify_principle_updates_in_place(iter_dir)

        on_disk = json.loads(updates_path.read_text())
        assert on_disk[0]["empirical_content"] is True

    def test_idempotent_on_already_classified(self, tmp_path: Path) -> None:
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        updates_path = iter_dir / "principle_updates.json"
        updates_path.write_text(json.dumps([
            _principle(
                pid="X", statement="iter-1: measured 460",
                empirical_content=True, derivation_type="empirical",
            ),
        ]))

        classify_principle_updates_in_place(iter_dir)
        once = updates_path.read_text()
        classify_principle_updates_in_place(iter_dir)
        twice = updates_path.read_text()
        assert once == twice

    def test_missing_file_no_op(self, tmp_path: Path) -> None:
        """No principle_updates.json — finalize must not crash."""
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        # No file. Should not raise.
        classify_principle_updates_in_place(iter_dir)


# ─── Validator: WARN on residual unset domain principles ──────────────────


class TestValidatePrinciplesHaveEmpiricalContent:
    def test_warns_on_unset_domain_principle(self) -> None:
        ps = [_principle(pid="X", statement="something neutral")]
        warnings = validate_principles_have_empirical_content(ps)
        assert warnings
        assert any("empirical_content" in w for w in warnings)
        assert any(w.startswith("WARN:") for w in warnings)

    def test_no_warning_when_classified(self) -> None:
        ps = [_principle(
            pid="X", statement="iter-1 measured X",
            empirical_content=True, derivation_type="empirical",
        )]
        warnings = validate_principles_have_empirical_content(ps)
        assert warnings == []

    def test_meta_principles_exempt(self) -> None:
        """Constraint principles from #169 are category=meta and don't
        need empirical_content tagging — they're orchestrator-emitted,
        not LLM-extracted."""
        ps = [_principle(pid="C-1", statement="Refuted: ...", category="meta")]
        warnings = validate_principles_have_empirical_content(ps)
        assert warnings == []


# ─── End-to-end: finalize_iteration runs the classifier ──────────────────


class TestFinalizeIntegrationWithClassifier:
    def test_finalize_classifies_before_merge(self, tmp_path: Path) -> None:
        """The end-to-end regression for #179 — same shape as #177's
        integration test. After finalize_iteration runs, principles.json
        has empirical_content set on the obviously-empirical statement."""
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()
        iter_dir = work_dir / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)

        (work_dir / "state.json").write_text(json.dumps({
            "phase": "HUMAN_FINDINGS_GATE", "iteration": 1, "run_id": "demo",
            "family": None, "timestamp": "2026-05-25T00:00:00Z",
        }))
        (work_dir / "principles.json").write_text(json.dumps({"principles": []}))
        (iter_dir / "findings.json").write_text(json.dumps({
            "iteration": 1, "bundle_ref": "runs/iter-1/bundle.yaml",
            "arms": [], "experiment_valid": True, "discrepancy_analysis": "",
        }))
        (iter_dir / "principle_updates.json").write_text(json.dumps([
            _principle(
                pid="RP-1",
                statement="iter-1: timsort uses 460 comparisons on n=200 k=5",
            ),
        ]))

        finalize_iteration(
            work_dir=work_dir, iter_dir=iter_dir,
            iteration=1, campaign=_campaign(),
        )

        merged = json.loads((work_dir / "principles.json").read_text())
        rp1 = next(p for p in merged["principles"] if p["id"] == "RP-1")
        assert rp1["empirical_content"] is True
        assert rp1["derivation_type"] == "empirical"
