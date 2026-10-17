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
