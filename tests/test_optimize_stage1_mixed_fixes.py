"""Stage-1 review fixes for mixed-level factors (nous-e2e/audit/
stage1-mixed-review-fixes.md). Each test FAILS on the pre-fix tree (9a9ef4c)
and passes after; the item it closes is in its name."""
from __future__ import annotations

import json
import random

import pytest

from orchestrator.optimize.design import mixed_screen
from orchestrator.optimize.effects import factor_test, fit_effects
from orchestrator.optimize.exclusions import non_estimable_terms
from orchestrator.optimize.factors import model_columns, parse_factors
from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.matrix import coded_as_run, expand
from orchestrator.optimize.synthetic import _choice, _numeric


def _res3_collapsed():
    fs = parse_factors([_choice("C", levels=("a", "b", "c"))]
                       + [_numeric(x, levels=(2, 16)) for x in "ABDE"])
    d = mixed_screen(fs, resolution=3, center_points=4)
    rows = expand(d, fs)
    run, _ = coded_as_run(d, fs, [r.levels for r in rows])
    return fs, d, rows, run


def test_M1_curvature_is_not_reported_as_a_categorical_or_an_interaction():
    """C 3 levels + A,B,D,E at resolution III, 4 centres; every corner 0,
    every centre +1 (pure curvature). Before: C F ~ 1e3-4e4, p < 0.001, and
    AB/AD/AE 'significant', lack of fit untestable (p None). After: C and the
    2fi are significant at about alpha, and lack of fit rejects every time."""
    _fs, _d, rows, run = _res3_collapsed()
    n, c_sig, ab_sig, lof = 200, 0, 0, 0
    for s in range(n):
        rng = random.Random(s)
        ys = [(1.0 if r.role == "center" else 0.0) + rng.gauss(0, 0.05) for r in rows]
        fit = fit_effects(run, ys, factor_ids=run.factor_ids,
                          omit_terms=non_estimable_terms(run))
        c_sig += bool(factor_test(fit, "C").significant)
        ab_sig += any(e.significant for e in fit.effects if len(e.terms) == 2)
        lof += (fit.lack_of_fit_p is not None and fit.lack_of_fit_p < 0.05)
    assert c_sig / n <= 0.10, c_sig
    assert ab_sig / n <= 0.15, ab_sig
    assert lof == n


def test_M1_a_2fi_in_the_span_of_kept_columns_on_the_corners_is_not_fitted():
    _fs, _d, rows, run = _res3_collapsed()
    ys = [0.0] * len(rows)
    ys[0] = 1.0
    fit = fit_effects(run, [y + 0.01 * i for i, y in enumerate(ys)],
                      factor_ids=run.factor_ids)
    fitted = {e.terms for e in fit.effects}
    for terms, spanning in fit.span_aliased:
        assert terms not in fitted and spanning
    assert {("A", "D"), ("A", "E")} <= {t for t, _ in fit.span_aliased}
    assert all(lab.startswith(("AD", "AE", "BD", "BE", "C[")) or "span(" in b
               for lab, b in fit.aliases if "span(" in b)


def test_M6_fit_aliases_on_a_resolution_V_four_level_campaign_are_empty(tmp_path):
    from tests.test_optimize_categorical_oracles import four_levels_x_numeric

    res = run_synthetic_campaign(four_levels_x_numeric(), seed=1, parent_dir=tmp_path)
    eff = json.loads((res.work_dir / "runs" / "iter-2" / "effects.json").read_text())
    assert eff["aliases"] == []
    rec = json.loads((res.work_dir / "runs" / "iter-2" / "recommendation.json").read_text())
    assert rec["aliases"] == [] and rec["alias_consequential"] == []
    cols = set(model_columns(parse_factors([dict(f) for f in four_levels_x_numeric().factors])[2]))
    for e in eff["effects"]:
        for t in e["terms"]:
            assert "[" not in t or t in cols, t


