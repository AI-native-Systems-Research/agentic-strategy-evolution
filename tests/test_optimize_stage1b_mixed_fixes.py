"""Stage-1b re-review fixes for mixed-level factors (nous-e2e/audit/
stage1b-mixed-rereview-fixes.md). Each N-test FAILS on 87ef4e8 and passes
after; the item it closes is in its name."""
from __future__ import annotations

import dataclasses
import json

import pytest

from orchestrator.optimize import invariants as inv
from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES
from tests.test_optimize_categorical_oracles import middle_level_best

SCREEN_CONFIRM = {"stages": ["verify", "screen", "confirm"]}


def _rec(res, it=2):
    return json.loads((res.work_dir / "runs" / f"iter-{it}" / "recommendation.json").read_text())


def _shortlist(res):
    return json.loads(next(res.work_dir.glob("runs/iter-*/shortlist.json")).read_text())


def _screen_obs(res):
    for ln in (res.work_dir / "transitions.jsonl").read_text().splitlines():
        t = json.loads(ln)
        if t["from"] == "screen":
            return t["observations"]
    raise AssertionError("no screen transition")


def test_N1_unknown_adequacy_shortlists_like_adequate_and_withholds(tmp_path):
    """3 levels, 4 centres: arc untested -> model_adequate null. Before:
    confirm read null as False (measured-leaders shortlist, 'lack of fit'
    log) while certification read it as True. After: the model's pick heads
    the shortlist, certification is withheld as curvature_untested, the
    policy observed null, and INV-SEM17 holds."""
    res = run_synthetic_campaign(middle_level_best(bowl=False), seed=1,
                                 parent_dir=tmp_path, campaign_overrides=SCREEN_CONFIRM)
    rec = _rec(res)
    assert rec["model_adequate"] is None and rec["model_adequate_basis"] == "curvature_untested"
    assert _shortlist(res)["finalists"][0]["why"] == "screen recommendation"
    assert res.report["certified"] is False
    assert "curvature_untested" in res.report["certification_withheld"]
    assert _screen_obs(res)["model_adequate"] is None
    assert inv.check_certificate_rests_on_adequate_model(res.report, rec) == []


def test_N1_the_invariant_catches_a_certificate_on_unknown_adequacy():
    rec = {"model_adequate": None, "model_adequate_basis": "curvature_untested"}
    assert inv.check_certificate_rests_on_adequate_model(
        {"certified": True, "certification_withheld": []}, rec)
    assert inv.check_certificate_rests_on_adequate_model(
        {"certified": False, "certification_withheld": ["bound_above_epsilon"]}, rec)
    assert inv.check_certificate_rests_on_adequate_model(
        {"certified": False, "certification_withheld": ["curvature_untested"]}, rec) == []


def test_N1_report_md_explains_the_new_reasons():
    from orchestrator.optimize.report_md import WITHHELD_MEANING

    for r in ("curvature_untested", "lack_of_fit_not_computable",
              "curvature_not_isolated"):
        assert r in WITHHELD_MEANING and "unknown" in WITHHELD_MEANING[r]


def test_N5_no_pure_error_means_adequacy_unknown_not_true(tmp_path):
    res = run_synthetic_campaign(
        SURFACES["additive"](), seed=1, parent_dir=tmp_path,
        campaign_overrides={**SCREEN_CONFIRM,
                            "design": {"screen": {"resolution": 5, "center_points": 0},
                                       "confirm": {"replicates": 3}}})
    rec = _rec(res)
    assert rec["model_adequate"] is None
    assert rec["model_adequate_basis"] == "lack_of_fit_not_computable"
    assert res.report["certified"] is False
    assert "lack_of_fit_not_computable" in res.report["certification_withheld"]


def test_N12_a_lost_level_is_not_listed_as_curvature_untested(tmp_path):
    s = dataclasses.replace(middle_level_best(bowl=False),
                            fails_at=lambda lv: lv["POL"] == "arc")
    res = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path,
                                 campaign_overrides=SCREEN_CONFIRM)
    rec = _rec(res)
    assert rec["lost_levels"] == {"POL": ["arc"]}
    assert "arc" not in (rec.get("curvature_untested_levels") or {}).get("POL", [])


def test_N2_a_lost_level_gets_no_fabricated_ls_mean_and_is_never_named_best(tmp_path):
    from tests.test_optimize_categorical_oracles import four_levels_x_numeric

    s = dataclasses.replace(four_levels_x_numeric(), fails_at=lambda lv: lv["C"] == "y")
    res = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path,
                                 campaign_overrides=SCREEN_CONFIRM)
    eff = json.loads((res.work_dir / "runs" / "iter-2" / "effects.json").read_text())
    [cat] = eff["categoricals"]
    y = next(lv for lv in cat["levels"] if lv["level"] == "y")
    assert y["ls_mean"] is None and y["effect"] is None and y["lost"] is True
    assert cat["levels_fitted"] == 3 and cat["levels_declared"] == 4
    f = json.loads((res.work_dir / "runs" / "iter-2" / "findings.json").read_text())
    arm = next(a for a in f["arms"] if a["metadata"].get("label") == "C")
    assert arm["metadata"]["best_level"] != "y"
    assert res.recommendation.get("C") != "y"


