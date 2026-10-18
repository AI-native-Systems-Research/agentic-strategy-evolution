"""#321 P4 item 2: adequacy power beyond +-0.5 and at screen, Holm across the
adequacy tests, snapping, and V from the rows actually fitted.

Behavioral: real fits through the real seams (no LLM, no subprocess), and
synthetic campaigns through the harness, asserting on disk artifacts and on
measured rates.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pytest

from orchestrator.optimize import adequacy
from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import NON_QUADRATIC, SURFACES, Surface, _numeric


def _recs(work_dir: Path) -> list[dict]:
    paths = sorted((Path(work_dir) / "runs").glob("iter-*/recommendation.json"),
                   key=lambda p: int(p.parent.name.split("-")[1]))
    return [json.loads(p.read_text()) for p in paths]


def _dm(work_dir: Path, stage: str) -> dict:
    for d in sorted((Path(work_dir) / "runs").glob("iter-*")):
        e = d / "effects.json"
        if e.exists() and json.loads(e.read_text()).get("stage") == stage:
            return json.loads((d / "design_matrix.json").read_text())
    raise AssertionError(stage)


# ── snapping (WP-B limit 8) ──────────────────────────────────────────────────

def _coarse() -> Surface:
    """Both knobs levels_only {2, 8, 16}: coded +-0.5 and +-0.8 snap to -1, 0
    or +1 on BOTH axes, so every candidate's image is a composite point -- a
    validation run there would only re-measure a point the fit interpolates."""
    fs = []
    for k in "AB":
        a = _numeric(k, levels=(2, 8, 16), grid=None)
        a.pop("grid")
        a["levels_only"] = True
        fs.append(a)
    return Surface(name="coarse", noise_sd=0.05, factors=tuple(fs),
                   fn=lambda lv: 10 - 0.02 * (lv["A"] - 9) ** 2 - 0.03 * (lv["B"] - 10) ** 2)


def _half_coarse() -> Surface:
    a = _numeric("A", levels=(2, 8, 16), grid=None)
    a.pop("grid")
    a["levels_only"] = True
    return Surface(name="half_coarse", noise_sd=0.05, factors=(a, _numeric("B")),
                   fn=lambda lv: 10 - 0.02 * (lv["A"] - 9) ** 2 - 0.03 * (lv["B"] - 10) ** 2)


def test_validation_points_that_snap_onto_the_composite_are_declined_by_name(tmp_path):
    """Pre-P4 the coarse campaign registered 4 validation rows that ran AT
    composite points (+-0.5 on {2, 8, 16} snaps to the lattice), so its
    "validation check" re-measured interpolated configurations and could pass
    a refine against a screen rejection. Now nothing runs there: the
    registration names every declined candidate, the check is not computable
    (no_validation_point_runnable), and the verdict stays unresolved."""
    r = run_synthetic_campaign(_coarse(), seed=1, parent_dir=tmp_path)
    dm = _dm(r.work_dir, "refine")
    assert not [x for x in dm["rows"] if x["role"] == "validation"]
    v = dm["validation"]
    assert v["declined_reason"] == "every_candidate_snaps_onto_a_design_point"
    assert v["points_declined"] and all(
        d["reason"] == "snaps_onto_a_design_point" for d in v["points_declined"])
    rf = [x for x in _recs(r.work_dir) if x["stage"] == "refine"][-1]
    assert rf["model_adequacy"]["validation"]["reason"] == "no_validation_point_runnable"
    assert rf["model_adequacy"]["validation"]["rejected"] is None


def test_a_point_snapped_on_one_axis_runs_and_records_its_image(tmp_path):
    """A levels_only on A only: A's coordinate snaps to the lattice, B's does
    not, so the point is off the composite and runs; planned and as-run coded
    points are both registered, and no run sits on a composite point."""
    r = run_synthetic_campaign(_half_coarse(), seed=1, parent_dir=tmp_path)
    dm = _dm(r.work_dir, "refine")
    design = {tuple(row["levels"][k] for k in ("A", "B"))
              for row in dm["rows"] if row["role"] != "validation"}
    val = [tuple(row["levels"][k] for k in ("A", "B"))
           for row in dm["rows"] if row["role"] == "validation"]
    assert val and not (set(val) & design) and len(set(val)) == len(val)
    v = dm["validation"]
    assert len(v["as_run_coded"]) == len(v["planned_coded"]) == len(val)
    assert any(p != a for p, a in zip(v["planned_coded"], v["as_run_coded"]))


def test_validation_points_never_collapse_and_take_the_next_best():
    """Seam: a key that maps every point with first coordinate +0.5 onto a
    forbidden image declines them; the maximin fills its seats from the rest."""
    def key(c):
        return (0.0,) + tuple(c[1:]) if c[0] > 0 else tuple(c)
    forbidden = {(0.0, 0.5, 0.5), (0.0, 0.5, -0.5), (0.0, -0.5, 0.5), (0.0, -0.5, -0.5)}
    declined: list = []
    pts = adequacy.validation_points(3, 4, seed=0, key=key, forbidden=forbidden,
                                     declined=declined)
    assert len(pts) == 4 and all(p[0] < 0 for p in pts)
    assert len(set(declined)) == 4


# ── the outer ring ──────────────────────────────────────────────────────────

def test_the_outer_ring_is_maximin_against_the_inner_points():
    pts = adequacy.validation_points(2, 4, seed=0, outer=2)
    inner, outer = pts[:4], pts[4:]
    assert {abs(c) for p in inner for c in p} == {0.5}
    assert {abs(c) for p in outer for c in p} == {0.8}
    assert len(set(outer)) == 2
    assert pts[:4] == adequacy.validation_points(2, 4, seed=0)   # inner unchanged


def _corner_bumps() -> Surface:
    """A smooth bowl plus four narrow bumps at coded (+-0.8, +-0.8): every
    +-0.5 point sits where the bumps are ~0, so the inner ring cannot see
    them; the +-0.8 ring lands on them."""
    def fn(lv):
        x, y = (lv["A"] - 9) / 7.0, (lv["B"] - 9) / 7.0
        g = lambda u: math.exp(-((abs(u) - 0.8) / 0.08) ** 2)  # noqa: E731
        return 10 - 0.5 * x * x - 0.5 * y * y + 3.0 * g(x) * g(y)
    return Surface(name="corner_bumps", noise_sd=0.05,
                   factors=(_numeric("A"), _numeric("B")), fn=fn)


def test_the_outer_ring_has_power_where_the_inner_ring_has_none(tmp_path):
    """corner_bumps seeds 1-4: without the ring (pre-P4) the validation check
    did not reject (p = 0.585, 0.053, 0.957, 0.538) and the model was taken as
    adequate; with it, the adequacy family rejects on every seed."""
    off = {"design": {"screen": {"resolution": 5, "center_points": 4},
                      "refine": {"kind": "central_composite", "center_points": 4,
                                 "validation_outer_points": 0}}}
    inner_rej = ring_rej = 0
    for seed in range(1, 5):
        a = run_synthetic_campaign(_corner_bumps(), seed=seed, parent_dir=tmp_path / f"a{seed}",
                                   campaign_overrides=off)
        b = run_synthetic_campaign(_corner_bumps(), seed=seed, parent_dir=tmp_path / f"b{seed}")
        ra = [x for x in _recs(a.work_dir) if x["stage"] == "refine"][-1]["model_adequacy"]
        rb = [x for x in _recs(b.work_dir) if x["stage"] == "refine"][-1]["model_adequacy"]
        inner_rej += "validation_prediction" in ra["family"]["rejected"]
        ring_rej += "validation_prediction" in rb["family"]["rejected"]
        assert b.report.get("model_adequate") is False
    assert inner_rej == 0
    assert ring_rej == 4


# ── Holm across lack of fit + validation (WP-B limit 3) ──────────────────────

def test_the_adequacy_family_is_size_alpha_under_a_true_quadratic():
    """Real composite + 6 validation points (inner + ring), a TRUE quadratic,
    iid normal noise, 1000 replicates. Each test alone is size alpha; they
    share the pure-error denominator, so they are positively dependent and
    'reject if either' runs at ~0.07 (measured 0.068-0.072 over 3 x 4000),
    not 2 alpha. Holm across the two holds the family at alpha (Holm 1979,
    any dependence; measured 0.032-0.037)."""
    from orchestrator.optimize.design import central_composite
    from orchestrator.optimize.effects import fit_effects

    d = central_composite(("A", "B"), center_points=4)
    pts = adequacy.validation_points(2, 4, seed=0, outer=2)
    rng = random.Random(5)

    def f(a, b):
        return 5 + a - 0.5 * b + 0.3 * a * b - 0.8 * a * a + 0.2 * b * b

    either = fam = 0
    n = 1000
    for _ in range(n):
        ys = [f(*p.coded) + rng.gauss(0, 0.1) for p in d.points]
        fit = fit_effects(d, ys, factor_ids=("A", "B"))
        obs = [({"A": a, "B": b}, f(a, b) + rng.gauss(0, 0.1)) for a, b in pts]
        chk = adequacy.prediction_check(fit, [], [], obs)
        tests = [("lack_of_fit", fit.lack_of_fit_p), ("validation_prediction", chk["p"])]
        either += any(p < 0.05 for _n, p in tests)
        fam += bool(adequacy.adequacy_family(tests)["rejected"])
    assert either / n > 0.06           # above alpha: fails the family claim
    assert fam / n <= 0.05             # measured 0.032-0.037 at n = 4000


def test_v_is_built_from_the_rows_actually_fitted():
    """WP-B limit 9: an objective model fitted on a SUBSET of the composite
    (a metric missing on 4 rows). V from the full design's (X'X)^-1 is too
    small; V from the subset is exact -- the per-point prediction variance must
    equal x'(X_s'X_s)^-1 x computed here independently."""
    from orchestrator.optimize.design import central_composite
    from orchestrator.optimize.effects import fit_effects
    import dataclasses

    d = central_composite(("A", "B"), center_points=4)
    keep = [i for i in range(len(d.points)) if i not in (0, 5)]
    sub = dataclasses.replace(d, points=tuple(d.points[i] for i in keep))
    rng = random.Random(2)
    ys = [1 + p.coded[0] + p.coded[1] ** 2 + rng.gauss(0, 0.1) for p in sub.points]
    fit = fit_effects(sub, ys, factor_ids=("A", "B"))
    cols, terms = adequacy.fit_matrix(fit, sub, ("A", "B"))
    pt = {"A": 0.5, "B": -0.5}
    chk = adequacy.prediction_check(fit, cols, terms, [(pt, 1.0)])
    inv = adequacy._invert(adequacy._xtx(cols))
    x = [1.0] + [math.prod(pt[t] for t in ts) for ts in terms[1:]]
    h = sum(x[i] * inv[i][j] * x[j] for i in range(len(x)) for j in range(len(x)))
    assert chk["points"][0]["pi_half_width"] == pytest.approx(
        chk["bonferroni_t"] * math.sqrt(fit.pure_error_var * (1 + h)), rel=1e-9)
    full_cols = adequacy.model_columns(d, ("A", "B"))[2]
    inv_full = adequacy._invert(adequacy._xtx(full_cols))
    h_full = sum(x[i] * inv_full[i][j] * x[j] for i in range(len(x)) for j in range(len(x)))
    assert h > h_full                       # the full design understates V


# ── screen validation (WP-B limit 5) ─────────────────────────────────────────

def test_screen_validation_points_are_held_out_tested_and_kept_out_of_the_foldover(tmp_path):
    """design.screen.validation_points: 4 on bowl. The points run after the
    screen, are held out of the screen fit, are checked in the adequacy family
    (screen_validation), and the screen's planned rows are unchanged."""
    ov = {"design": {"screen": {"resolution": 5, "center_points": 4, "validation_points": 4},
                     "refine": {"kind": "central_composite", "center_points": 4}}}
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path, campaign_overrides=ov)
    plain = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path / "p")
    dm, dm0 = _dm(r.work_dir, "screen"), _dm(plain.work_dir, "screen")
    val = [x for x in dm["rows"] if x["role"] == "validation"]
    assert len(val) == 4
    assert [x["levels"] for x in dm["rows"] if x["role"] != "validation"] == \
        [x["levels"] for x in dm0["rows"]]
    sc = _recs(r.work_dir)[0]["model_adequacy"]
    assert sc["screen_validation"]["points_measured"] == 4
    assert "validation_prediction" in {t["name"] for t in sc["family"]["tests"]}


