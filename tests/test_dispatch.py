"""Tests for the agent dispatch module."""
import json

import jsonschema
import pytest
import yaml

from orchestrator.dispatch import StubDispatcher


SCHEMAS_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent / "schemas"


def _load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text())
    return json.loads(path.read_text())


class TestStubDispatcher:
    @pytest.fixture
    def work_dir(self, tmp_path):
        (tmp_path / "runs" / "iter-1" / "reviews").mkdir(parents=True)
        return tmp_path

    def test_dispatch_planner_produces_valid_bundle(self, work_dir):
        dispatcher = StubDispatcher(work_dir)
        output_path = work_dir / "runs" / "iter-1" / "bundle.yaml"
        dispatcher.dispatch("planner", "design", output_path=output_path, iteration=1)
        assert output_path.exists()
        bundle = yaml.safe_load(output_path.read_text())
        jsonschema.validate(bundle, _load_schema("bundle.schema.yaml"))

    def test_dispatch_executor_produces_valid_findings(self, work_dir):
        dispatcher = StubDispatcher(work_dir)
        output_path = work_dir / "runs" / "iter-1" / "findings.json"
        dispatcher.dispatch("executor", "run", output_path=output_path, iteration=1)
        assert output_path.exists()
        findings = json.loads(output_path.read_text())
        jsonschema.validate(findings, _load_schema("findings.schema.json"))

    def test_dispatch_executor_refuted(self, work_dir):
        dispatcher = StubDispatcher(work_dir)
        output_path = work_dir / "runs" / "iter-1" / "findings.json"
        dispatcher.dispatch(
            "executor", "run",
            output_path=output_path, iteration=1, h_main_result="REFUTED",
        )
        findings = json.loads(output_path.read_text())
        assert findings["arms"][0]["status"] == "REFUTED"
        jsonschema.validate(findings, _load_schema("findings.schema.json"))

    def test_dispatch_reviewer_produces_review(self, work_dir):
        dispatcher = StubDispatcher(work_dir)
        output_path = work_dir / "runs" / "iter-1" / "reviews" / "review-stats.md"
        dispatcher.dispatch(
            "reviewer", "review-design",
            output_path=output_path, perspective="statistical-rigor",
        )
        assert output_path.exists()
        content = output_path.read_text()
        assert "statistical-rigor" in content
        assert "No CRITICAL" in content

    def test_dispatch_extractor_appends_principle(self, work_dir):
        (work_dir / "principles.json").write_text('{"principles": []}')
        dispatcher = StubDispatcher(work_dir)
        dispatcher.dispatch(
            "extractor", "extract",
            output_path=work_dir / "principles.json", iteration=1,
        )
        result = json.loads((work_dir / "principles.json").read_text())
        assert len(result["principles"]) == 1
        jsonschema.validate(result, _load_schema("principles.schema.json"))

    def test_dispatch_extractor_creates_new_file(self, work_dir):
        dispatcher = StubDispatcher(work_dir)
        output_path = work_dir / "new_principles.json"
        # Do NOT pre-create the file
        dispatcher.dispatch(
            "extractor", "extract", output_path=output_path, iteration=1,
        )
        result = json.loads(output_path.read_text())
        assert len(result["principles"]) == 1

    def test_dispatch_extractor_accumulates(self, work_dir):
        (work_dir / "principles.json").write_text('{"principles": []}')
        dispatcher = StubDispatcher(work_dir)
        path = work_dir / "principles.json"
        dispatcher.dispatch("extractor", "extract", output_path=path, iteration=1)
        dispatcher.dispatch("extractor", "extract", output_path=path, iteration=2)
        result = json.loads(path.read_text())
        assert len(result["principles"]) == 2
        assert result["principles"][0]["id"] != result["principles"][1]["id"]

    def test_dispatch_unknown_role_rejected(self, work_dir):
        dispatcher = StubDispatcher(work_dir)
        with pytest.raises(ValueError, match="Unknown role"):
            dispatcher.dispatch(
                "unknown", "phase", output_path=work_dir / "out.txt",
            )
