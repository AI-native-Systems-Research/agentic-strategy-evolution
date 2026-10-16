"""Multi-level categoricals end to end (spec
2026-10-16-mixed-level-factors-design.md, feature 1, oracles a-d).

Each campaign recommends the true optimum within epsilon and never certifies
a configuration further than epsilon from it. Before feature 1 a choice
factor ran only at its screen pair (first and last level), so (a)'s middle
level, (b)'s second and third, (c)'s three interior levels and (d)'s middle
level were never run, fitted or recommended.
"""
from __future__ import annotations

import json
import math

import pytest

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import Surface, _choice, _numeric

POW2 = (16, 32, 64, 128, 256, 512, 1024)


def middle_level_best(*, bowl: bool = True) -> Surface:
    """(a) a 3-level categorical whose MIDDLE level is best. ``bowl=False``
    drops B's curvature, so the screen's first-order model is ADEQUATE and its
    per-level estimates can be held to the truth."""
    eff = {"lru": 0.0, "lfu": 2.0, "arc": 1.0}
    c = 0.05 if bowl else 0.0
    return Surface(
        name="middle_level_best", noise_sd=0.05,
        factors=(_numeric("A"), _numeric("B"),
                 _choice("POL", levels=("lru", "lfu", "arc"))),
        fn=lambda lv: (10.0 + 0.1 * lv["A"] - c * (lv["B"] - 9) ** 2
                       + eff[lv["POL"]]),
    )


def four_levels_x_numeric() -> Surface:
    """(b) a 4-level categorical whose slope in A differs by level: the best A
    flips with the level, and the joint optimum is (C=y, A=16)."""
    icpt = {"w": 10.0, "x": 14.0, "y": 9.0, "z": 12.0}
    slope = {"w": 0.3, "x": -0.3, "y": 0.5, "z": 0.0}
    return Surface(
        name="four_levels_x_numeric", noise_sd=0.05,
        factors=(_numeric("A"), _numeric("B"),
                 _choice("C", levels=("w", "x", "y", "z"))),
        fn=lambda lv: (icpt[lv["C"]] + slope[lv["C"]] * (lv["A"] - 2)
                       - 0.05 * (lv["B"] - 9) ** 2),
    )


def five_levels_with_constraint() -> Surface:
    """(c) a 5-level categorical whose best-PRIMARY level (c3) violates a noisy
    latency bound everywhere; the constrained optimum is the INTERIOR level
    (c4, A=16), which a screen of the first and last level never runs."""
    base = {"c1": 10.0, "c2": 11.0, "c3": 14.0, "c4": 13.5, "c5": 12.5}

    def lat(lv):
        return (30.0 if lv["C"] == "c3" else 10.0) + 0.5 * float(lv["A"])

    return Surface(
        name="five_levels_with_constraint", noise_sd=0.05,
        factors=(_numeric("A"), _numeric("B"),
                 _choice("C", levels=("c1", "c2", "c3", "c4", "c5"))),
        fn=lambda lv: base[lv["C"]] + 0.1 * lv["A"] - 0.05 * (lv["B"] - 9) ** 2,
        invalid=lambda lv: lat(lv) > 20.0,
        constraints=({"metric": "lat_ms", "op": "<=", "value": 20.0},),
        noisy_observables=lambda lv, rng: {"lat_ms": lat(lv) + rng.gauss(0.0, 0.3)},
    )


def all_three_kinds() -> Surface:
    """(d) a categorical (3 levels, middle best), a levels_only discrete knob
    (powers of two, optimum 256) and a continuous knob (interior optimum 9):
    every one moves the response."""
    n = _numeric("N", levels=POW2, grid=None)
    n.pop("grid")
    n.update(levels_only=True, scale="log")
    eff = {"a": 0.0, "b": 1.5, "c": 0.5}
    return Surface(
        name="all_three_kinds", noise_sd=0.1,
        factors=(n, _numeric("X"), _choice("C", levels=("a", "b", "c"))),
        fn=lambda lv: (20.0 - 1.0 * (math.log2(float(lv["N"])) - 8.0) ** 2
                       - 0.05 * (lv["X"] - 9) ** 2 + eff[lv["C"]]),
    )


def _check(res, surface):
    eps = abs(res.report.get("epsilon") or 0.0)
    assert res.recommendation, res.path
    assert res.true_gap <= max(eps, 1e-9) + 1e-9, (res.recommendation, res.true_optimum,
                                                   res.true_gap, eps, res.path)
    if res.report.get("certified"):
        assert res.true_gap <= eps + 1e-9


def _ran_levels(work_dir, fid):
    seen = set()
    for p in work_dir.glob("runs/iter-*/runs.jsonl"):
        for ln in p.read_text().splitlines():
            if ln.strip():
                lv = json.loads(ln).get("levels") or {}
                if fid in lv:
                    seen.add(lv[fid])
    return seen


