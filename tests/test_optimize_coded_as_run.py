"""The fit's design matrix is the coded ACTUAL levels, not the nominal plan.

Two defects, one principle (INV-STAT14):

  * a ``choice`` factor's centre point RUNS at its first level, but the fit
    used to code it 0 -- halfway between two levels of a categorical that has
    no halfway. That biased every coefficient touching the factor once the
    design stopped being orthogonal (any exclusion) and made lack-of-fit
    reject correctly specified models;
  * a central composite's axial points are CLAMPED to the declared range by
    ``decode_coded`` (|coded| = 1.41 / 1.68 lands on the range edge), but the
    fit still regressed on the nominal +-1.41 / 1.68 -- coordinates that were
    never run. An errors-in-variables bias that rejected a TRULY LINEAR model
    for lack of fit at p ~ 0.001.

Every test here is zero-token: the synthetic surfaces and hand-built
responses know the true coefficients, so recovery is checked directly.
"""
from __future__ import annotations

import dataclasses
import json
import random

import pytest

from orchestrator.optimize import factors as factors_mod
from orchestrator.optimize.design import (
    central_composite, full_factorial, with_center_points,
)
from orchestrator.optimize.effects import fit_effects
from orchestrator.optimize.factors import code_actual, parse_factors
from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.matrix import coded_as_run, expand, matrix_payload
from orchestrator.optimize.synthetic import SURFACES, _choice, _numeric

ALPHA = 0.05


def _factors(*raw):
    return parse_factors(list(raw))


# ─── code_actual ───────────────────────────────────────────────────────────


def test_code_actual_choice_and_numeric():
    a, c = _factors(_numeric("A", levels=(2, 4, 8, 16)), _choice("C"))
    assert code_actual(c, "off") == -1.0 and code_actual(c, "on") == 1.0
    assert code_actual(a, 2) == -1.0 and code_actual(a, 16) == 1.0
    assert code_actual(a, 9) == 0.0
    assert code_actual(a, 4) == pytest.approx((4 - 9) / 7)
    with pytest.raises(ValueError):
        code_actual(c, "maybe")


def test_code_actual_inverts_decode_coded_inside_the_range():
    """Metamorphic: decode then code is the identity wherever nothing snaps."""
    (a,) = _factors(_numeric("A", levels=(0.0, 1.0), grid=None))
    for x in (-1.0, -0.5, 0.0, 0.25, 1.0):
        assert code_actual(a, factors_mod.decode_coded(a, x)) == pytest.approx(x)
    # ... and a clamped axial point codes at the edge it actually ran at.
    assert code_actual(a, factors_mod.decode_coded(a, 1.68)) == 1.0
    assert code_actual(a, factors_mod.decode_coded(a, -1.68)) == -1.0


# ─── coded_as_run ──────────────────────────────────────────────────────────


def _levels_by_pos(design, facs):
    return [dict(r.levels) for r in expand(design, facs)]


def test_choice_centre_point_is_coded_at_the_level_it_ran():
    facs = _factors(_numeric("A", levels=(2, 16)), _choice("C"))
    d = with_center_points(full_factorial(["A", "C"]), 3)
    lv = _levels_by_pos(d, facs)
    assert all(lv[i]["C"] == "off" for i, p in enumerate(d.points) if p.role == "center")
    run, nominal = coded_as_run(d, facs, lv)
    assert nominal == []
    for p in run.points:
        if p.role == "center":
            assert p.coded == (0.0, -1.0)
    # The corners are unchanged: they ran exactly where the plan said.
    for p0, p1 in zip(d.points, run.points):
        if p0.role == "corner":
            assert p0.coded == p1.coded


def test_clamped_axial_point_is_coded_at_the_range_edge_it_ran():
    facs = _factors(_numeric("A", levels=(2, 4, 8, 16)), _numeric("B", levels=(2, 4, 8, 16)))
    d = central_composite(["A", "B"], center_points=3)
    run, _ = coded_as_run(d, facs, _levels_by_pos(d, facs))
    axial = [p.coded for p in run.points if p.role == "axial"]
    assert sorted(axial) == sorted([(-1.0, 0.0), (1.0, 0.0), (0.0, -1.0), (0.0, 1.0)])
    assert all(abs(c) <= 1.0 for p in run.points for c in p.coded)