def test_screen_validation_rejects_a_cliff_the_centre_points_cannot_attribute(tmp_path):
    """step_cliff at the screen: the first-order + 2fi model misses the cliff
    at the +-0.5 points; the screen-stage check rejects on every seed."""
    ov = {"design": {"screen": {"resolution": 5, "center_points": 4, "validation_points": 4},
                     "refine": {"kind": "central_composite", "center_points": 4}}}
    for seed in range(1, 5):
        r = run_synthetic_campaign(NON_QUADRATIC["step_cliff"](), seed=seed,
                                   parent_dir=tmp_path / str(seed), campaign_overrides=ov)
        sc = _recs(r.work_dir)[0]["model_adequacy"]
        assert sc["screen_validation"]["rejected"] is True
        assert not r.report.get("certified")


def _hunt(amp=0.08) -> Surface:
    """A, B numeric with mild curvature plus a two-level choice C. With 3
    screen centre points the centres never run C = on, so curvature under it
    is UNTESTED (curvature_untested)."""
    from orchestrator.optimize.synthetic import _choice

    def fn(lv):
        xa, xb = (lv["A"] - 9) / 7.0, (lv["B"] - 9) / 7.0
        c = 1.0 if lv["C"] == "on" else 0.0
        return 10 + 0.3 * xa + 0.2 * xb + 0.2 * c - amp * (xa * xa + xb * xb)
    return Surface(name="hunt", noise_sd=0.05,
                   factors=(_numeric("A"), _numeric("B"), _choice("C")), fn=fn)


