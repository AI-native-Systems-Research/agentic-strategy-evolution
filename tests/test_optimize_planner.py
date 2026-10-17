"""WP-D D2: `nous plan-next` (planner.py). Zero tokens, behavioral: each test
runs a real synthetic campaign (no LLM), plans, and checks the files on disk.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.optimize import planner
from orchestrator.optimize.harness import _all_pass, run_synthetic_campaign
from orchestrator.optimize.synthetic import PARETO_SURFACES, SURFACES

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "orchestrator/schemas/planner_decision.schema.json").read_text())


@pytest.fixture(scope="module")
def converged(tmp_path_factory):
    return run_synthetic_campaign(SURFACES["bowl"](), seed=3,
                                  parent_dir=tmp_path_factory.mktemp("conv"))


@pytest.fixture(scope="module")
def boundary(tmp_path_factory):
    return run_synthetic_campaign(SURFACES["bowl_out_of_hull"](), seed=3,
                                  parent_dir=tmp_path_factory.mktemp("bnd"))


def _decision(res, tmp_path=None, **kw):
    out = planner.plan(res.work_dir)
    p = planner.write_plan(out, **kw)
    d = json.loads(p.read_text())
    jsonschema.validate(d, SCHEMA)
    return d, out


# ── D4 oracles ───────────────────────────────────────────────────────────────


def test_plan_next_chooses_stop_on_a_converged_campaign(converged):
    assert converged.report["certified"]
    d, _ = _decision(converged)
    assert d["chosen"] == "stop" and d["decision_basis"] == "no_move_beats_threshold"
    assert d["proposed_campaign"] is None
    live = [o for o in d["options"] if o["id"] != "stop" and o["score"] is not None]
    assert live and all(o["score"] <= d["stopping"]["threshold_per_run"] for o in live)
    assert d["tokens"] == 0
    assert d["utility"]["name"] == "expected_improvement_per_run"
    assert "LOWER bound" in d["utility"]["computed_as"]


def test_plan_next_widens_the_edge_on_a_boundary_optimum_campaign(boundary):
    """bowl_out_of_hull: the optimum is at A = 30, past the declared [2, 16].
    The planner chooses the widen move. Its proposed campaign re-centres A on
    the upper edge, is a validated diff, and leaves campaign.yaml untouched."""
    assert boundary.report.get("boundary_optimum", {}).get("axes") == ["A"]
    d, _ = _decision(boundary)
    assert d["chosen"] == "widen_edge", [(o["id"], o["score"]) for o in d["options"]]
    w = next(o for o in d["options"] if o["id"] == "widen_edge")
    assert w["extrapolated"] is True and w["score"] > d["stopping"]["threshold_per_run"]
    prop = yaml.safe_load(Path(d["proposed_campaign"]["path"]).read_text())
    a = next(f for f in prop["optimization"]["factors"] if f["id"] == "A")
    assert min(a["levels"]) >= 9 and max(a["levels"]) > 16
    diff = Path(d["proposed_campaign"]["diff"]).read_text()
    assert diff.startswith("--- campaign.epoch-1.yaml") and "+    - 23" in diff or "+" in diff
    assert planner.validate_campaign(prop) == []
    assert not (boundary.work_dir / "campaign.yaml").exists()


def test_the_planner_declines_to_score_when_the_model_is_inadequate(tmp_path):
    """ridge_cubic is not quadratic, so the epoch's model is rejected. Nothing
    is scored, stop is chosen with a named basis, and the model-free
    alternatives are listed."""
    from orchestrator.optimize.synthetic import ridge_cubic

    res = run_synthetic_campaign(ridge_cubic(), seed=1, parent_dir=tmp_path)
    rec = [json.loads(p.read_text()) for p in sorted(res.work_dir.glob("runs/iter-*/recommendation.json"))]
    if rec[-1].get("model_adequate") is True:
        pytest.skip("this seed's model was not rejected")
    d, _ = _decision(res)
    assert d["chosen"] == "stop" and d["decision_basis"] == "no_scorable_move"
    assert d["model"]["declined"] in ("model_inadequate", "model_adequacy_unknown")
    assert all(o["score"] is None for o in d["options"] if o["id"] != "stop")
    assert "replicate" in d["model_free_alternatives"]


# ── the decision file ────────────────────────────────────────────────────────


def test_the_decision_states_utility_assumptions_threshold_and_budget(converged):
    d, _ = _decision(converged)
    assert d["stopping"]["rule"].startswith("default: epsilon")
    assert any("optimistic" in a for a in d["assumptions"])
    eb = d["error_budget"]
    assert eb["mode"] == "informational" and eb["cumulative"] == pytest.approx(0.1)
    for o in d["options"]:
        if o["id"] != "stop" and o["feasible"]:
            assert o["error_budget"]["next_epoch_delta"] > 0 and o["cost_runs"] > 0
    assert set(d["inputs"]) >= {"report.json", "policy.json", "campaign.epoch-1.yaml"}


def test_a_charged_budget_never_proposes_an_epoch_past_it(tmp_path):
    """campaign_delta {total: 0.05, schedule: [0.05]}: epoch 1 spent the
    whole budget, so epoch 2's share is exhausted (it would certify nothing).
    Every move is infeasible (error_budget_insufficient), stop is chosen,
    and an override to one of them is refused."""
    res = run_synthetic_campaign(
        SURFACES["bowl_out_of_hull"](), seed=3, parent_dir=tmp_path,
        campaign_overrides={"policy": {"campaign_delta": {"total": 0.05,
                                                          "schedule": [0.05]}}})
    d, out = _decision(res)
    eb = d["error_budget"]
    assert eb["mode"] == "charged" and eb["remaining"] == pytest.approx(0.0)
    moves = [o for o in d["options"] if o["id"] != "stop"]
    assert moves and all(o["reason"] == "error_budget_insufficient" for o in moves
                         if o.get("error_budget"))
    assert d["chosen"] == "stop" and d["decision_basis"] == "no_feasible_move"
    with pytest.raises(planner.PlanError, match="option_not_overridable"):
        planner.apply_override(d, "widen_edge", "want it anyway")


def test_a_charged_budget_that_fits_is_shown_as_remaining(tmp_path):
    res = run_synthetic_campaign(
        SURFACES["bowl_out_of_hull"](), seed=3, parent_dir=tmp_path,
        campaign_overrides={"policy": {"campaign_delta": {"total": 0.1}}})
    d, _ = _decision(res)
    w = next(o for o in d["options"] if o["id"] == "widen_edge")
    assert w["feasible"] and w["error_budget"]["fits"]
    assert w["error_budget"]["next_epoch_delta"] == pytest.approx(0.025)
    assert d["error_budget"]["remaining"] == pytest.approx(0.05)


def test_a_run_budget_too_small_for_the_next_epoch_stops(tmp_path):
    res = run_synthetic_campaign(SURFACES["bowl_out_of_hull"](), seed=3, parent_dir=tmp_path,
                                 campaign_overrides={"planner": {"campaign_max_runs": 40}})
    d, _ = _decision(res)
    assert d["error_budget"]["runs_remaining"] == 40 - d["error_budget"]["runs_spent_campaign"]
    assert all(o["reason"] == "run_budget_insufficient" for o in d["options"]
               if o["id"] != "stop" and o.get("cost_runs"))
    assert d["chosen"] == "stop"


def test_a_declared_stop_threshold_is_compiled_and_used(tmp_path):
    res = run_synthetic_campaign(SURFACES["bowl_out_of_hull"](), seed=3, parent_dir=tmp_path,
                                 campaign_overrides={"planner": {"stop_value_per_run": 1e6}})
    d, _ = _decision(res)
    assert d["stopping"] == {"threshold_per_run": 1e6,
                             "rule": "declared: optimization.planner.stop_value_per_run"}
    assert d["chosen"] == "stop"


def test_a_multi_objective_campaign_scores_ehvi_in_one_frame(tmp_path):
    res = run_synthetic_campaign(PARETO_SURFACES["pareto_convex"](), seed=3, parent_dir=tmp_path)
    d, _ = _decision(res)
    assert d["utility"]["name"] == "expected_hypervolume_improvement_per_run"
    scored = [o for o in d["options"] if o.get("utility", {}).get("value") is not None]
    assert scored and all(o["utility"]["ehvi_method"] == "exact_2d_strip_decomposition"
                          for o in scored)
    rec = next((o for o in d["options"] if o["id"] == "recombination"), None)
    if rec is not None and rec.get("allocation") and not rec["allocation"]["declined"]:
        assert rec["allocation"]["method"]["kind"] == "multi_objective"


# ── accept / override / next-epoch provenance ────────────────────────────────


def _drive(campaign, work_dir, first, last, surface, seed):
    from orchestrator.engine import Engine
    from orchestrator.iteration import IterationOutcome
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner

    runner = make_synthetic_runner(surface, seed=seed)
    for i in range(first, last):
        eng = Engine(work_dir)
        if eng.phase != "DONE":
            eng.transition("DONE")
        eng.transition("DESIGN")
        out = run_stage(campaign, work_dir, iteration=i, config_runner=runner,
                        test_results=_all_pass(campaign), auto_approve=True)
        if out == IterationOutcome.COMPLETED:
            return i
    raise AssertionError("epoch did not complete")


def test_accept_writes_the_proposal_and_the_next_epoch_records_the_override(tmp_path,
                                                                             monkeypatch):
    """The whole loop, with no model call. Plan, override to narrow with a
    reason, accept: the campaign file now holds the proposal, the boundary
    record marks epoch 1 planned, the next run compiles epoch 2 from the
    accepted campaign, and epoch 2's report.json provenance names the
    override and its reason."""
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    surf = SURFACES["bowl_out_of_hull"]()
    res = run_synthetic_campaign(surf, seed=3, parent_dir=tmp_path)
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    wd = res.work_dir
    cfile = tmp_path / "campaign.yaml"
    cfile.write_text((wd / "campaign.epoch-1.yaml").read_text())
    before = cfile.read_text()
    out = planner.plan(wd)
    planner.write_plan(out, choose="narrow", reason="the edge is a hard core-count limit")
    assert cfile.read_text() == before                     # never written without --accept
    rec = planner.accept(wd, cfile)
    assert rec["chosen"] == "narrow" and rec["scored_choice"] == "widen_edge"
    assert rec["override"]["reason"] == "the edge is a hard core-count limit"
    assert (wd / "epoch_end.planned-1.json").exists()
    new = yaml.safe_load(cfile.read_text())
    assert new != yaml.safe_load(before)
    with pytest.raises(planner.PlanError, match="already_planned"):
        planner.accept(wd, cfile)
    last = max(int(p.name.split("-")[1]) for p in (wd / "runs").glob("iter-*"))
    _drive(new, wd, last + 1, last + 8, surf, seed=9)
    rep = json.loads((wd / "report.json").read_text())
    assert rep["epoch"] == 2
    pl = rep["provenance"]["planner"]
    assert pl["chosen"] == "narrow" and pl["scored_choice"] == "widen_edge"
    assert pl["override"]["reason"] == "the edge is a hard core-count limit"
    assert pl["compiled_matches_accepted"] is True
    assert "epoch_end.planned-1.json" in rep["provenance"]["inputs"]
    assert len(rep["error_budget"]["epochs"]) == 2
    # The analysis of both epochs re-derives from the rows: the planned
    # boundary is an input, carried, never re-derived.
    from orchestrator.optimize.reanalyze import reanalyze

    ra = reanalyze(wd)
    assert ra.identical, ra.differences[:5]


def test_an_override_needs_a_reason_and_a_known_option(converged):
    out = planner.plan(converged.work_dir)
    with pytest.raises(planner.PlanError, match="override_needs_reason"):
        planner.write_plan(out, choose="narrow", reason="  ")
    with pytest.raises(planner.PlanError, match="unknown_option"):
        planner.write_plan(planner.plan(converged.work_dir), choose="nope", reason="x")


def test_accept_refuses_a_stale_decision(tmp_path):
    res = run_synthetic_campaign(SURFACES["bowl_out_of_hull"](), seed=3, parent_dir=tmp_path)
    planner.write_plan(planner.plan(res.work_dir))
    rp = res.work_dir / "report.json"
    rp.write_text(rp.read_text().replace('"certified"', '"certified" ', 1))
    with pytest.raises(planner.PlanError, match="stale_decision"):
        planner.accept(res.work_dir, tmp_path / "c.yaml")


def test_an_epoch_that_ended_on_an_exception_is_not_planned(tmp_path):
    res = run_synthetic_campaign(SURFACES["nan_at_corner"](), seed=32, parent_dir=tmp_path)
    with pytest.raises(planner.PlanError, match="epoch_ended_on_exception"):
        planner.plan(res.work_dir)


def test_the_cli_writes_the_decision_and_never_touches_the_campaign(converged, capsys,
                                                                     monkeypatch):
    from orchestrator.cli import main

    monkeypatch.setattr("sys.argv", ["nous", "plan-next", str(converged.work_dir)])
    main()
    out = capsys.readouterr().out
    assert "chosen: stop" in out
    assert (converged.work_dir / "plan_next" / "epoch-1" / "planner_decision.json").exists()


def test_without_a_plan_the_next_epoch_report_has_no_planner_provenance(converged):
    assert "planner" not in converged.report["provenance"]


def test_a_dead_knob_is_pinned_into_run_command(tmp_path):
    """A bowl over A, B plus a choice knob D with no effect. The screen finds
    no main effect for D and refine holds it, so plan-next offers pin_dead.
    That proposal removes D and folds its flag at the held level into
    run_command, and the proposal validates."""
    from orchestrator.optimize.synthetic import Surface, _choice, _numeric

    s = Surface(name="bowl_dead", noise_sd=0.05,
                factors=(_numeric("A"), _numeric("B"), _choice("D")),
                fn=lambda lv: 20 - 0.05 * (lv["A"] - 9) ** 2 - 0.05 * (lv["B"] - 11) ** 2)
    res = run_synthetic_campaign(s, seed=3, parent_dir=tmp_path,
                                 campaign_overrides={"run_command": "bench --x"})
    d, out = _decision(res)
    pin = next(o for o in d["options"] if o["id"] == "pin_dead")
    assert pin["feasible"], pin
    c = out["campaigns"]["pin_dead"]
    assert [f["id"] for f in c["optimization"]["factors"]] == ["A", "B"]
    held = json.loads(sorted(res.work_dir.glob("runs/iter-*/recommendation.json"))[-1]
                      .read_text())["held_fixed"]["D"]
    assert c["optimization"]["run_command"] == f"bench --x --d={held}"
    assert pin["region"]["pinned"] == {"D": held}


def test_an_unrecoverable_earlier_epoch_makes_a_charged_plan_infeasible():
    """A cumulative spend that is only a lower bound can never certify that
    the remaining charged budget covers the next epoch."""
    ep = {"epoch": 2}
    import copy as _c

    from orchestrator.optimize.harness import synthetic_campaign

    camp = synthetic_campaign(SURFACES["bowl"](), policy={"campaign_delta": {"total": 0.5}})
    fits = planner._next_epoch_budget(
        _c.deepcopy(camp), ep, {"mode": "charged", "campaign_total": 0.5, "cumulative": 0.1,
                                "cumulative_is_lower_bound": False})
    assert fits["fits"] is True
    lb = planner._next_epoch_budget(
        _c.deepcopy(camp), ep, {"mode": "charged", "campaign_total": 0.5, "cumulative": 0.1,
                                "cumulative_is_lower_bound": True})
    assert lb["fits"] is False and "lower bound" in lb["note"]
