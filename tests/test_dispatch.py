"""Tests for the agent dispatch module."""
import json
import os
import warnings

import jsonschema
import pytest
import yaml

from orchestrator.dispatch import StubDispatcher
from orchestrator.gates import HumanGate
from orchestrator.protocols import Dispatcher, Gate


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

    def test_dispatch_planner_produces_valid_design_output(self, work_dir):
        dispatcher = _make_dispatcher(work_dir)
        output_path = work_dir / "runs" / "iter-1" / "design_raw.md"
        dispatcher.dispatch("planner", "design", output_path=output_path, iteration=1)
        assert output_path.exists()
        raw = output_path.read_text()
        # Should contain problem framing markdown and a yaml code fence
        assert "## Research Question" in raw
        assert "```yaml" in raw
        # Extract and validate the bundle from the yaml fence
        import re
        match = re.search(r"```yaml\s*\n(.*?)```", raw, re.DOTALL)
        assert match is not None
        bundle = yaml.safe_load(match.group(1))
        jsonschema.validate(bundle, _load_schema("bundle.schema.yaml"))

    def test_dispatch_executor_execute_analyze_produces_valid_output(self, work_dir):
        dispatcher = _make_dispatcher(work_dir)
        output_path = work_dir / "runs" / "iter-1" / "execute_analyze_output.json"
        dispatcher.dispatch("executor", "execute-analyze", output_path=output_path, iteration=1)
        assert output_path.exists()
        combined = json.loads(output_path.read_text())
        assert "plan" in combined
        assert "findings" in combined
        assert "principle_updates" in combined
        # Validate findings sub-schema
        jsonschema.validate(combined["findings"], _load_schema("findings.schema.json"))
        # Validate plan sub-schema
        jsonschema.validate(combined["plan"], _load_schema("experiment_plan.schema.yaml"))
        # Check principle_updates have expected fields
        assert len(combined["principle_updates"]) >= 1
        assert combined["principle_updates"][0]["category"] == "domain"

    def test_dispatch_executor_refuted(self, work_dir):
        dispatcher = _make_dispatcher(work_dir)
        output_path = work_dir / "runs" / "iter-1" / "execute_analyze_output.json"
        dispatcher.dispatch(
            "executor", "execute-analyze",
            output_path=output_path, iteration=1, h_main_result="REFUTED",
        )
        combined = json.loads(output_path.read_text())
        assert combined["findings"]["arms"][0]["status"] == "REFUTED"
        jsonschema.validate(combined["findings"], _load_schema("findings.schema.json"))

    def test_dispatch_unknown_role_rejected(self, work_dir):
        dispatcher = _make_dispatcher(work_dir)
        with pytest.raises(ValueError, match="Unknown role"):
            dispatcher.dispatch(
                "unknown", "phase", output_path=work_dir / "out.txt", iteration=1,
            )


    def test_dispatch_extractor_summarize(self, work_dir):
        dispatcher = _make_dispatcher(work_dir)
        output_path = work_dir / "runs" / "iter-1" / "investigation_summary.json"
        dispatcher.dispatch(
            "extractor", "summarize", output_path=output_path, iteration=1,
        )
        assert output_path.exists()
        summary = json.loads(output_path.read_text())
        jsonschema.validate(summary, _load_schema("investigation_summary.schema.json"))
        assert summary["iteration"] == 1

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




class TestProtocolConformance:
    def test_stub_dispatcher_satisfies_dispatcher_protocol(self, tmp_path):
        dispatcher = _make_dispatcher(tmp_path)
        assert isinstance(dispatcher, Dispatcher)

    def test_human_gate_satisfies_gate_protocol(self, monkeypatch):
        monkeypatch.setenv("NOUS_ALLOW_AUTO_APPROVE", "1")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            gate = HumanGate(auto_approve=True)
        assert isinstance(gate, Gate)

    def test_human_gate_auto_response_satisfies_gate_protocol(self):
        gate = HumanGate(auto_response="approve")
        assert isinstance(gate, Gate)