_UNTESTED = {"stages": ["verify", "screen", "confirm"],
             "design": {"screen": {"resolution": 5, "center_points": 3, "validation_points": 4},
                        "refine": {"kind": "central_composite", "center_points": 4}}}


def test_the_family_never_promotes_curvature_untested_to_adequate(tmp_path):
    """#321 P4 review HIGH 2. Seed 7: the screen's lack of fit is p = 0.033
    (a per-test rejection), the screen validation check p = 0.099, so Holm
    (thresholds 0.025, 0.05) sets the rejection aside -- and C = on was never
    measured at the centre. On 17b067c the verdict became True (adequate) and
    the curvature_untested basis was lost; now it is UNKNOWN with that basis
    (adequacy_multiplicity: holm). Under the per-test default the rejection
    stands (False)."""
    holm = run_synthetic_campaign(_hunt(), seed=7, parent_dir=tmp_path / "h",
                                  campaign_overrides={**_UNTESTED,
                                                      "policy": {"adequacy_multiplicity": "holm"}})
    rec = _recs(holm.work_dir)[0]
    fam = rec["model_adequacy"]["family"]
    assert [t["name"] for t in fam["tests"] if t["p"] < 0.05] == ["lack_of_fit"]
    assert fam["rejected"] == []
    assert rec["curvature_untested_levels"] == {"C": ["on"]}
    assert rec["model_adequate"] is None
    assert rec["model_adequate_basis"] == "curvature_untested"
    assert "curvature_untested" in holm.report["certification_withheld"]
    per = run_synthetic_campaign(_hunt(), seed=7, parent_dir=tmp_path / "p",
                                 campaign_overrides=_UNTESTED)
    assert _recs(per.work_dir)[0]["model_adequate"] is False


