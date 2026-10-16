"""Stage-1c (round 4) fixes for mixed-level factors (nous-e2e/audit/
stage1c-mixed-round4-fixes.md). Each P-test FAILS on f2d4fac and passes after."""
from __future__ import annotations

import json

import pytest

from orchestrator.optimize import invariants as inv
from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import Surface, _choice, _numeric

SCREEN_CONFIRM = {"stages": ["verify", "screen", "confirm"]}


def _rec(res, it=2):
    return json.loads((res.work_dir / "runs" / f"iter-{it}" / "recommendation.json").read_text())


def _conf(res):
    p = sorted(res.work_dir.glob("runs/iter-*/confirmation.json"))
    return json.loads(p[-1].read_text()) if p else {}


def _centre_only_best():
    """arc is the BEST level (+6) but every corner run at it fails; its centre
    rows (A = B = 9) measure. arc is lost at the corners."""
    return Surface(name="p1", noise_sd=0.05,
                   factors=(_numeric("A"), _numeric("B"),
                            _choice("POL", levels=("lru", "lfu", "arc"))),
                   fn=lambda lv: (10 + 0.1 * lv["A"] - 0.05 * (lv["B"] - 9) ** 2
                                  + {"lru": 0.0, "lfu": 2.0, "arc": 6.0}[lv["POL"]]),
                   fails_at=lambda lv: lv["POL"] == "arc" and lv["A"] != 9)


def test_P1_a_lost_level_never_wins_confirm_through_its_centre_rows(tmp_path):
    res = run_synthetic_campaign(
        _centre_only_best(), seed=1, parent_dir=tmp_path,
        campaign_overrides={**SCREEN_CONFIRM,
                            "design": {"screen": {"resolution": 5, "center_points": 6},
                                       "confirm": {"replicates": 3}}})
    rec, conf = _rec(res), _conf(res)
    assert rec["lost_levels"] == {"POL": ["arc"]}
    assert res.report["recommendation"]["levels"]["POL"] != "arc"
    assert all(f["levels"]["POL"] != "arc" for f in conf["finalists"])
    assert inv.check_recommendation_avoids_lost_levels(rec, res.report, conf) == []


def test_P1_the_invariant_now_reads_the_report_and_the_finalists():
    rec = {"levels": {"POL": "lfu"}, "lost_levels": {"POL": ["arc"]}}
    assert inv.check_recommendation_avoids_lost_levels(
        rec, {"recommendation": {"levels": {"POL": "arc"}}})
    assert inv.check_recommendation_avoids_lost_levels(
        rec, None, {"finalists": [{"levels": {"POL": "arc"}}]})


def test_P2_a_lost_and_an_inadmissible_level_on_one_factor_are_both_barred(tmp_path):
    """d fails everywhere (lost), c violates the latency bound everywhere
    (inadmissible); both beat a and b. Before: the dict merge kept only the
    lost list, so c could be recommended."""
    def lat(lv):
        return (30.0 if lv["C"] == "c" else 10.0) + 0.1 * float(lv["A"])

    s = Surface(name="p2", noise_sd=0.05,
                factors=(_numeric("A"), _numeric("B"),
                         _choice("C", levels=("a", "b", "c", "d"))),
                fn=lambda lv: 10 + 0.1 * lv["A"] + {"a": 0, "b": 1, "c": 5, "d": 6}[lv["C"]],
                fails_at=lambda lv: lv["C"] == "d",
                invalid=lambda lv: lat(lv) > 20.0,
                constraints=({"metric": "lat_ms", "op": "<=", "value": 20.0},),
                noisy_observables=lambda lv, rng: {"lat_ms": lat(lv) + rng.gauss(0, 0.3)})
    res = run_synthetic_campaign(
        s, seed=1, parent_dir=tmp_path,
        campaign_overrides={**SCREEN_CONFIRM, "response": {
            "primary": {"metric": "m", "direction": "maximize"},
            "constraints": [dict(c) for c in s.constraints]}})
    rec = _rec(res)
    assert rec["lost_levels"] == {"C": ["d"]} and rec["inadmissible_levels"] == {"C": ["c"]}
    assert all(c["levels"]["C"] not in ("c", "d") for c in rec["top_candidates"])
    assert res.recommendation["C"] == "b"


