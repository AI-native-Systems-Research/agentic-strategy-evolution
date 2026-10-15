"""Constraint models: rank candidates with a fitted model of every constraint.

The defect (observed on a real campaign, primary throughput maximised under
``p99 <= 90``): the fit modelled only the primary, so ``top_candidates`` ranked
INTERIOR points of a corner the screen had measured infeasible at every row,
confirm seated them, spent a round measuring them infeasible, and their
infeasibility withheld certification. ``SURFACES["infeasible_corner_interior"]``
reproduces it in closed form.

Three layers, all zero-token:

  * ORACLE / METAMORPHIC -- the same campaign with and without the constraint
    models (``stage_runner._MODEL_CONSTRAINTS``): the models never seat MORE
    infeasible finalists and never produce a WORSE answer against
    ``true_optimum``, and on the defect surface they strictly remove the
    wasted round.
  * UNIT -- ``decide.ranked`` with a real constraint ``Fit``: a confidently
    infeasible region is excluded, an uncertain one is kept.
  * PROPERTY -- excluding never removes a candidate whose confidence bound
    admits feasibility.
"""
from __future__ import annotations

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from orchestrator.optimize import constraint_models as cm
from orchestrator.optimize import stage_runner
from orchestrator.optimize.decide import ranked, recommend
from orchestrator.optimize.design import full_factorial, with_center_points
from orchestrator.optimize.effects import fit_effects
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES, _numeric

# ─── helpers ──────────────────────────────────────────────────────────────


def _finalists_measured_infeasible(work_dir) -> int:
    """Confirm finalists, over every round, that a measurement refused."""
    n = 0
    for d in sorted((work_dir / "runs").glob("iter-*")):
        conf = d / "confirmation.json"
        if conf.exists():
            for f in json.loads(conf.read_text()).get("finalists") or []:
                if f.get("status") != "ok":
                    n += 1
    return n


def _campaign(name, seed, tmp_path, monkeypatch, *, on: bool, constraint: dict,
              stages=None, rounds=None):
    monkeypatch.setattr(stage_runner, "_MODEL_CONSTRAINTS", on)
    s = SURFACES[name]()
    ov = {"response": {"primary": {"metric": "m", "direction": s.direction},
                       "constraints": [constraint]}}
    if stages:
        ov["stages"] = stages
    if rounds:
        ov["policy"] = {"confirm_max_rounds": rounds}
    res = run_synthetic_campaign(
        s, seed=seed, parent_dir=tmp_path / f"{name}-{seed}-{'on' if on else 'off'}",
        campaign_overrides=ov, max_iterations=12,
    )
    return res, _finalists_measured_infeasible(res.work_dir)


_CORNER = ("infeasible_corner_interior", {"metric": "p99_ms", "op": "<=", "value": 90})
_SLA = ("sla", {"metric": "p99_ms", "op": "<=", "value": 40})
_SCREEN_CONFIRM = ["verify", "screen", "confirm"]


# ─── (1) oracle / metamorphic ─────────────────────────────────────────────


#: (surface, constraint, stages, confirm_max_rounds). The corner surface has a
#: single refinable factor, so the validator rejects its default schedule
#: (refine needs >= 2) and it runs screen -> confirm only; ``sla`` also runs the
#: default screen -> refine -> confirm schedule.
_ORACLE_CASES = [
    (*_CORNER, _SCREEN_CONFIRM, None), (*_CORNER, _SCREEN_CONFIRM, 3),
    (*_SLA, _SCREEN_CONFIRM, None), (*_SLA, _SCREEN_CONFIRM, 3), (*_SLA, None, 3),
]


@pytest.mark.parametrize("surface,constraint,stages,rounds", _ORACLE_CASES)
@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_constraint_models_never_seat_more_infeasible_finalists_or_answer_worse(
    surface, constraint, stages, rounds, seed, tmp_path, monkeypatch,
):
    """Metamorphic pair over the oracle: WITH models is never worse than WITHOUT.

    Two quantities, both against ground truth rather than an artifact: the
    number of confirm finalists a measurement refused (each is a wasted seat),
    and the regret of the campaign's answer against ``true_optimum``. ``sla``'s
    p99 is deterministic, so its constraint has zero pure error and stays
    unmodelled -- the pair must then be IDENTICAL, which pins the fallback.
    """
    off, n_off = _campaign(surface, seed, tmp_path, monkeypatch, on=False,
                           constraint=constraint, stages=stages, rounds=rounds)
    on, n_on = _campaign(surface, seed, tmp_path, monkeypatch, on=True,
                         constraint=constraint, stages=stages, rounds=rounds)
    assert n_on <= n_off, (n_on, n_off)
    assert on.true_gap <= off.true_gap + 1e-9, (on.recommendation, off.recommendation)
    if surface == "sla":
        assert (on.recommendation, on.basis, n_on) == (off.recommendation, off.basis, n_off)


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_the_observed_defect_is_reproduced_without_models_and_gone_with_them(
    seed, tmp_path, monkeypatch,
):
    """The field defect, end to end: a round wasted on a known-infeasible corner.

    WITHOUT the models the screen's ranking nominates interior ``PF`` points of
    the ``BS=32, CMP=2`` corner (every screen row there measured infeasible),
    confirm measures them infeasible, and the correct answer is returned
    UNCERTIFIED. WITH them, no finalist is refused and the same answer
    certifies.
    """
    name, constraint = _CORNER
    off, n_off = _campaign(name, seed, tmp_path, monkeypatch, on=False,
                           constraint=constraint, stages=_SCREEN_CONFIRM)
    on, n_on = _campaign(name, seed, tmp_path, monkeypatch, on=True,
                         constraint=constraint, stages=_SCREEN_CONFIRM)
    assert n_off >= 1 and off.basis != "certified", (n_off, off.basis)
    assert n_on == 0, n_on
    assert on.basis == "certified", on.report.get("recommendation")
    assert on.recommendation == on.true_optimum


