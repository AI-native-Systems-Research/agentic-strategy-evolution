"""#324: a multi-objective (Pareto) campaign seats its known_valid_baseline in
every confirm round and reports each front point against it.

Before: the baseline was never seated with `response.objectives`, so the field
team measured the deployed configuration outside Nous, with its own seeds and
outside the error budget, to answer "how does the front compare with what is
deployed today?". Behavioral, zero LLM: real campaigns through the harness.
"""
from __future__ import annotations

import json

import jsonschema
import pytest

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import PARETO_SURFACES

REPORT_SCHEMA = json.loads(open("orchestrator/schemas/report.schema.json").read())


def _confirmations(wd):
    return [json.loads(p.read_text()) for p in sorted(
        wd.glob("runs/iter-*/confirmation.json"),
        key=lambda p: int(p.parent.name.split("-")[1]))]


def _baseline(surface):
    """The worst corner of the declared space: every factor at its first level."""
    return {f["id"]: f["levels"][0] for f in surface.factors}


@pytest.mark.parametrize("name", ["pareto_convex", "pareto_convex_min"])
def test_the_baseline_is_seated_every_round_and_the_front_is_compared(tmp_path, name):
    s = PARETO_SURFACES[name]()
    base = _baseline(s)
    r = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path / name,
                               campaign_overrides={"known_valid_baseline": base})
    confs = _confirmations(r.work_dir)
    assert confs, r.path
    for c in confs:
        seated = [f for f in c["finalists"] if f["levels"] == base]
        assert seated, "the baseline was not seated in a confirm round"
        assert "known_valid_baseline" in (seated[0].get("why") or "")
    fvb = r.report["front_vs_baseline"]
    jsonschema.validate(r.report, REPORT_SCHEMA)
    assert fvb["baseline"] == base and "separate" in fvb["claim"]
    assert fvb["points"], fvb
    for pt in fvb["points"]:
        assert set(pt["gain"]) == {o["metric"] for o in r.report["pareto"]["objectives"]}
        assert pt["verdict"] in {"dominates_baseline", "dominated_by_baseline",
                                 "trade_off", "undecided", "not_computable"}


def test_a_front_far_better_than_the_worst_corner_dominates_it(tmp_path):
    """The baseline is the worst corner on every objective, so at least one
    front point must be shown to dominate it, and none dominated by it."""
    s = PARETO_SURFACES["pareto_convex"]()
    r = run_synthetic_campaign(s, seed=2, parent_dir=tmp_path,
                               campaign_overrides={"known_valid_baseline": _baseline(s)})
    verdicts = [p["verdict"] for p in r.report["front_vs_baseline"]["points"]]
    assert "dominates_baseline" in verdicts
    assert "dominated_by_baseline" not in verdicts


def test_the_report_md_prints_the_comparison(tmp_path):
    from orchestrator.optimize.report_md import render_report_markdown

    s = PARETO_SURFACES["pareto_convex"]()
    r = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path,
                               campaign_overrides={"known_valid_baseline": _baseline(s)})
    md = render_report_markdown(r.work_dir)
    assert "Front vs the baseline" in md and "positive = better" in md


def test_the_preview_counts_the_seat_in_a_multi_objective_campaign():
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.preview import build_preview

    s = PARETO_SURFACES["pareto_convex"]()
    with_b = synthetic_campaign(s, known_valid_baseline=_baseline(s))
    without = synthetic_campaign(s)
    pv_b = build_preview(with_b, noise_sd=None, mean=None, run_secs=None)
    pv = build_preview(without, noise_sd=None, mean=None, run_secs=None)
    cb = next(x for x in pv_b.stages if x.stage == "confirm")
    c = next(x for x in pv.stages if x.stage == "confirm")
    reps = with_b["optimization"]["design"]["confirm"].get("replicates") or 3
    assert cb.runs - c.runs == reps


def test_without_a_baseline_nothing_changes(tmp_path):
    s = PARETO_SURFACES["pareto_convex"]()
    r = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path)
    assert "front_vs_baseline" not in r.report
