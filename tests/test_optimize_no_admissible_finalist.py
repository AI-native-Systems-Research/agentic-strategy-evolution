"""Confirm with NO admissible finalist: a stochastic constraint at its bound.

Reproduces, zero-token, a field campaign whose constraint metric's run-to-run
noise straddled its bound exactly where the primary peaked, so every confirm
finalist had at least one infeasible replicate (``SURFACES[
"stochastic_constraint_boundary"]``). That one state produced four misleading
artifacts, each pinned here:

  D1. ``confirmation.json`` epsilon = 0 (a percentage of a best that did not
      exist), which can never certify and is not what the author declared.
  D2. a ``nan_response`` semantic exception blaming the metric's definition,
      although every value was numeric — the finalists were INADMISSIBLE.
  D3. a ``measured`` recommendation of a configuration whose OTHER rows were
      measured infeasible (feasibility judged per row, not per configuration).
  D4. ``certification_withheld`` naming ``bound_not_computable`` rather than
      the real cause, and findings calling the experiment invalid.

Behavioural only: every assertion reads artifacts on disk.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.optimize import invariants as inv
from orchestrator.optimize.certificate import resolve_epsilon
from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES

SURFACE = "stochastic_constraint_boundary"
_CONSTRAINED = {
    "response": {"primary": {"metric": "m", "direction": "maximize"},
                 "constraints": [{"metric": "stall_ms", "op": "<=", "value": 10}]},
    "design": {"screen": {"resolution": 5, "center_points": 4},
               "refine": {"kind": "central_composite", "center_points": 4},
               "confirm": {"replicates": 5}},
}
# Seeds whose campaign reaches confirm with every finalist inadmissible (seeds 7-9
# end at refine on an out-of-hull stationary point, an unrelated branch; on
# seeds 2 and 4 the best measured ADMISSIBLE configuration is seated and wins).
_SEEDS = (1, 5, 6, 11)


def _run(tmp_path: Path, seed: int, *, rounds: int = 1, surface: str = SURFACE,
         overrides: dict | None = None, refill: bool = False):
    """The field state these tests pin is the round cap reached with every
    finalist inadmissible. The registered REFILL branch (policy.REFILL_ACCOUNTING)
    exists to add one round after exactly that state, so it is compiled out here
    unless ``refill`` is asked for; tests/test_optimize_refill.py owns it."""
    import orchestrator.optimize.policy as policy

    ov = dict(overrides if overrides is not None else _CONSTRAINED)
    ov["policy"] = {"confirm_max_rounds": rounds}
    saved = policy._REFILL_VACATED
    policy._REFILL_VACATED = refill
    try:
        return run_synthetic_campaign(
            SURFACES[surface](), seed=seed,
            parent_dir=tmp_path / f"{surface}-{seed}-{rounds}",
            campaign_overrides=ov, max_iterations=12,
        )
    finally:
        policy._REFILL_VACATED = saved


def _rows(work_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for p in sorted(work_dir.glob("runs/iter-*/runs.jsonl"))
        for line in p.read_text().splitlines() if line.strip()
    ]


def _confirmations(work_dir: Path) -> list[dict]:
    return [json.loads(p.read_text())
            for p in sorted(work_dir.glob("runs/iter-*/confirmation.json"))]


def _transitions(work_dir: Path) -> list[dict]:
    p = work_dir / "transitions.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


@pytest.fixture(scope="module", params=_SEEDS)
def campaign(request, tmp_path_factory):
    return _run(tmp_path_factory.mktemp("noadm"), request.param)


def test_the_surface_reproduces_the_field_state(campaign):
    """Precondition: confirm ran and NO finalist was admissible."""
    confs = _confirmations(campaign.work_dir)
    assert confs, campaign.path
    assert all(f["status"] == "infeasible" for f in confs[0]["finalists"])
    assert confs[0]["best"] is None


def test_all_inadmissible_finalists_do_not_raise_the_nan_exception(campaign):
    """D2: nan_response means a COMPLETE row with a non-finite primary, nothing else."""
    wd = campaign.work_dir
    assert not list(wd.glob("epoch_end-*.json")), json.loads(
        next(wd.glob("epoch_end-*.json")).read_text())
    assert "exception" not in campaign.path, campaign.path
    assert campaign.path[-1] == "report", campaign.path
    assert "epoch_ended" not in campaign.report
    for t in _transitions(wd):
        assert t["observations"].get("nan_response") is not True, t
    # And it was genuinely false: every complete row carries a finite primary.
    for row in _rows(wd):
        if row["status"] == "complete":
            v = row["response"]["m"]
            assert isinstance(v, (int, float)) and v == v


def test_epsilon_is_positive_and_resolved_from_the_documented_reference(campaign):
    """D1: no admissible best -> epsilon from the best measured ADMISSIBLE config."""
    conf = _confirmations(campaign.work_dir)[0]
    eps = conf["epsilon"]
    assert eps > 0, conf
    ref = conf["epsilon_reference"]
    assert ref["source"] == "best_observed", ref
    assert eps == pytest.approx(resolve_epsilon({"pct": 2.0}, ref["value"]))
    # The reference is itself an admissible configuration: every row there is complete.
    at_ref = [r for r in _rows(campaign.work_dir) if r.get("levels") == ref["levels"]]
    assert at_ref and all(r["status"] == "complete" for r in at_ref), at_ref
    assert campaign.report["epsilon"] == eps


def test_certification_reasons_name_the_real_cause(campaign):
    """D4: the bound is not 'not computable' for want of data; no finalist was admissible."""
    conf = _confirmations(campaign.work_dir)[0]
    assert "no_admissible_finalist" in conf["certification_withheld"]
    assert "bound_not_computable" not in conf["certification_withheld"]
    assert "no_admissible_finalist" in campaign.report["certification_withheld"]
    findings = json.loads(
        (campaign.work_dir / "runs" / f"iter-{conf['iteration']}" / "findings.json").read_text())
    arm = findings["arms"][0]
    # The measurements were fine; the configurations were inadmissible.
    assert findings["experiment_valid"] is True
    assert "inadmissible" in arm["observed"]
    assert "usable measurement" not in arm["observed"]


def test_report_md_explains_the_inadmissible_shortlist(campaign):
    from orchestrator.optimize.report_md import render_report_markdown

    md = render_report_markdown(campaign.work_dir)
    assert "no_admissible_finalist" in md
    assert "nan_response" not in md
    assert "| epsilon (acceptable regret) | 0 |" not in md


def _assert_recommendation_admissible(res):
    assert inv.check_recommendation_admissible_per_configuration(
        res.report, _rows(res.work_dir)) == []
    rec = res.report["recommendation"]
    if rec["basis"] in ("baseline", "none"):
        return
    at = [r for r in _rows(res.work_dir) if r.get("levels") == rec["levels"]]
    assert at, rec
    bad = [r["status"] for r in at if r["status"] != "complete"]
    assert not bad, (
        f"recommended {rec} although rows at those levels measured {bad}: "
        f"feasibility is per CONFIGURATION, not per row"
    )


def test_the_measured_rung_never_returns_a_configuration_with_an_infeasible_row(campaign):
    """D3, on the reproduction itself."""
    _assert_recommendation_admissible(campaign)


@pytest.mark.parametrize("seed", [0, 5, 7, 9])
@pytest.mark.parametrize("rounds", [1, 2])
def test_property_every_report_recommends_only_fully_complete_configurations(
    tmp_path, seed, rounds,
):
    """D3 as a property over seeds and round caps, including the loop branch."""
    res = _run(tmp_path, seed, rounds=rounds)
    _assert_recommendation_admissible(res)
    assert "exception" not in res.path or json.loads(
        next(res.work_dir.glob("epoch_end-*.json")).read_text()
    )["rule"]["when"] != {"nan_response": True}
    for conf in _confirmations(res.work_dir):
        assert conf["epsilon"] > 0, conf
        assert inv.check_epsilon_has_a_reference(conf) == []


@pytest.mark.parametrize("seed", [3, 5])
def test_property_holds_on_the_deterministic_constraint_surface(tmp_path, seed):
    sla = {"response": {"primary": {"metric": "m", "direction": "maximize"},
                        "constraints": [{"metric": "p99_ms", "op": "<=", "value": 40}]}}
    res = _run(tmp_path, seed, surface="sla", overrides=sla, rounds=2)
    _assert_recommendation_admissible(res)


def test_a_second_round_tops_up_from_the_ranking_instead_of_ending_the_epoch(tmp_path):
    """The registered `confirm -> confirm` branch is what an all-inadmissible
    round routes to when the round cap allows it — not the exception."""
    res = _run(tmp_path, 1, rounds=2)
    froms = [t["from"] for t in _transitions(res.work_dir)]
    assert froms.count("confirm") == 2, res.path
    confs = _confirmations(res.work_dir)
    first = {json.dumps(f["levels"], sort_keys=True) for f in confs[0]["finalists"]}
    second = {json.dumps(f["levels"], sort_keys=True) for f in confs[1]["finalists"]}
    assert not first & second, "round 2 re-seated a configuration round 1 measured inadmissible"
    assert res.path[-1] == "report"
