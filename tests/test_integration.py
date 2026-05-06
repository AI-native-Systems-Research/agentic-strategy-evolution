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
from run_iteration import _split_design_output, _merge_principles


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text())
    return json.loads(path.read_text())


@pytest.fixture(autouse=True)
def _allow_auto_approve(monkeypatch):
    """Set env var so auto_approve=True works in tests."""
    monkeypatch.setenv("NOUS_ALLOW_AUTO_APPROVE", "1")


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

        # INIT -> DESIGN
        engine.transition("DESIGN")
        dispatcher.dispatch(
            "planner", "design", output_path=iter_dir / "design_raw.md", iteration=1
        )
        _split_design_output((iter_dir / "design_raw.md").read_text(), iter_dir)
        bundle = yaml.safe_load((iter_dir / "bundle.yaml").read_text())
        jsonschema.validate(bundle, load_schema("bundle.schema.yaml"))

        # DESIGN -> HUMAN_DESIGN_GATE
        engine.transition("HUMAN_DESIGN_GATE")
        assert gate.prompt("Approve?") == ("approve", None)

        # HUMAN_DESIGN_GATE -> EXECUTE_ANALYZE
        engine.transition("EXECUTE_ANALYZE")
        dispatcher.dispatch(
            "executor", "execute-analyze",
            output_path=iter_dir / "execute_analyze_output.json", iteration=1,
        )
        # Split combined output
        combined = json.loads((iter_dir / "execute_analyze_output.json").read_text())
        (iter_dir / "experiment_plan.yaml").write_text(
            yaml.safe_dump(combined["plan"], default_flow_style=False, sort_keys=False)
        )
        (iter_dir / "findings.json").write_text(json.dumps(combined["findings"], indent=2))
        (iter_dir / "principle_updates.json").write_text(
            json.dumps(combined["principle_updates"], indent=2)
        )

        findings = combined["findings"]
        jsonschema.validate(findings, load_schema("findings.schema.json"))

        # Check fast-fail
        ff = check_fast_fail(findings)
        assert ff == FastFailAction.CONTINUE

        # EXECUTE_ANALYZE -> VALIDATE
        engine.transition("VALIDATE")
        dispatcher.write_execution_results(iter_dir / "execution_results.json", iteration=1)

        # VALIDATE -> HUMAN_FINDINGS_GATE
        engine.transition("HUMAN_FINDINGS_GATE")
        assert gate.prompt("Approve?") == ("approve", None)

        # Merge principles (Python, no LLM)
        _merge_principles(campaign_dir, iter_dir)
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

        engine.transition("DESIGN")
        dispatcher.dispatch(
            "planner", "design", output_path=iter_dir / "design_raw.md", iteration=1
        )
        _split_design_output((iter_dir / "design_raw.md").read_text(), iter_dir)

        engine.transition("HUMAN_DESIGN_GATE")

        # EXECUTE_ANALYZE with h-main refuted
        engine.transition("EXECUTE_ANALYZE")
        dispatcher.dispatch(
            "executor", "execute-analyze",
            output_path=iter_dir / "execute_analyze_output.json",
            iteration=1, h_main_result="REFUTED",
        )
        combined = json.loads((iter_dir / "execute_analyze_output.json").read_text())
        (iter_dir / "findings.json").write_text(json.dumps(combined["findings"], indent=2))
        (iter_dir / "principle_updates.json").write_text(
            json.dumps(combined["principle_updates"], indent=2)
        )

        findings = combined["findings"]

        # Fast-fail triggers
        ff = check_fast_fail(findings)
        assert ff == FastFailAction.SKIP_TO_EXTRACTION

        engine.transition("VALIDATE")
        engine.transition("HUMAN_FINDINGS_GATE")
        engine.transition("DONE")
        assert engine.phase == "DONE"

    def test_checkpoint_resume(self, campaign_dir):
        engine = Engine(campaign_dir)
        engine.transition("DESIGN")

        # Simulate crash: create new engine from same dir
        engine2 = Engine(campaign_dir)
        assert engine2.phase == "DESIGN"
        engine2.transition("HUMAN_DESIGN_GATE")
        assert engine2.phase == "HUMAN_DESIGN_GATE"

    def test_multi_iteration_campaign(self, campaign_dir):
        """Two full iterations: first confirmed, second refuted."""
        engine = Engine(campaign_dir)
        dispatcher = _make_dispatcher(campaign_dir)
        gate = _make_gate()

        # Iteration 1: confirmed
        engine.transition("DESIGN")
        iter_dir = campaign_dir / "runs" / "iter-1"
        dispatcher.dispatch(
            "planner", "design", output_path=iter_dir / "design_raw.md", iteration=1
        )
        _split_design_output((iter_dir / "design_raw.md").read_text(), iter_dir)
        engine.transition("HUMAN_DESIGN_GATE")
        engine.transition("EXECUTE_ANALYZE")
        dispatcher.dispatch(
            "executor", "execute-analyze",
            output_path=iter_dir / "execute_analyze_output.json", iteration=1,
        )
        combined = json.loads((iter_dir / "execute_analyze_output.json").read_text())
        (iter_dir / "findings.json").write_text(json.dumps(combined["findings"], indent=2))
        (iter_dir / "principle_updates.json").write_text(
            json.dumps(combined["principle_updates"], indent=2)
        )
        engine.transition("VALIDATE")
        engine.transition("HUMAN_FINDINGS_GATE")
        _merge_principles(campaign_dir, iter_dir)
        engine.transition("DONE")
        assert engine.iteration == 0

        # Loop to next iteration
        engine.transition("DESIGN")
        assert engine.iteration == 1

        # Iteration 2: refuted
        iter_dir2 = campaign_dir / "runs" / "iter-2"
        dispatcher.dispatch(
            "planner", "design", output_path=iter_dir2 / "design_raw.md", iteration=2
        )
        _split_design_output((iter_dir2 / "design_raw.md").read_text(), iter_dir2)
        engine.transition("HUMAN_DESIGN_GATE")
        engine.transition("EXECUTE_ANALYZE")
        dispatcher.dispatch(
            "executor", "execute-analyze",
            output_path=iter_dir2 / "execute_analyze_output.json",
            iteration=2, h_main_result="REFUTED",
        )
        combined2 = json.loads((iter_dir2 / "execute_analyze_output.json").read_text())
        (iter_dir2 / "findings.json").write_text(json.dumps(combined2["findings"], indent=2))
        (iter_dir2 / "principle_updates.json").write_text(
            json.dumps(combined2["principle_updates"], indent=2)
        )
        engine.transition("VALIDATE")
        engine.transition("HUMAN_FINDINGS_GATE")
        _merge_principles(campaign_dir, iter_dir2)
        engine.transition("DONE")
        assert engine.phase == "DONE"
        assert engine.iteration == 1

        # Verify principles accumulated
        principles = json.loads((campaign_dir / "principles.json").read_text())
        assert len(principles["principles"]) == 2


