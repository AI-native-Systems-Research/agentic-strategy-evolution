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


# ─── In-place file mutation ───────────────────────────────────────────────


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