def test_P3_every_level_inadmissible_reaches_the_report_on_its_own_line(tmp_path):
    from orchestrator.optimize.report_md import render_report_markdown
    from tests.test_optimize_categorical_oracles import five_levels_with_constraint

    s = five_levels_with_constraint()
    res = run_synthetic_campaign(
        s, seed=1, parent_dir=tmp_path,
        campaign_overrides={**SCREEN_CONFIRM, "response": {
            "primary": {"metric": "m", "direction": "maximize"},
            "constraints": [{"metric": "lat_ms", "op": "<=", "value": 5.0}]}})
    assert res.report["all_levels_inadmissible"] == ["C"]
    md = render_report_markdown(res.work_dir)
    assert "Every level inadmissible wherever measured:** C" in md
    assert "Levels inadmissible wherever measured (never recommended)" not in md


def test_P4_a_rejected_model_is_in_the_report_without_confirm(tmp_path):
    from orchestrator.optimize.report_md import render_report_markdown
    from orchestrator.optimize.synthetic import SURFACES

    res = run_synthetic_campaign(SURFACES["geometric_knob"](), seed=1, parent_dir=tmp_path,
                                 campaign_overrides={"stages": ["verify", "screen"]})
    rec = _rec(res)
    assert rec["model_adequate"] is False
    assert res.report["model_adequate"] is False
    assert "Model adequacy:** rejected" in render_report_markdown(res.work_dir)


def test_P8_aliases_not_assessed_reach_the_report(tmp_path):
    from orchestrator.optimize.report_md import render_report_markdown
    from tests.test_optimize_categorical_oracles import five_knobs_with_a_categorical

    res = run_synthetic_campaign(
        five_knobs_with_a_categorical(), seed=1, parent_dir=tmp_path,
        campaign_overrides={**SCREEN_CONFIRM,
                            "design": {"screen": {"resolution": 3, "center_points": 4},
                                       "confirm": {"replicates": 3}},
                            "policy": {"foldover": False}})
    assert res.report["aliases_not_assessed"] == _rec(res)["aliases_not_assessed"]
    assert "Aliases not assessed" in render_report_markdown(res.work_dir)


def test_P9_a_legacy_unknown_adequacy_record_names_a_reason(tmp_path):
    """A report.json with model_adequate null and no basis (a legacy record):
    report.md names model_adequacy_unknown, never an empty "(None — )"."""
    from orchestrator.optimize.report_md import render_report_markdown
    from orchestrator.optimize.synthetic import SURFACES

    res = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path,
                                 campaign_overrides={"stages": ["verify", "screen"]})
    rp = res.work_dir / "report.json"
    rep = json.loads(rp.read_text())
    rep["model_adequate"] = None
    rep.pop("model_adequate_basis", None)
    rp.write_text(json.dumps(rep))
    md = render_report_markdown(res.work_dir)
    assert "`model_adequacy_unknown`" in md and "(None" not in md


def test_P5_zero_pure_error_misfit_is_an_established_rejection_and_needs_lof_df():
    from orchestrator.optimize.design import full_factorial, with_center_points
    from orchestrator.optimize.effects import fit_effects
    from orchestrator.optimize.stage import decide_after_screen
    from orchestrator.optimize.stage_runner import _model_adequacy

    d = with_center_points(full_factorial(["A", "B"]), 3)
    lin = [1 + 2 * p.coded[0] - p.coded[1] for p in d.points]
    curved = [y + (1.0 if p.role == "center" else 0.0) for y, p in zip(lin, d.points)]
    fit = fit_effects(d, curved, factor_ids=["A", "B"])
    assert fit.lof_exact == "rejected"
    assert _model_adequacy(decide_after_screen(fit, []), False, fit, {}, d) == (False, None)
    # No lack-of-fit df (n - p - df_pe = 0): two replicated configurations and
    # a 2-parameter model -> nothing decided, even with zero pure error.
    from orchestrator.optimize.design import Design, DesignPoint

    d2 = Design(points=tuple(DesignPoint(coded=(c,), role="center", replicate=i)
                             for i, c in enumerate((-1.0, -1.0, 1.0, 1.0))),
                factor_ids=("A",))
    fit2 = fit_effects(d2, [1.0, 1.0, 3.0, 3.0], factor_ids=["A"])
    assert fit2.lof_exact is None and fit2.lof_exact_fit is False
    assert _model_adequacy(decide_after_screen(fit2, []), False, fit2, {}, d2) == (
        None, "lack_of_fit_not_computable")


