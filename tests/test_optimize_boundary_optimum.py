"""A boundary optimum is an answer, not an exception (policy `out_of_hull`).

Found on a real multi-repo Go campaign: concurrency, GOGC and GOMAXPROCS all
had their fitted optimum past a declared edge, two of them past HARD limits
(concurrency >= 1, GOMAXPROCS <= cores). Ending the epoch there handed back one
unreplicated row. The default now confirms the best configuration inside the
declared ranges and scopes the certificate to them; `end_epoch` is opt-in.

Oracle: ``bowl_out_of_hull`` peaks at A=30 against declared A in [2, 16], so the
best configuration INSIDE the ranges has A at its upper edge.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.report_md import render_report_markdown
from orchestrator.optimize.synthetic import SURFACES

SCHEMAS = Path(__file__).resolve().parents[1] / "orchestrator" / "schemas"


def _hit_boundary(res) -> bool:
    return "boundary_optimum" in res.report


@pytest.mark.parametrize("seed", [6, 31, 7, 11])
def test_a_boundary_optimum_is_confirmed_at_the_edge_not_ended(tmp_path, seed):
    res = run_synthetic_campaign(SURFACES["bowl_out_of_hull"](), seed=seed,
                                 parent_dir=tmp_path)
    assert res.path[-1] == "report" and "exception" not in res.path, res.path
    assert "epoch_ended" not in res.report
    if not _hit_boundary(res):
        pytest.skip("this seed's refine fit kept the optimum in the hull")
    assert "confirm" in res.path
    rec = res.report["recommendation"]
    assert rec["basis"] in ("certified", "terminal_best"), rec
    assert float(rec["levels"]["A"]) == 16.0, rec["levels"]
    assert "A" in res.report["boundary_optimum"]["axes"]
    assert res.report["boundary_optimum"]["certificate_scope"] == "declared_ranges"
    jsonschema.validate(res.report,
                        json.loads((SCHEMAS / "report.schema.json").read_text()))


def test_the_report_scopes_the_answer_and_names_the_axis_to_widen(tmp_path):
    res = run_synthetic_campaign(SURFACES["bowl_out_of_hull"](), seed=6,
                                 parent_dir=tmp_path)
    if not _hit_boundary(res):
        pytest.skip("this seed's refine fit kept the optimum in the hull")
    md = render_report_markdown(res.work_dir)
    assert "Boundary optimum" in md and "INSIDE the declared ranges" in md
    assert "**A**" in md and "upward" in md


def test_end_epoch_keeps_the_strict_exception(tmp_path):
    res = run_synthetic_campaign(SURFACES["bowl_out_of_hull"](), seed=6,
                                 parent_dir=tmp_path,
                                 campaign_overrides={"policy": {"out_of_hull": "end_epoch"}})
    assert res.path[-1] == "exception" and res.report["epoch_ended"]
    assert "boundary_optimum" not in res.report


def test_an_in_hull_optimum_carries_no_boundary_block(tmp_path):
    res = run_synthetic_campaign(SURFACES["bowl"](), seed=3, parent_dir=tmp_path)
    assert "boundary_optimum" not in res.report
    assert "Boundary optimum" not in render_report_markdown(res.work_dir)


def test_the_validator_rejects_an_unknown_out_of_hull_mode():
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.validate import validate_optimization_campaign

    camp = synthetic_campaign(SURFACES["bowl"](), policy={"out_of_hull": "widen"})
    errors = validate_optimization_campaign(camp)
    assert any("out_of_hull" in e for e in errors), errors
