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
    """Return a callable mimicking litellm.completion."""
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
    def test_dispatch_planner_frame_writes_problem_md(self, work_dir: Path) -> None:
        md = "# Problem Framing\n\n## Research Question\nDoes batch size matter?"
        d = _make_dispatcher(work_dir, [md])
        out = work_dir / "runs" / "iter-1" / "problem.md"

        d.dispatch("planner", "frame", output_path=out, iteration=1)

        assert out.exists()
        assert "Research Question" in out.read_text()

    def test_dispatch_planner_design_produces_valid_bundle(self, work_dir: Path) -> None:
        resp = f"Here is the bundle:\n\n```yaml\n{VALID_BUNDLE_YAML}```"
        d = _make_dispatcher(work_dir, [resp])
        out = work_dir / "runs" / "iter-1" / "bundle_out.yaml"

        d.dispatch("planner", "design", output_path=out, iteration=1)

        bundle = yaml.safe_load(out.read_text())
        schema = load_schema("bundle.schema.yaml")
        jsonschema.validate(bundle, schema)

    def test_dispatch_executor_produces_valid_findings(self, work_dir: Path) -> None:
        resp = f"Analysis:\n\n```json\n{VALID_FINDINGS_JSON}\n```"
        d = _make_dispatcher(work_dir, [resp])
        out = work_dir / "runs" / "iter-1" / "findings_out.json"

        d.dispatch("executor", "run", output_path=out, iteration=1)

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

    def test_schema_validation_failure_retries_once(self, work_dir: Path) -> None:
        # First response: invalid bundle (missing research_question)
        bad_yaml = "metadata:\n  iteration: 1\n  family: x\narms:\n  - type: h-main\n    prediction: p\n    mechanism: m\n    diagnostic: d\n"
        bad_resp = f"```yaml\n{bad_yaml}```"
        good_resp = f"```yaml\n{VALID_BUNDLE_YAML}```"
        mock_fn = make_mock_completion([bad_resp, good_resp])
        d = LLMDispatcher(
            work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn,
        )
        out = work_dir / "runs" / "iter-1" / "bundle_retry.yaml"

        d.dispatch("planner", "design", output_path=out, iteration=1)

        assert len(mock_fn.call_log) == 2
        bundle = yaml.safe_load(out.read_text())
        assert bundle["metadata"]["research_question"] is not None

    def test_schema_validation_failure_after_retry_raises(self, work_dir: Path) -> None:
        bad_yaml = "metadata:\n  iteration: 1\n  family: x\narms:\n  - type: h-main\n    prediction: p\n    mechanism: m\n    diagnostic: d\n"
        bad_resp = f"```yaml\n{bad_yaml}```"
        mock_fn = make_mock_completion([bad_resp, bad_resp])
        d = LLMDispatcher(
            work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn,
        )
        out = work_dir / "runs" / "iter-1" / "bundle_fail.yaml"

        with pytest.raises(RuntimeError, match="schema validation after retry"):
            d.dispatch("planner", "design", output_path=out, iteration=1)

    def test_missing_prompt_template_raises(self, work_dir: Path, tmp_path: Path) -> None:
        empty_prompts = tmp_path / "empty_prompts"
        empty_prompts.mkdir()
        d = _make_dispatcher(work_dir, ["unused"], prompts_dir=empty_prompts)
        out = work_dir / "out.md"

        with pytest.raises(FileNotFoundError):
            d.dispatch("planner", "frame", output_path=out, iteration=1)

    def test_protocol_conformance(self, work_dir: Path) -> None:
        d = _make_dispatcher(work_dir, [])
        assert isinstance(d, Dispatcher)

    def test_context_includes_campaign_fields(self, work_dir: Path) -> None:
        md = "# Framing\n\nStub output."
        mock_fn = make_mock_completion([md])
        d = LLMDispatcher(
            work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn,
        )
        out = work_dir / "runs" / "iter-1" / "problem.md"

        d.dispatch("planner", "frame", output_path=out, iteration=1)

        system_prompt = mock_fn.call_log[0]["messages"][0]["content"]
        assert "TestSystem" in system_prompt
        assert "latency_ms" in system_prompt
        assert "batch_size" in system_prompt

    def test_context_includes_active_principles(self, work_dir: Path) -> None:
        (work_dir / "principles.json").write_text(VALID_PRINCIPLES_JSON)
        resp = f"```yaml\n{VALID_BUNDLE_YAML}```"
        mock_fn = make_mock_completion([resp])
        d = LLMDispatcher(
            work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, completion_fn=mock_fn,
        )
        out = work_dir / "runs" / "iter-1" / "bundle_principles.yaml"

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
            "executor", "run", output_path=out, iteration=1, h_main_result="REFUTED",
        )

        findings = json.loads(out.read_text())
        # The mock response has CONFIRMED — proving h_main_result was ignored
        assert findings["arms"][0]["status"] == "CONFIRMED"

    def test_no_code_fence_raises(self, work_dir: Path) -> None:
        # Raw JSON without code fence should raise, not silently parse
        d = _make_dispatcher(work_dir, [VALID_FINDINGS_JSON])
        out = work_dir / "runs" / "iter-1" / "findings_raw.json"

        with pytest.raises(RuntimeError, match="No ```json``` code fence found"):
            d.dispatch("executor", "run", output_path=out, iteration=1)

    def test_multiple_code_fences_uses_last(self, work_dir: Path) -> None:
        first_json = json.dumps({"bad": True})
        resp = (
            f"First attempt:\n```json\n{first_json}\n```\n\n"
            f"Corrected:\n```json\n{VALID_FINDINGS_JSON}\n```"
        )
        d = _make_dispatcher(work_dir, [resp])
        out = work_dir / "runs" / "iter-1" / "findings_multi.json"

        d.dispatch("executor", "run", output_path=out, iteration=1)

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

    def test_missing_bundle_for_run_raises(self, work_dir: Path) -> None:
        # Remove the bundle so the run phase fails with a clear message
        (work_dir / "runs" / "iter-1" / "bundle.yaml").unlink()
        d = _make_dispatcher(work_dir, ["unused"])
        out = work_dir / "runs" / "iter-1" / "findings_fail.json"
        with pytest.raises(FileNotFoundError, match="design phase completed"):
            d.dispatch("executor", "run", output_path=out, iteration=1)

    def test_missing_findings_for_review_raises(self, work_dir: Path) -> None:
        (work_dir / "runs" / "iter-1" / "findings.json").unlink()
        d = _make_dispatcher(work_dir, ["unused"])
        out = work_dir / "runs" / "iter-1" / "review-test.md"
        with pytest.raises(FileNotFoundError, match="executor completed"):
            d.dispatch(
                "reviewer", "review-findings",
                output_path=out, iteration=1, perspective="test",
            )


