"""WP-B: how model adequacy is DETERMINED (spec 2026-10-17-model-adequacy-design.md).

Behavioral only: every test drives real campaigns through the synthetic
harness (zero LLM calls, no subprocess) or the pure-arithmetic seams, and
asserts on what lands on disk or what the arithmetic returns.

B1  validation points + prediction check + sticky verdict (the oracle)
B3  D-efficiency / VIF of the design as run, and in the preview
B4  opt-in screen-row reuse with a block (drift) term
B5  an inadequate model's argmax is never the answer; report.md says why
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import NON_QUADRATIC, SURFACES

SEEDS = range(1, 9)


def _recs(work_dir: Path) -> list[dict]:
    paths = sorted((Path(work_dir) / "runs").glob("iter-*/recommendation.json"),
                   key=lambda p: int(p.parent.name.split("-")[1]))
    return [json.loads(p.read_text()) for p in paths]


def _false_cert(res) -> bool:
    eps = res.report.get("epsilon")
    return bool(res.report.get("certified")) and eps is not None and res.true_gap > eps + 1e-9


def _refine_dir(work_dir: Path) -> Path:
    for d in sorted((Path(work_dir) / "runs").glob("iter-*")):
        e = d / "effects.json"
        if e.exists() and json.loads(e.read_text()).get("stage") == "refine":
            return d
    raise AssertionError("no refine stage ran")


# ── B1: the oracle ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["step_cliff", "ridge_cubic"])
def test_non_quadratic_surfaces_are_never_falsely_certified(name, tmp_path):
    """Before WP-B: step_cliff 6/8 and ridge_cubic 7/8 false certificates at
    seeds 1-8 (refine's 3-level lack of fit had ~alpha power and the screen's
    rejection was forgotten). After: 0/8, and each is caught by the held-out
    validation check."""
    runs = [run_synthetic_campaign(NON_QUADRATIC[name](), seed=seed,
                                   parent_dir=tmp_path / str(seed)) for seed in SEEDS]
    # The behavioral claim first, on report.json fields that predate WP-B.
    assert sum(_false_cert(r) for r in runs) == 0
    for r in runs:
        assert r.report.get("model_adequate") is False
        assert "model_inadequate" in (r.report.get("certification_withheld") or [])
    caught = sum([x for x in _recs(r.work_dir) if x["stage"] == "refine"][-1]
                 ["model_adequacy"]["validation"]["rejected"] is True for r in runs)
    assert caught == len(SEEDS)


@pytest.mark.parametrize("name", ["bowl", "geometric_knob_log"])
def test_smooth_surfaces_keep_their_power(name, tmp_path):
    """The validation check is not a certificate tax on surfaces the model
    represents: before WP-B these certified 6/8 at seeds 1-8, and they still
    do, with every recommendation within epsilon of the truth.

    ``saddle`` left this list with WP-A A1 (spec
    2026-10-17-certification-soundness.md): its two near-equal ridges leave a
    model bound of ~0.4-0.7 against an epsilon of 0.25 (pure-error df 3,
    Bonferroni over 80 challengers), so the delta_s half of the certificate
    is genuinely unearned there; ``test_saddle_withholds_on_the_model_bound``
    pins that."""
    certified = 0
    for seed in SEEDS:
        r = run_synthetic_campaign(SURFACES[name](), seed=seed,
                                   parent_dir=tmp_path / str(seed))
        certified += bool(r.report.get("certified"))
        assert not _false_cert(r)
    # Was >= 6 of 8. #321 P3's A5 skewness pretest (a veto at the a-priori
    # 0.25 of a preliminary test, Bancroft 1964) withholds ~25% of rounds on
    # Gaussian noise by construction -- its measured cost (spec §7).
    assert certified >= 4


def test_saddle_withholds_on_the_model_bound(tmp_path):
    """WP-A A1: on saddle the terminal bound alone certified 6/8, while the
    model bound over the unshortlisted candidates exceeded epsilon on every
    one of them. Now withheld, named, and never wrong. Since #321 H3 (the
    Scheffe constant, 5.3 against Bonferroni's 6.7-12 at df 3) the model half
    is narrow enough to certify on one seed (6: {A: 16, B: 11}, which TIES
    the optimum, gap 0.0); every other seed is withheld on the model half."""
    certified = 0
    for seed in SEEDS:
        r = run_synthetic_campaign(SURFACES["saddle"](), seed=seed,
                                   parent_dir=tmp_path / str(seed))
        assert not _false_cert(r)
        w = r.report.get("certification_withheld") or []
        if r.report.get("certified"):
            certified += 1
            continue
        assert "model_bound_above_epsilon" in w or "model_inadequate" in w, w
    assert certified <= 2


def test_validation_rows_are_registered_held_out_and_reconciled(tmp_path):
    """Refine pre-registers 4 off-lattice points at coded +-0.5 (A, B in
    {5.5 -> 6, 12.5 -> 12} on bowl's grid), runs them as their own block AFTER
    the composite, and holds them out of the fit."""
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path)
    d = _refine_dir(r.work_dir)
    dm = json.loads((d / "design_matrix.json").read_text())
    eff = json.loads((d / "effects.json").read_text())
    val = [row for row in dm["rows"] if row["role"] == "validation"]
    assert len(val) == 4
    assert {(v["levels"]["A"], v["levels"]["B"]) for v in val} == {
        (6, 6), (6, 12), (12, 6), (12, 12)}
    idx = sorted(v["row_index"] for v in val)
    assert dm["validation"]["row_indices"] == idx
    assert dm["run_order"][-4:] and sorted(dm["run_order"][-4:]) == idx
    assert eff["held_out_rows"]["row_indices"] == idx
    assert eff["n_runs"] + len(idx) == len(dm["rows"])


def test_validation_points_are_a_seeded_maximin_design():
    """The rule: points in {-0.5, +0.5}^k, deterministic in the seed, and each
    next point maximises its minimum distance to those already chosen."""
    from orchestrator.optimize import adequacy
    for k in (2, 3, 5):
        pts = adequacy.validation_points(k, 4, seed=0)
        assert pts == adequacy.validation_points(k, 4, seed=0)
        assert all(abs(abs(c) - 0.5) < 1e-12 for p in pts for c in p)
        assert len(set(pts)) == 4
        for i in range(1, len(pts)):
            rest = [c for c in _cube(k) if c not in pts[:i]]
            best = max(min(_d2(c, p) for p in pts[:i]) for c in rest)
            assert min(_d2(pts[i], p) for p in pts[:i]) == best
    assert len(adequacy.validation_points(14, 4, seed=3)) == 4   # sampled, bounded


def _cube(k):
    import itertools
    return [tuple(0.5 * s for s in c) for c in itertools.product((-1.0, 1.0), repeat=k)]


def _d2(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def test_the_prediction_check_is_size_alpha_under_the_registered_model():
    """Under a TRUE quadratic and iid normal noise the joint predictive F
    rejects at about alpha (Chow 1960): 400 simulated refine designs."""
    from orchestrator.optimize import adequacy
    from orchestrator.optimize.design import central_composite
    from orchestrator.optimize.effects import fit_effects

    d = central_composite(("A", "B"), center_points=4)
    pts = adequacy.validation_points(2, 4, seed=0)
    rng = random.Random(11)

    def f(a, b):
        return 5 + a - 0.5 * b + 0.3 * a * b - 0.8 * a * a + 0.2 * b * b

    rej = 0
    for _ in range(400):
        ys = [f(*p.coded) + rng.gauss(0, 0.1) for p in d.points]
        fit = fit_effects(d, ys, factor_ids=("A", "B"))
        labels, terms, cols = adequacy.model_columns(d, ("A", "B"))
        val = [({"A": a, "B": b}, f(a, b) + rng.gauss(0, 0.1)) for a, b in pts]
        rej += bool(adequacy.prediction_check(fit, cols, terms, val)["rejected"])
    assert rej / 400 < 0.09        # nominal 0.05; binomial sd ~0.011


def test_without_validation_refine_cannot_overturn_a_screen_rejection(tmp_path):
    """validation_points: 0. Before WP-B the refine's lack-of-fit pass simply
    overwrote the screen's rejection (model_adequate true, certified). Now the
    epoch verdict is UNKNOWN, screen_rejection_unresolved, and nothing certifies."""
    ov = {"design": {"screen": {"resolution": 5, "center_points": 4},
                     "refine": {"kind": "central_composite", "center_points": 4,
                                "validation_points": 0},
                     "confirm": {"replicates": 3}}}
    r = run_synthetic_campaign(NON_QUADRATIC["step_cliff"](), seed=1,
                               parent_dir=tmp_path, campaign_overrides=ov)
    assert not r.report.get("certified")
    refine = [x for x in _recs(r.work_dir) if x["stage"] == "refine"][-1]
    assert refine["model_adequate"] is None
    assert refine["model_adequate_basis"] == "screen_rejection_unresolved"
    assert "screen_rejection_unresolved" in (r.report.get("certification_withheld") or [])
    assert refine["model_adequacy"]["this_stage"]["verdict"] is True   # LOF passed


def test_every_oracle_campaign_satisfies_the_adequacy_invariant(tmp_path):
    """INV-STAT19 over real records, smooth and non-quadratic."""
    from orchestrator.optimize import invariants as inv
    for name, surf in (("bowl", SURFACES["bowl"]), ("step_cliff", NON_QUADRATIC["step_cliff"]),
                       ("ridge_cubic", NON_QUADRATIC["ridge_cubic"]),
                       ("two_peaks", NON_QUADRATIC["two_peaks"])):
        for seed in (1, 2):
            r = run_synthetic_campaign(surf(), seed=seed, parent_dir=tmp_path / f"{name}{seed}")
            assert inv.check_adequacy_determination(_recs(r.work_dir)) == [], name


# ── B3: design efficiency ────────────────────────────────────────────────────

def test_design_efficiency_is_recorded_for_the_design_as_run(tmp_path):
    """Every fitting stage records D-efficiency and centred VIFs. The 2^2 screen
    with centres is orthogonal (every VIF 1); the face-centred composite's
    quadratic columns are correlated (VIF > 1)."""
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path)
    recs = {x["stage"]: x for x in _recs(r.work_dir)}
    s = recs["screen"]["model_adequacy"]["design_efficiency"]
    q = recs["refine"]["model_adequacy"]["design_efficiency"]
    assert 0 < s["d_efficiency"] <= 1 and 0 < q["d_efficiency"] <= 1
    assert all(abs(v - 1.0) < 1e-9 for v in s["vif"].values())
    assert q["vif"]["A^2"] > 1.0 and q["vif"]["A"] == pytest.approx(1.0)
    press = recs["refine"]["model_adequacy"]["press"]
    assert press["press"] > 0 and press["r2_prediction"] is not None


def test_d_efficiency_matches_the_textbook_value():
    """|X'X/n|^(1/p) for a 2^2 factorial with an intercept + mains model is 1."""
    from orchestrator.optimize import adequacy
    from orchestrator.optimize.design import full_factorial
    from orchestrator.optimize.effects import model_matrix

    d = full_factorial(("A", "B"))
    labels, _t, cols, _q, _a = model_matrix(d, ("A", "B"), include_interactions=False)
    assert adequacy.design_efficiency(cols, labels)["d_efficiency"] == pytest.approx(1.0)


def test_the_preview_counts_validation_runs_and_reports_efficiency():
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.preview import build_preview, format_preview

    camp = synthetic_campaign(SURFACES["bowl"]())
    pv = build_preview(camp, noise_sd=0.05, mean=20.0, run_secs=[1.0])
    refine = next(s for s in pv.stages if s.stage == "refine")
    assert refine.runs == 12 + 4
    assert "4 off-lattice validation point(s)" in refine.note
    text = "\n".join(format_preview(pv))
    assert "screen design: D-efficiency" in text and "refine design: D-efficiency" in text


# ── B4: screen-row reuse with a block term ───────────────────────────────────

_REUSE = {"design": {"screen": {"resolution": 5, "center_points": 4},
                     "refine": {"kind": "central_composite", "center_points": 4,
                                "reuse_screen": True},
                     # #321 P3: the confirm default is the A5 floor; the arms
                     # compared below must share it.
                     "confirm": {"replicates": 6}}}


def _fresh_runs(work_dir) -> int:
    return sum(1 for p in Path(work_dir).glob("runs/iter-*/runs.jsonl")
               for ln in p.read_text().splitlines()
               if ln.strip() and not (json.loads(ln).get("reused_from") or {}).get("stage"))


def test_reuse_skips_the_screen_corners_and_fits_a_block_term(tmp_path):
    """bowl: the 4 refine cube corners equal the 4 measured screen corners, so
    they are not re-run (33 -> 29 fresh runs); the screen's 4 centres join as
    block-1 centres; the fit carries the block coefficient (drift check)."""
    plain = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path / "a")
    reuse = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path / "b",
                                   campaign_overrides=_REUSE)
    assert _fresh_runs(reuse.work_dir) == _fresh_runs(plain.work_dir) - 4
    d = _refine_dir(reuse.work_dir)
    rows = [json.loads(x) for x in (d / "runs.jsonl").read_text().splitlines() if x.strip()]
    carried = [x for x in rows if (x.get("reused_from") or {}).get("stage") == "screen"]
    assert len(carried) == 8                          # 4 corners + 4 centres
    assert {x["role"] for x in carried} == {"corner", "center"}
    eff = json.loads((d / "effects.json").read_text())
    assert eff["n_runs"] == 16                         # 12 composite + 4 block-1 centres
    rec = [x for x in _recs(reuse.work_dir) if x["stage"] == "refine"][-1]
    be = rec["model_adequacy"]["reuse"]["block_effect"]
    assert be["p"] > 0.05 and rec["model_adequacy"]["reuse"]["drift_detected"] is False
    dm = json.loads((d / "design_matrix.json").read_text())
    assert dm["stage_reuse"]["reused_count"] == 8
    assert reuse.recommendation == plain.recommendation


