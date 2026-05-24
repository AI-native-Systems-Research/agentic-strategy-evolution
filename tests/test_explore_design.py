"""Behavioral tests for the explore-then-synthesize DESIGN split (#132 Phase A)."""
from __future__ import annotations

from pathlib import Path

from orchestrator.explore_design import (
    DEFAULT_EXPLORE_SCOPES,
    ExploreReport,
    build_explore_prompt,
    build_synthesis_prompt,
    run_explore_stage,
)


def _campaign(**overrides):
    base = {
        "research_question": "What drives saturation?",
        "target_system": {
            "name": "BLIS",
            "description": "Inference simulator.",
            "observable_metrics": ["throughput", "latency"],
            "controllable_knobs": ["batch_size", "scheduling"],
            "repo_path": "/path/to/blis",
        },
    }
    base.update(overrides)
    return base


# ─── Per-scope prompt builders ─────────────────────────────────────────────

class TestBuildExplorePrompt:

    def test_metrics_prompt_focuses_on_observable_metrics(self):
        out = build_explore_prompt("metrics", _campaign())
        assert "Explore: metrics" in out
        assert "metric" in out.lower()
        assert "BLIS" in out  # target name appears

    def test_knobs_prompt_focuses_on_configuration(self):
        out = build_explore_prompt("knobs", _campaign())
        assert "knob" in out.lower() or "config" in out.lower()

    def test_prior_findings_prompt_references_findings_json(self):
        out = build_explore_prompt("prior_findings", _campaign())
        assert "findings.json" in out

    def test_principles_prompt_references_principles_store(self):
        out = build_explore_prompt("principles", _campaign())
        assert "principles" in out.lower()

    def test_every_prompt_marks_explorer_read_only(self):
        for scope in DEFAULT_EXPLORE_SCOPES:
            out = build_explore_prompt(scope, _campaign())
            # Read-only enforcement must be EXPLICIT — Explore subagents
            # don't have write tools, but the prompt should still say so.
            assert "Do not modify" in out or "read-only" in out.lower()


# ─── Run stage A: collect reports ──────────────────────────────────────────

class _RecordingRunner:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, scope: str, prompt: str, campaign: dict) -> ExploreReport:
        self.calls.append({"scope": scope, "prompt": prompt, "campaign": campaign})
        return ExploreReport(
            scope=scope,
            text=f"report for {scope}",
            duration_ms=100,
            input_tokens=200,
            output_tokens=80,
        )


class TestRunExploreStage:

    def test_runs_one_subagent_per_default_scope(self):
        runner = _RecordingRunner()
        result = run_explore_stage(_campaign(), runner=runner)

        assert len(runner.calls) == len(DEFAULT_EXPLORE_SCOPES)
        assert [r.scope for r in result.reports] == list(DEFAULT_EXPLORE_SCOPES)

    def test_custom_scopes_pass_through(self):
        runner = _RecordingRunner()
        run_explore_stage(_campaign(), scopes=["a", "b"], runner=runner)
        assert [c["scope"] for c in runner.calls] == ["a", "b"]

    def test_aggregates_token_counts(self):
        runner = _RecordingRunner()
        result = run_explore_stage(_campaign(), runner=runner)
        # 4 explorers × 200 input × 80 output.
        assert result.total_input_tokens == 800
        assert result.total_output_tokens == 320

    def test_lookup_by_scope_returns_correct_report(self):
        runner = _RecordingRunner()
        result = run_explore_stage(_campaign(), runner=runner)
        report = result.by_scope("metrics")
        assert report is not None
        assert report.scope == "metrics"


# ─── Stage B: synthesis prompt ─────────────────────────────────────────────

class TestBuildSynthesisPrompt:

    def _stage_a(self) -> "ExploreStageResult":  # type: ignore[name-defined]
        runner = _RecordingRunner()
        return run_explore_stage(_campaign(), runner=runner)

    def test_includes_every_explorer_report_under_its_scope(self, tmp_path):
        stage_a = self._stage_a()
        out = build_synthesis_prompt(
            stage_a, campaign=_campaign(), iteration=1,
            iter_dir=tmp_path / "runs" / "iter-1",
        )
        for scope in DEFAULT_EXPLORE_SCOPES:
            assert f"### {scope}" in out
            assert f"report for {scope}" in out

    def test_explicitly_forbids_re_reading_codebase(self, tmp_path):
        stage_a = self._stage_a()
        out = build_synthesis_prompt(
            stage_a, campaign=_campaign(), iteration=1,
            iter_dir=tmp_path / "runs" / "iter-1",
        )
        assert "Do not re-read" in out

    def test_required_outputs_named(self, tmp_path):
        stage_a = self._stage_a()
        out = build_synthesis_prompt(
            stage_a, campaign=_campaign(), iteration=2,
            iter_dir=tmp_path / "runs" / "iter-2",
        )
        assert "problem.md" in out
        assert "bundle.yaml" in out
        assert "iter-2" in out
        assert "bundle.schema.yaml" in out

    def test_research_question_appears(self, tmp_path):
        stage_a = self._stage_a()
        out = build_synthesis_prompt(
            stage_a, campaign=_campaign(), iteration=1,
            iter_dir=tmp_path / "runs" / "iter-1",
        )
        assert "What drives saturation?" in out