class TestGateSummaries:
    """Integration: gate summaries are generated when a summarizer is available."""

    @pytest.fixture
    def campaign_dir(self, tmp_path):
        shutil.copy(TEMPLATES_DIR / "state.json", tmp_path / "state.json")
        shutil.copy(TEMPLATES_DIR / "ledger.json", tmp_path / "ledger.json")
        shutil.copy(TEMPLATES_DIR / "principles.json", tmp_path / "principles.json")
        state = json.loads((tmp_path / "state.json").read_text())
        state["run_id"] = "test-summary-gate"
        (tmp_path / "state.json").write_text(json.dumps(state, indent=2))
        return tmp_path

    def test_gate_summary_file_created_at_design_gate(self, campaign_dir):
        """StubDispatcher generates a gate summary file during the design gate phase."""
        engine = Engine(campaign_dir)
        dispatcher = _make_dispatcher(campaign_dir)
        iter_dir = campaign_dir / "runs" / "iter-1"

        engine.transition("DESIGN")
        dispatcher.dispatch(
            "planner", "design", output_path=iter_dir / "design_raw.md", iteration=1,
        )
        _split_design_output((iter_dir / "design_raw.md").read_text(), iter_dir)

        # Generate gate summary (what run_iteration.py would do before the gate)
        dispatcher.dispatch(
            "summarizer", "summarize-gate",
            output_path=iter_dir / "gate_summary_design.json",
            iteration=1, perspective="design",
        )

        summary_path = iter_dir / "gate_summary_design.json"
        assert summary_path.exists()
        summary = json.loads(summary_path.read_text())
        assert summary["gate_type"] == "design"
