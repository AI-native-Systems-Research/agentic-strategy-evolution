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

    def test_dispatch_planner_produces_valid_bundle(self, work_dir):
        dispatcher = _make_dispatcher(work_dir)
        output_path = work_dir / "runs" / "iter-1" / "bundle.yaml"
        dispatcher.dispatch("planner", "design", output_path=output_path, iteration=1)
        assert output_path.exists()
        bundle = yaml.safe_load(output_path.read_text())
        jsonschema.validate(bundle, _load_schema("bundle.schema.yaml"))

    def test_dispatch_executor_produces_valid_findings(self, work_dir):
        dispatcher = _make_dispatcher(work_dir)
        output_path = work_dir / "runs" / "iter-1" / "findings.json"
        dispatcher.dispatch("executor", "run", output_path=output_path, iteration=1)
        assert output_path.exists()
        findings = json.loads(output_path.read_text())
        jsonschema.validate(findings, _load_schema("findings.schema.json"))

    def test_dispatch_executor_refuted(self, work_dir):
        dispatcher = _make_dispatcher(work_dir)
        output_path = work_dir / "runs" / "iter-1" / "findings.json"
        dispatcher.dispatch(
            "executor", "run",
            output_path=output_path, iteration=1, h_main_result="REFUTED",
        )
        findings = json.loads(output_path.read_text())
        assert findings["arms"][0]["status"] == "REFUTED"
        jsonschema.validate(findings, _load_schema("findings.schema.json"))

    def test_dispatch_reviewer_produces_review(self, work_dir):
        dispatcher = _make_dispatcher(work_dir)
        output_path = work_dir / "runs" / "iter-1" / "reviews" / "review-stats.md"
        dispatcher.dispatch(
            "reviewer", "review-design",
            output_path=output_path, iteration=1, perspective="statistical-rigor",
        )
        assert output_path.exists()
        content = output_path.read_text()
        assert "statistical-rigor" in content
        assert "No CRITICAL" in content

    def test_dispatch_extractor_appends_principle(self, work_dir):
        (work_dir / "principles.json").write_text('{"principles": []}')
        dispatcher = _make_dispatcher(work_dir)
        dispatcher.dispatch(
            "extractor", "extract",
            output_path=work_dir / "principles.json", iteration=1,
        )
        result = json.loads((work_dir / "principles.json").read_text())
        assert len(result["principles"]) == 1
        jsonschema.validate(result, _load_schema("principles.schema.json"))

    def test_dispatch_extractor_creates_new_file(self, work_dir):
        dispatcher = _make_dispatcher(work_dir)
        output_path = work_dir / "new_principles.json"
        # Do NOT pre-create the file
        dispatcher.dispatch(
            "extractor", "extract", output_path=output_path, iteration=1,
        )
        result = json.loads(output_path.read_text())
        assert len(result["principles"]) == 1

    def test_dispatch_extractor_accumulates(self, work_dir):
        (work_dir / "principles.json").write_text('{"principles": []}')
        dispatcher = _make_dispatcher(work_dir)
        path = work_dir / "principles.json"
        dispatcher.dispatch("extractor", "extract", output_path=path, iteration=1)
        dispatcher.dispatch("extractor", "extract", output_path=path, iteration=2)
        result = json.loads(path.read_text())
        assert len(result["principles"]) == 2
        assert result["principles"][0]["id"] != result["principles"][1]["id"]

    def test_dispatch_unknown_role_rejected(self, work_dir):
        dispatcher = _make_dispatcher(work_dir)
        with pytest.raises(ValueError, match="Unknown role"):
            dispatcher.dispatch(
                "unknown", "phase", output_path=work_dir / "out.txt", iteration=1,
            )


class TestDispatchErrorHandling:
    def test_corrupt_principles_file_raises(self, tmp_path):
        (tmp_path / "principles.json").write_text("{bad json")
        dispatcher = _make_dispatcher(tmp_path)
        with pytest.raises(RuntimeError, match="Cannot read existing principles"):
            dispatcher.dispatch(
                "extractor", "extract",
                output_path=tmp_path / "principles.json", iteration=1,
            )

    def test_principles_missing_key_raises(self, tmp_path):
        (tmp_path / "principles.json").write_text('{"data": []}')
        dispatcher = _make_dispatcher(tmp_path)
        with pytest.raises(RuntimeError, match="missing 'principles' key"):
            dispatcher.dispatch(
                "extractor", "extract",
                output_path=tmp_path / "principles.json", iteration=1,
            )

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
                "executor", "run",
                output_path=tmp_path / "findings.json",
                iteration=1, h_main_result="INVALID",
            )


class TestWritePrinciplesAtomicity:
    def test_rename_failure_preserves_original(self, tmp_path):
        (tmp_path / "principles.json").write_text('{"principles": []}')
        dispatcher = _make_dispatcher(tmp_path)
        with pytest.raises(OSError, match="cross-device"):
            with __import__("unittest.mock", fromlist=["patch"]).patch(
                "os.replace", side_effect=OSError("cross-device link")
            ):
                dispatcher.dispatch(
                    "extractor", "extract",
                    output_path=tmp_path / "principles.json", iteration=1,
                )
        # Original file unchanged
        result = json.loads((tmp_path / "principles.json").read_text())
        assert result == {"principles": []}
        # No temp files left
        assert list(tmp_path.glob("*.json.tmp")) == []

    def test_write_failure_preserves_original(self, tmp_path):
        (tmp_path / "principles.json").write_text('{"principles": []}')
        dispatcher = _make_dispatcher(tmp_path)
        with pytest.raises(OSError, match="disk full"):
            with __import__("unittest.mock", fromlist=["patch"]).patch(
                "os.write", side_effect=OSError("disk full")
            ):
                dispatcher.dispatch(
                    "extractor", "extract",
                    output_path=tmp_path / "principles.json", iteration=1,
                )
        # Original file unchanged
        result = json.loads((tmp_path / "principles.json").read_text())
        assert result == {"principles": []}
        # No temp files left
        assert list(tmp_path.glob("*.json.tmp")) == []


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