def _two_choices_under_curvature():
    from orchestrator.optimize.synthetic import Surface

    return Surface(
        name="two_choices_under_curvature", noise_sd=0.05,
        factors=(_numeric("A"), _numeric("B"), _choice("P"), _choice("Q")),
        fn=lambda lv: (20 - 0.05 * ((lv["A"] - 9) ** 2 + (lv["B"] - 9) ** 2)
                       + (1.0 if lv["P"] == "on" else 0.0)
                       + (-3.0 if lv["Q"] == "on" else 0.0)),
    )


def test_M2_two_held_choice_factors_do_not_use_the_confounded_centre_means(tmp_path):
    """P=on is worth +1 and Q=on -3. The diagonal centres run (off,off) and
    (on,on), whose means are 20 and 18, so a per-factor centre mean would hold
    P at OFF. Corner marginals are not confounded: P=on, Q=off."""
    res = run_synthetic_campaign(_two_choices_under_curvature(), seed=1,
                                 parent_dir=tmp_path)
    dm = None
    for p in sorted(res.work_dir.glob("runs/iter-*/design_matrix.json")):
        d = json.loads(p.read_text())
        if any(r.get("role") == "axial" for r in d.get("rows", [])):
            dm = d
    assert dm is not None, res.path
    assert dm["held_fixed"] == {"P": "on", "Q": "off"}
    assert dm["held_fixed_basis"] == {"P": "corner_marginal", "Q": "corner_marginal"}
    assert dm["centre_mean_confounded_with"] == {"P": ["Q"], "Q": ["P"]}
    assert res.recommendation == {"A": 9, "B": 9, "P": "on", "Q": "off"}


def test_M3_a_full_foldover_of_a_mixed_res_III_screen_leaves_2fi_main_aliasing():
    """Read off the combined matrix: the full fold kills odd words only, and
    C[12] is a product of two pseudo-columns."""
    from orchestrator.optimize.design import alias_pairs, combine, foldover

    fs = parse_factors([_choice("C", levels=("a", "b", "c", "d"))]
                       + [_numeric(x, levels=(2, 16)) for x in "ABDE"])
    d = mixed_screen(fs, resolution=3, center_points=0)
    mains = {c for f in fs for c in (["C[1]", "C[2]", "C[12]"] if f.id == "C" else [f.id])}
    left = alias_pairs(combine(d, foldover(d)))
    assert any(b in mains for _a, b in left), left


def test_M3_validator_refuses_mixed_res_III_with_the_foldover_on():
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.synthetic import Surface
    from orchestrator.validate import validate_optimization_campaign

    s = Surface(name="m3", factors=(_numeric("A"), _choice("C", ("a", "b", "c"))),
                fn=lambda lv: 0.0)
    c = synthetic_campaign(s)
    c["optimization"]["design"]["screen"]["resolution"] = 3
    hard = [e for e in validate_optimization_campaign(c) if not e.startswith("WARN")]
    assert any("foldover" in e and "resolution 4" in e for e in hard), hard
    c["optimization"]["policy"] = {"foldover": False}
    hard = [e for e in validate_optimization_campaign(c) if not e.startswith("WARN")]
    assert not any("policy.foldover" in e for e in hard)


def test_M3_M12_the_fold_block_records_its_basis_and_what_it_leaves(tmp_path):
    """Drive the foldover state on a mixed resolution-IV screen and read the
    registered fold block."""
    from orchestrator.optimize.stage_runner import _fold_on_basis

    fs = parse_factors([_choice("C", levels=("a", "b", "c", "d"))]
                       + [_numeric(x, levels=(2, 16)) for x in "ABD"])
    cfg = {"screen": {"resolution": 4, "center_points": 2}}
    assert _fold_on_basis(fs, cfg, [("C[12]A", "BD")]) == ("A", "single_column")
    assert _fold_on_basis(fs, cfg, [("C[12]C[1]", "zz")])[1] in ("single_column",
                                                                  "full_fallback")
    assert _fold_on_basis(fs, cfg, [("??", "!!")]) == (None, "full_fallback")


