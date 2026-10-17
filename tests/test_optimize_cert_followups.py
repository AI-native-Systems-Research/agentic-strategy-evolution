"""#321 P2: certification-soundness follow-ups to WP-A / WP-B.

Behavioral only: real campaigns through the synthetic harness (zero LLM
calls, no subprocess), asserting on confirmation.json / report.json, or on the
pure arithmetic of ``certificate``.
"""
from __future__ import annotations

import json
from pathlib import Path

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import PARETO_SURFACES, Surface, _numeric, _obj, _unit


def _confirmations(work_dir) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(
        Path(work_dir).glob("runs/iter-*/confirmation.json"),
        key=lambda p: int(p.parent.name.split("-")[1]))]


# ── item 5: the Pareto path reads model_adequate (WP-B limit 10) ─────────────

def _pareto_cubic() -> Surface:
    """A two-objective surface whose f1 is cubic in A: screen rejects on lack
    of fit, refine's validation check rejects, and the epoch's model_adequate
    is False -- yet each objective model is `modelled` at refine."""
    def x(lv):
        return (float(lv["A"]) - 9.0) / 7.0

    def f1(lv):
        return 12.0 - 6.0 * x(lv) ** 3 - 2.0 * x(lv) ** 2 + 1.5 * x(lv) + 0.5 * _unit(lv, "B")

    def f2(lv):
        return 10.0 + 4.0 * _unit(lv, "A") ** 2 + 1.0 * _unit(lv, "B")

    return Surface(name="pareto_cubic", noise_sd=0.05,
                   factors=(_numeric("A"), _numeric("B")), fn=f1,
                   objectives=(_obj("f1", f1), _obj("f2", f2)))


def test_a_rejected_model_seats_no_predicted_front_point(tmp_path):
    """Before #321 the multi-objective shortlist seated the rejected model's
    predicted extremes, its predicted preferred point and predicted spread,
    so the comparison was anchored on a surface the data refused. (Its
    predictions stay as RIVALS in the front statuses: a rival can only remove
    confidence, which is the conservative direction.)"""
    r = run_synthetic_campaign(_pareto_cubic(), seed=1, parent_dir=tmp_path)
    recs = [json.loads(p.read_text()) for p in r.work_dir.glob("runs/iter-*/recommendation.json")]
    assert recs and recs[-1]["model_adequate"] is False
    confs = _confirmations(r.work_dir)
    assert confs
    for c in confs:
        whys = [f.get("why") or "" for f in c["finalists"]]
        assert not any(w.startswith(("predicted extreme", "preferred point of the "
                                     "predicted")) for w in whys), whys
        assert "model_inadequate" in c["certification_withheld"]
    first = [f.get("why") or "" for f in confs[0]["finalists"]]
    measured = [w for w in first if w.startswith(("best measured", "measured nondominated"))]
    assert len(measured) >= 2, first           # measured points anchor it


def test_an_adequate_model_still_seats_predicted_points(tmp_path):
    r = run_synthetic_campaign(PARETO_SURFACES["pareto_convex"](), seed=1,
                               parent_dir=tmp_path)
    whys = [f.get("why") or "" for f in _confirmations(r.work_dir)[0]["finalists"]]
    assert any("predict" in w for w in whys), whys


# ── item 3: the constraint-exclusion delta is in the stated budget ──────────

_CORNER_OV = {"response": {"primary": {"metric": "m", "direction": "maximize"},
                           "constraints": [{"metric": "p99_ms", "op": "<=", "value": 90}]},
              "stages": ["verify", "screen", "confirm"]}


def _recommendations(work_dir) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(
        Path(work_dir).glob("runs/iter-*/recommendation.json"),
        key=lambda p: int(p.parent.name.split("-")[1]))]


def test_constraint_exclusion_is_a_third_union_term(tmp_path):
    """Before #321 constraint-model exclusion spent delta_screen on a family
    distinct from E_s while the stated budget was delta_screen +
    delta_terminal. The term is now registered, used, and summed."""
    from orchestrator.optimize.synthetic import SURFACES

    ov = dict(_CORNER_OV, policy={"delta_constraint": 0.02})
    r = run_synthetic_campaign(SURFACES["infeasible_corner_interior"](), seed=1,
                               parent_dir=tmp_path, campaign_overrides=ov)
    assert r.report["delta_constraint"] == 0.02
    eb = r.report["error_budget"]["epochs"][-1]
    assert eb["delta_constraint"] == 0.02
    assert abs(eb["spent"] - (r.report["delta_screen"] + r.report["delta_terminal"]
                              + 0.02)) < 1e-12
    cm = [e for e in _recommendations(r.work_dir)[-1]["constraint_models"] if e["modelled"]]
    assert cm and all(abs(e["delta"] - 0.02 / len(cm)) < 1e-12 for e in cm)