def test_an_exact_rejection_stays_a_veto_whatever_the_family_says(tmp_path):
    """Replaces the private-helper veto test with a campaign. The second
    objective is DETERMINISTIC (zero pure error) and curved at the centre, so
    its lack of fit is an EXACT rejection: a veto outside the Holm family. Its
    primary tests pass, so the family rejects nothing -- and the verdict must
    still be False, under holm and under the per-test default alike."""
    from orchestrator.optimize.synthetic import _obj

    f1 = lambda lv: 10 + 0.1 * lv["A"] + 0.1 * lv["B"]  # noqa: E731
    f2 = lambda lv: 5 + 0.1 * lv["A"] + (1.0 if lv["A"] == 9 else 0.0)  # noqa: E731
    surf = Surface(name="mo_exact", noise_sd=0.05,
                   factors=(_numeric("A", levels=(2, 16)), _numeric("B", levels=(2, 16))),
                   fn=f1, objectives=(_obj("f1", f1), _obj("f2", f2, noise_sd=0.0)))
    for adq in ("holm", "per_test"):
        r = run_synthetic_campaign(surf, seed=1, parent_dir=tmp_path / adq,
                                   campaign_overrides={"stages": ["verify", "screen", "confirm"],
                                                       "policy": {"adequacy_multiplicity": adq}})
        rec = _recs(r.work_dir)[0]
        fam = rec["model_adequacy"]["family"]
        assert fam["vetoes"] == ["lack_of_fit:f2"] and fam["rejected"] == []
        assert rec["model_adequate"] is False
        assert "model_inadequate" in r.report["certification_withheld"]


