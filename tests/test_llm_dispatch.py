"""Tests for LLMDispatcher — all LLM calls are mocked via completion_fn injection."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest
import yaml

from orchestrator.llm_dispatch import LLMDispatcher
from orchestrator.protocols import Dispatcher


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


def load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text())
    return json.loads(path.read_text())


# ------------------------------------------------------------------
# Mock helpers
# ------------------------------------------------------------------

def make_mock_completion(responses: list[str]):
    """Return a callable mimicking openai chat completions."""
    call_log: list[dict] = []
    idx = {"n": 0}

    def mock_fn(**kwargs):
        call_log.append(kwargs)
        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content=responses[idx["n"]]))]
        idx["n"] += 1
        return resp

    mock_fn.call_log = call_log  # type: ignore[attr-defined]
    return mock_fn


SAMPLE_CAMPAIGN = {
    "research_question": "Does batch size affect latency in TestSystem?",
    "target_system": {
        "name": "TestSystem",
        "description": "A test system for unit tests.",
        "observable_metrics": ["latency_ms", "throughput_rps"],
        "controllable_knobs": ["batch_size", "worker_count"],
    },
    "review": {
        "design_perspectives": ["rigor"],
        "findings_perspectives": ["rigor"],
        "max_review_rounds": 1,
    },
    "prompts": {
        "methodology_layer": "prompts/methodology",
        "domain_adapter_layer": None,
    },
}

VALID_EXPERIMENT_PLAN_YAML = """\
metadata:
  iteration: 1
  bundle_ref: runs/iter-1/bundle.yaml
arms:
  - arm_id: h-main
    conditions:
      - name: baseline
        cmd: "echo baseline"
  - arm_id: h-control-negative
    conditions:
      - name: control
        cmd: "echo control"
"""

VALID_BUNDLE_YAML = """\
metadata:
  iteration: 1
  family: test-family
  research_question: "Does batch size affect latency?"
arms:
  - type: h-main
    prediction: "latency decreases by 20% when batch_size doubles"
    mechanism: "Larger batches amortize fixed overhead"
    diagnostic: "Check if overhead is actually fixed"
  - type: h-control-negative
    prediction: "no effect at batch_size=1"
    mechanism: "No batching means no amortization"
    diagnostic: "Verify single-item path is unchanged"
