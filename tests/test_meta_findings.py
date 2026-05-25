"""Behavioral tests for the deterministic meta-findings emitter (issue #155).

These tests assert what's on disk after the emitter runs, not which
internal helper was called. Per CLAUDE.md, every test uses synthetic
inputs and the StubDispatcher / pure-Python paths — no live LLM calls.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.meta_findings import (
    SCHEMA_VERSION,
    emit_meta_findings,
    evidence_is_concrete,
    render_meta_findings_markdown,
    validate_evidence,
    write_meta_findings,
)
from orchestrator.validate import validate_meta_findings


# ─── Citation floor ────────────────────────────────────────────────────────


class TestEvidenceFloor:
    """The floor distinguishes triagable evidence from aspirational text."""

    @pytest.mark.parametrize("text", [
        "iter-3 design phase failed validation 4 times",
        "executor_log.jsonl lines 12-19 show repeated Bash failures",
        "Read tool call returned \"FileNotFoundError\" in iter-2",
        "input_tokens averaged 42000 across 6 calls",
        "h-main was REFUTED in iter-1, iter-2, iter-3",
        "patches/h-main.patch did not apply cleanly",
        "/Users/sri/inference-sim/sim.go:142 — knob `batch_size` lives here",
        "campaign.yaml: target_system.observable_metrics is unset",
    ])
    def test_concrete_evidence_passes(self, text: str) -> None:
        assert evidence_is_concrete(text), f"should pass: {text!r}"
        assert validate_evidence(text) is None

    @pytest.mark.parametrize("text", [
        "things were slow",
        "it didn't work",
        "needs improvement",
        "this could be better",
        "not great",
    ])
    def test_vague_evidence_fails(self, text: str) -> None:
        assert not evidence_is_concrete(text), f"should fail: {text!r}"
        err = validate_evidence(text)
        assert err is not None
        assert "vague" in err.lower() or "short" in err.lower()

    def test_empty_evidence_fails(self) -> None:
        assert validate_evidence("") is not None
        assert validate_evidence("a") is not None

    def test_non_string_fails(self) -> None:
        # Schema would reject before we get here, but the floor still defends.
        assert validate_evidence(None) is not None  # type: ignore[arg-type]
        assert validate_evidence(123) is not None  # type: ignore[arg-type]


# ─── Emitter behavior on synthetic campaign artifacts ──────────────────────


def _write_state(work_dir: Path, run_id: str = "test-run") -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "state.json").write_text(json.dumps({
        "phase": "DONE", "iteration": 1, "run_id": run_id,
        "family": "test", "timestamp": "2026-05-24T00:00:00Z",
    }))


def _write_ledger(work_dir: Path, iterations: list[int]) -> None:
    rows = [
        {"iteration": i, "status": "completed", "timestamp": "t"}
        for i in iterations
    ]
    (work_dir / "ledger.json").write_text(json.dumps({"iterations": rows}))


def _write_findings(
    work_dir: Path, iteration: int, *,
    h_main_status: str = "CONFIRMED", experiment_valid: bool = True,
) -> None:
    iter_dir = work_dir / "runs" / f"iter-{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    findings = {
        "iteration": iteration,
        "bundle_ref": f"runs/iter-{iteration}/bundle.yaml",
        "arms": [
            {
                "arm_type": "h-main",
                "predicted": ">10%",
                "observed": "12%" if h_main_status == "CONFIRMED" else "-2%",
                "status": h_main_status,
                "error_type": None if h_main_status == "CONFIRMED" else "direction",
                "diagnostic_note": None,
            },
        ],
        "experiment_valid": experiment_valid,
        "discrepancy_analysis": "stub",
    }
    (iter_dir / "findings.json").write_text(json.dumps(findings))


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


class TestEmitterShape:
    """The emitter must produce a schema-valid artifact for any campaign."""

    def test_minimal_campaign_yields_schema_valid_artifact(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        _write_state(work_dir)
        _write_ledger(work_dir, [1])
        _write_findings(work_dir, 1)

        payload = emit_meta_findings(work_dir, campaign={"target_system": {}})
        write_meta_findings(work_dir, payload)

        assert payload["schema_version"] == SCHEMA_VERSION
        assert payload["iterations_completed"] == 1

        result = validate_meta_findings(work_dir)
        assert result["status"] == "pass", result.get("errors")

    def test_artifact_lands_at_workdir_root(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        _write_state(work_dir)
        _write_ledger(work_dir, [1])
        _write_findings(work_dir, 1)

        payload = emit_meta_findings(work_dir, campaign={"target_system": {}})
        path = write_meta_findings(work_dir, payload)

        assert path == work_dir / "meta_findings.json"
        assert path.exists()
        on_disk = json.loads(path.read_text())
        assert on_disk["schema_version"] == SCHEMA_VERSION


class TestSystemAskDetection:
    """Target-system asks should be triggered by retry log + missing campaign fields."""

    def test_unset_observable_metrics_triggers_ask(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        _write_state(work_dir)
        _write_ledger(work_dir, [1])
        _write_findings(work_dir, 1)

        payload = emit_meta_findings(
            work_dir, campaign={"target_system": {"name": "X"}},
        )

        asks = payload["target_system_asks"]
        instr_asks = [a for a in asks if a["kind"] == "instrumentation"]
        assert instr_asks, f"expected an instrumentation ask, got: {asks}"
        # The evidence must be concrete — references campaign.yaml + observable_metrics.
        assert validate_evidence(instr_asks[0]["evidence"]) is None

    def test_set_observable_metrics_does_not_trigger(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        _write_state(work_dir)
        _write_ledger(work_dir, [1])
        _write_findings(work_dir, 1)

        payload = emit_meta_findings(
            work_dir,
            campaign={"target_system": {
                "name": "X",
                "observable_metrics": ["latency_ms", "throughput_qps"],
                "controllable_knobs": ["batch_size"],
            }},
        )
        kinds = {a["kind"] for a in payload["target_system_asks"]}
        assert "instrumentation" not in kinds
        assert "documentation" not in kinds

    def test_repeated_retry_failure_surfaces(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        _write_state(work_dir)
        _write_ledger(work_dir, [1, 2])
        _write_findings(work_dir, 1)
        _write_findings(work_dir, 2)
        _append_jsonl(work_dir / "retry_log.jsonl", [
            {"phase": "execute-analyze", "failure_type": "transient",
             "attempt": 1, "error": "network blip"},
            {"phase": "execute-analyze", "failure_type": "transient",
             "attempt": 2, "error": "network blip again"},
            {"phase": "execute-analyze", "failure_type": "transient",
             "attempt": 3, "error": "network blip third"},
        ])

        payload = emit_meta_findings(
            work_dir,
            campaign={"target_system": {
                "observable_metrics": ["x"], "controllable_knobs": ["y"],
            }},
        )

        repro_asks = [a for a in payload["target_system_asks"]
                      if a["kind"] == "reproducibility"]
        assert repro_asks
        ask = repro_asks[0]
        assert "transient" in ask["evidence"]
        assert "count=3" in ask["evidence"]


class TestNousAskDetection:
    """Nous self-improvement asks come from llm_metrics + retry_log."""

    def test_low_cache_hit_rate_surfaces(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        _write_state(work_dir)
        _write_ledger(work_dir, [1])
        _write_findings(work_dir, 1)
        _append_jsonl(work_dir / "llm_metrics.jsonl", [
            {"phase": "design", "input_tokens": 10000,
             "cache_read_input_tokens": 100, "output_tokens": 500},
            {"phase": "execute", "input_tokens": 8000,
             "cache_read_input_tokens": 200, "output_tokens": 600},
        ])

        payload = emit_meta_findings(
            work_dir,
            campaign={"target_system": {
                "observable_metrics": ["x"], "controllable_knobs": ["y"],
            }},
        )

        token_asks = [a for a in payload["nous_asks"]
                      if a["kind"] == "token_budget"]
        # Either a high-input ask or a low-cache ask must fire.
        assert token_asks
        assert any("cache" in a["evidence"] for a in token_asks)

    def test_no_anomalies_yields_empty_streams(self, tmp_path: Path) -> None:
        """Healthy campaign with full campaign.yaml + cache hits + no retries."""
        work_dir = tmp_path / "campaign"
        _write_state(work_dir)
        _write_ledger(work_dir, [1])
        _write_findings(work_dir, 1)
        _append_jsonl(work_dir / "llm_metrics.jsonl", [
            {"phase": "design", "input_tokens": 1000,
             "cache_read_input_tokens": 800, "output_tokens": 500},
        ])

        payload = emit_meta_findings(
            work_dir,
            campaign={"target_system": {
                "observable_metrics": ["x"], "controllable_knobs": ["y"],
            }},
        )

        # No surprises → all empty + a notes string.
        assert payload["target_system_asks"] == []
        assert payload["nous_asks"] == []
        assert payload["campaign_design_lessons"] == []
        assert "notes" in payload


class TestDesignLessonDetection:
    """Lessons surface from refutation patterns across iterations."""

    def test_invalid_experiment_surfaces_lesson(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        _write_state(work_dir)
        _write_ledger(work_dir, [1])
        _write_findings(work_dir, 1, experiment_valid=False)

        payload = emit_meta_findings(
            work_dir,
            campaign={"target_system": {
                "observable_metrics": ["x"], "controllable_knobs": ["y"],
            }},
        )
        lessons = payload["campaign_design_lessons"]
        assert lessons
        assert any("experiment_valid=false" in l["evidence"] for l in lessons)

    def test_refute_then_confirm_surfaces_lesson(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        _write_state(work_dir)
        _write_ledger(work_dir, [1, 2, 3])
        _write_findings(work_dir, 1, h_main_status="REFUTED")
        _write_findings(work_dir, 2, h_main_status="REFUTED")
        _write_findings(work_dir, 3, h_main_status="CONFIRMED")

        payload = emit_meta_findings(
            work_dir,
            campaign={"target_system": {
                "observable_metrics": ["x"], "controllable_knobs": ["y"],
            }},
        )

        # Should mention the iter-1 refute and iter-3 confirm.
        relevant = [
            l for l in payload["campaign_design_lessons"]
            if "iter-1" in l["evidence"] and "iter-3" in l["evidence"]
        ]
        assert relevant, payload["campaign_design_lessons"]


# ─── Validator-floor regression ───────────────────────────────────────────


class TestValidatorRejectsVague:
    """Hand-crafted meta_findings.json with vague evidence is rejected."""

    def test_vague_evidence_is_rejected(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()
        bad = {
            "schema_version": "1",
            "campaign_design_lessons": [
                {"lesson": "Things should be improved overall",
                 "evidence": "in general, slow"},
            ],
            "target_system_asks": [],
            "nous_asks": [],
        }
        (work_dir / "meta_findings.json").write_text(json.dumps(bad))

        result = validate_meta_findings(work_dir)
        assert result["status"] == "fail"
        joined = " | ".join(result["errors"])
        assert "campaign_design_lessons" in joined
        assert "vague" in joined.lower() or "short" in joined.lower()

    def test_missing_file_is_reported(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()
        result = validate_meta_findings(work_dir)
        assert result["status"] == "fail"
        assert "not found" in result["errors"][0]

    def test_concrete_evidence_passes(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()
        good = {
            "schema_version": "1",
            "campaign_design_lessons": [
                {"lesson": "Tighten experiment_plan validation upstream",
                 "evidence": "findings.json reported experiment_valid=false in iter-2"},
            ],
            "target_system_asks": [],
            "nous_asks": [],
        }
        (work_dir / "meta_findings.json").write_text(json.dumps(good))

        result = validate_meta_findings(work_dir)
        assert result["status"] == "pass", result.get("errors")


# ─── Markdown rendering for nous report ───────────────────────────────────


class TestRenderMarkdown:
    def test_renders_three_sections(self) -> None:
        payload = {
            "schema_version": "1",
            "campaign_design_lessons": [
                {"lesson": "Lesson A", "evidence": "iter-1 details"},
            ],
            "target_system_asks": [
                {"ask": "Ask B", "evidence": "campaign.yaml line 12",
                 "kind": "instrumentation"},
            ],
            "nous_asks": [],
        }
        md = render_meta_findings_markdown(payload)
        assert "## Meta-findings" in md
        assert "### Campaign-design lessons" in md
        assert "### Target-system asks" in md
        assert "### Nous asks" in md
        assert "Lesson A" in md
        assert "iter-1 details" in md
        assert "_None._" in md  # nous asks empty