def test_an_unconstrained_campaign_spends_two_terms(tmp_path):
    from orchestrator.optimize.synthetic import SURFACES

    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path)
    assert "delta_constraint" not in r.report
    eb = r.report["error_budget"]["epochs"][-1]
    assert eb["spent"] == r.report["delta_screen"] + r.report["delta_terminal"]


def test_delta_constraint_is_range_checked():
    from orchestrator.validate import _rule14_policy_ranges

    assert _rule14_policy_ranges({"policy": {"delta_constraint": 0.7}})
    assert not _rule14_policy_ranges({"policy": {"delta_constraint": 0.01}})


# ── item 1 (H3): a model bound independent of the candidate count ───────────

def _ccd_fit(surface, seed, noise=None):
    import dataclasses
    import random

    from orchestrator.optimize.decide import ranked
    from orchestrator.optimize.design import central_composite
    from orchestrator.optimize.effects import fit_effects
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.matrix import coded_as_run, expand

    s = dataclasses.replace(surface, noise_sd=noise) if noise else surface
    factors = parse_factors(list(s.factors))
    ids = [f.id for f in factors]
    d = central_composite(ids, center_points=4)
    rows = expand(d, factors)
    rng = random.Random(seed)
    ys = [s.fn(r.levels) + rng.gauss(0, s.noise_sd) for r in rows]
    d, _ = coded_as_run(d, factors, [r.levels for r in rows])
    fit = fit_effects(d, ys, factor_ids=ids)
    cands = ranked(fit, factors, direction="maximize", fitted_ids=ids,
                   held_fixed={}, top=None)
    return fit, factors, ids, cands


def test_scheffe_is_chosen_from_the_design_alone_and_beats_bonferroni_on_large_m():
    from orchestrator.optimize.certificate import simultaneous_critical

    small = simultaneous_critical(0.05, 8, 3, 3)       # 8 challengers, 3 terms
    large = simultaneous_critical(0.05, 6560, 14, 3)   # 9^4 grid, quadratic in 4
    assert small["used"] == "scheffe" or small["bonferroni"] <= small["scheffe"]
    assert large["used"] == "scheffe" and large["value"] < large["bonferroni"] / 4
    for c in (small, large):
        assert c["value"] == min(c["bonferroni"], c["scheffe"])


def test_the_region_bound_equals_brute_force_over_the_grid():
    """certificate.region_bound (branch and bound, no enumeration) must return
    exactly max_z U(z, x_hat) over the whole grid at the same constant -- the
    number enumeration would give -- when it converges."""
    from orchestrator.optimize.certificate import model_regret_bound, region_bound
    from orchestrator.optimize.synthetic import SURFACES

    for name, seed in (("bowl", 3), ("saddle", 5), ("choice_x_numeric", 2)):
        fit, factors, ids, cands = _ccd_fit(SURFACES[name](), seed, noise=0.5) \
            if name != "choice_x_numeric" else _fo_fit(SURFACES[name](), seed)
        b = model_regret_bound(fit, cands, cands[0], delta=0.05, direction="maximize")
        rg = region_bound(fit, factors, ids, cands[0], crit=b.critical["value"],
                          direction="maximize")
        assert rg["converged"], (name, rg)
        assert abs(rg["value"] - b.value) < 1e-9, (name, rg["value"], b.value)


def _fo_fit(surface, seed):
    import random

    from orchestrator.optimize.decide import ranked
    from orchestrator.optimize.design import full_factorial, with_center_points
    from orchestrator.optimize.effects import fit_effects
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.matrix import coded_as_run, expand

    factors = parse_factors(list(surface.factors))
    ids = [f.id for f in factors]
    d = with_center_points(full_factorial(ids), 4)
    rows = expand(d, factors)
    rng = random.Random(seed)
    ys = [surface.fn(r.levels) + rng.gauss(0, 0.5) for r in rows]
    d, _ = coded_as_run(d, factors, [r.levels for r in rows])
    fit = fit_effects(d, ys, factor_ids=ids)
    return fit, factors, ids, ranked(fit, factors, direction="maximize",
                                     fitted_ids=ids, held_fixed={}, top=None)