def test_T6_fold_on_a_pseudo_column_breaks_the_consequential_word():
    from orchestrator.optimize.design import alias_pairs, combine, foldover
    from orchestrator.optimize.stage_runner import _fold_on

    fs = parse_factors([_choice("C", levels=("a", "b", "c", "d"))]
                       + [_numeric(x, levels=(2, 16)) for x in "ABDE"])
    d = mixed_screen(fs, resolution=4, center_points=0)
    pairs = alias_pairs(d)
    cat_pair = next(p for p in pairs if p[0].startswith("C[") and p[1].startswith("C["))  \
        if any(p[0].startswith("C[") and p[1].startswith("C[") for p in pairs) else None
    target = cat_pair or next(p for p in pairs if "C[" in p[0] or "C[" in p[1])
    on = _fold_on(fs, {"screen": {"resolution": 4}}, [target])
    assert on is not None and on in d.factor_ids
    left = alias_pairs(combine(d, foldover(d, on=on)))
    assert tuple(target) not in {tuple(p) for p in left}, (target, on, left)


def test_M4_the_level_space_full_factorial_is_used_when_no_larger():
    """Three 3-level choices and a 2-level numeric (the finetune example):
    the replacement fraction at resolution V is 128 corners, the level-space
    full factorial 54 -- and it aliases nothing."""
    from orchestrator.optimize.design import alias_pairs, mixed_screen_options

    fs = parse_factors([_choice(x, levels=("p", "q", "r")) for x in ("O", "S", "P")]
                       + [_numeric("B", levels=(2, 16))])
    assert mixed_screen_options(fs, 5) == {"replacement": 128, "level_full": 54,
                                           "chosen": "level_full"}
    d = mixed_screen(fs, resolution=5, center_points=0)
    rows = expand(d, fs)
    assert len(rows) == 54 and d.kind == "mixed_level_full"
    combos = {tuple(r.levels[f.id] for f in fs) for r in rows}
    assert len(combos) == 54 and alias_pairs(d) == []


def test_M4_preview_and_validator_say_which_screen_and_why():
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.preview import build_preview, format_preview
    from orchestrator.optimize.synthetic import Surface
    from orchestrator.validate import validate_optimization_campaign

    s = Surface(name="m4", fn=lambda lv: 0.0,
                factors=tuple(_choice(x, levels=("p", "q", "r")) for x in ("O", "S", "P"))
                + (_numeric("B", levels=(2, 16)),))
    c = synthetic_campaign(s)
    text = "\n".join(format_preview(build_preview(c, noise_sd=0.1, mean=1.0,
                                                  run_secs=[1.0])))
    assert "LEVEL-SPACE full factorial (54 runs" in text and "128" in text
    assert any("level-space full factorial (54 runs" in e
               for e in validate_optimization_campaign(c))


@pytest.mark.parametrize("lost, expect", [("arc", "lfu"), ("lfu", "arc")])
def test_M5_a_categorical_that_loses_a_level_is_refitted_not_aborted(tmp_path, lost, expect):
    """Every run at one level fails. Before: the campaign aborted ('cannot
    support even a main-effects-only model'). After: fitted on the remaining
    levels, the lost level recorded and never recommended -- even when it is
    the truly best level."""
    import dataclasses

    from tests.test_optimize_categorical_oracles import middle_level_best

    s = dataclasses.replace(middle_level_best(), fails_at=lambda lv: lv["POL"] == lost)
    res = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path)
    assert not any(str(p).startswith("aborted") for p in res.path), res.path
    assert res.recommendation.get("POL") == expect
    fx = json.loads((res.work_dir / "runs" / "iter-2" / "fit_exclusions.json").read_text())
    assert fx["lost_levels"] == {"POL": [lost]}
    rec = json.loads((res.work_dir / "runs" / "iter-2" / "recommendation.json").read_text())
    assert rec["lost_levels"] == {"POL": [lost]}
    assert all(c["levels"]["POL"] != lost for c in rec["top_candidates"])


