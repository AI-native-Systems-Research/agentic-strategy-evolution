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


# ── "What to do next" when an epoch ends -- found on a real multi-repo run ──

def test_an_out_of_hull_end_names_the_axis_in_real_levels_and_the_command(tmp_path):
    """The epoch_end guidance said 'see recommendation.json's stationary_point',
    which is in CODED units. report.md must say which knob, in its own units,
    which way, and what to run."""
    import dataclasses
    from orchestrator.optimize.synthetic import SURFACES

    res = run_synthetic_campaign(SURFACES["bowl_out_of_hull"](), seed=1,
                                 parent_dir=tmp_path)
    md = render_report_markdown(res.work_dir)
    if not res.report.get("epoch_ended"):
        pytest.skip("this seed did not end on an exception")
    assert "## What to do next" in md and "nous resume" in md
    assert "Extend `" in md or "Do not extend" in md


def _out_of_hull_work_dir(tmp_path, factors, stationary_point):
    import yaml

    (tmp_path / "campaign.yaml").write_text(yaml.safe_dump(
        {"kind": "optimization", "optimization": {"factors": factors}}))
    it = tmp_path / "runs" / "iter-1"
    it.mkdir(parents=True)
    (it / "recommendation.json").write_text(json.dumps(
        {"stationary_point": stationary_point}))
    return tmp_path


_COUNT = {"id": "CONC", "name": "concurrency", "type": "numeric", "levels": [1, 2, 4],
          "grid": 1, "scale": "log", "apply": "--c={level}",
          "manipulation": {"observable": "cfg.x", "op": "==", "value": "{level}"},
          "relations": [{"id": "R1", "kind": "correctness", "statement": "s", "native_test": "t"}]}
_PROCS = {"id": "PROCS", "name": "procs", "type": "numeric", "levels": [1, 2, 8],
          "grid": 1, "scale": "log", "apply": "--p={level}",
          "manipulation": {"observable": "cfg.x", "op": "==", "value": "{level}"},
          "relations": [{"id": "R1", "kind": "correctness", "statement": "s", "native_test": "t"}]}


def test_a_count_already_at_its_floor_is_pinned_not_extended_below_one(tmp_path):
    """Found on a real Go campaign: 'extend concurrency downward to about 0.5'."""
    from orchestrator.optimize.report_md import _out_of_hull_axes

    [line] = _out_of_hull_axes(_out_of_hull_work_dir(tmp_path, [_COUNT], {"CONC": -2.5}))
    assert "Pin `CONC=1`" in line and "Extend" not in line


@pytest.mark.parametrize("coded", [1.2, 2.0, 3.0, 6.0])
def test_every_extension_suggestion_is_a_runnable_level_past_the_edge(tmp_path, coded):
    """'GOMAXPROCS to about 22.6' is not a level the target can run: the
    suggestion must sit on the grid and strictly beyond the edge it extends."""
    import re

    from orchestrator.optimize.report_md import _out_of_hull_axes

    [line] = _out_of_hull_axes(_out_of_hull_work_dir(tmp_path, [_PROCS], {"PROCS": coded}))
    suggested = re.search(r"e\.g\. to ([0-9.e+]+)", line).group(1)
    assert float(suggested).is_integer() and "." not in suggested
    assert float(suggested) > 8
    assert "hard limit" in line and "pin `PROCS=8`" in line


@pytest.mark.parametrize("coded", [-1.5, -3.0])
def test_a_downward_suggestion_never_leaves_the_log_domain(tmp_path, coded):
    import re

    from orchestrator.optimize.report_md import _out_of_hull_axes

    batch = {"id": "BATCH", "name": "batch", "type": "numeric", "levels": [4, 16, 64],
             "grid": 1, "scale": "log", "apply": "--b={level}",
             "manipulation": {"observable": "cfg.x", "op": "==", "value": "{level}"},
          "relations": [{"id": "R1", "kind": "correctness", "statement": "s", "native_test": "t"}]}
    [line] = _out_of_hull_axes(_out_of_hull_work_dir(tmp_path, [batch], {"BATCH": coded}))
    suggested = float(re.search(r"e\.g\. to ([0-9.e+]+)", line).group(1))
    assert 1 <= suggested < 4