def test_missing_levels_are_reported_not_silently_coded():
    facs = _factors(_numeric("A", levels=(2, 16)), _choice("C"))
    d = with_center_points(full_factorial(["A", "C"]), 2)
    lv = _levels_by_pos(d, facs)
    lv[1] = {}
    run, nominal = coded_as_run(d, facs, lv)
    assert nominal == [1]
    assert run.points[1].coded == d.points[1].coded


def test_pre_registration_still_records_the_plan():
    """design_matrix.json is what was PLANNED; recoding the fit changes nothing there."""
    facs = _factors(_numeric("A", levels=(2, 4, 8, 16)), _choice("C"))
    d = with_center_points(full_factorial(["A", "C"]), 2)
    before = json.dumps(matrix_payload(d, facs, run_order_seed=3), sort_keys=True)
    coded_as_run(d, facs, _levels_by_pos(d, facs))
    assert json.dumps(matrix_payload(d, facs, run_order_seed=3), sort_keys=True) == before


# ─── oracle: a correctly specified model must not be rejected ─────────────


def _lof_reject_rate(fits) -> float:
    ps = [f.lack_of_fit_p for f in fits if f.lack_of_fit_p is not None]
    assert len(ps) == len(fits), "every fit should carry a lack-of-fit test"
    return sum(p < ALPHA for p in ps) / len(ps)


def _linear_ccd_fits(n_seeds, *, as_run: bool):
    """A TRULY LINEAR surface (in the real levels) on a clamped CCD."""
    facs = _factors(_numeric("A", levels=(2, 4, 8, 16)), _numeric("B", levels=(2, 4, 8, 16)))
    d = central_composite(["A", "B"], center_points=4)
    lv = _levels_by_pos(d, facs)
    run, _ = coded_as_run(d, facs, lv)
    fits = []
    for s in range(n_seeds):
        rng = random.Random(s)
        ys = [10 + 0.5 * x["A"] + 0.2 * x["B"] + rng.gauss(0, 0.5) for x in lv]
        fits.append(fit_effects(run if as_run else d, ys, factor_ids=["A", "B"]))
    return fits


def test_linear_surface_on_clamped_ccd_is_not_rejected_above_alpha():
    """The lack-of-fit p-value of a correctly specified model is ~uniform, so
    it rejects at ~alpha. Fitting on the nominal axial coordinates rejected at
    ~100%; on the coordinates that ran it rejects at ~alpha."""
    n = 300
    rate = _lof_reject_rate(_linear_ccd_fits(n, as_run=True))
    # alpha + ~3 binomial SEs.
    assert rate <= ALPHA + 3 * (ALPHA * (1 - ALPHA) / n) ** 0.5, rate
    # The instrument has power: the nominal coding is the defect.
    assert _lof_reject_rate(_linear_ccd_fits(n, as_run=False)) > 4 * ALPHA


def test_linear_surface_coefficients_are_recovered_within_their_intervals():
    """95% intervals cover the TRUE coded coefficients at ~95%. The truth in
    coded units: A = 9 + 7a, so beta_A = 0.5 * 7, beta_B = 0.2 * 7, the
    interaction and both curvatures are 0."""
    truth = {"A": 3.5, "B": 1.4, "AB": 0.0, "A^2": 0.0, "B^2": 0.0}
    fits = _linear_ccd_fits(300, as_run=True)
    for label in ("A", "B", "AB"):
        cover = sum(
            next(e for e in f.effects if e.label == label).ci_low <= truth[label]
            <= next(e for e in f.effects if e.label == label).ci_high
            for f in fits
        ) / len(fits)
        assert cover >= 0.92, (label, cover)
    for label in ("A", "B"):
        mean = sum(next(e for e in f.effects if e.label == label).estimate
                   for f in fits) / len(fits)
        assert mean == pytest.approx(truth[label], abs=0.02)