def test_a_searched_space_is_no_longer_a_permanent_veto(tmp_path, monkeypatch):
    """Before #321 every searched campaign withheld with
    model_bound_not_exhaustive. With CANDIDATE_CAP forced to 1 the bowl
    campaign is SEARCHED, its unevaluated grid is bounded by branch and
    bound, and it certifies on seeds where the enumerated campaign does."""
    from orchestrator.optimize import decide
    from orchestrator.optimize.synthetic import SURFACES

    monkeypatch.setattr(decide, "CANDIDATE_CAP", 1)
    certified = 0
    for seed in range(1, 5):
        r = run_synthetic_campaign(SURFACES["bowl"](), seed=seed,
                                   parent_dir=tmp_path / str(seed))
        assert "model_bound_not_exhaustive" not in r.report["certification_withheld"]
        rec = [json.loads(p.read_text()) for p in r.work_dir.glob(
            "runs/iter-*/recommendation.json")]
        assert any("unevaluated" in (x["residual_regret_model"].get("critical") or {})
                   for x in rec)
        certified += r.report["certified"]
        if r.report["certified"]:
            assert r.true_gap <= r.report["epsilon"] + 1e-9
    assert certified >= 2


# ── item 4: the multi-objective model half ───────────────────────────────────

def _mo_fits(surface, seed, noise=0.05):
    import random

    from orchestrator.optimize.constraint_models import fit_objective_models
    from orchestrator.optimize.design import central_composite
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.matrix import coded_as_run, expand
    from orchestrator.optimize.synthetic import objective_values

    factors = parse_factors(list(surface.factors))
    ids = [f.id for f in factors]
    d = central_composite(ids, center_points=4)
    rows = expand(d, factors)
    rng = random.Random(seed)
    recs = []
    for r in rows:
        v = objective_values(surface, r.levels)
        recs.append(("complete", {m: x + rng.gauss(0, noise) for m, x in v.items()}))
    d, _ = coded_as_run(d, factors, [r.levels for r in rows])
    om = fit_objective_models([{"metric": o["metric"], "direction": o["direction"]}
                               for o in surface.objectives], d, recs, fitted_ids=ids)
    return {m: o.fit for m, o in om.items()}, factors, ids


def test_the_front_model_half_bounds_an_unmeasured_dominator():
    """On pareto_convex, B raises both objectives: {A: 2, B: 2} is dominated
    by {A: 2, B: 16} on both by 1.0 >> epsilon, so an honest model half
    must refuse to rule out an unmeasured dominator of it (D >= 0), while a
    true front point is cleared (D < 0). Before #321 a front certificate had
    no model half at all."""
    from orchestrator.optimize import pareto
    from orchestrator.optimize.certificate import front_model_half

    s = PARETO_SURFACES["pareto_convex"]()
    fits, factors, ids = _mo_fits(s, seed=1)
    objs = [pareto.Objective(o["metric"], o["direction"], {}) for o in s.objectives]
    eps = {"f1": 0.25, "f2": 0.25}
    bad = front_model_half(fits, objs, eps, {"A": 2, "B": 2}, factors=factors,
                           fitted_ids=ids, held_fixed={}, delta=0.05)
    good = front_model_half(fits, objs, eps, {"A": 2, "B": 16}, factors=factors,
                            fitted_ids=ids, held_fixed={}, delta=0.05)
    assert bad["computable"] and bad["value"] >= 0.0, bad
    assert bad["dominator"]["B"] > 2
    assert good["computable"] and good["value"] < 0.0, good


def test_a_front_certificate_states_its_model_half(tmp_path):
    """Every multi-objective certificate now carries a computable model half
    below zero: no unmeasured configuration can epsilon-dominate the chosen
    point on the event the objective-model family holds."""
    from orchestrator.optimize.harness import evaluate_pareto_campaign

    n = 0
    for seed in (1, 2):
        r = evaluate_pareto_campaign(PARETO_SURFACES["pareto_convex"](), seed=seed,
                                     parent_dir=tmp_path / str(seed))
        rep = json.loads((Path(r["work_dir"]) / "report.json").read_text())
        if rep["certified"]:
            n += 1
            mh = rep["pareto"]["model_half"]
            assert mh["computable"] and mh["value"] < 0.0
            assert all(c["used"] == "scheffe" for c in mh["critical"].values())
        assert not r["false_certified"]
    assert n >= 1


