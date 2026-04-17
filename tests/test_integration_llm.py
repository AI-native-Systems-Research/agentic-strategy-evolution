"""Integration test — full single-iteration loop with mocked LLM responses."""
import json
import shutil
import warnings
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest
import yaml

from orchestrator.engine import Engine
from orchestrator.llm_dispatch import LLMDispatcher
from orchestrator.fastfail import check_fast_fail, FastFailAction
from orchestrator.gates import HumanGate


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

SAMPLE_CAMPAIGN = {
    "research_question": "Does batch size affect latency in TestSystem?",
    "target_system": {
        "name": "TestSystem",
        "description": "A test system for integration testing.",
        "observable_metrics": ["latency_ms", "throughput_rps"],
        "controllable_knobs": ["batch_size", "worker_count"],
    },
    "review": {
        "design_perspectives": ["rigor", "causal"],
        "findings_perspectives": ["rigor", "causal"],
        "max_review_rounds": 1,
    },
    "prompts": {
        "methodology_layer": "prompts/methodology",
        "domain_adapter_layer": None,
    },
}

BUNDLE_YAML = """\
metadata:
  iteration: 1
  family: integration-test
  research_question: "Does batch size affect latency in TestSystem?"
arms:
  - type: h-main
    prediction: "latency decreases by 20% when batch_size doubles"
    mechanism: "Larger batches amortize fixed overhead"
    diagnostic: "Check if overhead is actually fixed"
  - type: h-control-negative
    prediction: "no effect at batch_size=1"
    mechanism: "No batching means no amortization"
    diagnostic: "Verify single-item path"
"""

FINDINGS_JSON = json.dumps({
    "iteration": 1,
    "bundle_ref": "runs/iter-1/bundle.yaml",
    "arms": [
        {
            "arm_type": "h-main",
            "predicted": "latency decreases by 20% when batch_size doubles",
            "observed": "latency decreased by 22%",
            "status": "CONFIRMED",
            "error_type": None,
            "diagnostic_note": "Consistent with amortization model.",
        },
        {
            "arm_type": "h-control-negative",
            "predicted": "no effect at batch_size=1",
            "observed": "no significant change observed",
            "status": "CONFIRMED",
            "error_type": None,
            "diagnostic_note": None,
        },
    ],
    "discrepancy_analysis": "All arms confirmed. Batch amortization holds.",
    "dominant_component_pct": None,
}, indent=2)

PRINCIPLES_JSON = json.dumps({
    "principles": [
        {
            "id": "RP-1",
            "statement": "Batch size amortizes fixed overhead",
            "confidence": "medium",
            "regime": "batch_size > 1",
            "evidence": ["iteration-1-h-main"],
            "contradicts": [],
            "extraction_iteration": 1,
            "mechanism": "Fixed per-request overhead shared across batch",
            "applicability_bounds": "Only when fixed overhead dominates",
            "superseded_by": None,
            "category": "domain",
            "status": "active",
        }
    ]
}, indent=2)


def _mock_responses() -> dict[tuple[str, str], str]:
    """Map (role, phase) to canned LLM responses."""
    return {
        ("planner", "frame"): (
            "# Problem Framing\n\n"
            "## Research Question\nDoes batch size affect latency?\n\n"
            "## Baseline\nSingle-request latency is 50ms.\n\n"
            "## Experimental Conditions\nVary batch_size from 1 to 64.\n\n"
            "## Success Criteria\n20% latency reduction at batch_size=32.\n\n"
            "## Constraints\nThroughput must not degrade.\n\n"
            "## Prior Knowledge\nNo principles extracted yet.\n"
        ),
        ("planner", "design"): f"```yaml\n{BUNDLE_YAML}```",
        ("executor", "run"): f"```json\n{FINDINGS_JSON}\n```",
        ("reviewer", "review-design"): (
            "# Review — {perspective}\n\n"
            "## CRITICAL\nNo CRITICAL findings.\n\n"
            "## IMPORTANT\nNo IMPORTANT findings.\n\n"
            "## SUGGESTION\nConsider adding a robustness arm.\n"
        ),
        ("reviewer", "review-findings"): (
            "# Review — {perspective}\n\n"
            "## CRITICAL\nNo CRITICAL findings.\n\n"
            "## IMPORTANT\nNo IMPORTANT findings.\n\n"
            "## SUGGESTION\nReport confidence intervals.\n"
        ),
        ("extractor", "extract"): f"```json\n{PRINCIPLES_JSON}\n```",
    }


def _make_routing_completion(responses: dict[tuple[str, str], str]):
    """Build a completion_fn that returns canned responses based on prompt content."""
    call_log: list[dict] = []

    def mock_fn(**kwargs):
        call_log.append(kwargs)
        system_msg = kwargs["messages"][0]["content"]

        # Determine which response to return based on prompt keywords
        if "problem framing document" in system_msg:
            text = responses[("planner", "frame")]
        elif "principle store" in system_msg.lower():
            text = responses[("extractor", "extract")]
        elif "hypothesis bundle" in system_msg and "review" not in system_msg.lower():
            text = responses[("planner", "design")]
        elif "review" in system_msg.lower() and "hypothesis bundle" in system_msg.lower():
            text = responses[("reviewer", "review-design")]
        elif "review" in system_msg.lower() and "experiment findings" in system_msg.lower():
            text = responses[("reviewer", "review-findings")]
        elif "analyze" in system_msg.lower() and "findings" in system_msg.lower():
            text = responses[("executor", "run")]
        else:
            text = "Unrecognized prompt."

        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content=text))]
        return resp

    mock_fn.call_log = call_log  # type: ignore[attr-defined]
    return mock_fn