def _mixed_fits(n_seeds, *, as_run: bool, drop_corner: bool,
                pin_centres: bool = False):
    """A x C (numeric x choice) with centre points; truth known in coded units.

    y = 10 + 0.3 A + 2 [C=on] + 0.1 A [C=on]. With a = (A - 9)/7 and
    [C=on] = (c + 1)/2 the coded coefficients are
      A: 0.3*7 + 0.1*7/2 = 2.45, C: 1 + 0.1*9/2 = 1.45, AC: 0.1*7/2 = 0.35.
    ``drop_corner`` removes the (A high, B high, C on) corner -- an exclusion,
    which is what makes the design non-orthogonal and lets a mis-coded centre
    leak into the interaction.
    """
    facs = _factors(_numeric("A", levels=(2, 16)), _numeric("B", levels=(2, 16)),
                    _choice("C"))
    d = with_center_points(full_factorial(["A", "B", "C"]), 4)
    lv = _levels_by_pos(d, facs)
    if pin_centres:
        # The pre-2026-10-16 layout: every centre row at C's FIRST level.
        lv = [dict(x, C="off") if p.role == "center" else x
              for x, p in zip(lv, d.points)]
    run, _ = coded_as_run(d, facs, lv)
    use = run if as_run else d
    keep = [i for i, x in enumerate(lv)
            if not (drop_corner and x["A"] == 16 and x["B"] == 16 and x["C"] == "on")]
    sub = dataclasses.replace(use, points=tuple(use.points[i] for i in keep))
    fits = []
    for s in range(n_seeds):
        rng = random.Random(1000 + s)
        ys = [10 + 0.3 * x["A"] + (2.0 if x["C"] == "on" else 0.0)
              + (0.1 * x["A"] if x["C"] == "on" else 0.0) + rng.gauss(0, 0.3)
              for x in lv]
        fits.append(fit_effects(sub, [ys[i] for i in keep],
                                factor_ids=["A", "B", "C"]))
    return fits


def _mean(fits, label):
    return sum(next(e for e in f.effects if e.label == label).estimate
               for f in fits) / len(fits)


@pytest.mark.parametrize("drop_corner", [False, True])
def test_mixed_choice_numeric_recovers_the_interaction_without_bias(drop_corner):
    fits = _mixed_fits(300, as_run=True, drop_corner=drop_corner)
    assert _mean(fits, "AC") == pytest.approx(0.35, abs=0.02)
    assert _mean(fits, "C") == pytest.approx(1.45, abs=0.02)
    assert _mean(fits, "A") == pytest.approx(2.45, abs=0.02)
    assert _lof_reject_rate(fits) <= ALPHA + 3 * (ALPHA * (1 - ALPHA) / 300) ** 0.5


def test_mixed_choice_numeric_nominal_coding_is_the_defect():
    """Regression guard on the instrument: with the old coding the centre rows
    lie about C, so C's main effect is biased and lack of fit rejects. Built on
    the PINNED centre layout the defect was observed under (every centre at
    C's first level); cycled centres are the subject of
    test_optimize_centre_levels."""
    fits = _mixed_fits(100, as_run=False, drop_corner=True, pin_centres=True)
    assert abs(_mean(fits, "AC") - 0.35) > 0.1
    assert _lof_reject_rate(fits) > 0.5


# ─── end to end: the real stage runner fits the coordinates that ran ──────


def _effects(work_dir):
    return [json.loads(p.read_text())
            for p in sorted((work_dir / "runs").glob("iter-*/effects.json"))]


def test_additive_surface_with_a_choice_factor_is_not_rejected(tmp_path):
    """`additive` is linear in A, B and C: no fitting stage should reject it at
    a rate above alpha. Before the fix the screen rejected on every seed."""
    ps = []
    for s in range(1, 13):
        res = run_synthetic_campaign(SURFACES["additive"](), seed=s,
                                     parent_dir=tmp_path / str(s))
        ps += [e["lack_of_fit_p"] for e in _effects(res.work_dir)
               if e.get("lack_of_fit_p") is not None]
    assert ps
    assert sum(p < ALPHA for p in ps) / len(ps) <= 0.2, ps


def test_effects_json_records_the_coordinates_the_fit_used(tmp_path):
    res = run_synthetic_campaign(SURFACES["additive"](), seed=1, parent_dir=tmp_path)
    by_stage = {e["stage"]: e for e in _effects(res.work_dir)}
    screen = by_stage["screen"]["fit_coordinates"]
    assert screen["basis"] == "coded_actual_levels"
    ci = screen["factor_ids"].index("C")
    centres = [r for r in screen["rows"] if r["role"] == "center"]
    # Planned at the nominal origin, fitted at the level each centre RAN: the
    # four centres cycle C through off/on (spec 2026-10-16 feature 3).
    assert centres and all(r["planned"][ci] == 0.0 for r in centres)
    assert sorted(r["fitted"][ci] for r in centres) == [-1.0, -1.0, 1.0, 1.0]
    refine = by_stage["refine"]["fit_coordinates"]
    axial = [r for r in refine["rows"] if r["role"] == "axial"]
    assert axial
    assert all(max(abs(v) for v in r["planned"]) > 1.0 for r in axial)
    assert all(max(abs(v) for v in r["fitted"]) <= 1.0 for r in axial)