def test_M5_a_level_inadmissible_wherever_measured_is_recorded_and_never_named(tmp_path):
    from tests.test_optimize_categorical_oracles import five_levels_with_constraint

    s = five_levels_with_constraint()
    res = run_synthetic_campaign(
        s, seed=1, parent_dir=tmp_path,
        campaign_overrides={"response": {
            "primary": {"metric": "m", "direction": "maximize"},
            "constraints": [dict(c) for c in s.constraints]}})
    rec = json.loads((res.work_dir / "runs" / "iter-2" / "recommendation.json").read_text())
    assert rec["inadmissible_levels"] == {"C": ["c3"]}
    assert all(c["levels"]["C"] != "c3" for c in rec["top_candidates"])


def test_M7_planned_aliases_the_fit_separated_are_reported_with_their_inflation():
    from orchestrator.optimize.design import alias_pairs
    from orchestrator.optimize.effects import planned_aliases_separated

    fs = parse_factors([_choice("C", levels=("a", "b", "c"))]
                       + [_numeric(x, levels=(2, 16)) for x in "ABDE"])
    d = mixed_screen(fs, resolution=4, center_points=4, allow_level_full=False)
    rows = expand(d, fs)
    run, _ = coded_as_run(d, fs, [r.levels for r in rows])
    rng = random.Random(0)
    fit = fit_effects(run, [rng.gauss(0, 1) for _ in rows], factor_ids=run.factor_ids)
    sep = planned_aliases_separated(alias_pairs(d), fit)
    assert {tuple(s["planned"]) for s in sep} == {("C[1]A", "BE"), ("C[1]B", "AE"),
                                                  ("C[1]E", "AB")}
    assert all(v > 1.0 for s in sep for v in s["variance_inflation"].values())


def test_M7_effects_json_carries_the_separated_planned_aliases(tmp_path):
    from orchestrator.optimize.synthetic import Surface

    s = Surface(name="m7", noise_sd=0.05,
                factors=(_choice("C", levels=("a", "b", "c")),)
                + tuple(_numeric(x, levels=(2, 16)) for x in "ABDE"),
                fn=lambda lv: 1.0 + 0.1 * lv["A"] + (1.0 if lv["C"] == "b" else 0.0))
    res = run_synthetic_campaign(
        s, seed=1, parent_dir=tmp_path,
        campaign_overrides={"stages": ["verify", "screen", "confirm"],
                            "design": {"screen": {"resolution": 4, "center_points": 4},
                                       "confirm": {"replicates": 3}},
                            "policy": {"foldover": False}})
    eff = json.loads((res.work_dir / "runs" / "iter-2" / "effects.json").read_text())
    assert {tuple(x["planned"]) for x in eff["planned_aliases_separated"]} >= {("C[1]A", "BE")}


def test_M8_untested_curvature_levels_are_recorded_and_adequacy_is_unknown(tmp_path):
    """3 levels, 4 centre points: two centre configurations (lru, lfu), so the
    curvature check never looks under arc. Before: model_adequate True and no
    record. After: recorded in effects.json and recommendation.json, and
    model_adequate is null (unknown)."""
    from tests.test_optimize_categorical_oracles import middle_level_best

    res = run_synthetic_campaign(middle_level_best(bowl=False), seed=1,
                                 parent_dir=tmp_path,
                                 campaign_overrides={"stages": ["verify", "screen", "confirm"]})
    eff = json.loads((res.work_dir / "runs" / "iter-2" / "effects.json").read_text())
    rec = json.loads((res.work_dir / "runs" / "iter-2" / "recommendation.json").read_text())
    assert eff["curvature_untested_levels"] == {"POL": ["arc"]}
    assert rec["curvature_untested_levels"] == {"POL": ["arc"]}
    assert rec["model_adequate"] is None
    assert res.recommendation.get("POL") == "lfu"


def test_M8_full_coverage_keeps_model_adequate_true(tmp_path):
    from tests.test_optimize_categorical_oracles import middle_level_best

    res = run_synthetic_campaign(
        middle_level_best(bowl=False), seed=1, parent_dir=tmp_path,
        campaign_overrides={"stages": ["verify", "screen", "confirm"],
                            "design": {"screen": {"resolution": 5, "center_points": 6},
                                       "confirm": {"replicates": 3}}})
    rec = json.loads((res.work_dir / "runs" / "iter-2" / "recommendation.json").read_text())
    assert "curvature_untested_levels" not in rec and rec["model_adequate"] is True


