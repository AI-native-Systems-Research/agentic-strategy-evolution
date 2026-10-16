"""``levels_only: true`` -- an ordered numeric knob that runs only at its
declared levels (spec 2026-10-16-mixed-level-factors-design.md, feature 2).

The oracle: a knob whose runnable values are the powers of two 16..1024 and
whose response peaks at 256. Declared as an ordinary ``numeric`` + ``grid: 1``
the candidate axis is nine interpolated points (16, 27, 45, 76, 128, 215,
362, 609, 1024) -- 256 is not among them -- so the campaign recommends a
value the knob does not take. Declared ``levels_only`` every value Nous ever
asks the target to run, and every value it recommends, is a declared level,
and the recommendation is 256.
"""
from __future__ import annotations

import math

import pytest

from orchestrator.optimize.factors import code_actual, decode_coded, is_refinable, parse_factors
from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import Surface, _numeric

POW2 = (16, 32, 64, 128, 256, 512, 1024)


def _raw(**kw) -> dict:
    f = _numeric("N", levels=POW2, grid=None)
    f.pop("grid")
    f.update(kw)
    return f


def _surface(*, levels_only: bool) -> Surface:
    n = _raw(scale="log", **({"levels_only": True} if levels_only else {"grid": 1}))
    return Surface(
        name="levels_only_pow2" if levels_only else "levels_only_pow2_gridded",
        noise_sd=0.2,
        factors=(n, _numeric("B")),
        fn=lambda lv: 100.0 - 3.0 * (math.log2(float(lv["N"])) - 8.0) ** 2
        + 0.2 * float(lv["B"]),
    )


def _all_levels(work_dir, fid):
    import json

    seen = set()
    for p in work_dir.glob("runs/iter-*/runs.jsonl"):
        for ln in p.read_text().splitlines():
            if ln.strip():
                lv = json.loads(ln).get("levels") or {}
                if fid in lv:
                    seen.add(lv[fid])
    return seen


# ── parsing and the coding seam ─────────────────────────────────────────────


def test_levels_only_is_parsed_and_stays_refinable():
    f = parse_factors([_raw(levels_only=True, scale="log")])[0]
    assert f.levels_only is True
    assert is_refinable(f)


def test_levels_only_with_grid_is_rejected():
    with pytest.raises(ValueError, match="levels_only.*grid|grid.*levels_only"):
        parse_factors([_raw(levels_only=True, grid=1)])


def test_levels_only_on_a_choice_factor_is_rejected():
    from orchestrator.optimize.synthetic import _choice

    raw = _choice("C", levels=("a", "b", "c"))
    raw["levels_only"] = True
    with pytest.raises(ValueError, match="levels_only"):
        parse_factors([raw])


def test_levels_only_rejects_duplicate_levels():
    with pytest.raises(ValueError, match="duplicate|distinct"):
        parse_factors([_raw(levels=[16, 32, 32, 64], levels_only=True)])


@pytest.mark.parametrize("coded, expected", [
    (0.0, 128),          # log-axis midpoint of [16, 1024] is 128
    (0.4, 256),          # log2 = 7 + 0.4*3 = 8.2 -> nearest declared is 2^8
    (0.5, 256),          # log2 = 8.5: a tie in log space goes to the LOWER level
    (1.68, 1024),        # an axial point past the cube clamps, then snaps
    (-1.41, 16),
])
def test_decode_coded_snaps_to_the_nearest_declared_level_in_log_space(coded, expected):
    f = parse_factors([_raw(levels_only=True, scale="log")])[0]
    got = decode_coded(f, coded)
    assert got == expected and type(got) is int


def test_decode_coded_snaps_in_linear_space_without_scale_log():
    f = parse_factors([_raw(levels=[64, 128, 256, 1024], levels_only=True,
                            scale="linear")])[0]
    # linear midpoint 544: |544-256| = 288 < |544-1024| = 480
    assert decode_coded(f, 0.0) == 256
    assert code_actual(f, 256) == pytest.approx((256 - 544) / 480)


def test_candidate_axis_is_exactly_the_declared_levels():
    from orchestrator.optimize.decide import _axis

    f = parse_factors([_raw(levels_only=True, scale="log")])[0]
    axis = _axis(f)
    assert [lv for _c, lv in axis] == list(POW2)
    assert [c for c, _lv in axis] == pytest.approx([code_actual(f, lv) for lv in POW2])