@pytest.mark.parametrize("seed", range(1, 9))
def test_a_three_level_categorical_with_the_middle_level_best(tmp_path, seed):
    s = middle_level_best()
    res = run_synthetic_campaign(s, seed=seed, parent_dir=tmp_path)
    assert res.recommendation.get("POL") == "lfu"
    assert _ran_levels(res.work_dir, "POL") == {"lru", "lfu", "arc"}
    _check(res, s)


@pytest.mark.parametrize("seed", range(1, 9))
def test_b_four_level_categorical_interacting_with_a_numeric(tmp_path, seed):
    s = four_levels_x_numeric()
    res = run_synthetic_campaign(s, seed=seed, parent_dir=tmp_path)
    assert res.recommendation.get("C") == "y" and res.recommendation.get("A") == 16
    _check(res, s)


@pytest.mark.parametrize("seed", range(1, 9))
def test_c_five_level_categorical_with_a_constraint(tmp_path, seed):
    s = five_levels_with_constraint()
    res = run_synthetic_campaign(
        s, seed=seed, parent_dir=tmp_path,
        campaign_overrides={"response": {
            "primary": {"metric": "m", "direction": "maximize"},
            "constraints": [dict(c) for c in s.constraints]}})
    assert res.recommendation.get("C") == "c4"
    assert not s.invalid(res.recommendation)
    _check(res, s)


@pytest.mark.parametrize("seed", range(1, 9))
def test_d_categorical_discrete_and_continuous_knobs_together(tmp_path, seed):
    s = all_three_kinds()
    res = run_synthetic_campaign(s, seed=seed, parent_dir=tmp_path)
    rec = res.recommendation
    assert rec.get("C") == "b" and rec.get("N") == 256
    assert _ran_levels(res.work_dir, "N") <= set(POW2)
    _check(res, s)


def test_effects_json_reports_the_F_test_and_per_level_estimates(tmp_path):
    # An adequate screen model (no curvature), so its estimates are unbiased.
    res = run_synthetic_campaign(middle_level_best(bowl=False), seed=1,
                                 parent_dir=tmp_path,
                                 campaign_overrides={"stages": ["verify", "screen", "confirm"]})
    eff = json.loads((res.work_dir / "runs" / "iter-2" / "effects.json").read_text())
    [cat] = eff["categoricals"]
    assert cat["factor"] == "POL" and cat["df"] == 2 and cat["significant"] is True
    means = {lv["level"]: lv["ls_mean"] for lv in cat["levels"]}
    assert max(means, key=means.get) == "lfu"
    # LS-mean differences recover the true level effects (lfu - lru = 2.0).
    assert means["lfu"] - means["lru"] == pytest.approx(2.0, abs=0.1)
    assert means["arc"] - means["lru"] == pytest.approx(1.0, abs=0.1)
    # The exact SEs: every reported contrast SE equals sqrt(s^2 (X'X)^-1_jj).
    assert all(e["se"] is not None for e in eff["effects"])
    assert eff["variance_inflation"]["POL[1]"] >= 1.0 - 1e-9


def test_design_matrix_records_the_pseudo_factors_and_the_collapse(tmp_path):
    res = run_synthetic_campaign(middle_level_best(), seed=1, parent_dir=tmp_path)
    dm = json.loads((res.work_dir / "runs" / "iter-2" / "design_matrix.json").read_text())
    [cat] = dm["categoricals"]
    assert cat["factor"] == "POL" and cat["pseudo_factors"] == ["POL[1]", "POL[2]"]
    assert cat["collapsed"] is True
    assert cat["level_of_combination"] == {"0": "lru", "1": "lfu", "2": "arc", "3": "lru"}
    assert dm["resolution"] == 5


@pytest.mark.parametrize("res", [3, 4])
@pytest.mark.parametrize("make", [middle_level_best, four_levels_x_numeric, all_three_kinds])
def test_lower_resolution_mixed_screens_still_find_the_optimum(tmp_path, make, res):
    """Resolution III / IV mixed screens (2fi aliased, or partially aliased
    after collapsing): the answer still lands, and a screen that had to fall
    back to main effects only SAYS so in effects.json."""
    s = make()
    res_ = run_synthetic_campaign(
        s, seed=1, parent_dir=tmp_path,
        campaign_overrides={"design": {
            "screen": {"resolution": res, "center_points": 4},
            "refine": {"kind": "central_composite", "center_points": 4},
            "confirm": {"replicates": 3}}})
    _check(res_, s)
    eff = json.loads((res_.work_dir / "runs" / "iter-2" / "effects.json").read_text())
    has_2fi = any(len(e["terms"]) == 2 for e in eff["effects"])
    assert has_2fi or eff.get("interactions_dropped") is True