def _noisy_sla():
    s = SURFACES["sla"]()
    return dataclasses.replace(
        s, name="sla_noisy_p99", noise_sd=0.5,
        extra_observables=lambda lv: {},
        noisy_observables=lambda lv, rng: {
            "p99_ms": 2 * lv["A"] + lv["B"] + rng.gauss(0.0, 1.0)},
    )


def test_truly_linear_constraint_model_is_not_rejected_for_lack_of_fit(tmp_path):
    """The noisy-p99 variant of `sla`: p99 = 2A + B + noise is EXACTLY linear.
    Its constraint model was rejected for lack of fit at refine (p ~ 0.001)
    when fitted on nominal axial coordinates."""
    reasons = []
    for s in range(1, 13):
        res = run_synthetic_campaign(
            _noisy_sla(), seed=s, parent_dir=tmp_path / str(s),
            campaign_overrides={"response": {
                "primary": {"metric": "m", "direction": "maximize"},
                "constraints": [{"metric": "p99_ms", "op": "<=", "value": 40}]}},
        )
        for p in sorted((res.work_dir / "runs").glob("iter-*/recommendation.json")):
            for m in json.loads(p.read_text()).get("constraint_models") or []:
                reasons.append(m["reason"])
    assert reasons
    rejected = [r for r in reasons if r.startswith("lack of fit")]
    assert len(rejected) / len(reasons) <= 0.2, reasons


# ─── honest coding exposes non-estimable terms: omit them, keep the rest ──


def test_a_quadratic_of_a_two_level_remnant_is_omitted():
    """Refine kept only BS in {8, 20} (coded {-1, 0}): BS^2 == -BS there, so the
    curvature is not estimable. The nominal coding hid this behind an axial
    row at -1.41 that ran at -1."""
    from orchestrator.optimize.exclusions import model_is_full_rank, non_estimable_terms

    facs = _factors(_numeric("BS", levels=(8, 20, 32)), _numeric("PF", levels=(0, 4, 8)))
    d = central_composite(["BS", "PF"], center_points=3)
    lv = _levels_by_pos(d, facs)
    run, _ = coded_as_run(d, facs, lv)
    keep = [i for i, x in enumerate(lv) if x["BS"] < 32]
    sub = dataclasses.replace(run, points=tuple(run.points[i] for i in keep))
    assert not model_is_full_rank(sub)
    omitted = non_estimable_terms(sub)
    assert omitted == [("BS", "BS")]
    assert model_is_full_rank(sub, omit_terms=omitted)
    rng = random.Random(0)
    ys = [100 - 2 * lv[i]["BS"] + 3 * lv[i]["PF"] - 0.2 * lv[i]["PF"] ** 2
          + rng.gauss(0, 0.1) for i in keep]
    fit = fit_effects(sub, ys, factor_ids=["BS", "PF"], omit_terms=omitted)
    assert [e.label for e in fit.quadratic] == ["PF^2"]
    # BS: -2 per unit, half-width 12 -> -24 in coded units.
    assert next(e for e in fit.effects if e.label == "BS").estimate == pytest.approx(-24, abs=0.3)


def test_an_interaction_over_three_cells_is_omitted_and_the_rest_kept():
    """Every BS=high, CMP=on row infeasible-and-unmeasured: on the three
    surviving cells BS*CMP = -1 - BS - CMP, so only that term goes."""
    from orchestrator.optimize.exclusions import non_estimable_terms

    facs = _factors(_numeric("BS", levels=(8, 32)), _choice("POL", levels=("fifo", "sjf")),
                    _choice("CMP"))
    d = with_center_points(full_factorial(["BS", "POL", "CMP"]), 3)
    lv = _levels_by_pos(d, facs)
    run, _ = coded_as_run(d, facs, lv)
    keep = [i for i, x in enumerate(lv) if not (x["BS"] == 32 and x["CMP"] == "on")]
    sub = dataclasses.replace(run, points=tuple(run.points[i] for i in keep))
    assert non_estimable_terms(sub) == [("BS", "CMP")]