def test_M9_a_minimize_campaign_names_the_LOWEST_ls_mean_level(tmp_path):
    import dataclasses

    from tests.test_optimize_categorical_oracles import middle_level_best

    s = dataclasses.replace(middle_level_best(bowl=False), direction="minimize")
    res = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path,
                                 campaign_overrides={"stages": ["verify", "screen", "confirm"]})
    f = json.loads((res.work_dir / "runs" / "iter-2" / "findings.json").read_text())
    arm = next(a for a in f["arms"] if a["metadata"].get("label") == "POL")
    assert arm["metadata"]["best_level"] == "lru"          # effects lru 0 < arc 1 < lfu 2
    p = json.loads((res.work_dir / "runs" / "iter-2" / "principle_updates.json").read_text())
    st = next(x["statement"] for x in p if x["id"].endswith("-POL"))
    assert "'lru'" in st and "lowest" in st
    assert res.recommendation.get("POL") == "lru"


def _write_runs(tmp_path, rows):
    it = tmp_path / "runs" / "iter-1"
    it.mkdir(parents=True)
    (it / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return tmp_path


def _centre_row(c, y):
    return {"status": "complete", "role": "center", "levels": {"C": c},
            "response": {"m": y}}


def test_T8_the_centre_mean_rule_respects_minimize(tmp_path):
    from orchestrator.optimize.stage_runner import _centre_mean_best

    fs = parse_factors([_choice("C")])
    wd = _write_runs(tmp_path, [_centre_row("off", 5.0), _centre_row("on", 3.0),
                                _centre_row("off", 5.2), _centre_row("on", 3.1)])
    assert _centre_mean_best(wd, 1, fs, "m", "minimize") == {"C": "on"}
    assert _centre_mean_best(wd, 1, fs, "m", "maximize") == {"C": "off"}


def test_T11_a_level_missing_a_centre_row_falls_back(tmp_path):
    from orchestrator.optimize.stage_runner import _centre_mean_best

    fs = parse_factors([_choice("C", levels=("a", "b", "c"))])
    wd = _write_runs(tmp_path, [_centre_row("a", 5.0), _centre_row("b", 9.0)])
    assert _centre_mean_best(wd, 1, fs, "m", "maximize") == {}


def test_M10_a_construction_failure_in_the_validator_is_surfaced_not_swallowed(monkeypatch):
    from orchestrator.optimize import design as design_mod
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.validate import validate_optimization_campaign
    from tests.test_optimize_categorical_oracles import middle_level_best

    c = synthetic_campaign(middle_level_best())
    c["optimization"]["design"]["max_runs"] = 10

    def boom(*a, **k):
        raise RuntimeError("construction bug")

    monkeypatch.setattr(design_mod, "mixed_screen", boom)
    with pytest.raises(RuntimeError, match="construction bug"):
        validate_optimization_campaign(c)


def _lo_campaign(**over):
    from orchestrator.optimize.harness import synthetic_campaign
    from tests.test_optimize_levels_only import _surface

    c = synthetic_campaign(_surface(levels_only=True))
    c["optimization"]["factors"][0].update(over)
    return c


def test_M11_preview_and_validator_name_the_levels_a_narrow_screen_pair_never_runs():
    from orchestrator.optimize.preview import build_preview, format_preview
    from orchestrator.validate import validate_optimization_campaign

    c = _lo_campaign(screen_levels=[32, 512])
    text = "\n".join(format_preview(build_preview(c, noise_sd=0.2, mean=100.0,
                                                  run_secs=[1.0])))
    assert "runnable set [32, 64, 128, 256, 512]" in text
    assert "NEVER run: [16, 1024]" in text
    assert any(e.startswith("WARN") and "[16, 1024]" in e
               for e in validate_optimization_campaign(c))


def test_T9_levels_only_with_a_narrow_screen_pair_never_runs_outside_it(tmp_path):
    from tests.test_optimize_levels_only import _all_levels, _surface

    s = _surface(levels_only=True)
    s.factors[0]["screen_levels"] = [32, 512]
    res = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path)
    assert _all_levels(res.work_dir, "N") <= {32, 64, 128, 256, 512}
    assert res.recommendation["N"] == 256