def test_N6_a_categorical_reduced_to_two_levels_keeps_a_1df_test_and_can_drop(tmp_path):
    from orchestrator.optimize.synthetic import Surface, _choice, _numeric

    s = Surface(name="n6", noise_sd=0.05,
                factors=(_numeric("A"), _numeric("B"),
                         _choice("POL", levels=("lru", "lfu", "arc"))),
                fn=lambda lv: 10 + 0.1 * lv["A"] + (5.0 if lv["POL"] == "arc" else 0.0),
                fails_at=lambda lv: lv["POL"] == "arc")
    res = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path,
                                 campaign_overrides=SCREEN_CONFIRM)
    eff = json.loads((res.work_dir / "runs" / "iter-2" / "effects.json").read_text())
    [cat] = eff["categoricals"]
    assert cat["factor"] == "POL" and cat["df"] == 1 and cat["significant"] is False
    assert "POL" in eff["dropped_factors"]


def test_N3_a_level_measured_only_at_centre_rows_is_lost_not_leaked(tmp_path):
    """Every CORNER run at arc fails; the arc centre rows (A = B = 9) measure.
    Before: arc kept, the corner model rank-deficient, curvature isolation
    silently skipped, C 'significant' from the centre contrast and the model
    'adequate'. After: arc's centre rows are left out, arc is lost, the fit is
    isolated, and it is recorded."""
    from orchestrator.optimize.synthetic import Surface, _choice, _numeric

    s = Surface(name="n3", noise_sd=0.05,
                factors=(_numeric("A"), _numeric("B"),
                         _choice("POL", levels=("lru", "lfu", "arc"))),
                fn=lambda lv: (10 + 0.1 * lv["A"] - 0.05 * (lv["B"] - 9) ** 2
                               + {"lru": 0.0, "lfu": 2.0, "arc": 1.0}[lv["POL"]]),
                fails_at=lambda lv: lv["POL"] == "arc" and lv["A"] != 9)
    res = run_synthetic_campaign(
        s, seed=1, parent_dir=tmp_path,
        campaign_overrides={**SCREEN_CONFIRM,
                            "design": {"screen": {"resolution": 5, "center_points": 6},
                                       "confirm": {"replicates": 3}}})
    fx = json.loads((res.work_dir / "runs" / "iter-2" / "fit_exclusions.json").read_text())
    assert fx["lost_at_corners"] == {"POL": ["arc"]}
    assert fx["lost_levels"] == {"POL": ["arc"]}
    assert "level_lost_at_corners" in fx["excluded_by_reason"]
    eff = json.loads((res.work_dir / "runs" / "iter-2" / "effects.json").read_text())
    assert eff["centre_isolated"] is True
    assert res.recommendation.get("POL") == "lfu"


def test_N3_a_non_isolated_mixed_fit_says_so_and_adequacy_is_unknown():
    from orchestrator.optimize.design import mixed_screen
    from orchestrator.optimize.effects import fit_effects
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.matrix import coded_as_run, expand
    from orchestrator.optimize.stage import decide_after_screen
    from orchestrator.optimize.stage_runner import _model_adequacy
    from orchestrator.optimize.synthetic import _choice, _numeric

    fs = parse_factors([_choice("C", levels=("a", "b", "c")), _numeric("A", levels=(2, 16))])
    d = mixed_screen(fs, resolution=5, center_points=4)
    rows = expand(d, fs)
    keep = [i for i, r in enumerate(rows)
            if not (r.role == "corner" and r.levels["C"] == "b")]
    run, _ = coded_as_run(d, fs, [r.levels for r in rows])
    sub = dataclasses.replace(run, points=tuple(run.points[i] for i in keep))
    ys = [float(i % 3) + 0.01 * i for i in range(len(keep))]
    fit = fit_effects(sub, ys, factor_ids=sub.factor_ids, include_interactions=False)
    assert fit.centre_isolated is False
    assert fit.centre_isolation_reason == "corner_model_rank_deficient"
    adequate, basis = _model_adequacy(decide_after_screen(fit, fs), False, fit, {}, sub)
    assert adequate is None and basis in ("curvature_not_isolated",
                                          "lack_of_fit_not_computable")


def test_N4_report_json_and_md_carry_the_adequacy_and_level_facts(tmp_path):
    s = dataclasses.replace(middle_level_best(bowl=False),
                            fails_at=lambda lv: lv["POL"] == "arc")
    res = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path,
                                 campaign_overrides=SCREEN_CONFIRM)
    assert res.report["lost_levels"] == {"POL": ["arc"]}
    from orchestrator.optimize.report_md import render_report_markdown

    md = render_report_markdown(res.work_dir)
    assert "Levels lost" in md and "POL: arc" in md
    res2 = run_synthetic_campaign(middle_level_best(bowl=False), seed=1,
                                  parent_dir=tmp_path / "b",
                                  campaign_overrides=SCREEN_CONFIRM)
    assert res2.report["model_adequate"] is None
    assert res2.report["model_adequate_basis"] == "curvature_untested"
    assert res2.report["curvature_untested_levels"] == {"POL": ["arc"]}
    md2 = render_report_markdown(res2.work_dir)
    assert "Model adequacy:** unknown" in md2 and "Curvature never checked under" in md2


