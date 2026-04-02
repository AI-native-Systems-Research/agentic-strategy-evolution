"""End-to-end integration tests — full single-iteration with stub agents."""
import json
import shutil
import warnings
from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.engine import Engine
from orchestrator.dispatch import StubDispatcher
from orchestrator.fastfail import check_fast_fail, FastFailAction
from orchestrator.gates import HumanGate


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text())
    return json.loads(path.read_text())


def _make_gate():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return HumanGate(auto_approve=True)


def _make_dispatcher(work_dir):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return StubDispatcher(work_dir)


class TestSingleIterationHappyPath:
    """Orchestrator completes one full iteration with stub agents."""

    @pytest.fixture
    def campaign_dir(self, tmp_path):
        shutil.copy(TEMPLATES_DIR / "state.json", tmp_path / "state.json")
        shutil.copy(TEMPLATES_DIR / "ledger.json", tmp_path / "ledger.json")
        shutil.copy(TEMPLATES_DIR / "principles.json", tmp_path / "principles.json")
        state = json.loads((tmp_path / "state.json").read_text())
        state["run_id"] = "test-integration-001"
        (tmp_path / "state.json").write_text(json.dumps(state, indent=2))
        return tmp_path

    def test_happy_path_confirmed(self, campaign_dir):
        engine = Engine(campaign_dir)
        dispatcher = _make_dispatcher(campaign_dir)
        gate = _make_gate()
        iter_dir = campaign_dir / "runs" / "iter-1"

        # INIT -> FRAMING
        engine.transition("FRAMING")
        shutil.copy(TEMPLATES_DIR / "problem.md", campaign_dir / "problem.md")

        # FRAMING -> DESIGN
        engine.transition("DESIGN")
        dispatcher.dispatch(
            "planner", "design", output_path=iter_dir / "bundle.yaml", iteration=1
        )
        bundle = yaml.safe_load((iter_dir / "bundle.yaml").read_text())
        jsonschema.validate(bundle, load_schema("bundle.schema.yaml"))

        # DESIGN -> DESIGN_REVIEW
        engine.transition("DESIGN_REVIEW")
        for p in ["stats", "causal", "confound", "generalization", "clarity"]:
            dispatcher.dispatch(
                "reviewer", "review-design",
                output_path=iter_dir / "reviews" / f"review-{p}.md",
                perspective=p,
            )

        # DESIGN_REVIEW -> HUMAN_DESIGN_GATE (no criticals)
        engine.transition("HUMAN_DESIGN_GATE")
        assert gate.prompt("Approve?") == "approve"

        # HUMAN_DESIGN_GATE -> RUNNING
        engine.transition("RUNNING")
        dispatcher.dispatch(
            "executor", "run", output_path=iter_dir / "findings.json", iteration=1
        )
        findings = json.loads((iter_dir / "findings.json").read_text())
        jsonschema.validate(findings, load_schema("findings.schema.json"))

        # Check fast-fail
        ff = check_fast_fail(findings)
        assert ff == FastFailAction.CONTINUE

        # RUNNING -> FINDINGS_REVIEW
        engine.transition("FINDINGS_REVIEW")

        # FINDINGS_REVIEW -> HUMAN_FINDINGS_GATE
        engine.transition("HUMAN_FINDINGS_GATE")
        assert gate.prompt("Approve?") == "approve"

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
        assert len(principles["principles"]) == 1

        # Campaign done
        engine.transition("DONE")
        assert engine.phase == "DONE"

    def test_fast_fail_h_main_refuted(self, campaign_dir):
        engine = Engine(campaign_dir)
        dispatcher = _make_dispatcher(campaign_dir)
        gate = _make_gate()
        iter_dir = campaign_dir / "runs" / "iter-1"

        for s in ["FRAMING", "DESIGN"]:
            engine.transition(s)
        dispatcher.dispatch(
            "planner", "design", output_path=iter_dir / "bundle.yaml", iteration=1
        )

        engine.transition("DESIGN_REVIEW")
        engine.transition("HUMAN_DESIGN_GATE")
        engine.transition("RUNNING")

        # Executor produces refuted findings
        dispatcher.dispatch(
            "executor", "run",
            output_path=iter_dir / "findings.json",
            iteration=1, h_main_result="REFUTED",
        )
        findings = json.loads((iter_dir / "findings.json").read_text())

        # Fast-fail triggers
        ff = check_fast_fail(findings)
        assert ff == FastFailAction.SKIP_TO_EXTRACTION

        engine.transition("FINDINGS_REVIEW")
        engine.transition("HUMAN_FINDINGS_GATE")
        # Skip TUNING -> go to EXTRACTION
        engine.transition("EXTRACTION")
        assert engine.phase == "EXTRACTION"

    def test_checkpoint_resume(self, campaign_dir):
        engine = Engine(campaign_dir)
        engine.transition("FRAMING")
        engine.transition("DESIGN")

        # Simulate crash: create new engine from same dir
        engine2 = Engine(campaign_dir)
        assert engine2.phase == "DESIGN"
        engine2.transition("DESIGN_REVIEW")
        assert engine2.phase == "DESIGN_REVIEW"

    def test_multi_iteration_campaign(self, campaign_dir):
        """Two full iterations: first confirmed, second refuted."""
        engine = Engine(campaign_dir)
        dispatcher = _make_dispatcher(campaign_dir)
        gate = _make_gate()

        # Iteration 1: confirmed
        engine.transition("FRAMING")
        engine.transition("DESIGN")
        iter_dir = campaign_dir / "runs" / "iter-1"
        dispatcher.dispatch(
            "planner", "design", output_path=iter_dir / "bundle.yaml", iteration=1
        )
        engine.transition("DESIGN_REVIEW")
        engine.transition("HUMAN_DESIGN_GATE")
        engine.transition("RUNNING")
        dispatcher.dispatch(
            "executor", "run", output_path=iter_dir / "findings.json", iteration=1
        )
        engine.transition("FINDINGS_REVIEW")
        engine.transition("HUMAN_FINDINGS_GATE")
        engine.transition("TUNING")
        engine.transition("EXTRACTION")
        dispatcher.dispatch(
            "extractor", "extract",
            output_path=campaign_dir / "principles.json", iteration=1,
        )
        assert engine.iteration == 0

        # Loop to next iteration
        engine.transition("DESIGN")
        assert engine.iteration == 1

        # Iteration 2: refuted
        iter_dir2 = campaign_dir / "runs" / "iter-2"
        dispatcher.dispatch(
            "planner", "design", output_path=iter_dir2 / "bundle.yaml", iteration=2
        )
        engine.transition("DESIGN_REVIEW")
        engine.transition("HUMAN_DESIGN_GATE")
        engine.transition("RUNNING")
        dispatcher.dispatch(
            "executor", "run",
            output_path=iter_dir2 / "findings.json",
            iteration=2, h_main_result="REFUTED",
        )
        engine.transition("FINDINGS_REVIEW")
        engine.transition("HUMAN_FINDINGS_GATE")
        engine.transition("EXTRACTION")  # Skip TUNING
        dispatcher.dispatch(
            "extractor", "extract",
            output_path=campaign_dir / "principles.json", iteration=2,
        )

        engine.transition("DONE")
        assert engine.phase == "DONE"
        assert engine.iteration == 1

        # Verify principles accumulated
        principles = json.loads((campaign_dir / "principles.json").read_text())
        assert len(principles["principles"]) == 2