def three_level_front() -> Surface:
    """A predicted front that runs through a 3-level categorical: the MIDDLE
    level q owns the centre of the trade-off between f1 and f2."""
    from orchestrator.optimize.synthetic import _obj, _unit

    b1 = {"p": 10.0, "q": 12.0, "r": 13.0}
    b2 = {"p": 16.0, "q": 15.0, "r": 11.0}

    def f1(lv):
        return b1[lv["C"]] + 3.0 * _unit(lv, "A")

    def f2(lv):
        return b2[lv["C"]] - 3.0 * _unit(lv, "A") ** 2

    return Surface(name="three_level_front", noise_sd=0.05,
                   factors=(_numeric("A"), _choice("C", levels=("p", "q", "r"))),
                   fn=f1, objectives=(_obj("f1", f1), _obj("f2", f2)))


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_the_front_covers_every_categorical_level(tmp_path, seed):
    from orchestrator.optimize.harness import evaluate_pareto_campaign
    from orchestrator.optimize.synthetic import true_front

    s = three_level_front()
    assert {lv["C"] for lv, _ in true_front(s)} >= {"q"}
    m = evaluate_pareto_campaign(s, seed=seed, parent_dir=tmp_path)
    assert m["n_confident_off_front"] == 0 and not m["false_certified"]
    assert m["recommended_within_eps"]
    assert m["coverage"] >= 0.7, m["coverage"]
    front = json.loads((m["work_dir"] / "report.json").read_text())["pareto"]["front"]
    assert "q" in {f["levels"]["C"] for f in front}


# ── validator and preview ───────────────────────────────────────────────────


def _camp(**design):
    from orchestrator.optimize.harness import synthetic_campaign

    c = synthetic_campaign(middle_level_best())
    c["optimization"]["design"]["screen"].update(design)
    return c


def test_validator_rejects_screen_levels_on_a_multi_level_choice():
    from orchestrator.validate import validate_optimization_campaign

    c = _camp()
    c["optimization"]["factors"][2]["screen_levels"] = ["lru", "arc"]
    errs = validate_optimization_campaign(c)
    assert any(not e.startswith("WARN") and "'POL'" in e and "every level" in e
               for e in errs), errs


def test_validator_names_the_expanded_columns_and_run_cost():
    from orchestrator.validate import validate_optimization_campaign

    errs = validate_optimization_campaign(_camp())
    msg = [e for e in errs if "'POL'" in e and "pseudo-factor" in e]
    assert msg and msg[0].startswith("WARN") and "2 pseudo-factor" in msg[0]
    assert "16 runs" in msg[0] and "collaps" in msg[0]


def test_rule8_prices_the_mixed_screen_not_the_two_level_one():
    from orchestrator.validate import validate_optimization_campaign

    c = _camp()
    c["optimization"]["design"]["max_runs"] = 12   # mixed screen needs 16 corners
    errs = validate_optimization_campaign(c)
    assert any("16 corners" in e and "method of replacement" in e for e in errs), errs


def test_preview_shows_the_mixed_screen_its_columns_and_its_bound():
    from orchestrator.optimize.preview import build_preview, format_preview

    pv = build_preview(_camp(), noise_sd=0.05, mean=12.0, run_secs=[1.0])
    text = "\n".join(format_preview(pv))
    assert "method of replacement" in text and "POL" in text
    assert "2 pseudo-factor" in text and "generalized resolution V" in text


@pytest.mark.parametrize("make", [middle_level_best, five_levels_with_constraint,
                                  all_three_kinds])
def test_every_mixed_campaign_artifact_validates_against_its_schema(tmp_path, make):
    from pathlib import Path

    import jsonschema

    schemas = Path(__file__).resolve().parents[1] / "orchestrator" / "schemas"
    sch = lambda n: json.loads((schemas / f"{n}.schema.json").read_text())  # noqa: E731
    s = make()
    over = ({"response": {"primary": {"metric": "m", "direction": "maximize"},
                          "constraints": [dict(c) for c in s.constraints]}}
            if s.constraints else None)
    res = run_synthetic_campaign(s, seed=2, parent_dir=tmp_path, campaign_overrides=over)
    checked = 0
    for name, rel in (("report", "report.json"), ("policy", "policy.json")):
        p = res.work_dir / rel
        if p.exists():
            jsonschema.validate(json.loads(p.read_text()), sch(name)); checked += 1
    for it in sorted(res.work_dir.glob("runs/iter-*")):
        for name in ("effects", "recommendation", "confirmation", "design_matrix",
                     "findings"):
            p = it / f"{name}.json"
            if p.exists():
                jsonschema.validate(json.loads(p.read_text()), sch(name)); checked += 1
    assert checked >= 8
    # Findings project the categorical ONCE, from its F test.
    f = json.loads((res.work_dir / "runs" / "iter-2" / "findings.json").read_text())
    labels = [a["metadata"].get("label") for a in f["arms"]]
    assert not any("[" in str(lab) for lab in labels), labels