# ── item 2: the post-selection validation block ─────────────────────────────

_VAL_OV = {"known_valid_baseline": {"A": 2, "B": 2},
           "design": {"screen": {"resolution": 5, "center_points": 4},
                      "refine": {"kind": "central_composite", "center_points": 4},
                      "confirm": {"replicates": 3}, "validate": {"replicates": 4}}}


def test_the_validation_block_estimates_the_gain_without_the_winners_curse(tmp_path):
    """Before #321 the reported value and the gain point estimate came from
    the replicates that SELECTED the winner (biased upward; spec section 5
    measured +0.19). The block re-measures winner and baseline on fresh
    blocks drawn after the winner is fixed: its intervals cover the true
    gain at about the nominal level, and its value is the fresh mean."""
    import dataclasses

    from orchestrator.optimize.synthetic import SURFACES

    s = dataclasses.replace(SURFACES["bowl"](), noise_sd=0.4)
    covered = n = 0
    for seed in range(1, 9):
        r = run_synthetic_campaign(s, seed=seed, parent_dir=tmp_path / str(seed),
                                   campaign_overrides=_VAL_OV, max_iterations=10)
        assert "validate" in r.path
        v = r.report["post_selection_validation"]
        if v.get("skipped"):
            continue
        g = v["gain"]
        assert g["method"] == "welch_t"
        true = s.fn(r.recommendation) - s.fn({"A": 2, "B": 2})
        n += 1
        covered += g["low"] <= true <= g["high"]
        assert r.report["recommendation"]["value"] == v["value"]
        assert v["epsilon_reference"]["source"] == "validation_winner"
        runs = [json.loads(ln) for p in r.work_dir.glob("runs/iter-*/runs.jsonl")
                for ln in p.read_text().splitlines() if ln.strip()]
        val_iter = [p.parent for p in r.work_dir.glob("runs/iter-*/validation.json")][0]
        assert len((val_iter / "runs.jsonl").read_text().splitlines()) == 8   # 4 x 2
    assert n >= 6 and covered >= n - 1


def test_the_validation_block_needs_a_baseline():
    from orchestrator.validate import _rule31_validate_block

    assert _rule31_validate_block({"design": {"validate": {"replicates": 3}}})
    assert not _rule31_validate_block({"design": {"validate": {"replicates": 3}},
                                       "known_valid_baseline": {"A": 2}})


def test_the_preview_counts_replicates_times_two():
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.preview import build_preview
    from orchestrator.optimize.synthetic import SURFACES

    c = synthetic_campaign(SURFACES["bowl"](), **_VAL_OV)
    pv = build_preview(c, noise_sd=None, mean=None, run_secs=None)
    st = next(x for x in pv.stages if x.stage == "validate")
    assert st.runs == 8 and not st.conditional


# ── item 7: the charged cross-epoch budget ──────────────────────────────────

def test_campaign_delta_shares_never_exceed_the_total():
    from orchestrator.optimize.policy import campaign_delta_share

    geo = {"total": 0.1}
    assert sum(campaign_delta_share(geo, e) for e in range(1, 60)) <= 0.1
    assert campaign_delta_share(geo, 1) == 0.05
    sch = {"total": 0.1, "schedule": [0.06, 0.03]}
    assert campaign_delta_share(sch, 3) == 0.0


def test_an_epoch_certifies_at_its_share(tmp_path):
    """Epoch 1 under total 0.1 (geometric) certifies at 0.05, split 1:1 over
    delta_screen : delta_terminal -- 0.025 each, not the declared 0.05 each."""
    from orchestrator.optimize.synthetic import SURFACES

    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path,
                               campaign_overrides={"policy": {"campaign_delta": {"total": 0.1}}})
    assert r.report["delta_screen"] == r.report["delta_terminal"] == 0.025
    eb = r.report["error_budget"]
    assert eb["mode"] == "charged" and eb["binding"] and eb["within_total"]
    assert abs(eb["cumulative"] - 0.05) < 1e-12