def test_P6_a_secondary_objective_without_a_lof_test_makes_adequacy_unknown():
    from types import SimpleNamespace

    from orchestrator.optimize.design import full_factorial, with_center_points
    from orchestrator.optimize.effects import fit_effects
    from orchestrator.optimize.pareto_stage import models_rejected, models_untested
    from orchestrator.optimize.stage import decide_after_screen
    from orchestrator.optimize.stage_runner import _model_adequacy

    import random

    d = with_center_points(full_factorial(["A", "B"]), 3)
    rng = random.Random(0)
    prim = fit_effects(d, [1 + p.coded[0] + rng.gauss(0, 0.1) for p in d.points],
                       factor_ids=["A", "B"])
    assert prim.lack_of_fit_p is not None
    d0 = full_factorial(["A", "B"])            # no centres: no pure error
    sec = fit_effects(d0, [1.0, 2.0, 2.5, 4.0], factor_ids=["A", "B"])
    om = {"f2": SimpleNamespace(fit=sec)}
    assert models_untested(om) == ["f2"] and models_rejected(om) == []
    dec = decide_after_screen(prim, [])
    assert _model_adequacy(dec, [], prim, {}, d, mo_untested=["f2"]) == (
        None, "lack_of_fit_not_computable")
    assert _model_adequacy(dec, [], prim, {}, d)[0] is True


def test_P7_screen_choice_is_the_stored_decision_never_an_invented_resolution():
    import dataclasses

    from orchestrator.optimize.design import mixed_screen
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.matrix import matrix_payload

    fs = parse_factors([_numeric("A"), _choice("C", levels=("a", "b", "c"))])
    d = mixed_screen(fs, resolution=3, center_points=2)
    sc = matrix_payload(d, fs, run_order_seed=1)["screen_choice"]
    assert sc["resolution_requested"] == 3 and sc["chosen"] == "level_full"
    assert sc["level_full"] == 6 and sc["replacement"] == 8
    bare = dataclasses.replace(d, screen_choice=(), requested_resolution=None)
    sc2 = matrix_payload(bare, fs, run_order_seed=1)["screen_choice"]
    assert sc2["chosen"] is None and "reason" in sc2 and "resolution_requested" not in sc2


def test_P9_centre_isolation_reason_without_centres_and_rule30_parse_message():
    from orchestrator.optimize.artifacts import write_effects
    from orchestrator.optimize.design import mixed_screen
    from orchestrator.optimize.effects import fit_effects
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.matrix import coded_as_run, expand
    from orchestrator.validate import _rule30_mixed_resolution_three_foldover

    import tempfile
    from pathlib import Path

    fs = parse_factors([_numeric("A"), _choice("C", levels=("a", "b", "c"))])
    d = mixed_screen(fs, resolution=5, center_points=0)
    rows = expand(d, fs)
    run, _ = coded_as_run(d, fs, [r.levels for r in rows])
    fit = fit_effects(run, [float(i) for i in range(len(rows))], factor_ids=run.factor_ids)
    out = Path(tempfile.mkdtemp())
    eff = json.loads(write_effects(out, fit, factors=fs, stage="screen").read_text())
    assert eff["centre_isolated"] is False and eff["centre_isolation_reason"] == "no_centre_rows"
    bad = [{"id": "C", "type": "choice", "levels": ["a", "b", "c"]}]   # no manipulation
    msg = _rule30_mixed_resolution_three_foldover({}, {"screen": {"resolution": 3}}, bad)
    assert msg and "do not parse" in msg[0] and "foldover" not in msg[0].split("because")[1]