def test_N7_measured_exclusions_stay_measured_and_the_level_invariant_has_teeth(tmp_path):
    s = dataclasses.replace(middle_level_best(bowl=False),
                            fails_at=lambda lv: lv["POL"] == "arc")
    res = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path,
                                 campaign_overrides=SCREEN_CONFIRM)
    rec = _rec(res)
    assert {"POL": "arc"} not in rec["excluded_measured_infeasible"]
    assert inv.check_recommendation_avoids_lost_levels(rec) == []
    bad = dict(rec, levels={**rec["levels"], "POL": "arc", "A": 9})
    assert inv.check_recommendation_avoids_lost_levels(bad)


def test_N8_every_level_inadmissible_is_recorded_not_dropped(tmp_path):
    from tests.test_optimize_categorical_oracles import five_levels_with_constraint

    s = five_levels_with_constraint()
    res = run_synthetic_campaign(
        s, seed=1, parent_dir=tmp_path,
        campaign_overrides={**SCREEN_CONFIRM, "response": {
            "primary": {"metric": "m", "direction": "maximize"},
            "constraints": [{"metric": "lat_ms", "op": "<=", "value": 5.0}]}})
    rec = _rec(res)
    assert sorted(rec["inadmissible_levels"]["C"]) == ["c1", "c2", "c3", "c4", "c5"]
    assert rec["all_levels_inadmissible"] == ["C"]
    assert inv.check_recommendation_avoids_lost_levels(rec) == []


def test_N10_rule30_does_not_refuse_a_level_space_factorial_screen():
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.synthetic import Surface, _choice, _numeric
    from orchestrator.validate import validate_optimization_campaign

    # 3 levels x one numeric: the level-space factorial is 6 runs, the
    # resolution-III replacement fraction 8, so the factorial is built.
    s = Surface(name="n10", fn=lambda lv: 0.0,
                factors=(_numeric("A"), _choice("C", levels=("a", "b", "c"))))
    c = synthetic_campaign(s)
    c["optimization"]["design"]["screen"]["resolution"] = 3
    hard = [e for e in validate_optimization_campaign(c) if not e.startswith("WARN")]
    assert not any("policy.foldover" in e for e in hard), hard


def test_N11_design_matrix_persists_the_screen_choice(tmp_path):
    res = run_synthetic_campaign(middle_level_best(bowl=False), seed=1,
                                 parent_dir=tmp_path, campaign_overrides=SCREEN_CONFIRM)
    dm = json.loads((res.work_dir / "runs" / "iter-2" / "design_matrix.json").read_text())
    sc = dm["screen_choice"]
    assert sc["chosen"] == "level_full" and sc["level_full"] == 12
    assert sc["replacement"] == 16 and sc["resolution_requested"] == 5 and sc["rule"]


def test_N13_span_aliased_interactions_are_listed_as_not_assessed(tmp_path):
    from tests.test_optimize_categorical_oracles import five_knobs_with_a_categorical

    res = run_synthetic_campaign(
        five_knobs_with_a_categorical(), seed=1, parent_dir=tmp_path,
        campaign_overrides={**SCREEN_CONFIRM,
                            "design": {"screen": {"resolution": 3, "center_points": 4},
                                       "confirm": {"replicates": 3}},
                            "policy": {"foldover": False}})
    rec = _rec(res)
    eff = json.loads((res.work_dir / "runs" / "iter-2" / "effects.json").read_text())
    assert eff["aliased_in_span"]
    assert rec["aliases_not_assessed"] == ["".join(x["term"]) for x in eff["aliased_in_span"]]


def test_N5_a_deterministic_exact_fit_stays_adequate_a_deterministic_misfit_is_unknown():
    from orchestrator.optimize.design import full_factorial, with_center_points
    from orchestrator.optimize.effects import fit_effects
    from orchestrator.optimize.stage import decide_after_screen
    from orchestrator.optimize.stage_runner import _model_adequacy

    d = with_center_points(full_factorial(["A", "B"]), 3)
    lin = [1 + 2 * p.coded[0] - p.coded[1] for p in d.points]
    fit = fit_effects(d, lin, factor_ids=["A", "B"])
    assert fit.lack_of_fit_p is None and fit.lof_exact_fit
    assert _model_adequacy(decide_after_screen(fit, []), False, fit, {}, d) == (True, None)
    curved = [y + (1.0 if p.role == "center" else 0.0) for y, p in zip(lin, d.points)]
    fit2 = fit_effects(d, curved, factor_ids=["A", "B"])
    # Superseded by stage-1c P5: with lack-of-fit df, nonzero residuals against
    # zero pure error are an ESTABLISHED lack of fit, not "not computable".
    assert _model_adequacy(decide_after_screen(fit2, []), False, fit2, {}, d) == (
        False, None)