def test_reuse_detects_a_between_stage_shift(tmp_path):
    """A constant +0.5 shift applied to every run after the screen is exactly
    the drift the block term exists to absorb: its t test flags it, and the
    recommendation is unaffected."""
    import dataclasses

    from orchestrator.optimize import synthetic

    base = SURFACES["bowl"]()
    calls = {"n": 0}

    def fn(lv, _f=base.fn):
        calls["n"] += 1
        return _f(lv) + (0.5 if calls["n"] > 8 else 0.0)

    shifted = dataclasses.replace(base, fn=fn)
    r = run_synthetic_campaign(shifted, seed=1, parent_dir=tmp_path,
                               campaign_overrides=_REUSE)
    rec = [x for x in _recs(r.work_dir) if x["stage"] == "refine"][-1]
    assert rec["model_adequacy"]["reuse"]["drift_detected"] is True
    assert rec["model_adequacy"]["reuse"]["block_effect"]["estimate"] < -0.3
    assert synthetic.true_optimum(base)[0] == r.recommendation


def test_reuse_is_refused_with_a_choice_factor(tmp_path):
    """bowl_centred holds a choice factor at refine; reuse is refused and the
    stage runs exactly as without the option."""
    a = run_synthetic_campaign(SURFACES["bowl_centred"](), seed=1, parent_dir=tmp_path / "a")
    b = run_synthetic_campaign(SURFACES["bowl_centred"](), seed=1, parent_dir=tmp_path / "b",
                               campaign_overrides=_REUSE)
    assert _fresh_runs(a.work_dir) == _fresh_runs(b.work_dir)
    assert "stage_reuse" not in json.loads(
        (_refine_dir(b.work_dir) / "design_matrix.json").read_text())