def test_lack_of_fit_not_computable_stays_unknown_under_the_family(tmp_path):
    """No centre points: no pure error, so no lack-of-fit test exists and the
    family has nothing to overturn. Under adequacy_multiplicity: holm the
    verdict stays UNKNOWN with its basis (a guard: an overturn needs a
    rejected TEST, which this basis excludes by construction)."""
    r = run_synthetic_campaign(
        SURFACES["additive"](), seed=1, parent_dir=tmp_path,
        campaign_overrides={"stages": ["verify", "screen", "confirm"],
                            "policy": {"adequacy_multiplicity": "holm"},
                            "design": {"screen": {"resolution": 5, "center_points": 0}}})
    rec = _recs(r.work_dir)[0]
    assert rec["model_adequate"] is None
    assert rec["model_adequate_basis"] == "lack_of_fit_not_computable"
    assert "lack_of_fit_not_computable" in r.report["certification_withheld"]


def test_a_mixed_level_campaign_never_reports_adequate_without_isolation(tmp_path):
    """curvature_not_isolated guard through campaigns: a 3-level categorical
    whose middle level fails at every corner, holm family, 8 seeds. The
    identifiability reduction drops the lost level first, so the fit is
    isolated on every seed (measured 120/120 in a wider hunt) -- and whenever
    adequate is reported True, the fit WAS isolated."""
    from orchestrator.optimize.synthetic import _choice

    lv = {"a": 0, "b": 1, "c": 2}
    surf = Surface(name="lost_mid", noise_sd=0.05,
                   factors=(_choice("C", levels=("a", "b", "c")), _numeric("A", levels=(2, 16))),
                   fn=lambda x: 10 + 0.1 * x["A"] + lv[x["C"]],
                   fails_at=lambda x: x["C"] == "b" and x["A"] != 9)
    for seed in range(1, 9):
        r = run_synthetic_campaign(surf, seed=seed, parent_dir=tmp_path / str(seed),
                                   campaign_overrides={"stages": ["verify", "screen", "confirm"],
                                                       "policy": {"adequacy_multiplicity": "holm"},
                                                       "design": {"screen": {"resolution": 5,
                                                                             "center_points": 8}}})
        rec = _recs(r.work_dir)[0]
        eff = json.loads(next(r.work_dir.glob("runs/iter-*/effects.json")).read_text())
        if rec["model_adequate"] is True:
            assert eff.get("centre_isolated") is not False