def test_T9_two_runnable_levels_while_refinable_omits_the_quadratic(tmp_path):
    """levels [16, 64, 1024] screened at [16, 64]: refinable (3 levels) but only
    two runnable inside the pair -- the quadratic is omitted, nothing crashes."""
    from tests.test_optimize_levels_only import _surface

    s = _surface(levels_only=True)
    s.factors[0].update(levels=[16, 64, 1024], screen_levels=[16, 64])
    res = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path)
    assert not any(str(p).startswith("aborted") for p in res.path), res.path
    effs = [json.loads(p.read_text()) for p in res.work_dir.glob("runs/iter-*/effects.json")]
    refine = [e for e in effs if e["stage"] == "refine"]
    assert refine and ["N", "N"] in refine[0].get("omitted_terms", [])
    assert res.recommendation["N"] in (16, 64)


# ── T3: centre cycling for multi-level categoricals ─────────────────────────


def _centres(Ls_choice, n_c, extra_two_level=0):
    from orchestrator.optimize.matrix import centre_points_record

    raw = [_numeric("A", levels=(2, 16))]
    raw += [_choice(f"C{i}", levels=tuple(f"l{j}" for j in range(L)))
            for i, L in enumerate(Ls_choice)]
    fs = parse_factors(raw)
    d = mixed_screen(fs, resolution=5, center_points=n_c) if any(
        L > 2 for L in Ls_choice) else None
    if d is None:
        from orchestrator.optimize.design import full_factorial, with_center_points
        d = with_center_points(full_factorial([f.id for f in fs]), n_c)
    return centre_points_record(d, fs)


def test_T3_three_levels_six_centres_two_each():
    rec = _centres([3], 6)
    assert rec["per_level"]["C0"] == {"l0": 2, "l1": 2, "l2": 2}
    assert rec["configurations"] == 3 and rec["pure_error_df"] == 3
    assert rec["warnings"] == []


def test_T3_five_levels_four_centres_covers_two_and_warns():
    rec = _centres([5], 4)
    assert rec["per_level"]["C0"] == {"l0": 2, "l1": 2, "l2": 0, "l3": 0, "l4": 0}
    assert rec["configurations"] == 2 and rec["pure_error_df"] == 2
    assert len(rec["warnings"]) == 1 and "'l2', 'l3', 'l4'" in rec["warnings"][0]


@pytest.mark.parametrize("n_c, cfgs, c0, c1", [
    (4, 2, {"l0": 2, "l1": 2, "l2": 0}, {"off": 2, "on": 2}),
    (12, 6, {"l0": 4, "l1": 4, "l2": 4}, {"off": 6, "on": 6}),
])
def test_T3_three_levels_with_a_two_level_choice(n_c, cfgs, c0, c1):
    """Balance is per CONFIGURATION: (L=3, L=2) cycle with period lcm = 6."""
    from orchestrator.optimize.matrix import centre_points_record

    fs = parse_factors([_numeric("A", levels=(2, 16)),
                        _choice("C0", levels=("l0", "l1", "l2")), _choice("C1")])
    rec = centre_points_record(mixed_screen(fs, resolution=5, center_points=n_c), fs)
    assert rec["configurations"] == cfgs
    assert rec["per_level"] == {"C0": c0, "C1": c1}


# ── T7: the INV-STAT14 checker's mixed branch ───────────────────────────────


