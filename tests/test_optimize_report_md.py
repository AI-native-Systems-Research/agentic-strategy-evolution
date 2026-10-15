"""report.md and continue-gate summaries for kind: optimization are rendered, not generated.

The reflective kind writes both with an LLMDispatcher call. For the optimization
kind that call is unbudgeted spend and routes through OPENAI_* (#304), so these
surfaces are rendered from report.json and the progress snapshot instead. The
tests assert the artifacts on disk and that no model call was logged.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator.campaign import _generate_report
from orchestrator.optimize.harness import run_synthetic_campaign, synthetic_campaign
from orchestrator.optimize.report_md import (
    BASIS_MEANING,
    render_report_markdown,
    write_gate_summary,
)
from orchestrator.optimize.synthetic import SURFACES

SCHEMAS = Path(__file__).resolve().parents[1] / "orchestrator" / "schemas"


@pytest.fixture(scope="module")
def finished(tmp_path_factory):
    return run_synthetic_campaign(
        SURFACES["bowl"](), seed=3, parent_dir=tmp_path_factory.mktemp("rmd"),
    )


def _metric_phases(work_dir: Path) -> list[str]:
    path = work_dir / "llm_metrics.jsonl"
    if not path.exists():
        return []
    return [json.loads(l).get("phase") for l in path.read_text().splitlines() if l.strip()]


def test_report_md_restates_the_recommendation_in_report_json(finished):
    md = render_report_markdown(finished.work_dir)
    rec = finished.report["recommendation"]
    assert f"`{rec['basis']}`" in md
    assert BASIS_MEANING[rec["basis"]] in md
    for k, v in rec["levels"].items():
        assert f"`{k}={v}`" in md
    assert finished.report["policy_hash"] in md


def test_generate_report_renders_report_md_without_a_model_call(finished):
    campaign = synthetic_campaign(SURFACES["bowl"]())
    before = _metric_phases(finished.work_dir)
    _generate_report(campaign, finished.work_dir, None)
    md = (finished.work_dir / "report.md").read_text()
    assert md == render_report_markdown(finished.work_dir)
    # Nothing was dispatched: no new llm_metrics row, in particular no `report`.
    assert _metric_phases(finished.work_dir) == before


def test_report_md_says_plainly_when_no_report_json_exists(tmp_path):
    md = render_report_markdown(tmp_path)
    assert "No `report.json` was written" in md
    assert "Recommendation" not in md


def test_gate_summary_validates_against_the_gate_summary_schema(finished):
    path = write_gate_summary(finished.work_dir, 2)
    assert path == finished.work_dir / "runs" / "iter-2" / "gate_summary_continue.json"
    doc = json.loads(path.read_text())
    jsonschema.validate(doc, json.loads((SCHEMAS / "gate_summary.schema.json").read_text()))
    assert doc["gate_type"] == "continue"