class TestBLISCampaign:
    def test_blis_campaign_validates_against_schema(self) -> None:
        blis_path = Path(__file__).resolve().parent.parent / "examples" / "blis" / "campaign.yaml"
        campaign = yaml.safe_load(blis_path.read_text())
        schema = load_schema("campaign.schema.yaml")
        jsonschema.validate(campaign, schema)


# ------------------------------------------------------------------
# Real execution routes (run-plan, run-analyze)
# ------------------------------------------------------------------

VALID_EXPERIMENT_PLAN_JSON = json.dumps({
    "baseline": {
        "description": "Default config baseline",
        "command": "./sim run --metrics-path {metrics_path}",
    },
    "experiments": [
        {
            "arm_type": "h-main",
            "description": "Test batch size doubling",
            "config_changes": "Added --batch-size 64",
            "command": "./sim run --batch-size 64 --metrics-path {metrics_path}",
        },
        {
            "arm_type": "h-control-negative",
            "description": "Single item batch",
            "config_changes": "Set --batch-size 1",
            "command": "./sim run --batch-size 1 --metrics-path {metrics_path}",
        },
    ],
}, indent=2)

SAMPLE_CAMPAIGN_WITH_EXECUTION = {
    **SAMPLE_CAMPAIGN,
    "target_system": {
        **SAMPLE_CAMPAIGN["target_system"],
        "execution": {
            "run_command": "./sim run --metrics-path {metrics_path}",
            "repo_path": None,
            "timeout": 300,
        },
    },
}