def test_T7_the_fit_coordinates_invariant_catches_a_corrupted_contrast_cell(tmp_path):
    from orchestrator.optimize.invariants import check_fit_coordinates_are_actual
    from tests.test_optimize_categorical_oracles import middle_level_best

    res = run_synthetic_campaign(middle_level_best(bowl=False), seed=1,
                                 parent_dir=tmp_path,
                                 campaign_overrides={"stages": ["verify", "screen", "confirm"]})
    eff = json.loads((res.work_dir / "runs" / "iter-2" / "effects.json").read_text())
    fc = eff["fit_coordinates"]
    rows = [json.loads(ln)["levels"] for ln in
            (res.work_dir / "runs" / "iter-2" / "runs.jsonl").read_text().splitlines()
            if ln.strip()]
    by_idx = {}
    for ln in (res.work_dir / "runs" / "iter-2" / "runs.jsonl").read_text().splitlines():
        if ln.strip():
            r = json.loads(ln)
            by_idx[r["row_index"]] = r["levels"]
    levels_rows = [by_idx[i] for i in sorted(by_idx)]
    fs = parse_factors([dict(f) for f in middle_level_best(bowl=False).factors])
    assert check_fit_coordinates_are_actual(fc, levels_rows, fs) == []
    j = fc["factor_ids"].index("POL[2]")
    fc["rows"][0]["fitted"][j] = -fc["rows"][0]["fitted"][j]
    errs = check_fit_coordinates_are_actual(fc, levels_rows, fs)
    assert len(errs) == 1 and "POL[2]" in errs[0]
    assert rows


# ── T10: the search above the cap, with a constraint and with objectives ────


def test_T10_the_searched_space_still_finds_c4_under_the_constraint(tmp_path, monkeypatch):
    from orchestrator.optimize import decide
    from tests.test_optimize_categorical_oracles import five_levels_with_constraint

    monkeypatch.setattr(decide, "CANDIDATE_CAP", 1)
    s = five_levels_with_constraint()
    res = run_synthetic_campaign(
        s, seed=1, parent_dir=tmp_path,
        campaign_overrides={"response": {
            "primary": {"metric": "m", "direction": "maximize"},
            "constraints": [dict(c) for c in s.constraints]}})
    rec = json.loads((res.work_dir / "runs" / "iter-2" / "recommendation.json").read_text())
    assert rec["candidate_space"]["exhaustive"] is False
    assert res.recommendation.get("C") == "c4"


def test_T10_the_searched_space_keeps_the_middle_level_on_the_front(tmp_path, monkeypatch):
    from orchestrator.optimize import decide
    from orchestrator.optimize.harness import evaluate_pareto_campaign
    from tests.test_optimize_categorical_oracles import three_level_front

    monkeypatch.setattr(decide, "CANDIDATE_CAP", 1)
    m = evaluate_pareto_campaign(three_level_front(), seed=1, parent_dir=tmp_path)
    front = json.loads((m["work_dir"] / "report.json").read_text())["pareto"]["front"]
    assert "q" in {f["levels"]["C"] for f in front}
    assert m["n_confident_off_front"] == 0 and not m["false_certified"]


# ── T12: levels_only linear tie ─────────────────────────────────────────────


def test_T12_a_linear_tie_goes_to_the_lower_level():
    from orchestrator.optimize.factors import decode_coded

    raw = _numeric("N", levels=(10, 20, 40), grid=None)
    raw.pop("grid")
    raw.update(levels_only=True, scale="linear")
    f = parse_factors([raw])[0]
    # linear: mid 25, half 15; coded 0.333.. -> 30, equidistant from 20 and 40.
    assert decode_coded(f, 1.0 / 3.0) == 20
    assert decode_coded(f, 1.0 / 3.0 + 1e-6) == 40


def test_docs_preview_states_the_categorical_level_comparison_se():
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.preview import build_preview, format_preview
    from tests.test_optimize_categorical_oracles import five_knobs_with_a_categorical

    c = synthetic_campaign(five_knobs_with_a_categorical())
    text = "\n".join(format_preview(build_preview(c, noise_sd=0.1, mean=12.0,
                                                  run_secs=[1.0])))
    # 32 corners, L = 3: sqrt(6 / 32) = 0.433
    assert "POL (3 levels)" in text and "0.433 sd" in text