# ── B5: an inadequate model is not the answer ────────────────────────────────

def test_an_inadequate_model_never_supplies_the_answer_and_report_md_says_so(tmp_path):
    """step_cliff, confirm declared absent: before WP-B the report fell to the
    `model` rung -- the misspecified quadratic's argmax -- as its answer. Now
    the model rung is barred, the measured rung answers, and report.md says
    the surface is not well approximated and what to do."""
    from orchestrator.optimize.report_md import render_report_markdown

    r = run_synthetic_campaign(NON_QUADRATIC["step_cliff"](), seed=1, parent_dir=tmp_path,
                               campaign_overrides={"stages": ["verify", "screen", "refine"]})
    assert r.report["recommendation"]["basis"] != "model"
    assert r.report["recommendation"]["basis"] == "measured"
    assert r.report.get("model_adequate") is False
    assert "validation_prediction" in r.report.get("model_rejected_by", [])
    md = render_report_markdown(r.work_dir)
    assert "NOT well approximated" in md
    assert "scale: log" in md and "narrow the ranges" in md
    assert "best MEASURED valid configuration" in md


# ── review round: H1 (a same-class refit never erases a rejection) ──────────

def test_a_foldover_pass_does_not_erase_a_screen_rejection(tmp_path):
    """interaction_only at resolution IV, seed 14: the screen's lack of fit
    rejects, the registered foldover's combined fit passes. The foldover is
    the SAME first-order model refitted on more rows, so the epoch verdict
    stays false and nothing certifies on it."""
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from test_optimize_foldover import _RES4_OVERRIDES

    r = run_synthetic_campaign(SURFACES["interaction_only"](), seed=14,
                               parent_dir=tmp_path,
                               campaign_overrides=dict(_RES4_OVERRIDES))
    recs = {x["stage"]: x for x in _recs(r.work_dir)}
    assert recs["screen"]["model_adequacy"]["this_stage"]["verdict"] is False
    assert recs["foldover"]["model_adequacy"]["this_stage"]["verdict"] is True
    assert recs["foldover"]["model_adequate"] is False
    assert r.report.get("model_adequate") is False
    assert not r.report.get("certified")
    assert "model_inadequate" in (r.report.get("certification_withheld") or [])