def test_a_schedule_past_its_end_certifies_nothing(tmp_path, monkeypatch):
    """Epoch 2 with a one-entry schedule has no share: withheld, named."""
    from orchestrator.optimize import policy as pm
    from orchestrator.optimize.synthetic import SURFACES

    real = pm.compile_policy
    monkeypatch.setattr(pm, "compile_policy",
                        lambda c, **kw: real(c, **{**kw, "epoch": 2}))
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path,
                               campaign_overrides={"policy": {"campaign_delta": {
                                   "total": 0.1, "schedule": [0.1]}}})
    assert not r.report["certified"]
    assert "campaign_delta_exhausted" in r.report["certification_withheld"]


def test_a_stop_at_a_continue_gate_is_charged(tmp_path):
    from orchestrator.optimize.policy import read_policy
    from orchestrator.optimize.provenance import error_budget, record_continue_gate_stop
    from orchestrator.optimize.synthetic import SURFACES

    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path,
                               campaign_overrides={"policy": {"campaign_delta": {"total": 0.1}}})
    record_continue_gate_stop(r.work_dir, iteration=3)
    eb = error_budget(r.work_dir, read_policy(r.work_dir))
    assert eb["stops_at_continue_gate"][0]["charged"] == 0.05
    assert abs(eb["cumulative"] - 0.05) < 1e-12      # spent once, at compile


def test_campaign_delta_is_validated():
    from orchestrator.validate import _rule14_policy_ranges

    assert _rule14_policy_ranges({"policy": {"campaign_delta": {"total": 0.1,
                                                                "schedule": [0.08, 0.05]}}})
    assert not _rule14_policy_ranges({"policy": {"campaign_delta": {"total": 0.1}}})


# ── item 8: held-factor inertness (TOST) ─────────────────────────────────────

_INERT_OV = {"design": {"screen": {"resolution": 5, "center_points": 4},
                        "refine": {"kind": "central_composite", "center_points": 4},
                        "confirm": {"replicates": 3},
                        "inertness": {"replicates": 6, "margin": {"pct": 2}}}}


def _inert_c():
    from orchestrator.optimize.synthetic import Surface, _choice, _numeric

    return Surface(name="inert_c", noise_sd=0.05,
                   factors=(_numeric("A"), _numeric("B"), _choice("C")),
                   fn=lambda lv: 20 - 0.05 * (lv["A"] - 9) ** 2 - 0.05 * (lv["B"] - 11) ** 2
                   + (0.01 if lv["C"] == "on" else 0.0))


def test_an_inert_held_factor_is_shown_inert_and_a_live_one_is_not(tmp_path):
    """Before #321 certificate_scope could only say a held factor's other
    levels were NOT covered. With design.inertness, refine's held choice
    factor C is flipped at the winner: on `additive` (C worth 2.0, margin
    ~0.3) TOST refuses equivalence; on a surface where C is worth 0.01 it is
    shown inert, and the scope statement says so -- as a local equivalence,
    not a certificate over the other slice."""
    from orchestrator.optimize.synthetic import SURFACES

    live = run_synthetic_campaign(SURFACES["additive"](), seed=1,
                                  parent_dir=tmp_path / "live", campaign_overrides=_INERT_OV)
    sc = live.report["certificate_scope"]
    assert sc["held_fixed"] == {"C": "on"}
    assert sc["inertness"]["not_shown_inert"] == ["C"]
    shown = 0
    for seed in (1, 2, 3):
        r = run_synthetic_campaign(_inert_c(), seed=seed, parent_dir=tmp_path / str(seed),
                                   campaign_overrides=_INERT_OV)
        sc = r.report["certificate_scope"]
        if sc.get("held_fixed"):
            shown += sc["inertness"]["shown_inert"] == ["C"]
            if sc["inertness"]["shown_inert"]:
                assert "local equivalence" in sc["statement"]
    assert shown >= 2


def test_tost_is_an_equivalence_test_of_size_alpha():
    """TOST's size at the margin boundary is at most alpha (Schuirmann 1987;
    Berger 1982): true difference exactly = margin, n = 6, 4000 trials."""
    import random

    from orchestrator.optimize.stage_runner import tost

    rng = random.Random(3)
    wrong = sum(bool(tost([rng.gauss(1.0, 1.0) for _ in range(6)], margin=1.0,
                          alpha=0.05, paired=True)["equivalent"]) for _ in range(4000))
    assert wrong / 4000 <= 0.05 + 0.01