def test_refine_design_runs_only_declared_levels_and_codes_what_ran():
    from orchestrator.optimize.matrix import coded_as_run, expand
    from orchestrator.optimize.stage_runner import _build_design

    factors = parse_factors([_raw(levels_only=True, scale="log"), _numeric("B")])
    design = _build_design(factors, {"refine": {"center_points": 3}}, "refine")
    rows = expand(design, factors)
    assert {r.levels["N"] for r in rows} <= set(POW2)
    run, nominal = coded_as_run(design, factors, [r.levels for r in rows])
    assert nominal == []
    j = run.factor_ids.index("N")
    for p, r in zip(run.points, rows):
        assert p.coded[j] == pytest.approx(code_actual(factors[0], r.levels["N"]))


# ── the oracle ───────────────────────────────────────────────────────────────


def _truth():
    # Over the RUNNABLE set: N in POW2, B in its declared grid. B is monotone,
    # so the optimum is (256, 16).
    return {"N": 256, "B": 16}


@pytest.mark.parametrize("seed", range(1, 9))
def test_levels_only_recommends_the_declared_optimum_and_never_runs_off_set(tmp_path, seed):
    res = run_synthetic_campaign(_surface(levels_only=True), seed=seed,
                                 parent_dir=tmp_path)
    rec = res.recommendation
    assert rec.get("N") in POW2, rec
    assert rec["N"] == _truth()["N"]
    # Every value the campaign ever asked the target to run is runnable.
    assert _all_levels(res.work_dir, "N") <= set(POW2)
    # Never certifies a configuration off the true optimum by more than eps.
    fn = _surface(levels_only=True).fn
    gap = fn(_truth()) - fn(rec)
    if res.report.get("certified"):
        assert gap <= abs(res.report.get("epsilon") or 0.0) + 1e-9


def test_without_levels_only_the_recommendation_is_off_set(tmp_path):
    """The gap this feature closes, measured: the interpolated axis cannot
    contain 256, so an ordinary gridded numeric recommends a value the knob
    does not take on every seed."""
    off = 0
    for seed in range(1, 5):
        res = run_synthetic_campaign(_surface(levels_only=False), seed=seed,
                                     parent_dir=tmp_path / str(seed))
        off += res.recommendation.get("N") not in POW2
    assert off >= 1


# ── schema, validator, preview ──────────────────────────────────────────────


def _campaign(**factor_over):
    from orchestrator.optimize.harness import synthetic_campaign

    c = synthetic_campaign(_surface(levels_only=True))
    c["optimization"]["factors"][0].update(factor_over)
    c["optimization"]["factors"][0] = {
        k: v for k, v in c["optimization"]["factors"][0].items() if v is not None}
    return c


def test_schema_accepts_levels_only_and_rejects_a_non_boolean():
    from pathlib import Path

    import jsonschema
    import yaml

    schema = yaml.safe_load((Path(__file__).resolve().parents[1] / "orchestrator"
                             / "schemas" / "campaign.schema.yaml").read_text())
    jsonschema.validate(_campaign(), schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_campaign(levels_only="yes"), schema)


def test_validator_hard_errors_on_levels_only_with_grid():
    from orchestrator.validate import validate_optimization_campaign

    errs = validate_optimization_campaign(_campaign(grid=1))
    hard = [e for e in errs if not e.startswith("WARN") and "levels_only" in e]
    assert hard and "grid" in hard[0]


def test_validator_warns_on_levels_only_over_two_levels():
    from orchestrator.validate import validate_optimization_campaign

    errs = validate_optimization_campaign(_campaign(levels=[16, 1024]))
    assert any(e.startswith("WARN") and "levels_only" in e and "N" in e for e in errs)


def test_levels_only_silences_the_integer_levels_without_grid_warning():
    from orchestrator.validate import validate_optimization_campaign

    errs = validate_optimization_campaign(_campaign())
    assert not any("no grid" in e and "'N'" in e for e in errs), errs
    assert not any("levels_only" in e for e in errs), errs


def test_preview_names_the_runnable_set_of_a_levels_only_factor():
    from orchestrator.optimize.preview import build_preview, format_preview

    pv = build_preview(_campaign(), noise_sd=0.2, mean=100.0, run_secs=[1.0])
    text = "\n".join(format_preview(pv))
    assert "levels_only" in text and "1024" in text