def test_the_epoch_rule_is_strictly_higher_class_with_validation():
    from orchestrator.optimize import adequacy

    ev = adequacy.epoch_verdict
    assert ev([("screen", 1, False, False), ("foldover", 1, True, False)])[0] is False
    assert ev([("screen", 1, False, False), ("refine", 2, True, True)])[0] is True
    v, _by, basis = ev([("screen", 1, False, False), ("refine", 2, True, False)])
    assert v is None and basis == "screen_rejection_unresolved"
    assert ev([("refine", 2, False, True), ("refine", 2, True, True)])[0] is False
    assert ev([("screen", 1, True, False), ("foldover", 1, None, False)])[0] is None


# ── review round: H2 (a reused row is counted once) ─────────────────────────

def test_reuse_does_not_double_count_measurements(tmp_path):
    """With reuse_screen the screen's rows appear twice on disk (the screen's
    own and refine's copy). Measured means and their replicate counts are
    identical with and without the copies."""
    from orchestrator.optimize.stage_runner import _top_measured

    def _stage_reused(row):
        return bool((row.get("reused_from") or {}).get("stage"))

    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path,
                               campaign_overrides=_REUSE)
    assert any(_stage_reused(json.loads(ln))
               for p in r.work_dir.glob("runs/iter-*/runs.jsonl")
               for ln in p.read_text().splitlines() if ln.strip())
    with_copies = _top_measured(r.work_dir, "m", k=50)
    # Truth: means over the genuine measurements only.
    sums: dict = {}
    for p in r.work_dir.glob("runs/iter-*/runs.jsonl"):
        for ln in p.read_text().splitlines():
            row = json.loads(ln) if ln.strip() else None
            if not row or row.get("status") != "complete" or _stage_reused(row):
                continue
            k = json.dumps(row["levels"], sort_keys=True)
            sums.setdefault(k, []).append(row["response"]["m"])
    for t in with_copies:
        vs = sums[json.dumps(t["levels"], sort_keys=True)]
        assert t["n"] == len(vs)
        assert t["m"] == pytest.approx(sum(vs) / len(vs))