def test_property_omitting_non_estimable_terms_agrees_with_the_solver():
    """Over every corner subset of a 2^3 + centres (one factor a choice), the
    rank verdict after omission predicts what fit_effects does."""
    import itertools as it

    from orchestrator.optimize.exclusions import model_is_full_rank, non_estimable_terms

    facs = _factors(_numeric("A", levels=(2, 16)), _numeric("B", levels=(2, 16)), _choice("C"))
    d = with_center_points(full_factorial(["A", "B", "C"]), 3)
    run, _ = coded_as_run(d, facs, _levels_by_pos(d, facs))
    rng = random.Random(7)
    ys = [rng.gauss(0, 1) for _ in run.points]
    centres = [i for i, p in enumerate(run.points) if p.role == "center"]
    checked = 0
    for r in range(3, 9):
        for corners in it.combinations(range(8), r):
            keep = sorted(list(corners) + centres)
            sub = dataclasses.replace(run, points=tuple(run.points[i] for i in keep))
            omit = non_estimable_terms(sub)
            predicted = model_is_full_rank(sub, omit_terms=omit)
            try:
                fit_effects(sub, [ys[i] for i in keep], factor_ids=["A", "B", "C"],
                            omit_terms=omit)
                actual = True
            except ValueError:
                actual = False
            assert predicted == actual, (corners, omit)
            checked += 1
    assert checked > 200


# ─── INV-STAT15: infeasible rows are fitted, never returned ───────────────


def _bowl_constrained():
    """bowl's optimum (9, 11) sits past a noisy ``A + B <= 18`` constraint, so the
    constraint boundary -- where the constrained optimum lives -- is exactly
    where excluding infeasible rows truncates the design."""
    s = SURFACES["bowl"]()
    return dataclasses.replace(
        s, name="bowl_constrained",
        invalid=lambda lv: lv["A"] + lv["B"] > 18,
        noisy_observables=lambda lv, rng: {"load": lv["A"] + lv["B"] + rng.gauss(0, 0.5)},
    )


def _constrained_run(seed, tmp_path, monkeypatch, statuses):
    from orchestrator.optimize import stage_runner

    monkeypatch.setattr(stage_runner, "_PRIMARY_FIT_STATUSES", frozenset(statuses))
    s = _bowl_constrained()
    return s, run_synthetic_campaign(
        s, seed=seed, parent_dir=tmp_path / f"{seed}-{len(statuses)}",
        campaign_overrides={
            "response": {"primary": {"metric": "m", "direction": "maximize"},
                         "constraints": [{"metric": "load", "op": "<=", "value": 18}]},
            "policy": {"confirm_max_rounds": 3}},
        max_iterations=12,
    )


def test_infeasible_rows_are_fitted_and_recorded(tmp_path, monkeypatch):
    from orchestrator.optimize import stage_runner

    assert "infeasible" in stage_runner._PRIMARY_FIT_STATUSES
    assert "rejected" not in stage_runner._PRIMARY_FIT_STATUSES
    assert "failed" not in stage_runner._PRIMARY_FIT_STATUSES
    s, res = _constrained_run(3, tmp_path, monkeypatch, {"complete", "infeasible"})
    counts = [(_e.get("fit_coordinates") or {}).get("rows_by_status") or {}
              for _e in _effects(res.work_dir)]
    assert any(c.get("infeasible", 0) > 0 for c in counts), counts
    assert res.recommendation and not s.invalid(res.recommendation)


def test_fitting_infeasible_rows_is_never_worse_on_the_constrained_oracle(
    tmp_path, monkeypatch,
):
    """The evidence behind INV-STAT15, as a metamorphic pair per seed: fitting
    infeasible rows never loses an answer and never returns an infeasible
    configuration. Per seed it is not uniformly better -- on some seeds the
    excluding rule's report lands one grid step (0.2) closer -- hence the
    tolerance; over 16 seeds it is better on average (mean regret 0.15 vs 0.44
    over the seeds excluding even answered, worst case 0.2 vs 2.7) and
    excluding aborted 4 of 16 with a rank-deficient refine."""
    lost = 0
    for seed in range(1, 7):
        s_in, inc = _constrained_run(seed, tmp_path / "in", monkeypatch,
                                     {"complete", "infeasible"})
        s_ex, exc = _constrained_run(seed, tmp_path / "ex", monkeypatch, {"complete"})
        assert inc.recommendation, inc.path
        assert not s_in.invalid(inc.recommendation), inc.recommendation
        if not exc.recommendation:
            lost += 1
            continue
        assert inc.true_gap <= exc.true_gap + 0.2 + 1e-9, (seed, inc.recommendation,
                                                           exc.recommendation)
    assert lost >= 1, "the excluding rule never lost an answer, so this proves nothing"

