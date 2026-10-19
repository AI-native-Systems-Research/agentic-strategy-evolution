"""Centre points that cover every categorical level (spec
2026-10-16-mixed-level-factors-design.md, feature 3).

The gap: every centre row ran each choice factor at its FIRST level, so the
curvature check (lack of fit on pure error) only ever looked under that
level. ``curvature_under_second_level`` is the oracle: C=off is flat at 15,
C=on is a bowl peaking at 16 at the design centre and reading 11.1 at every
corner. With all centres at ``off`` the screen sees no curvature, nothing
refines, and the campaign recommends ``off`` (1.0 below the optimum, epsilon
~0.32). With the centres cycled the ``on`` centres show the bowl, lack of fit
fires, refine holds C=on and finds (9, 9).
"""
from __future__ import annotations

import json

import pytest

from orchestrator.optimize.design import full_factorial, with_center_points
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.harness import run_synthetic_campaign, synthetic_campaign
from orchestrator.optimize.matrix import coded_as_run, expand, matrix_payload
from orchestrator.optimize.synthetic import (
    _choice,
    _numeric,
    curvature_under_second_level,
)


def _screen(factors, n_c):
    return with_center_points(full_factorial([f.id for f in factors]), n_c)


def _centre_levels(design, factors):
    return [r.levels for r in expand(design, factors) if r.role == "center"]


# ── the assignment rule ──────────────────────────────────────────────────────


def test_centres_cycle_a_two_level_choice_and_keep_numerics_at_mid():
    fs = parse_factors([_numeric("A"), _choice("C")])
    got = _centre_levels(_screen(fs, 4), fs)
    assert [lv["C"] for lv in got] == ["off", "on", "off", "on"]
    assert {lv["A"] for lv in got} == {9}


def test_two_choice_factors_use_the_diagonal_not_the_full_product():
    """The full product at n_c = 4 is four singletons and zero pure-error df;
    the diagonal pairs the level indices: two configurations, two each."""
    fs = parse_factors([_numeric("A"), _choice("C"), _choice("D", ("x", "y"))])
    got = [(lv["C"], lv["D"]) for lv in _centre_levels(_screen(fs, 4), fs)]
    assert got == [("off", "x"), ("on", "y"), ("off", "x"), ("on", "y")]


@pytest.mark.parametrize("n_c, expected", [
    (1, ["off"]), (2, ["off", "off"]), (3, ["off", "off", "off"]),
    (5, ["off", "on", "off", "on", "off"]),
])
def test_every_centre_configuration_is_replicated_at_least_twice(n_c, expected):
    fs = parse_factors([_numeric("A"), _choice("C")])
    assert [lv["C"] for lv in _centre_levels(_screen(fs, n_c), fs)] == expected


def test_a_campaign_without_choice_factors_keeps_one_centre_configuration():
    fs = parse_factors([_numeric("A"), _numeric("B")])
    got = _centre_levels(_screen(fs, 4), fs)
    assert len({json.dumps(lv, sort_keys=True) for lv in got}) == 1


# ── pure error within groups, and every df consumer ──────────────────────────


def test_pure_error_is_pooled_within_identical_configurations():
    """Two configurations of two replicates: df 2, and the variance is the
    pooled WITHIN-group one -- a level effect between the groups is not
    error."""
    from orchestrator.optimize.effects import fit_effects

    fs = parse_factors([_numeric("A"), _choice("C")])
    design = _screen(fs, 4)
    rows = expand(design, fs)
    run, _ = coded_as_run(design, fs, [r.levels for r in rows])
    ys = []
    for r in rows:
        if r.role == "center":
            base = 10.0 if r.levels["C"] == "off" else 20.0
            ys.append(base + (0.1 if r.replicate < 2 else -0.1))
        else:
            ys.append(10.0 + (10.0 if r.levels["C"] == "on" else 0.0))
    fit = fit_effects(run, ys, factor_ids=run.factor_ids)
    assert fit.pure_error_df == 2
    # {10.1, 9.9} and {20.1, 19.9}: each has variance 0.02, pooled 0.02. The
    # plain variance over all four centres would be ~33 -- the level effect.
    assert fit.pure_error_var == pytest.approx(0.02)


def test_the_payload_records_the_centre_assignment_and_its_df():
    fs = parse_factors([_numeric("A"), _choice("C")])
    payload = matrix_payload(_screen(fs, 4), fs, run_order_seed=1)
    cp = payload["centre_points"]
    assert cp["assignment"] == "diagonal_cyclic"
    assert cp["configurations"] == 2 and cp["pure_error_df"] == 2
    assert cp["per_level"] == {"C": {"off": 2, "on": 2}}
    assert cp["warnings"] == []


def test_the_payload_warns_when_a_level_gets_no_centre_point():
    fs = parse_factors([_numeric("A"), _choice("C")])
    cp = matrix_payload(_screen(fs, 3), fs, run_order_seed=1)["centre_points"]
    assert cp["per_level"] == {"C": {"off": 3, "on": 0}}
    assert any("'on'" in w and "curvature" in w for w in cp["warnings"])


def test_a_campaign_without_choice_factors_has_no_centre_record():
    fs = parse_factors([_numeric("A"), _numeric("B")])
    assert "centre_points" not in matrix_payload(_screen(fs, 4), fs, run_order_seed=1)


def test_preview_df_counts_distinct_centre_configurations():
    from orchestrator.optimize.preview import build_preview

    camp = synthetic_campaign(curvature_under_second_level())
    pv = build_preview(camp, noise_sd=0.05, mean=15.0, run_secs=[1.0])
    assert pv.pure_error_df == 2          # 4 centres in 2 configurations


def test_validator_warns_when_centre_points_leave_a_level_uncovered():
    from orchestrator.validate import validate_optimization_campaign

    camp = synthetic_campaign(curvature_under_second_level())
    camp["optimization"]["design"]["screen"]["center_points"] = 3
    errs = validate_optimization_campaign(camp)
    assert any(e.startswith("WARN") and "'C'" in e and "centre" in e for e in errs)
    camp["optimization"]["design"]["screen"]["center_points"] = 4
    assert not any("centre point" in e and "'C'" in e
                   for e in validate_optimization_campaign(camp))


# ── the oracle ───────────────────────────────────────────────────────────────


def _visited(res) -> list[str]:
    return list(res.path)


@pytest.mark.parametrize("seed", range(1, 9))
def test_curvature_under_a_non_first_level_is_detected_refined_and_found(tmp_path, seed):
    s = curvature_under_second_level()
    res = run_synthetic_campaign(s, seed=seed, parent_dir=tmp_path)
    assert "refine" in _visited(res), res.path
    assert res.recommendation == {"A": 9, "B": 9, "C": "on"}
    eps = abs(res.report.get("epsilon") or 0.0)
    if res.report.get("certified"):
        assert res.true_gap <= eps + 1e-9


def test_refine_holds_the_choice_factor_at_its_best_centre_mean(tmp_path):
    res = run_synthetic_campaign(curvature_under_second_level(), seed=1,
                                 parent_dir=tmp_path)
    refine_dm = None
    for p in sorted(res.work_dir.glob("runs/iter-*/design_matrix.json")):
        dm = json.loads(p.read_text())
        if any(r.get("role") == "axial" for r in dm.get("rows", [])):
            refine_dm = dm
    assert refine_dm is not None
    assert refine_dm["held_fixed"] == {"C": "on"}
    assert refine_dm["held_fixed_basis"] == {"C": "centre_mean"}
