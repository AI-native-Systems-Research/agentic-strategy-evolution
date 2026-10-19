"""meta_findings.json for kind: optimization agrees with report.json.

Found by the first end-to-end campaign: an UNCERTIFIED report (basis
terminal_best) was summarised in meta_findings.json as `verdict: deploy` for a
reflective-shaped candidate `iter-2/h-main/0`, and the target asks told the
author a "planner had to infer from code in iter-1 design phase" -- a phase this
kind does not have. Two artifacts of one campaign must not disagree about
whether to ship.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.meta_findings import emit_meta_findings, validate_caveat
from orchestrator.optimize.harness import run_synthetic_campaign, synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES

#: Recommendation basis -> the only deployment verdict consistent with it.
EXPECTED = {
    "certified": "deploy",
    "terminal_best": "deploy_with_caveats",
    "model": "deploy_with_caveats",
    "measured": "deploy_with_caveats",
    "baseline": "fall_back_to_baseline",
    "none": "fall_back_to_baseline",
}


@pytest.mark.parametrize("surface,seed", [
    ("bowl", 3), ("sla", 5), ("fails_at_one_level", 11), ("nan_at_corner", 7),
    ("additive", 1), ("saddle", 2),
])
def test_deployment_verdict_follows_the_report_ladder(surface, seed, tmp_path):
    res = run_synthetic_campaign(SURFACES[surface](), seed=seed, parent_dir=tmp_path)
    campaign = synthetic_campaign(SURFACES[surface]())
    payload = emit_meta_findings(Path(res.work_dir), campaign)
    rec = payload["deployment_recommendation"]
    basis = res.report["recommendation"]["basis"]
    assert rec["verdict"] == EXPECTED[basis], (basis, rec)
    for c in rec["caveats"]:
        assert validate_caveat(c) is None, c
    if rec["verdict"] == "deploy_with_caveats":
        assert any(basis in c for c in rec["caveats"])
    # No reflective-only vocabulary leaks into an optimization campaign's asks.
    for ask in payload["target_system_asks"]:
        assert "design phase" not in ask["evidence"], ask


def test_a_campaign_with_no_report_falls_back_and_says_why(tmp_path):
    campaign = synthetic_campaign(SURFACES["bowl"]())
    rec = emit_meta_findings(tmp_path, campaign)["deployment_recommendation"]
    assert rec["verdict"] == "fall_back_to_baseline"
    assert any("report.json" in c for c in rec["caveats"])