def load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text())
    return json.loads(path.read_text())


@pytest.fixture(autouse=True)
def _allow_auto_approve(monkeypatch):
    monkeypatch.setenv("NOUS_ALLOW_AUTO_APPROVE", "1")


def _make_gate():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return HumanGate(auto_approve=True)


class TestSingleIterationWithMockedLLM:
    """Drive the full orchestrator loop with LLMDispatcher and mocked LLM responses."""

    @pytest.fixture()
    def campaign_dir(self, tmp_path: Path) -> Path:
        shutil.copy(TEMPLATES_DIR / "state.json", tmp_path / "state.json")
        shutil.copy(TEMPLATES_DIR / "ledger.json", tmp_path / "ledger.json")
        shutil.copy(TEMPLATES_DIR / "principles.json", tmp_path / "principles.json")
        state = json.loads((tmp_path / "state.json").read_text())
        state["run_id"] = "test-llm-integration-001"
        (tmp_path / "state.json").write_text(json.dumps(state, indent=2))
        return tmp_path

    def test_full_iteration_with_mocked_llm(self, campaign_dir: Path) -> None:
        engine = Engine(campaign_dir)
        mock_fn = _make_routing_completion(_mock_responses())
        dispatcher = LLMDispatcher(
            work_dir=campaign_dir,
            campaign=SAMPLE_CAMPAIGN,
            completion_fn=mock_fn,
        )
        gate = _make_gate()
        iter_dir = campaign_dir / "runs" / "iter-1"

        # INIT -> FRAMING
        engine.transition("FRAMING")
        dispatcher.dispatch(
            "planner", "frame",
            output_path=iter_dir / "problem.md", iteration=1,
        )
        assert (iter_dir / "problem.md").exists()

        # FRAMING -> DESIGN
        engine.transition("DESIGN")
        dispatcher.dispatch(
            "planner", "design",
            output_path=iter_dir / "bundle.yaml", iteration=1,
        )
        bundle = yaml.safe_load((iter_dir / "bundle.yaml").read_text())
        jsonschema.validate(bundle, load_schema("bundle.schema.yaml"))

        # DESIGN -> DESIGN_REVIEW
        engine.transition("DESIGN_REVIEW")
        for perspective in SAMPLE_CAMPAIGN["review"]["design_perspectives"]:
            dispatcher.dispatch(
                "reviewer", "review-design",
                output_path=iter_dir / "reviews" / f"review-{perspective}.md",
                iteration=1, perspective=perspective,
            )

        # DESIGN_REVIEW -> HUMAN_DESIGN_GATE
        engine.transition("HUMAN_DESIGN_GATE")
        assert gate.prompt("Approve design?") == "approve"

        # HUMAN_DESIGN_GATE -> RUNNING
        engine.transition("RUNNING")
        dispatcher.dispatch(
            "executor", "run",
            output_path=iter_dir / "findings.json", iteration=1,
        )
        findings = json.loads((iter_dir / "findings.json").read_text())
        jsonschema.validate(findings, load_schema("findings.schema.json"))

        # Check fast-fail
        ff = check_fast_fail(findings)
        assert ff == FastFailAction.CONTINUE

        # RUNNING -> FINDINGS_REVIEW
        engine.transition("FINDINGS_REVIEW")
        for perspective in SAMPLE_CAMPAIGN["review"]["findings_perspectives"]:
            dispatcher.dispatch(
                "reviewer", "review-findings",
                output_path=iter_dir / "reviews" / f"review-findings-{perspective}.md",
                iteration=1, perspective=perspective,
            )

        # FINDINGS_REVIEW -> HUMAN_FINDINGS_GATE
        engine.transition("HUMAN_FINDINGS_GATE")
        assert gate.prompt("Approve findings?") == "approve"

        # H-main confirmed -> TUNING
        engine.transition("TUNING")

        # TUNING -> EXTRACTION
        engine.transition("EXTRACTION")
        dispatcher.dispatch(
            "extractor", "extract",
            output_path=campaign_dir / "principles.json", iteration=1,
        )
        principles = json.loads((campaign_dir / "principles.json").read_text())
        jsonschema.validate(principles, load_schema("principles.schema.json"))
        assert len(principles["principles"]) >= 1

        # EXTRACTION -> DONE
        engine.transition("DONE")
        assert engine.phase == "DONE"

        # Verify all expected artifacts exist
        assert (iter_dir / "problem.md").exists()
        assert (iter_dir / "bundle.yaml").exists()
        assert (iter_dir / "findings.json").exists()
        assert (iter_dir / "reviews").is_dir()

        # Verify LLM was called the expected number of times:
        # 1 frame + 1 design + 2 design reviewers + 1 executor +
        # 2 findings reviewers + 1 extractor = 8
        assert len(mock_fn.call_log) == 8