def test_recommendation_records_what_the_constraint_models_did(tmp_path, monkeypatch):
    """``recommendation.json`` lets a reader audit the exclusion without refitting."""
    name, constraint = _CORNER
    res, _ = _campaign(name, 1, tmp_path, monkeypatch, on=True,
                       constraint=constraint, stages=_SCREEN_CONFIRM)
    rec = json.loads((res.work_dir / "runs" / "iter-2" / "recommendation.json").read_text())
    (entry,) = rec["constraint_models"]
    assert entry["metric"] == "p99_ms" and entry["modelled"] is True
    assert entry["applied"] is True
    assert entry["excluded_confidently_infeasible"] >= 1
    assert entry["at_recommendation"]["verdict"] in ("feasible", "uncertain")
    # No surviving candidate sits in the corner every measurement refused.
    assert not [c for c in rec["top_candidates"]
                if c["levels"]["BS"] == 32 and c["levels"]["CMP"] == 2]
    assert isinstance(rec["recommendation_constraint_uncertain"], list)


def test_an_unmodellable_constraint_is_recorded_with_its_reason(tmp_path, monkeypatch):
    """``sla``'s deterministic p99 has no pure error: unmodelled, and it says why."""
    name, constraint = _SLA
    res, _ = _campaign(name, 1, tmp_path, monkeypatch, on=True,
                       constraint=constraint, stages=_SCREEN_CONFIRM)
    rec = json.loads((res.work_dir / "runs" / "iter-2" / "recommendation.json").read_text())
    (entry,) = rec["constraint_models"]
    assert entry["modelled"] is False
    assert "pure-error" in entry["reason"]
    assert entry["excluded_confidently_infeasible"] == 0
    assert entry["at_recommendation"] is None


# ─── (2) unit: confidently infeasible excluded, uncertain kept ────────────


def _factors():
    return parse_factors([_numeric("A"), _numeric("B", levels=(2, 16))])


def _fits(*, p99_coef=(50.0, 20.0, 5.0), centre_p99=(44.0, 56.0, 48.0, 52.0),
          op="<=", value=62.0):
    """A primary fit (maximised at A=+1) and a REAL constraint fit over a 2^2+4c."""
    d = with_center_points(full_factorial(["A", "B"]), 4)
    ys, p99 = [], []
    ci = 0
    for p in d.points:
        a, b = p.coded
        ys.append(10.0 + 2.0 * a + 0.5 * b + (0.01 * ci if p.role == "center" else 0.0))
        if p.role == "center":
            p99.append(centre_p99[ci])
            ci += 1
        else:
            p99.append(p99_coef[0] + p99_coef[1] * a + p99_coef[2] * b)
    fit = fit_effects(d, ys, factor_ids=["A", "B"])
    records = [("infeasible" if y > value else "complete", {"p99_ms": y}) for y in p99]
    models = cm.fit_constraint_models(
        [{"metric": "p99_ms", "op": op, "value": value}], d, records,
        fitted_ids=["A", "B"],
    )
    return fit, models


def test_confidently_infeasible_region_is_excluded_and_uncertain_region_kept():
    fit, models = _fits()
    assert models[0].modelled, models[0].reason
    kw = dict(direction="maximize", fitted_ids=["A", "B"], held_fixed={}, top=None)
    everything = ranked(fit, _factors(), **kw)
    kept = ranked(fit, _factors(), constraint_models=models, constraint_delta=0.05, **kw)
    kept_levels = [c.levels for c in kept]
    verdicts = {json.dumps(c.levels, sort_keys=True):
                cm.bound(models[0], c.coded, delta=0.05) for c in everything}

    excluded = [c for c in everything if c.levels not in kept_levels]
    assert excluded, "the A=+1, B=+1 corner region must be confidently infeasible"
    assert all(verdicts[json.dumps(c.levels, sort_keys=True)]["verdict"] == "infeasible"
               for c in excluded)
    # Uncertain candidates whose POINT prediction violates are KEPT: exclusion
    # never rests on a point prediction.
    point_violating_kept = [
        c for c in kept
        if verdicts[json.dumps(c.levels, sort_keys=True)]["predicted"] > 62.0
    ]
    assert point_violating_kept, "an uncertain, point-violating candidate must stay"
    assert all(verdicts[json.dumps(c.levels, sort_keys=True)]["verdict"] == "uncertain"
               for c in point_violating_kept)
    # The unconstrained argmax (A=16, B=16) is confidently infeasible; the
    # recommendation moves off it.
    assert everything[0].levels == {"A": 16, "B": 16}
    rec = recommend(fit, _factors(), direction="maximize", fitted_ids=["A", "B"],
                    held_fixed={}, constraint_models=models, constraint_delta=0.05)
    assert rec.levels != {"A": 16, "B": 16}