class TestRunPlanDispatch:
    def test_dispatch_run_plan_produces_valid_plan(self, work_dir: Path) -> None:
        response = f"```json\n{VALID_EXPERIMENT_PLAN_JSON}\n```"
        d = LLMDispatcher(
            work_dir=work_dir,
            campaign=SAMPLE_CAMPAIGN_WITH_EXECUTION,
            completion_fn=make_mock_completion([response]),
        )
        out = work_dir / "runs" / "iter-1" / "experiment_plan.json"
        d.dispatch("executor", "run-plan", output_path=out, iteration=1)
        assert out.exists()
        plan = json.loads(out.read_text())
        schema = load_schema("experiment_plan.schema.json")
        jsonschema.validate(plan, schema)
        assert plan["baseline"]["command"]
        assert len(plan["experiments"]) == 2

    def test_run_plan_context_includes_execution_config(self, work_dir: Path) -> None:
        response = f"```json\n{VALID_EXPERIMENT_PLAN_JSON}\n```"
        mock = make_mock_completion([response])
        d = LLMDispatcher(
            work_dir=work_dir,
            campaign=SAMPLE_CAMPAIGN_WITH_EXECUTION,
            completion_fn=mock,
        )
        out = work_dir / "runs" / "iter-1" / "experiment_plan.json"
        d.dispatch("executor", "run-plan", output_path=out, iteration=1)
        # The prompt should contain the run_command_template
        prompt = mock.call_log[0]["messages"][0]["content"]
        assert "./sim run --metrics-path {metrics_path}" in prompt

    def test_run_plan_missing_bundle_raises(self, work_dir: Path) -> None:
        (work_dir / "runs" / "iter-1" / "bundle.yaml").unlink()
        d = LLMDispatcher(
            work_dir=work_dir,
            campaign=SAMPLE_CAMPAIGN_WITH_EXECUTION,
            completion_fn=make_mock_completion(["unused"]),
        )
        out = work_dir / "runs" / "iter-1" / "plan.json"
        with pytest.raises(FileNotFoundError, match="design phase completed"):
            d.dispatch("executor", "run-plan", output_path=out, iteration=1)


class TestRunAnalyzeDispatch:
    def test_dispatch_run_analyze_produces_valid_findings(self, work_dir: Path) -> None:
        # Write experiment results to disk
        results = {"baseline": {"latency_ms": 100}, "h-main": {"latency_ms": 80}}
        results_path = work_dir / "runs" / "iter-1" / "experiment_results.json"
        results_path.write_text(json.dumps(results, indent=2))

        response = f"```json\n{VALID_FINDINGS_JSON}\n```"
        d = LLMDispatcher(
            work_dir=work_dir,
            campaign=SAMPLE_CAMPAIGN_WITH_EXECUTION,
            completion_fn=make_mock_completion([response]),
        )
        out = work_dir / "runs" / "iter-1" / "findings_real.json"
        d.dispatch("executor", "run-analyze", output_path=out, iteration=1)
        assert out.exists()
        findings = json.loads(out.read_text())
        schema = load_schema("findings.schema.json")
        jsonschema.validate(findings, schema)

    def test_run_analyze_context_includes_experiment_results(self, work_dir: Path) -> None:
        results = {"baseline": {"latency_ms": 100}, "h-main": {"latency_ms": 80}}
        results_path = work_dir / "runs" / "iter-1" / "experiment_results.json"
        results_path.write_text(json.dumps(results, indent=2))

        response = f"```json\n{VALID_FINDINGS_JSON}\n```"
        mock = make_mock_completion([response])
        d = LLMDispatcher(
            work_dir=work_dir,
            campaign=SAMPLE_CAMPAIGN_WITH_EXECUTION,
            completion_fn=mock,
        )
        out = work_dir / "runs" / "iter-1" / "findings_real.json"
        d.dispatch("executor", "run-analyze", output_path=out, iteration=1)
        prompt = mock.call_log[0]["messages"][0]["content"]
        assert "latency_ms" in prompt

    def test_run_analyze_missing_results_raises(self, work_dir: Path) -> None:
        d = LLMDispatcher(
            work_dir=work_dir,
            campaign=SAMPLE_CAMPAIGN_WITH_EXECUTION,
            completion_fn=make_mock_completion(["unused"]),
        )
        out = work_dir / "runs" / "iter-1" / "findings_real.json"
        with pytest.raises(FileNotFoundError, match="experiment_results.json"):
            d.dispatch("executor", "run-analyze", output_path=out, iteration=1)

    def test_analysis_mode_still_works(self, work_dir: Path) -> None:
        """Existing (executor, run) route still works with no execution config."""
        response = f"```json\n{VALID_FINDINGS_JSON}\n```"
        d = _make_dispatcher(work_dir, [response])
        out = work_dir / "runs" / "iter-1" / "findings_analysis.json"
        d.dispatch("executor", "run", output_path=out, iteration=1)
        assert out.exists()
        findings = json.loads(out.read_text())
        schema = load_schema("findings.schema.json")
        jsonschema.validate(findings, schema)
