"""Tests for the agent dispatch module."""
import json
import os
import warnings

import jsonschema
import pytest
import yaml

from orchestrator.dispatch import StubDispatcher
from orchestrator.gates import HumanGate


SCHEMAS_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent / "schemas"


def _load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text())
    return json.loads(path.read_text())


def _make_dispatcher(work_dir):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return StubDispatcher(work_dir)


class TestStubDispatcher:
    @pytest.fixture
    def work_dir(self, tmp_path):
        (tmp_path / "runs" / "iter-1" / "reviews").mkdir(parents=True)
        return tmp_path

    def test_dispatch_planner_writes_individual_files(self, work_dir):
        dispatcher = _make_dispatcher(work_dir)
        iter_dir = work_dir / "runs" / "iter-1"
        output_path = iter_dir / "design_log.md"
        dispatcher.dispatch("planner", "design", output_path=output_path, iteration=1)
        # Stub writes files directly
        assert (iter_dir / "problem.md").exists()
        assert "## Research Question" in (iter_dir / "problem.md").read_text()
        assert (iter_dir / "bundle.yaml").exists()
        bundle = yaml.safe_load((iter_dir / "bundle.yaml").read_text())
        jsonschema.validate(bundle, _load_schema("bundle.schema.yaml"))
        assert (iter_dir / "handoff_snapshot.md").exists()
        # Campaign-level handoff
        assert (work_dir / "handoff.md").exists()

    def test_dispatch_executor_writes_individual_files(self, work_dir):
        dispatcher = _make_dispatcher(work_dir)
        iter_dir = work_dir / "runs" / "iter-1"
        output_path = iter_dir / "executor_log.md"
        dispatcher.dispatch("executor", "execute-analyze", output_path=output_path, iteration=1)
        assert (iter_dir / "experiment_plan.yaml").exists()
        assert (iter_dir / "findings.json").exists()
        assert (iter_dir / "principle_updates.json").exists()
        findings = json.loads((iter_dir / "findings.json").read_text())
        jsonschema.validate(findings, _load_schema("findings.schema.json"))
        plan = yaml.safe_load((iter_dir / "experiment_plan.yaml").read_text())
        jsonschema.validate(plan, _load_schema("experiment_plan.schema.yaml"))
        principles = json.loads((iter_dir / "principle_updates.json").read_text())
        assert len(principles) >= 1
        assert principles[0]["category"] == "domain"

    def test_dispatch_executor_refuted(self, work_dir):
        dispatcher = _make_dispatcher(work_dir)
        iter_dir = work_dir / "runs" / "iter-1"
        output_path = iter_dir / "executor_log.md"
        dispatcher.dispatch(
            "executor", "execute-analyze",
            output_path=output_path, iteration=1, h_main_result="REFUTED",
        )
        findings = json.loads((iter_dir / "findings.json").read_text())
        assert findings["arms"][0]["status"] == "REFUTED"
        jsonschema.validate(findings, _load_schema("findings.schema.json"))

    def test_dispatch_unknown_role_rejected(self, work_dir):
        dispatcher = _make_dispatcher(work_dir)
        with pytest.raises(ValueError, match="Unknown role"):
            dispatcher.dispatch(
                "unknown", "phase", output_path=work_dir / "out.txt", iteration=1,
            )


    def test_dispatch_summarizer_produces_valid_gate_summary(self, work_dir):
        dispatcher = _make_dispatcher(work_dir)
        output_path = work_dir / "runs" / "iter-1" / "gate_summary.json"
        dispatcher.dispatch(
            "summarizer", "summarize-gate",
            output_path=output_path, iteration=1, perspective="design",
        )
        assert output_path.exists()
        summary = json.loads(output_path.read_text())
        assert summary["gate_type"] == "design"
        assert len(summary["key_points"]) >= 1
        jsonschema.validate(summary, _load_schema("gate_summary.schema.json"))


class TestDispatchErrorHandling:
    def test_stub_dispatcher_emits_warning(self, tmp_path):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            StubDispatcher(tmp_path)
            assert len(w) == 1
            assert "StubDispatcher" in str(w[0].message)

    def test_invalid_h_main_result_raises(self, tmp_path):
        dispatcher = _make_dispatcher(tmp_path)
        with pytest.raises(ValueError, match="Invalid h_main_result"):
            dispatcher.dispatch(
                "executor", "execute-analyze",
                output_path=tmp_path / "output.json",
                iteration=1, h_main_result="INVALID",
            )