def test_ge_constraint_mirrors_le():
    """``metric >= v`` excludes where the UPPER bound is below ``v``."""
    fit, models = _fits(p99_coef=(50.0, -20.0, -5.0), op=">=", value=38.0)
    assert models[0].modelled
    kept = ranked(fit, _factors(), direction="maximize", fitted_ids=["A", "B"],
                  held_fixed={}, top=None, constraint_models=models)
    assert {"A": 16, "B": 16} not in [c.levels for c in kept]


@pytest.mark.parametrize("constraint,why", [
    ({"metric": "p99_ms", "op": "==", "value": 50}, "violating side"),
    ({"metric": "p99_ms", "op": "!=", "value": 50}, "violating side"),
    ({"metric": "p99_ms", "op": "<=", "value": 50, "when": [2]}, "guarded"),
    ({"metric": "p99_ms", "op": "<=", "value": "fast"}, "not a number"),
])
def test_unmodellable_constraints_fall_back_to_measurement(constraint, why):
    d = with_center_points(full_factorial(["A", "B"]), 4)
    records = [("complete", {"p99_ms": 50.0 + i}) for i in range(len(d.points))]
    (m,) = cm.fit_constraint_models([constraint], d, records, fitted_ids=["A", "B"])
    assert not m.modelled and why in m.reason


def test_no_pure_error_and_missing_metric_are_unmodelled_and_failed_rows_skipped():
    d = with_center_points(full_factorial(["A", "B"]), 4)
    c = {"metric": "p99_ms", "op": "<=", "value": 60}
    flat = [("complete", {"p99_ms": 50.0}) for _ in d.points]           # deterministic
    (m,) = cm.fit_constraint_models([c], d, flat, fitted_ids=["A", "B"])
    assert not m.modelled and "pure-error" in m.reason
    missing = [("complete", {"p99_ms": 50.0})] * (len(d.points) - 1) + [("complete", {})]
    (m,) = cm.fit_constraint_models([c], d, missing, fitted_ids=["A", "B"])
    assert not m.modelled and "missing" in m.reason
    # A FAILED or REJECTED row is not a measurement: skipped, never "missing".
    recs = [("complete", {"p99_ms": 50.0 + 20 * p.coded[0] + (i % 3)})
            for i, p in enumerate(d.points)]
    recs[0] = ("failed", {})
    recs[1] = ("rejected", {"p99_ms": 1e9})
    (m,) = cm.fit_constraint_models([c], d, recs, fitted_ids=["A", "B"])
    assert m.n_rows == len(d.points) - 2


# ─── (3) property: never exclude a candidate that might be feasible ───────


@settings(max_examples=60, deadline=None)
@given(
    b0=st.floats(-50, 50), ba=st.floats(-30, 30), bb=st.floats(-30, 30),
    noise=st.lists(st.floats(-5, 5), min_size=4, max_size=4).filter(
        lambda xs: max(xs) - min(xs) > 1e-3),
    op=st.sampled_from(["<", "<=", ">", ">="]), value=st.floats(-60, 60),
    delta=st.sampled_from([0.01, 0.05, 0.2]),
)
def test_exclusion_never_removes_a_candidate_whose_bound_admits_feasibility(
    b0, ba, bb, noise, op, value, delta,
):
    centre = [b0 + n for n in noise]
    fit, models = _fits(p99_coef=(b0, ba, bb), centre_p99=centre, op=op, value=value)
    kw = dict(direction="maximize", fitted_ids=["A", "B"], held_fixed={}, top=None)
    everything = ranked(fit, _factors(), **kw)
    kept = [c.levels for c in ranked(fit, _factors(), constraint_models=models,
                                     constraint_delta=delta, **kw)]
    assert kept, "the space is never emptied by a model"
    # The admissibility test is restated HERE from the definition, not read back
    # from `cm.bound`: a property that asked the code under test for its own
    # verdict would pass under a mutation that excludes on the point prediction.
    from scipy.stats import t as student_t

    m = models[0]
    for c in everything:
        if not m.modelled:
            assert c.levels in kept
            continue
        y, se = cm.predicted_with_se(m.fit, c.coded)
        half = float(student_t.ppf(1 - delta, m.fit.pure_error_df)) * se
        admits_feasible = {
            "<=": y - half <= value, "<": y - half < value,
            ">=": y + half >= value, ">": y + half > value,
        }[op]
        if admits_feasible:
            assert c.levels in kept, (c.levels, y, se)
