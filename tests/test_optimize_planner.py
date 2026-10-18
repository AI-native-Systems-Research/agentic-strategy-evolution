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


# Function-scoped: a written decision is sealed with a key under the
# per-test NOUS_STATE_HOME (conftest), so a work_dir must not outlive its test.
@pytest.fixture
def converged(tmp_path):
    return run_synthetic_campaign(SURFACES["bowl"](), seed=3, parent_dir=tmp_path / "conv")


@pytest.fixture
def boundary(tmp_path):
    return run_synthetic_campaign(SURFACES["bowl_out_of_hull"](), seed=3,
                                  parent_dir=tmp_path / "bnd")


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
    assert "TRUE lower bound" in d["utility"]["computed_as"]


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
    assert d["stopping"]["threshold_per_run"] == 1e6
    assert d["stopping"]["rule"] == "declared: optimization.planner.stop_value_per_run"
    assert d["chosen"] == "stop"


def test_a_multi_objective_campaign_scores_ehvi_in_one_frame(tmp_path):
    res = run_synthetic_campaign(PARETO_SURFACES["pareto_convex"](), seed=3, parent_dir=tmp_path)
    d, _ = _decision(res)
    assert d["utility"]["name"] == "expected_hypervolume_improvement_per_run"
    scored = [o for o in d["options"] if o.get("utility", {}).get("value") is not None]
    assert scored and all("monte_carlo" in o["utility"]["method"]
                          and o["utility"]["seed"] and o["utility"]["samples"]
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


def test_an_inadequate_model_offers_the_bo_block_as_a_model_free_alternative(tmp_path,
                                                                              monkeypatch):
    """With planner.bo declared and the RSM model rejected, plan-next scores
    nothing but offers bo_block: a next-epoch region bounding the TPE
    proposals, with their provenance. The sampler is faked at the seam, so
    no optuna is needed."""
    from orchestrator.optimize import bo_proposer
    from orchestrator.optimize.synthetic import ridge_cubic

    def fake(trials, space, objectives, config, n):
        assert config["seed"] == 5 and trials
        return [{"A": 6, "B": 10}, {"A": 10, "B": 14}]

    monkeypatch.setattr(bo_proposer, "_optuna_sampler", fake)
    res = run_synthetic_campaign(ridge_cubic(), seed=1, parent_dir=tmp_path,
                                 campaign_overrides={"planner": {"bo": {"seed": 5}}})
    d, out = _decision(res)
    if d["model"]["model_adequate"] is True:
        pytest.skip("this seed's model was not rejected")
    bo = next(o for o in d["options"] if o["id"] == "bo_block")
    assert bo["feasible"] and bo["score"] is None
    assert "bo_block" in d["model_free_alternatives"]
    assert d["bo"]["seed"] == 5 and d["bo"]["n_trials_from_rows"] > 0
    c = out["campaigns"]["bo_block"]
    a = next(f for f in c["optimization"]["factors"] if f["id"] == "A")
    assert (min(a["levels"]), max(a["levels"])) == (6, 10)
    planner.write_plan(planner.plan(res.work_dir), choose="bo_block",
                       reason="model rejected; try the TPE region")
    dd = json.loads((res.work_dir / "plan_next/epoch-1/planner_decision.json").read_text())
    assert dd["chosen"] == "bo_block" and dd["override"]["scored_choice"] == "stop"


def _iid_fit(n_measured: int, cand_mean: float):
    """A fit whose posterior makes the n measured points i.i.d. N(0, 1) and
    the candidate an independent N(cand_mean, 1): one indicator column per
    point, coefficient variance 1, intercept 0 with no variance, and a huge
    df so the multivariate t is Gaussian."""
    from orchestrator.optimize.effects import Effect, Fit

    p = n_measured + 1
    effs = tuple(Effect(label=f"z{i}", terms=(f"z{i}",), estimate=(cand_mean if i == n_measured
                                                                    else 0.0), se=1.0)
                 for i in range(p))
    cov = [[0.0] * (p + 1) for _ in range(p + 1)]
    for i in range(1, p + 1):
        cov[i][i] = 1.0
    fit = Fit(intercept=0.0, effects=effs, n_runs=10 ** 6, pure_error_var=1.0,
              pure_error_df=10 ** 6, term_terms=((),) + tuple((f"z{i}",) for i in range(p)),
              covariance=tuple(tuple(r) for r in cov))
    pts = [{f"z{j}": (1.0 if j == i else 0.0) for j in range(p)} for i in range(p)]
    return fit, pts[:n_measured], pts[n_measured:]


def test_the_score_is_a_true_lower_bound_on_the_increment():
    """The reviewer's counterexample (H1): 100 measured i.i.d. N(0, 1) points,
    tau = 0, and a region adding one x ~ N(0.5, 1). The true increment
    E[max(M, X, 0)] - E[max(M, 0)] is about 0.014. The old score
    max_R EI - max_M EI was 0.299 (a difference of two lower bounds); the
    joint bound must not exceed the true increment."""
    import random as _r

    from scipy.stats import norm

    from orchestrator.optimize import allocate

    # the true increment, independently (a large plain Monte Carlo)
    rng = _r.Random(1)
    n, tot = 100_000, 0.0
    for _ in range(n):
        m = max(max(rng.gauss(0, 1) for _ in range(100)), 0.0)
        tot += max(rng.gauss(0.5, 1) - m, 0.0)
    true_inc = tot / n
    assert 0.005 < true_inc < 0.03
    fit, M, X = _iid_fit(100, 0.5)
    jb = allocate.joint_increment_bound(
        fits={"m": fit}, objectives=[{"metric": "m", "direction": "maximize"}],
        measured_coded=M, cand_coded=X, tau=0.0, samples=4000)
    assert jb["value"] <= true_inc + 0.01, jb["value"]
    # the old score, for the record: EI(x) - max_m EI(m) over tau = 0
    old = (0.5 * norm.cdf(0.5) + norm.pdf(0.5)) - norm.pdf(0.0)
    assert old > 0.25 and jb["value"] < old / 10
    assert "seed=" in jb["method"] and jb["samples"] == 4000


def test_the_joint_bound_matches_the_one_point_gaussian_case():
    """With no measured points and tau fixed, the bound is the plain EI."""
    from scipy.stats import norm

    from orchestrator.optimize import allocate

    fit, _M, X = _iid_fit(0, 0.3)
    jb = allocate.joint_increment_bound(
        fits={"m": fit}, objectives=[{"metric": "m", "direction": "maximize"}],
        measured_coded=[], cand_coded=X, tau=0.0, samples=20000)
    assert jb["value"] == pytest.approx(0.3 * norm.cdf(0.3) + norm.pdf(0.3), rel=0.03)


def test_a_joint_bound_past_the_work_cap_declines(monkeypatch):
    from orchestrator.optimize import allocate

    fit, M, X = _iid_fit(3, 0.0)
    monkeypatch.setattr(allocate, "JOINT_WORK_CAP", 10)
    jb = allocate.joint_increment_bound(
        fits={"m": fit}, objectives=[{"metric": "m", "direction": "maximize"}],
        measured_coded=M, cand_coded=X, samples=100)
    assert jb["value"] is None and jb["declined"] == "joint_work_too_large"
    assert "joint_work_too_large" in allocate.DECLINE_REASONS


def test_the_planner_scores_the_counterexample_by_the_joint_bound(monkeypatch):
    """Through planner._value (the score plan-next records): on the H1
    counterexample it must be at most the true increment (~0.014). At
    60f909e it was max_R EI - max_M EI = 0.299. Levels ARE the fit's
    coordinates here (coded_of patched to the identity)."""
    from orchestrator.optimize import allocate

    monkeypatch.setattr(allocate, "coded_of", lambda lv, **_k: dict(lv))
    fit, M, X = _iid_fit(100, 0.5)
    ep = {"objectives": [{"metric": "m", "direction": "maximize"}], "fits": {"m": fit},
          "fitted_ids": [], "factors": [], "held_fixed": {}, "model_adequate": True,
          "measured": [{"levels": c, "mean": {}} for c in M]}
    v = planner._value(ep, [(c, c) for c in X], None)
    assert v["value"] is not None and v["value"] < 0.03, v
    assert v["marginal_bound_not_used"] > 0.25        # what the old score would have used


# ── accept refusals (review H2, M1, M2) ─────────────────────────────────────


def _planned(tmp_path, **kw):
    res = run_synthetic_campaign(SURFACES["bowl_out_of_hull"](), seed=3,
                                 parent_dir=tmp_path / "c", **kw)
    cf = tmp_path / "campaign.yaml"
    cf.write_text((res.work_dir / "campaign.epoch-1.yaml").read_text())
    planner.write_plan(planner.plan(res.work_dir))
    return res.work_dir, cf


def test_accept_refuses_a_campaign_edited_since_the_plan_and_leaves_it_unchanged(tmp_path):
    """H2: an edit (here a comment plus a changed level) after planning is
    the author's work; accept must not discard it."""
    wd, cf = _planned(tmp_path)
    edited = cf.read_text().replace("research_question:", "# my note\nresearch_question:")
    edited = edited.replace("- 16\n", "- 15\n", 1)
    cf.write_text(edited)
    with pytest.raises(planner.PlanError, match="campaign_edited_since_plan"):
        planner.accept(wd, cf)
    assert cf.read_text() == edited
    assert not (wd / "epoch_end.planned-1.json").exists()
    rec = planner.accept(wd, cf, force_overwrite=True)
    bak = tmp_path / "campaign.yaml.bak-epoch-1"
    assert bak.read_text() == edited and rec["backup"] == str(bak)
    assert rec["replaced_matches_registered"] is False


def test_an_unedited_accept_also_backs_up_the_replaced_file(tmp_path):
    wd, cf = _planned(tmp_path)
    before = cf.read_text()
    planner.accept(wd, cf)
    assert (tmp_path / "campaign.yaml.bak-epoch-1").read_text() == before


def test_accept_refuses_when_any_measured_row_changed_after_planning(tmp_path):
    """M1: one byte appended to runs/iter-1/... (any recorded run file)."""
    wd, cf = _planned(tmp_path)
    runs = sorted(wd.glob("runs/iter-*/runs.jsonl"))[0]
    runs.write_bytes(runs.read_bytes() + b" ")
    with pytest.raises(planner.PlanError, match="stale_decision"):
        planner.accept(wd, cf)


@pytest.mark.parametrize("name", ["transitions.jsonl", "runs/iter-2/effects.json"])
def test_accept_refuses_when_another_planner_input_changed(tmp_path, name):
    wd, cf = _planned(tmp_path)
    p = wd / name
    p.write_bytes(p.read_bytes() + b"\n")
    with pytest.raises(planner.PlanError, match="stale_decision"):
        planner.accept(wd, cf)


def test_accept_refuses_a_tampered_decision(tmp_path):
    """M2: `chosen` rewritten in the file to an option the planner marked
    error_budget_insufficient. The seal catches the edit; and a resealed
    tampered decision is still refused by the re-applied choice rules."""
    wd, cf = _planned(tmp_path, campaign_overrides={
        "policy": {"campaign_delta": {"total": 0.05, "schedule": [0.05]}}})
    dp = wd / "plan_next/epoch-1/planner_decision.json"
    d = json.loads(dp.read_text())
    bad = next(o for o in d["options"] if o.get("reason") == "error_budget_insufficient")
    d["chosen"] = d["scored_choice"] = bad["id"]
    dp.write_text(json.dumps(d))
    with pytest.raises(planner.PlanError, match="decision_tampered"):
        planner.accept(wd, cf)
    planner._seal_decision(wd, dp)                       # an attacker with the key
    with pytest.raises(planner.PlanError, match="decision_invalid|error_budget"):
        planner.accept(wd, cf)
    assert not (wd / "epoch_end.planned-1.json").exists()


def test_accept_refuses_a_decision_without_its_seal(tmp_path):
    wd, cf = _planned(tmp_path)
    (wd / "plan_next/epoch-1/planner_decision.json.seal").unlink()
    with pytest.raises(planner.PlanError, match="decision_unsealed"):
        planner.accept(wd, cf)


def test_reanalysis_is_identical_right_after_an_accept(tmp_path):
    """M3: accept writes epoch_end.planned-1.json after epoch 1's report; it
    is a decision about epoch 2, not an input epoch 1 changed."""
    from orchestrator.optimize.reanalyze import reanalyze

    wd, cf = _planned(tmp_path)
    planner.accept(wd, cf)
    ra = reanalyze(wd)
    assert ra.identical, (ra.differences[:3], ra.input_changes[:3])
    assert "epoch_end.planned-1.json" in ra.not_rederived
