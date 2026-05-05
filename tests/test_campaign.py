"""Tests for multi-iteration campaign loop."""
import json
import shutil
import warnings
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest
import yaml

from orchestrator.dispatch import StubDispatcher
from orchestrator.engine import Engine
from run_campaign import run_campaign
from run_iteration import IterationOutcome, _save_human_feedback

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text())
    return json.loads(path.read_text())


SAMPLE_CAMPAIGN = {
    "research_question": "Does batch size affect latency?",
    "target_system": {
        "name": "TestSystem",
        "description": "A test system.",
        "observable_metrics": ["latency_ms"],
        "controllable_knobs": ["batch_size"],
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


def _setup_work_dir(tmp_path):
    """Create an initialized work directory."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    for t in ["state.json", "ledger.json", "principles.json"]:
        shutil.copy(TEMPLATES_DIR / t, work_dir / t)
    state = json.loads((work_dir / "state.json").read_text())
    state["run_id"] = "test-campaign"
    (work_dir / "state.json").write_text(json.dumps(state, indent=2))
    return work_dir


def _patch_for_stub(monkeypatch):
    """Monkeypatch LLMDispatcher and HumanGate for stub-based testing."""
    import run_iteration as ri
    import run_campaign as rc

    def stub_factory(work_dir, campaign, model=None):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return StubDispatcher(work_dir)

    monkeypatch.setattr(ri, "LLMDispatcher", stub_factory)

    # Also patch the LLMDispatcher in run_campaign (used for summarize)
    monkeypatch.setattr(rc, "LLMDispatcher", stub_factory)


def _patch_gates_approve(monkeypatch):
    """All gates auto-approve."""
    import run_iteration as ri
    import run_campaign as rc
    gate = MagicMock(prompt=MagicMock(return_value=("approve", None)))
    monkeypatch.setattr(ri, "HumanGate", lambda: gate)
    monkeypatch.setattr(rc, "HumanGate", lambda: gate)
    return gate


class TestTwoIterationHappyPath:
    def test_two_iterations_complete(self, tmp_path, monkeypatch):
        work_dir = _setup_work_dir(tmp_path)
        _patch_for_stub(monkeypatch)
        _patch_gates_approve(monkeypatch)

        run_campaign(SAMPLE_CAMPAIGN, work_dir, max_iterations=2)

        # Engine should be DONE
        engine = Engine(work_dir)
        assert engine.phase == "DONE"

        # Ledger should have baseline + 2 iteration rows
        ledger = json.loads((work_dir / "ledger.json").read_text())
        iter_rows = [r for r in ledger["iterations"] if r["iteration"] > 0]
        assert len(iter_rows) == 2  # both iter-1 and iter-2 (final) get ledger rows
        jsonschema.validate(ledger, _load_schema("ledger.schema.json"))

        # Investigation summary should exist for iter-1
        summary_path = work_dir / "runs" / "iter-1" / "investigation_summary.json"
        assert summary_path.exists()
        summary = json.loads(summary_path.read_text())
        jsonschema.validate(summary, _load_schema("investigation_summary.schema.json"))

        # Principles should have accumulated across iterations
        principles = json.loads((work_dir / "principles.json").read_text())
        assert len(principles["principles"]) == 2

        # Both iter dirs should exist
        assert (work_dir / "runs" / "iter-1" / "bundle.yaml").exists()
        assert (work_dir / "runs" / "iter-2" / "bundle.yaml").exists()


class TestStopsOnHumanAbort:
    def test_abort_at_continue_gate(self, tmp_path, monkeypatch):
        work_dir = _setup_work_dir(tmp_path)
        _patch_for_stub(monkeypatch)

        import run_iteration as ri
        import run_campaign as rc

        # Iteration gates approve, but continue gate aborts
        iter_gate = MagicMock(prompt=MagicMock(return_value=("approve", None)))
        continue_gate = MagicMock(prompt=MagicMock(return_value=("abort", None)))
        monkeypatch.setattr(ri, "HumanGate", lambda: iter_gate)
        monkeypatch.setattr(rc, "HumanGate", lambda: continue_gate)

        run_campaign(SAMPLE_CAMPAIGN, work_dir, max_iterations=5)

        engine = Engine(work_dir)
        assert engine.phase == "DONE"
        # Only 1 iteration completed
        assert (work_dir / "runs" / "iter-1" / "findings.json").exists()
        assert not (work_dir / "runs" / "iter-2").exists()


class TestStopsAtMaxIterations:
    def test_single_iteration_max(self, tmp_path, monkeypatch):
        work_dir = _setup_work_dir(tmp_path)
        _patch_for_stub(monkeypatch)
        _patch_gates_approve(monkeypatch)

        run_campaign(SAMPLE_CAMPAIGN, work_dir, max_iterations=1)

        engine = Engine(work_dir)
        assert engine.phase == "DONE"
        assert (work_dir / "runs" / "iter-1" / "findings.json").exists()
        # No continue gate should have been invoked (iter 1 is final)
        assert not (work_dir / "runs" / "iter-2").exists()


class TestThreeIterations:
    def test_three_iterations_accumulate_principles(self, tmp_path, monkeypatch):
        work_dir = _setup_work_dir(tmp_path)
        _patch_for_stub(monkeypatch)
        _patch_gates_approve(monkeypatch)

        run_campaign(SAMPLE_CAMPAIGN, work_dir, max_iterations=3)

        engine = Engine(work_dir)
        assert engine.phase == "DONE"

        principles = json.loads((work_dir / "principles.json").read_text())
        assert len(principles["principles"]) == 3

        # Ledger has rows for all 3 iterations (including final)
        ledger = json.loads((work_dir / "ledger.json").read_text())
        iter_rows = [r for r in ledger["iterations"] if r["iteration"] > 0]
        assert len(iter_rows) == 3

        # Summaries for iter 1 and 2 (not iter 3 since it's final)
        assert (work_dir / "runs" / "iter-1" / "investigation_summary.json").exists()
        assert (work_dir / "runs" / "iter-2" / "investigation_summary.json").exists()


class TestAbortDuringIteration:
    def test_abort_during_gate(self, tmp_path, monkeypatch):
        """If the human aborts during a gate, campaign stops
        and engine state is preserved for potential resume."""
        work_dir = _setup_work_dir(tmp_path)
        _patch_for_stub(monkeypatch)

        import run_iteration as ri
        import run_campaign as rc

        # Iteration gate aborts
        gate = MagicMock(prompt=MagicMock(return_value=("abort", None)))
        monkeypatch.setattr(ri, "HumanGate", lambda: gate)
        monkeypatch.setattr(rc, "HumanGate", lambda: gate)

        run_campaign(SAMPLE_CAMPAIGN, work_dir, max_iterations=5)

        engine = Engine(work_dir)
        # Engine is at the first human gate (HUMAN_FRAMING_GATE) — preserved for resume
        assert engine.phase == "HUMAN_FRAMING_GATE"


class TestSaveHumanFeedback:
    """Tests for _save_human_feedback helper."""

    def test_creates_new_file_with_first_entry(self, tmp_path):
        _save_human_feedback(tmp_path, "framing", "Too vague")
        fb = json.loads((tmp_path / "human_feedback.json").read_text())
        assert fb["framing"][0]["reason"] == "Too vague"
        assert fb["framing"][0]["attempt"] == 1
        assert "timestamp" in fb["framing"][0]

    def test_appends_to_existing_entries(self, tmp_path):
        _save_human_feedback(tmp_path, "design", "First rejection")
        _save_human_feedback(tmp_path, "design", "Second rejection")
        fb = json.loads((tmp_path / "human_feedback.json").read_text())
        assert len(fb["design"]) == 2
        assert fb["design"][1]["attempt"] == 2
        assert fb["design"][1]["reason"] == "Second rejection"

    def test_corrupt_json_resets_store(self, tmp_path):
        (tmp_path / "human_feedback.json").write_text("{invalid json!!")
        _save_human_feedback(tmp_path, "findings", "After corruption")
        fb = json.loads((tmp_path / "human_feedback.json").read_text())
        assert fb["findings"][0]["reason"] == "After corruption"
        assert fb["findings"][0]["attempt"] == 1

    def test_multiple_phases_independent(self, tmp_path):
        _save_human_feedback(tmp_path, "framing", "Framing issue")
        _save_human_feedback(tmp_path, "design", "Design issue")
        fb = json.loads((tmp_path / "human_feedback.json").read_text())
        assert len(fb["framing"]) == 1
        assert len(fb["design"]) == 1