"""

VALID_FINDINGS_JSON = json.dumps({
    "iteration": 1,
    "bundle_ref": "runs/iter-1/bundle.yaml",
    "experiment_valid": True,
    "arms": [
        {
            "arm_type": "h-main",
            "predicted": "latency decreases by 20%",
            "observed": "latency decreased by 18%",
            "status": "CONFIRMED",
            "error_type": None,
            "diagnostic_note": "Close to predicted value.",
        },
        {
            "arm_type": "h-control-negative",
            "predicted": "no effect at batch_size=1",
            "observed": "no significant change",
            "status": "CONFIRMED",
            "error_type": None,
            "diagnostic_note": None,
        },
    ],
    "discrepancy_analysis": "All arms confirmed. Batch amortization mechanism validated.",
    "dominant_component_pct": None,
}, indent=2)

VALID_PRINCIPLES_JSON = json.dumps({
    "principles": [
        {
            "id": "RP-1",
            "statement": "Batch size amortizes fixed overhead in TestSystem",
            "confidence": "medium",
            "regime": "batch_size > 1",
            "evidence": ["iteration-1-h-main"],
            "contradicts": [],
            "extraction_iteration": 1,
            "mechanism": "Fixed per-request overhead is shared across batch items",
            "applicability_bounds": "Only when fixed overhead dominates",
            "superseded_by": None,
            "category": "domain",
            "status": "active",
        }
    ]
}, indent=2)


@pytest.fixture()
def work_dir(tmp_path: Path) -> Path:
    """Create a work directory with minimal campaign structure."""
    iter_dir = tmp_path / "runs" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "problem.md").write_text(
        "# Problem Framing\n\n## Research Question\n"
        "Does batch size affect latency in TestSystem?\n"
    )
    (iter_dir / "bundle.yaml").write_text(VALID_BUNDLE_YAML)
    (iter_dir / "findings.json").write_text(VALID_FINDINGS_JSON)
    # Stub execution_results.json needed by _build_context for analyze route
    exec_results = {
        "plan_ref": "runs/iter-1/experiment_plan.yaml",
        "setup_results": [],
        "arms": [
            {"arm_id": "h-main", "conditions": [
                {"name": "baseline", "cmd": "echo baseline", "exit_code": 0,
                 "stdout_tail": "baseline", "stderr_tail": "", "output_content": None},
            ]},
        ],
    }
    (iter_dir / "execution_results.json").write_text(json.dumps(exec_results, indent=2))
    (tmp_path / "principles.json").write_text(
        json.dumps({"principles": []}, indent=2)
    )
    return tmp_path


def _make_dispatcher(
    work_dir: Path, responses: list[str], **kwargs
) -> LLMDispatcher:
    return LLMDispatcher(
        work_dir=work_dir,
        campaign=SAMPLE_CAMPAIGN,
        completion_fn=make_mock_completion(responses),
        **kwargs,
    )


# ------------------------------------------------------------------
# Unit tests
# ------------------------------------------------------------------

class TestLLMDispatcher:
    def test_dispatch_planner_design_writes_raw_text(self, work_dir: Path) -> None:
        raw_text = "# Design\n\nHere is the experiment design with a bundle.\n\n```yaml\nmetadata:\n  iteration: 1\n```"
        d = _make_dispatcher(work_dir, [raw_text])
        out = work_dir / "runs" / "iter-1" / "design_out.md"

        d.dispatch("planner", "design", output_path=out, iteration=1)

        assert out.exists()
        assert out.read_text() == raw_text

    def test_dispatch_executor_produces_valid_findings(self, work_dir: Path) -> None:
        resp = f"Analysis:\n\n```json\n{VALID_FINDINGS_JSON}\n```"
        d = _make_dispatcher(work_dir, [resp])
        out = work_dir / "runs" / "iter-1" / "findings_out.json"

        d.dispatch("executor", "analyze", output_path=out, iteration=1)

        findings = json.loads(out.read_text())
        schema = load_schema("findings.schema.json")
        jsonschema.validate(findings, schema)

    def test_dispatch_reviewer_produces_markdown(self, work_dir: Path) -> None:
        review_md = "# Review — rigor\n\n## CRITICAL\nNo CRITICAL findings.\n"
        d = _make_dispatcher(work_dir, [review_md])
        out = work_dir / "runs" / "iter-1" / "review-rigor.md"

        d.dispatch(
            "reviewer", "review-design",
            output_path=out, iteration=1, perspective="rigor",
        )

        assert out.exists()
        assert "rigor" in out.read_text()

    def test_dispatch_extractor_writes_principles(self, work_dir: Path) -> None:
        resp = f"Updated principles:\n\n```json\n{VALID_PRINCIPLES_JSON}\n```"
        d = _make_dispatcher(work_dir, [resp])
        out = work_dir / "principles.json"

        d.dispatch("extractor", "extract", output_path=out, iteration=1)

        store = json.loads(out.read_text())
        assert len(store["principles"]) == 1
        assert store["principles"][0]["id"] == "RP-1"

    def test_design_no_schema_validation_in_dispatcher(self, work_dir: Path) -> None:
        """Design route (fmt=None) writes raw text — no schema validation."""
        raw = "Some design text without any valid yaml"
        mock_fn = make_mock_completion([raw])
        d = LLMDispatcher(
            work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn,
        )
        out = work_dir / "runs" / "iter-1" / "design_raw.md"

        d.dispatch("planner", "design", output_path=out, iteration=1)

        # Only one call — no retry, no schema validation
        assert len(mock_fn.call_log) == 1
        assert out.read_text() == raw

    def test_missing_prompt_template_raises(self, work_dir: Path, tmp_path: Path) -> None:
        empty_prompts = tmp_path / "empty_prompts"
        empty_prompts.mkdir()
        d = _make_dispatcher(work_dir, ["unused"], prompts_dir=empty_prompts)
        out = work_dir / "out.md"

        with pytest.raises(FileNotFoundError):
            d.dispatch("planner", "design", output_path=out, iteration=1)

    def test_protocol_conformance(self, work_dir: Path) -> None:
        d = _make_dispatcher(work_dir, [])
        assert isinstance(d, Dispatcher)

    def test_context_includes_campaign_fields(self, work_dir: Path) -> None:
        raw = "Design output stub."
        mock_fn = make_mock_completion([raw])
        d = LLMDispatcher(
            work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn,
        )
        out = work_dir / "runs" / "iter-1" / "design_ctx.md"

        d.dispatch("planner", "design", output_path=out, iteration=1)

        system_prompt = mock_fn.call_log[0]["messages"][0]["content"]
        assert "TestSystem" in system_prompt
        assert "latency_ms" in system_prompt
        assert "batch_size" in system_prompt

    def test_context_includes_active_principles(self, work_dir: Path) -> None:
        (work_dir / "principles.json").write_text(VALID_PRINCIPLES_JSON)
        raw = "Design with principles context."
        mock_fn = make_mock_completion([raw])
        d = LLMDispatcher(
            work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn,
        )
        out = work_dir / "runs" / "iter-1" / "design_principles.md"

        d.dispatch("planner", "design", output_path=out, iteration=1)

        system_prompt = mock_fn.call_log[0]["messages"][0]["content"]
        assert "Batch size amortizes fixed overhead" in system_prompt

    def test_h_main_result_ignored(self, work_dir: Path) -> None:
        resp = f"```json\n{VALID_FINDINGS_JSON}\n```"
        mock_fn = make_mock_completion([resp])
        d = LLMDispatcher(
            work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn,
        )
        out = work_dir / "runs" / "iter-1" / "findings_hmain.json"

        # Pass REFUTED but executor should still use its own analysis
        d.dispatch(
            "executor", "analyze", output_path=out, iteration=1, h_main_result="REFUTED",
        )

        findings = json.loads(out.read_text())
        # The mock response has CONFIRMED — proving h_main_result was ignored
        assert findings["arms"][0]["status"] == "CONFIRMED"

    def test_no_code_fence_retries_then_raises(self, work_dir: Path) -> None:
        # Raw JSON without code fence triggers retry; if retry also fails, raises
        d = _make_dispatcher(work_dir, [VALID_FINDINGS_JSON, VALID_FINDINGS_JSON])
        out = work_dir / "runs" / "iter-1" / "findings_raw.json"

        with pytest.raises(RuntimeError, match="retry response could not be parsed"):
            d.dispatch("executor", "analyze", output_path=out, iteration=1)

    def test_no_code_fence_retry_succeeds(self, work_dir: Path) -> None:
        # First response has no fence, retry returns a proper fenced response
        fenced = f"```json\n{VALID_FINDINGS_JSON}\n```"
        d = _make_dispatcher(work_dir, [VALID_FINDINGS_JSON, fenced])
        out = work_dir / "runs" / "iter-1" / "findings_retry.json"

        d.dispatch("executor", "analyze", output_path=out, iteration=1)
        findings = json.loads(out.read_text())
        assert "arms" in findings

    def test_multiple_code_fences_uses_last(self, work_dir: Path) -> None:
        first_json = json.dumps({"bad": True})
        resp = (
            f"First attempt:\n```json\n{first_json}\n```\n\n"
            f"Corrected:\n```json\n{VALID_FINDINGS_JSON}\n```"
        )
        d = _make_dispatcher(work_dir, [resp])
        out = work_dir / "runs" / "iter-1" / "findings_multi.json"

        d.dispatch("executor", "analyze", output_path=out, iteration=1)

        findings = json.loads(out.read_text())
        assert "arms" in findings  # Used the valid last fence, not the bad first one

    def test_unknown_role_phase_raises(self, work_dir: Path) -> None:
        d = _make_dispatcher(work_dir, [])
        with pytest.raises(ValueError, match="Unknown role/phase"):
            d.dispatch("wizard", "conjure", output_path=work_dir / "x", iteration=1)


    def test_invalid_campaign_missing_target_system_raises(self, work_dir: Path) -> None:
        bad_campaign = {"review": {}, "prompts": {}}
        with pytest.raises(ValueError, match="missing 'target_system'"):
            LLMDispatcher(
                work_dir=work_dir, campaign=bad_campaign,
                completion_fn=make_mock_completion([]),
            )

    def test_invalid_campaign_missing_keys_raises(self, work_dir: Path) -> None:
        bad_campaign = {
            "target_system": {"name": "X"},
            "review": {},
            "prompts": {},
        }
        with pytest.raises(ValueError, match="missing required keys"):
            LLMDispatcher(
                work_dir=work_dir, campaign=bad_campaign,
                completion_fn=make_mock_completion([]),
            )

    def test_missing_bundle_for_plan_execution_raises(self, work_dir: Path) -> None:
        # Remove the bundle so the plan-execution phase fails with a clear message
        (work_dir / "runs" / "iter-1" / "bundle.yaml").unlink()
        d = _make_dispatcher(work_dir, ["unused"])
        out = work_dir / "runs" / "iter-1" / "experiment_plan.yaml"
        with pytest.raises(FileNotFoundError, match="design phase completed"):
            d.dispatch("executor", "plan-execution", output_path=out, iteration=1)

    def test_missing_findings_for_review_raises(self, work_dir: Path) -> None:
        (work_dir / "runs" / "iter-1" / "findings.json").unlink()
        d = _make_dispatcher(work_dir, ["unused"])
        out = work_dir / "runs" / "iter-1" / "review-test.md"
        with pytest.raises(FileNotFoundError, match="executor completed"):
            d.dispatch(
                "reviewer", "review-findings",
                output_path=out, iteration=1, perspective="test",
            )


class TestExampleCampaign:
    def test_example_campaign_validates_against_schema(self) -> None:
        example_path = Path(__file__).resolve().parent.parent / "examples" / "campaign.yaml"
        campaign = yaml.safe_load(example_path.read_text())
        schema = load_schema("campaign.schema.yaml")
        jsonschema.validate(campaign, schema)


class TestInvestigationSummaryContext:
    """Verify investigation_summary is injected into design prompts."""

    def test_design_iter1_gets_first_iteration_default(self, work_dir: Path) -> None:
        raw = "Design output for iter 1."
        mock_fn = make_mock_completion([raw])
        d = LLMDispatcher(
            work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn,
        )
        out = work_dir / "runs" / "iter-1" / "design_ctx.md"
        d.dispatch("planner", "design", output_path=out, iteration=1)
        prompt = mock_fn.call_log[0]["messages"][0]["content"]
        assert "first iteration" in prompt.lower()

    def test_design_iter2_includes_previous_summary(self, work_dir: Path) -> None:
        # Set up iter-2 directory with bundle
        iter2 = work_dir / "runs" / "iter-2"
        iter2.mkdir(parents=True)
        (iter2 / "bundle.yaml").write_text(VALID_BUNDLE_YAML)
        # Write investigation summary for iter-1
        summary = {
            "iteration": 1,
            "what_was_tested": "Batch size amortization",
            "key_findings": "H-main confirmed at 18% improvement",
            "principles_changed": "Inserted RP-1",
            "open_questions": "Does this hold under high load?",
            "suggested_next_direction": "Test with worker_count scaling",
        }
        summary_path = work_dir / "runs" / "iter-1" / "investigation_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2))

        raw = "Design output for iter 2."
        mock_fn = make_mock_completion([raw])
        d = LLMDispatcher(
            work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn,
        )
        out = iter2 / "design_ctx.md"
        d.dispatch("planner", "design", output_path=out, iteration=2)
        prompt = mock_fn.call_log[0]["messages"][0]["content"]
        assert "Batch size amortization" in prompt
        assert "H-main confirmed" in prompt

    def test_design_iter2_missing_summary_gets_default(self, work_dir: Path) -> None:
        # Set up iter-2 without a summary for iter-1
        iter2 = work_dir / "runs" / "iter-2"
        iter2.mkdir(parents=True)
        (iter2 / "bundle.yaml").write_text(VALID_BUNDLE_YAML)

        raw = "Design output without prior summary."
        mock_fn = make_mock_completion([raw])
        d = LLMDispatcher(
            work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn,
        )
        out = iter2 / "design_ctx.md"
        d.dispatch("planner", "design", output_path=out, iteration=2)
        prompt = mock_fn.call_log[0]["messages"][0]["content"]
        assert "No investigation summary available" in prompt

    def test_design_gets_research_question_from_campaign(self, work_dir: Path) -> None:
        """Design phase gets research_question from campaign config directly."""
        raw = "Design output."
        mock_fn = make_mock_completion([raw])
        d = LLMDispatcher(
            work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn,
        )
        out = work_dir / "runs" / "iter-1" / "design_rq.md"
        d.dispatch("planner", "design", output_path=out, iteration=1)
        prompt = mock_fn.call_log[0]["messages"][0]["content"]
        assert "Does batch size affect latency in TestSystem?" in prompt


class TestSummarizeDispatch:
    """Verify the summarize route works end-to-end via LLMDispatcher."""

    VALID_SUMMARY_JSON = json.dumps({
        "iteration": 1,
        "what_was_tested": "Batch size amortization hypothesis",
        "key_findings": "H-main confirmed with 18% latency reduction",
        "principles_changed": "Inserted RP-1: batch amortization",
        "open_questions": "Does this hold under high contention?",
        "suggested_next_direction": "Test with concurrent workers",
    }, indent=2)

    def test_dispatch_summarize_produces_valid_summary(self, work_dir: Path) -> None:
        resp = f"```json\n{self.VALID_SUMMARY_JSON}\n```"
        d = _make_dispatcher(work_dir, [resp])
        out = work_dir / "runs" / "iter-1" / "investigation_summary.json"
        d.dispatch("extractor", "summarize", output_path=out, iteration=1)
        assert out.exists()
        summary = json.loads(out.read_text())
        schema = load_schema("investigation_summary.schema.json")
        jsonschema.validate(summary, schema)

    def test_summarize_context_includes_bundle_and_findings(self, work_dir: Path) -> None:
        resp = f"```json\n{self.VALID_SUMMARY_JSON}\n```"
        mock_fn = make_mock_completion([resp])
        d = LLMDispatcher(
            work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn,
        )
        out = work_dir / "runs" / "iter-1" / "investigation_summary.json"
        d.dispatch("extractor", "summarize", output_path=out, iteration=1)
        prompt = mock_fn.call_log[0]["messages"][0]["content"]
        # Should contain bundle and findings content
        assert "h-main" in prompt
        assert "CONFIRMED" in prompt


# Minimal campaign without observable_metrics/controllable_knobs
MINIMAL_CAMPAIGN = {
    "research_question": "What drives latency in MySystem?",
    "target_system": {
        "name": "MySystem",
        "description": "A system under test.",
        "repo_path": "/tmp/fake-repo",
    },
    "review": {
        "design_perspectives": ["rigor"],
        "findings_perspectives": ["rigor"],
        "max_review_rounds": 1,
    },
    "prompts": {
        "methodology_layer": "prompts/methodology",
        "domain_adapter_layer": None,
    },
}


class TestSimplifiedCampaign:
    """Campaigns without observable_metrics/controllable_knobs should be valid."""

    def test_minimal_campaign_accepted_by_dispatcher(self, work_dir: Path) -> None:
        """LLMDispatcher should accept a campaign without metrics/knobs."""
        d = LLMDispatcher(
            work_dir=work_dir,
            campaign=MINIMAL_CAMPAIGN,
            completion_fn=make_mock_completion(["stub"]),
        )
        assert isinstance(d, Dispatcher)

    def test_minimal_campaign_context_has_empty_metrics(self, work_dir: Path) -> None:
        """Context should show 'Not specified' for missing metrics/knobs."""
        raw = "Design output stub."
        mock_fn = make_mock_completion([raw])
        d = LLMDispatcher(
            work_dir=work_dir,
            campaign=MINIMAL_CAMPAIGN,
            completion_fn=mock_fn,
        )
        out = work_dir / "runs" / "iter-1" / "design_minimal.md"
        d.dispatch("planner", "design", output_path=out, iteration=1)
        prompt = mock_fn.call_log[0]["messages"][0]["content"]
        assert "Not specified" in prompt

    def test_full_campaign_still_works(self, work_dir: Path) -> None:
        """Existing full campaigns with metrics/knobs remain valid."""
        raw = "Design output stub."
        mock_fn = make_mock_completion([raw])
        d = LLMDispatcher(
            work_dir=work_dir,
            campaign=SAMPLE_CAMPAIGN,
            completion_fn=mock_fn,
        )
        out = work_dir / "runs" / "iter-1" / "design_full.md"
        d.dispatch("planner", "design", output_path=out, iteration=1)
        prompt = mock_fn.call_log[0]["messages"][0]["content"]
        assert "latency_ms" in prompt

    def test_minimal_campaign_validates_against_schema(self) -> None:
        """Schema should accept campaign without metrics/knobs."""
        schema = load_schema("campaign.schema.yaml")
        jsonschema.validate(MINIMAL_CAMPAIGN, schema)


class TestGateSummaryDispatch:
    """Verify the summarizer/summarize-gate route works."""

    VALID_GATE_SUMMARY = json.dumps({
        "gate_type": "design",
        "summary": "Testing whether batch size amortizes overhead in TestSystem.",
        "key_points": [
            "H-main predicts 20% latency reduction when batch_size doubles",
            "Control-negative checks no effect at batch_size=1",
            "Confirms if fixed overhead is the bottleneck",
        ],
    }, indent=2)

    def test_dispatch_summarize_gate_produces_valid_summary(self, work_dir: Path) -> None:
        resp = f"```json\n{self.VALID_GATE_SUMMARY}\n```"
        d = _make_dispatcher(work_dir, [resp])
        out = work_dir / "runs" / "iter-1" / "gate_summary.json"
        d.dispatch("summarizer", "summarize-gate", output_path=out, iteration=1)
        assert out.exists()
        summary = json.loads(out.read_text())
        schema = load_schema("gate_summary.schema.json")
        jsonschema.validate(summary, schema)

    def test_summarize_gate_context_includes_bundle(self, work_dir: Path) -> None:
        resp = f"```json\n{self.VALID_GATE_SUMMARY}\n```"
        mock_fn = make_mock_completion([resp])
        d = LLMDispatcher(
            work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn,
        )
        out = work_dir / "runs" / "iter-1" / "gate_summary.json"
        d.dispatch(
            "summarizer", "summarize-gate", output_path=out, iteration=1,
            perspective="design",
        )
        prompt = mock_fn.call_log[0]["messages"][0]["content"]
        assert "h-main" in prompt.lower() or "bundle" in prompt.lower()


class TestHumanFeedbackContext:
    """Verify human_feedback.json is read per-phase instead of feedback.md."""

    def test_design_phase_reads_design_feedback(self, work_dir: Path) -> None:
        fb = {
            "design": [{"attempt": 1, "reason": "Control arm is trivial", "timestamp": "2026-01-01T00:01:00+00:00"}],
            "findings": [],
        }
        (work_dir / "runs" / "iter-1" / "human_feedback.json").write_text(json.dumps(fb))
        raw = "Design output with feedback."
        mock_fn = make_mock_completion([raw])
        d = LLMDispatcher(work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn)
        d.dispatch("planner", "design", output_path=work_dir / "runs" / "iter-1" / "design_fb.md", iteration=1)
        prompt = mock_fn.call_log[0]["messages"][0]["content"]
        assert "Control arm is trivial" in prompt

    def test_no_feedback_file_gives_empty_context(self, work_dir: Path) -> None:
        # Ensure no feedback file exists
        fb_path = work_dir / "runs" / "iter-1" / "human_feedback.json"
        if fb_path.exists():
            fb_path.unlink()
        raw = "Design stub."
        mock_fn = make_mock_completion([raw])
        d = LLMDispatcher(work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn)
        d.dispatch("planner", "design", output_path=work_dir / "runs" / "iter-1" / "design_nofb.md", iteration=1)
        prompt = mock_fn.call_log[0]["messages"][0]["content"]
        assert "Human Feedback" not in prompt

    def test_plan_execution_loads_findings_json_context(self, work_dir: Path) -> None:
        """plan-execution phase should load findings.json into context dict."""
        resp = f"```yaml\n{VALID_EXPERIMENT_PLAN_YAML}\n```"
        mock_fn = make_mock_completion([resp])
        d = LLMDispatcher(work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn)
        # Verify _build_context includes findings_json for plan-execution
        ctx = d._build_context("executor", "plan-execution", iteration=1, perspective=None)
        assert "findings_json" in ctx
        assert "CONFIRMED" in ctx["findings_json"]

    def test_plan_execution_reads_findings_feedback(self, work_dir: Path) -> None:
        """plan-execution maps to 'findings' key in human_feedback.json."""
        fb = {"framing": [], "design": [], "findings": [
            {"attempt": 1, "reason": "Results look suspicious", "timestamp": "2026-01-01T00:00:00+00:00"}
        ]}
        (work_dir / "runs" / "iter-1" / "human_feedback.json").write_text(json.dumps(fb))
        d = LLMDispatcher(work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=make_mock_completion(["stub"]))
        ctx = d._build_context("executor", "plan-execution", iteration=1, perspective=None)
        assert "Results look suspicious" in ctx["human_feedback"]

    def test_multiple_rejections_uses_latest(self, work_dir: Path) -> None:
        fb = {"design": [
            {"attempt": 1, "reason": "First issue", "timestamp": "2026-01-01T00:00:00+00:00"},
            {"attempt": 2, "reason": "Still weak after revision", "timestamp": "2026-01-01T00:01:00+00:00"},
        ], "findings": []}
        (work_dir / "runs" / "iter-1" / "human_feedback.json").write_text(json.dumps(fb))
        mock_fn = make_mock_completion(["Design stub."])
        d = LLMDispatcher(work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn)
        d.dispatch("planner", "design", output_path=work_dir / "runs" / "iter-1" / "design_multi_fb.md", iteration=1)
        prompt = mock_fn.call_log[0]["messages"][0]["content"]
        assert "Still weak after revision" in prompt
        assert "First issue" not in prompt
        assert "attempt 2" in prompt.lower()

    def test_corrupt_feedback_json_gives_empty_context(self, work_dir: Path) -> None:
        (work_dir / "runs" / "iter-1" / "human_feedback.json").write_text("not valid json{{{")
        raw = "Design stub."
        mock_fn = make_mock_completion([raw])
        d = LLMDispatcher(work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn)
        d.dispatch("planner", "design", output_path=work_dir / "runs" / "iter-1" / "design_corrupt_fb.md", iteration=1)
        prompt = mock_fn.call_log[0]["messages"][0]["content"]
        assert "Human Feedback" not in prompt

    def test_plan_execution_without_findings_does_not_crash(self, work_dir: Path) -> None:
        """First run: plan-execution should not crash when findings.json is missing."""
        (work_dir / "runs" / "iter-1" / "findings.json").unlink()
        resp = f"```yaml\n{VALID_EXPERIMENT_PLAN_YAML}\n```"
        mock_fn = make_mock_completion([resp])
        d = LLMDispatcher(work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn)
        d.dispatch("executor", "plan-execution", output_path=work_dir / "runs" / "iter-1" / "experiment_plan.yaml", iteration=1)