# ── #321 P4 item 4: partial reuse across choice slices is REJECTED ──────────

def test_reuse_screen_with_a_choice_factor_is_a_validation_error():
    """Declaring reuse_screen with a choice factor used to be refused silently
    at runtime (an option that could never take effect). It is now a hard
    validation error naming the reason; without a choice factor it is clean."""
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.validate import validate_optimization_campaign

    bad = synthetic_campaign(SURFACES["bowl_centred"](), **_REUSE)
    errs = [e for e in validate_optimization_campaign(bad)
            if "reuse_screen" in e and not e.startswith("WARN")]
    assert errs and "interactions" in errs[0] and "constant shift" in errs[0]
    ok = synthetic_campaign(SURFACES["bowl"](), **_REUSE)
    assert not [e for e in validate_optimization_campaign(ok) if "reuse_screen" in e]


def test_a_block_term_cannot_absorb_a_choice_by_numeric_interaction():
    """Why the rejection holds, by arithmetic. Truth: y = 1 + 2A + 3C + 4AC,
    with C = +1 the refine slice. Fitting the slice model (1, A) plus a block
    indicator on slice rows (C = +1) together with reused off-slice rows
    (C = -1) recovers the slice slope 2 + 4 = 6 only if the off-slice rows
    differ by a constant. They differ by 3C + 4AC, so the slope is biased."""
    from orchestrator.optimize.effects import _solve_normal_equations

    a_lv = [-1.0, 0.0, 1.0]
    rows = [(a, 1.0) for a in a_lv] * 2 + [(a, -1.0) for a in a_lv] * 2
    y = [1 + 2 * a + 3 * c + 4 * a * c for a, c in rows]
    cols = [[1.0] * len(rows), [a for a, _c in rows],
            [1.0 if c < 0 else 0.0 for _a, c in rows]]   # block = off-slice
    b = _solve_normal_equations(cols, y)
    assert b[1] == pytest.approx(2.0)        # the pooled slope, not the slice's 6
    slice_only = _solve_normal_equations(
        [[1.0] * 6, [a for a, c in rows if c > 0]], [v for v, (_a, c) in zip(y, rows) if c > 0])
    assert slice_only[1] == pytest.approx(6.0)
