"""Multi-objective ``kind: optimization``: the Pareto core and its oracles.

Spec ``docs/superpowers/specs/2026-10-15-pareto-front-design.md``. Zero LLM
calls: every campaign here runs through the in-process synthetic target
(``harness.run_synthetic_campaign``), and every assertion is on an artifact or
on the answer scored against exhaustively enumerated truth
(``synthetic.true_front``).
"""
from __future__ import annotations

import itertools
import json
import math
import random
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from orchestrator.optimize import pareto
from orchestrator.optimize.harness import (
    evaluate_pareto_campaign,
    run_synthetic_campaign,
    synthetic_campaign,
)
from orchestrator.optimize.policy import compile_policy
from orchestrator.optimize.synthetic import PARETO_SURFACES, SURFACES

SEEDS = range(1, 9)

# ── the pure core ────────────────────────────────────────────────────────────

_pts2 = st.lists(st.tuples(st.floats(0, 1), st.floats(0, 1)), min_size=1, max_size=8)
_pts3 = st.lists(st.tuples(st.floats(0, 1), st.floats(0, 1), st.floats(0, 1)),
                 min_size=1, max_size=6)


def _hv_inclusion_exclusion(points, ref):
    """Brute-force hypervolume: inclusion-exclusion over boxes (small sets)."""
    pts = [tuple(max(0.0, p[k] - ref[k]) for k in range(len(ref))) for p in points]
    total = 0.0
    for r in range(1, len(pts) + 1):
        for sub in itertools.combinations(pts, r):
            vol = math.prod(min(p[k] for p in sub) for k in range(len(ref)))
            total += (-1) ** (r + 1) * vol
    return total


@settings(max_examples=150, deadline=None)
@given(_pts2)
def test_hypervolume_2d_is_exact(points):
    assert pareto.hypervolume(points, [0.0, 0.0])[0] == pytest.approx(
        _hv_inclusion_exclusion(points, [0.0, 0.0]), abs=1e-9)


@settings(max_examples=100, deadline=None)
@given(_pts3)
def test_hypervolume_3d_slicing_is_exact(points):
    assert pareto.hypervolume(points, [0.0] * 3)[0] == pytest.approx(
        _hv_inclusion_exclusion(points, [0.0] * 3), abs=1e-9)


@settings(max_examples=80, deadline=None)
@given(_pts2, st.tuples(st.floats(0, 1), st.floats(0, 1)))
def test_hypervolume_never_decreases_when_a_point_is_added(points, extra):
    """Metamorphic: HV is monotone in the point set."""
    ref = [0.0, 0.0]
    assert pareto.hypervolume(points + [extra], ref)[0] >= \
        pareto.hypervolume(points, ref)[0] - 1e-12


def test_hypervolume_monte_carlo_for_four_objectives_is_close_and_seeded():
    pts = [[0.5, 0.5, 0.5, 0.5], [1.0, 0.2, 0.2, 0.2]]
    v1, method = pareto.hypervolume(pts, [0.0] * 4)
    v2, _ = pareto.hypervolume(pts, [0.0] * 4)
    assert v1 == v2, "the MC estimate must be reproducible (fixed seed)"
    assert "monte_carlo" in method
    assert v1 == pytest.approx(_hv_inclusion_exclusion(pts, [0.0] * 4), rel=0.02)


@settings(max_examples=150, deadline=None)
@given(st.lists(st.tuples(st.integers(0, 5), st.integers(0, 5)), min_size=1, max_size=12))
def test_nondominated_indices_is_exactly_the_pareto_set(points):
    vecs = [list(p) for p in points]
    keep = set(pareto.nondominated_indices(vecs))
    for i, v in enumerate(vecs):
        dominated = any(pareto.strictly_dominates(w, v) for j, w in enumerate(vecs) if j != i)
        assert (i not in keep) == dominated


def test_a_difference_below_epsilon_is_not_dominance():
    assert not pareto.eps_dominates([1.05, 1.0], [1.0, 1.0], [0.1, 0.1])
    assert pareto.eps_dominates([1.2, 1.0], [1.0, 1.0], [0.1, 0.1])
    assert not pareto.eps_dominates([1.2, 0.99], [1.0, 1.0], [0.1, 0.1])


def _objs(k=2):
    return [pareto.Objective(f"f{i + 1}", "maximize", {"abs": 0.1}) for i in range(k)]


def test_knee_picks_the_bulge_and_weights_miss_a_concave_interior():
    objs = _objs()
    lv = [{"x": i} for i in range(5)]
    convex = [[0.0, 1.0], [0.6, 0.9], [0.8, 0.8], [0.9, 0.6], [1.0, 0.0]]
    concave = [[0.0, 1.0], [0.3, 0.45], [0.5, 0.25], [0.7, 0.1], [1.0, 0.0]]
    eps_z = [0.01, 0.01]
    assert pareto.preferred_index(pareto.Preference("knee"), objs, convex, lv, eps_z) == 2
    w = pareto.Preference("weights", weights={"f1": 1.0, "f2": 1.0})
    assert pareto.preferred_index(w, objs, concave, lv, eps_z) in (0, 4), \
        "no weighted sum reaches an interior point of a concave front"
    lex = pareto.Preference("lexicographic", order=("f2", "f1"))
    assert pareto.preferred_index(lex, objs, concave, lv, eps_z) == 0


def test_front_gaps_are_adjacent_pairs_largest_first():
    zs = [[0.0, 1.0], [0.1, 0.9], [0.9, 0.1], [1.0, 0.0]]
    gaps = pareto.front_gaps(zs)
    assert gaps[0]["between"] == [1, 2] and gaps[0]["size"] == pytest.approx(0.8)
    assert len(gaps) == 3


def _mp(levels, f1, f2, source="confirm"):
    return pareto.MeasuredPoint(levels, {"f1": list(f1), "f2": list(f2)}, source)


def test_measured_front_claims_only_what_the_variance_supports():
    objs = _objs()
    eps = {"f1": 0.1, "f2": 0.1}
    far = [_mp({"x": 0}, [10.0, 10.1, 9.9], [1.0, 1.1, 0.9]),
           _mp({"x": 1}, [1.0, 1.1, 0.9], [10.0, 10.1, 9.9])]
    pooled = {m: pareto.pooled_variance(far, m) for m in ("f1", "f2")}
    st_far = {e.index: e.status for e in pareto.measured_front(far, objs, eps, delta=0.05,
                                                               pooled=pooled)}
    assert st_far == {0: "confidently_nondominated", 1: "confidently_nondominated"}
    # Same means, NO replicates anywhere: the variance is unknown, so nothing
    # can be ruled out -- an unknown is not a zero.
    single = [_mp({"x": 0}, [10.0], [1.0]), _mp({"x": 1}, [1.0], [10.0])]
    pooled = {m: pareto.pooled_variance(single, m) for m in ("f1", "f2")}
    assert {e.status for e in pareto.measured_front(single, objs, eps, delta=0.05,
                                                    pooled=pooled)} == {"possibly_dominated"}


@settings(max_examples=60, deadline=None)
@given(st.integers(0, 10_000))
def test_more_replicates_never_strip_a_confident_status_of_a_separated_pair(seed):
    """Metamorphic: doubling the replicates of two well-separated trade-off
    points (same means, same spread) keeps both confident."""
    rng = random.Random(seed)
    base = [rng.gauss(0, 0.05) for _ in range(3)]
    a = _mp({"x": 0}, [10 + b for b in base], [1 + b for b in base])
    b = _mp({"x": 1}, [1 + b for b in base], [10 + b for b in base])
    objs, eps = _objs(), {"f1": 0.1, "f2": 0.1}

    def statuses(points):
        pooled = {m: pareto.pooled_variance(points, m) for m in ("f1", "f2")}
        return {e.status for e in pareto.measured_front(points, objs, eps, delta=0.05,
                                                        pooled=pooled)}
    assert statuses([a, b]) == {"confidently_nondominated"}
    a2 = _mp({"x": 0}, a.samples["f1"] * 2, a.samples["f2"] * 2)
    b2 = _mp({"x": 1}, b.samples["f1"] * 2, b.samples["f2"] * 2)
    assert statuses([a2, b2]) == {"confidently_nondominated"}


# ── the compiled policy ──────────────────────────────────────────────────────


def _mo_campaign(**opt):
    c = synthetic_campaign(PARETO_SURFACES["pareto_convex"]())
    c["optimization"].update(opt)
    return c


def test_multi_objective_policy_registers_the_gap_fill_branch_before_certification():
    pol = compile_policy(_mo_campaign())
    rules = [t for t in pol["transitions"] if t["from"] == "confirm" and "when" in t]
    keys = [tuple(sorted(t["when"])) for t in rules]
    gap = next(i for i, t in enumerate(rules) if "front_gap_large" in t["when"])
    cert = next(i for i, t in enumerate(rules) if t["when"] == {"certified": True})
    assert gap < cert, keys
    assert rules[gap]["accounting"] == "front gap fill, Bonferroni over rounds"
    assert rules[gap]["to"] == "confirm"
    assert [o["metric"] for o in pol["objective"]["objectives"]] == ["f1", "f2"]
    # Multi-objective defaults: a second round exists, the shortlist holds a front.
    assert pol["states"]["confirm"]["design"]["max_rounds"] == 2
    assert pol["states"]["confirm"]["design"]["shortlist_size"] == 6


def test_a_map_valued_epsilon_reaches_each_objective():
    pol = compile_policy(_mo_campaign(policy={"epsilon": {"f1": {"pct": 1}, "f2": {"abs": 0.5}}}))
    eps = {o["metric"]: o["epsilon"] for o in pol["objective"]["objectives"]}
    assert eps == {"f1": {"pct": 1}, "f2": {"abs": 0.5}}
    assert pol["objective"]["epsilon"] == {"pct": 1}


@pytest.mark.parametrize("name", sorted(SURFACES))
def test_single_objective_policies_carry_no_multi_objective_vocabulary(name):
    pol = compile_policy(synthetic_campaign(SURFACES[name]()))
    assert "objectives" not in pol["objective"]
    assert not any("front_gap_large" in (t.get("when") or {}) for t in pol["transitions"])


# ── the oracles: properties over seeds 1-8 ───────────────────────────────────

#: Property 2's floor per surface: the TRUE hypervolume of the reported
#: confidently-nondominated configurations as a fraction of the true front's,
#: in one frame (each objective normalised over the valid grid, reference =
#: worst valid value). Each floor sits below the worst measured seed (1-8,
#: quoted below) by at least 0.03 -- a regression guard, not an aspiration:
#:   convex 0.996 / concave 0.988 -- the whole curve is found;
#:   with_constraint 0.859 -- the cut edge is on a noisy constraint, and boundary
#:     configurations get struck off by a single infeasible replicate (the
#:     parent spec's sticky rule), so part of the constrained edge is lost;
#:   three 0.836 -- a 2-D front surface on a 9x9x9 grid from 78 runs;
#:   choice_split 0.950 -- both branches, the C=on one carried from screen;
#:   noisy 0.490 -- noise ~ epsilon, so neighbouring points stay unresolved;
#:     the statuses are a SIMULTANEOUS claim over the front (alpha =
#:     delta / (N (N-1) K)), which leaves as few as 1-2 confident points here
#:     (it was 0.781 under the per-point alpha = delta / ((N-1) K)).
HV_FLOOR = {"pareto_convex": 0.95, "pareto_concave": 0.95,
            "pareto_with_constraint": 0.85, "pareto_three": 0.80,
            "pareto_choice_split": 0.90, "pareto_noisy": 0.45}


@pytest.fixture(scope="module")
def oracle_runs(tmp_path_factory):
    cache: dict = {}

    def get(name, seed, rounds=None):
        key = (name, seed, rounds)
        if key not in cache:
            ov = {"policy": {"confirm_max_rounds": rounds}} if rounds else None
            cache[key] = evaluate_pareto_campaign(
                PARETO_SURFACES[name](), seed=seed,
                parent_dir=tmp_path_factory.mktemp(f"{name}-{seed}-{rounds}"),
                campaign_overrides=ov)
        return cache[key]
    return get


@pytest.mark.parametrize("name", sorted(PARETO_SURFACES))
def test_every_confident_point_is_within_epsilon_of_the_true_front(name, oracle_runs):
    """Property 1 (+ admissibility): no reported confidently_nondominated point
    is off the true front by epsilon, or truly inadmissible."""
    for seed in SEEDS:
        r = oracle_runs(name, seed)
        assert r["path_tail"] == "report", (seed, r["path"])
        assert r["n_confident_off_front"] == 0, (seed, r["off_front"])


@pytest.mark.parametrize("name", sorted(PARETO_SURFACES))
def test_reported_front_hypervolume_reaches_the_stated_fraction(name, oracle_runs):
    """Property 2."""
    for seed in SEEDS:
        r = oracle_runs(name, seed)
        assert r["hv_ratio"] >= HV_FLOOR[name], (seed, r["hv_ratio"])


@pytest.mark.parametrize("name", sorted(PARETO_SURFACES))
def test_the_recommendation_is_on_the_true_front_and_never_falsely_certified(name, oracle_runs):
    """Property 3, and the false-certification count it implies (0)."""
    for seed in SEEDS:
        r = oracle_runs(name, seed)
        assert r["recommended_within_eps"], (seed, r["recommended"])
        assert not r["false_certified"], seed


@pytest.mark.parametrize("name", sorted(set(PARETO_SURFACES) - {"pareto_noisy"}))
def test_gap_fill_rounds_never_lower_the_hypervolume(name, oracle_runs):
    """Property 5 (metamorphic): raising confirm_max_rounds 1 -> 2 -> 3, which
    is what lets the registered gap-fill branch run, never lowers the true
    hypervolume -- of the confident points nor of the whole reported front.

    ``pareto_noisy`` is excluded from the CONFIDENT half on purpose and checked
    below: with noise about one epsilon, a gap fill adds a neighbour closer than
    the replicates can resolve, which honestly strips its neighbours'
    confidence."""
    for seed in SEEDS:
        hv = [oracle_runs(name, seed, rounds) for rounds in (1, 2, 3)]
        for a, b in zip(hv, hv[1:]):
            assert b["hv_ratio"] >= a["hv_ratio"] - 1e-9, (seed, [h["hv_ratio"] for h in hv])
            assert b["hv_ratio_front"] >= a["hv_ratio_front"] - 1e-9, seed


def test_noise_at_epsilon_degrades_statuses_not_truth(oracle_runs):
    """On ``pareto_noisy`` the campaign must not CLAIM what it cannot resolve:
    fewer points are confident than on the quiet surface, none is off the true
    front, and none of its answers is certified falsely."""
    quiet = [oracle_runs("pareto_convex", s)["n_confident"] for s in SEEDS]
    noisy = [oracle_runs("pareto_noisy", s)["n_confident"] for s in SEEDS]
    assert sum(noisy) < sum(quiet)
    assert all(oracle_runs("pareto_noisy", s)["n_confident_off_front"] == 0 for s in SEEDS)


def test_a_choice_factor_front_keeps_both_branches(oracle_runs):
    """Refine holds C at one level; the front must still carry both branches."""
    for seed in SEEDS:
        r = oracle_runs("pareto_choice_split", seed)
        rep = json.loads((Path(r["work_dir"]) / "report.json").read_text())
        levels = {f["levels"]["C"] for f in rep["pareto"]["front"]
                  if f["status"] == "confidently_nondominated"}
        assert levels == {"on", "off"}, (seed, levels)


def test_preference_methods_reach_the_points_they_promise(tmp_path):
    """Weights miss a concave interior; knee and lexicographic still return a
    point on the true front (spec oracle ``pareto_concave``)."""
    surface = PARETO_SURFACES["pareto_concave"]()
    base = {"objectives": [{"metric": "f1", "direction": "maximize"},
                           {"metric": "f2", "direction": "maximize"}]}
    out = {}
    for method, extra in (("knee", {}), ("weights", {"weights": {"f1": 1.0, "f2": 1.0}}),
                          ("lexicographic", {"order": ["f2", "f1"]})):
        r = evaluate_pareto_campaign(
            surface, seed=1, parent_dir=tmp_path / method,
            campaign_overrides={"response": {**base, "preference": {"method": method, **extra}}})
        assert r["recommended_within_eps"], (method, r["recommended"])
        out[method] = r["recommended"]
    assert out["weights"]["A"] in (2, 16), "a weighted sum can only pick an extreme here"
    assert out["lexicographic"]["A"] == 2


# ── artifacts ────────────────────────────────────────────────────────────────


def test_multi_objective_artifacts_carry_the_front(tmp_path):
    r = run_synthetic_campaign(PARETO_SURFACES["pareto_convex"](), seed=1, parent_dir=tmp_path)
    rec = json.loads(sorted(Path(r.work_dir).glob("runs/iter-*/recommendation.json"))[-1].read_text())
    assert rec["objectives"] == ["f1", "f2"]
    assert rec["front_size_predicted"] >= 2
    assert {"f1", "f2"} == set(rec["objective_models"])
    assert any(p["status"] == "nondominated" for p in rec["predicted_front"])
    par = r.report["pareto"]
    assert par["preference"]["chosen"] == r.report["recommendation"]["levels"]
    assert par["hypervolume"]["normalized"] is True
    assert [f["mean"]["f1"] for f in par["front"]] == sorted(
        (f["mean"]["f1"] for f in par["front"]), reverse=True)
    conf = json.loads(sorted(Path(r.work_dir).glob("runs/iter-*/confirmation.json"))[-1].read_text())
    assert conf["pareto"]["front"] == par["front"]


def test_report_md_renders_the_front_with_the_preferred_point_marked(tmp_path):
    from orchestrator.optimize.report_md import render_report_markdown

    r = run_synthetic_campaign(PARETO_SURFACES["pareto_convex"](), seed=1, parent_dir=tmp_path)
    md = render_report_markdown(r.work_dir)
    assert "## Trade-off front" in md
    assert md.count("**(preferred)**") == 1
    assert "Hypervolume" in md and "## What to do next" in md


@pytest.mark.parametrize("name", ["additive", "sla", "bowl"])
def test_single_objective_artifacts_carry_no_front(name, tmp_path):
    r = run_synthetic_campaign(SURFACES[name](), seed=1, parent_dir=tmp_path)
    assert "pareto" not in r.report
    for p in Path(r.work_dir).glob("runs/iter-*/recommendation.json"):
        assert "predicted_front" not in json.loads(p.read_text())
    for p in Path(r.work_dir).glob("runs/iter-*/confirmation.json"):
        assert "pareto" not in json.loads(p.read_text())


@pytest.mark.parametrize("name", sorted(PARETO_SURFACES))
def test_every_oracle_artifact_satisfies_the_pareto_invariants(name, oracle_runs):
    """INV-STAT17 / INV-SEM18 / INV-VOC09 over every oracle campaign."""
    from orchestrator.optimize import invariants as inv

    for seed in SEEDS:
        wd = Path(oracle_runs(name, seed)["work_dir"])
        rep = json.loads((wd / "report.json").read_text())
        assert inv.check_pareto_front(rep["pareto"]) == [], seed
        assert inv.check_pareto_certificate(rep) == [], seed
        assert inv.check_gap_fill_branch(json.loads((wd / "policy.json").read_text())) == []
        for p in wd.glob("runs/iter-*/confirmation.json"):
            conf = json.loads(p.read_text())
            assert inv.check_pareto_front(conf["pareto"]) == [], (seed, p)
            assert inv.check_pareto_certificate(conf) == [], (seed, p)


# ── the infeasible-finalist rule, evaluated (and rejected) ───────────────────


def test_an_infeasible_finalist_still_withholds_certification(tmp_path, monkeypatch):
    """Why ``_INFEASIBLE_FINALIST_CAVEAT`` stays OFF, pinned by the oracle.

    The evaluated alternative let a campaign certify despite an infeasible
    finalist when >= 2 admissible finalists remained, their bound was within
    epsilon and the model was adequate. Over every constrained surface x seeds
    1-8 it raised the certification rate (sla 0->5/8 at 3 rounds,
    deterministic_constraint_axis 0->8/8, pareto_with_constraint 1->7/8 at 2
    rounds) with no false certificate EXCEPT here: on
    ``stochastic_constraint_boundary`` (seed 2, 3 rounds) it certified a
    configuration that is truly INADMISSIBLE -- it passed every one of its own
    replicates by luck while a sibling finalist in the same stochastic region
    did not, which is exactly the evidence the veto reads. Today's rule does not.
    """
    import orchestrator.optimize.stage_runner as sr

    surface = SURFACES["stochastic_constraint_boundary"]()
    ov = {"response": {"primary": {"metric": "m", "direction": "maximize"},
                       "constraints": [{"metric": "stall_ms", "op": "<=", "value": 10}]},
          "policy": {"confirm_max_rounds": 3}}

    def run(flag, sub):
        monkeypatch.setattr(sr, "_INFEASIBLE_FINALIST_CAVEAT", flag)
        return run_synthetic_campaign(surface, seed=2, parent_dir=tmp_path / sub,
                                      campaign_overrides=ov)

    caveat = run(True, "caveat")
    assert caveat.report["certified"] and surface.invalid(caveat.recommendation)
    today = run(False, "today")
    assert not (today.report["certified"] and surface.invalid(today.recommendation))


def _knee_distance_ranking(par):
    """Each front point's signed distance from the line through the two
    extremes, in the record's own normalisation frame (larger = more knee)."""
    import math

    objs = par["objectives"]
    fr = par["frame"]

    def z(mean):
        return [(-1.0 if o["direction"] == "minimize" else 1.0)
                * (mean[o["metric"]] - fr["worst"][o["metric"]]) / fr["range"][o["metric"]]
                for o in objs]

    zs = [z(f["mean"]) for f in par["front"]]
    a = max(range(len(zs)), key=lambda i: (zs[i][0], zs[i][1]))
    b = max(range(len(zs)), key=lambda i: (zs[i][1], zs[i][0]))
    dx, dy = zs[b][0] - zs[a][0], zs[b][1] - zs[a][1]
    n = [dy, -dx]
    norm = math.hypot(*n) or 1.0
    n = [n[0] / norm, n[1] / norm]
    if n[0] + n[1] < 0:
        n = [-n[0], -n[1]]
    return [n[0] * (p[0] - zs[a][0]) + n[1] * (p[1] - zs[a][1]) for p in zs]


@pytest.mark.parametrize("name", ["pareto_convex", "pareto_noisy",
                                  "pareto_with_constraint", "pareto_choice_split"])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_the_knee_is_the_knee_of_the_whole_measured_front(name, seed, oracle_runs):
    """Found on a real Go campaign: with only two confidently-nondominated
    points the knee was chosen among THEM -- degenerate, so the tie-break
    picked an extreme 24% slower than an interior point. The preference ranges
    over the whole measured front; confidence decides certification only."""
    r = oracle_runs(name, seed)
    par = json.loads((Path(r["work_dir"]) / "report.json").read_text())["pareto"]
    if len(par["front"]) < 3:
        pytest.skip("a front of fewer than three points has no interior")
    d = _knee_distance_ranking(par)
    chosen = [i for i, f in enumerate(par["front"])
              if f["levels"] == par["preference"]["chosen"]]
    assert chosen, "the preferred point is not on the reported front"
    assert d[chosen[0]] >= max(d) - 1e-9


def test_the_optimize_package_imports_no_forbidden_dependency():
    """orchestrator/optimize/__init__.py: stdlib + scipy.stats only. An import
    anywhere in the package (module level OR inside a function) is a
    dependency the harness does not declare."""
    import ast

    forbidden = {"numpy", "pandas", "statsmodels", "pyDOE3", "pydoe3", "hypothesis"}
    pkg = Path(__file__).resolve().parents[1] / "orchestrator" / "optimize"
    hits = []
    for py in sorted(pkg.glob("*.py")):
        for node in ast.walk(ast.parse(py.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            hits += [f"{py.name}:{node.lineno} {n}" for n in names
                     if n.split(".")[0] in forbidden]
    assert hits == [], hits


# ── unknown epsilon, simultaneous statuses, incomplete rows, lone points ──────


def test_an_unknown_epsilon_never_rules_a_predicted_rival_out():
    """A2: eps None on an objective is not a zero width. A prediction ahead of
    c on every objective (by eps where eps is known, by anything where it is
    not) is UNRESOLVED, so c is possibly_dominated."""
    objs = _objs()
    c = _mp({"x": 0}, [10.0, 10.1, 9.9], [5.0, 5.1, 4.9])
    pred = pareto.PredictedPoint({"x": 9}, {}, {"f1": 10.5, "f2": 5.01}, {}, "nondominated")
    pooled = {m: pareto.pooled_variance([c], m) for m in ("f1", "f2")}
    known = pareto.measured_front([c], objs, {"f1": 0.1, "f2": 0.1}, delta=0.05,
                                  pooled=pooled, predicted=[pred])
    unknown = pareto.measured_front([c], objs, {"f1": 0.1, "f2": None}, delta=0.05,
                                    pooled=pooled, predicted=[pred])
    assert known[0].status == "confidently_nondominated"  # 0.01 < eps on f2
    assert unknown[0].status == "possibly_dominated"
    assert unknown[0].dominated_by[0]["kind"] == "predicted"
    assert pareto.scalar_epsilon(pareto.Preference("knee"), objs, [0.1, None]) is None


def test_an_unknown_epsilon_withholds_certification(tmp_path):
    """A2 end to end: an objective whose best is exactly 0 has no reference
    for a pct epsilon. The campaign reports it, computes no gap threshold
    from a fake zero, and does not certify."""
    import dataclasses

    s = PARETO_SURFACES["pareto_convex"]()
    f1, _ = s.objectives
    zero = {"metric": "f2", "direction": "maximize", "fn": lambda lv: 0.0, "noise_sd": 0.0}
    s = dataclasses.replace(s, objectives=(f1, zero))
    r = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path)
    par = r.report["pareto"]
    assert par["epsilon"]["f2"] is None and par["epsilon_unknown"] == ["f2"]
    assert r.report["certified"] is False
    assert "epsilon_unknown" in r.report["certification_withheld"]


def test_dominance_statuses_are_simultaneous_over_the_front():
    """A3: a rival resolvable at delta / ((N-1) K) but not at
    delta / (N (N-1) K) leaves the point possibly_dominated."""
    from scipy.stats import t as student_t

    objs, eps = _objs(), {"f1": 0.1, "f2": 0.1}
    pooled = {"f1": (1.0, 30), "f2": (1.0, 30)}  # se of a difference: 1.0
    t_old = student_t.ppf(1 - 0.05 / ((3 - 1) * 2), 30)
    t_new = student_t.ppf(1 - 0.05 / (3 * 2 * 2), 30)
    g = (t_old + t_new) / 2 - 0.1  # d trails c on f1 by g, leads on f2
    c = _mp({"x": 0}, [10.0, 10.0], [10.0, 10.0])
    d = _mp({"x": 1}, [10.0 - g, 10.0 - g], [11.0, 11.0])
    far = _mp({"x": 2}, [0.0, 0.0], [0.0, 0.0])
    assert -g + t_old < 0.1 < -g + t_new
    st = {e.index: e.status for e in pareto.measured_front([c, d, far], objs, eps,
                                                           delta=0.05, pooled=pooled)}
    assert st[0] == "possibly_dominated"


def test_a_lone_configuration_has_no_regret_bound():
    """A5: no rival is no bound -- never a certifying 0.0."""
    objs = _objs()
    p = [_mp({"x": 0}, [10.0, 10.1], [1.0, 1.1])]
    pooled = {m: pareto.pooled_variance(p, m) for m in ("f1", "f2")}
    frame = pareto.make_frame(objs, [x.means() for x in p], {"f1": 0.1, "f2": 0.1})
    reg, why = pareto.scalar_regret(objs, p, 0, [0], [1.0, 1.0], frame, pooled, delta=0.05)
    assert reg is None and why.startswith("no_feasible_rival")
    reg, why = pareto.min_improvement_regret(objs, p, 0, [0], frame, [0.0, 0.0], pooled,
                                             delta=0.05)
    assert reg is None and why.startswith("no_feasible_rival")


def test_a_finalist_missing_a_secondary_objective_is_unmeasured(tmp_path, monkeypatch):
    """A4 / A6: a configuration whose rows report objective 1 but not
    a usable objective 2 (here +inf) is listed in pareto.excluded_incomplete, never silently
    dropped and never re-based on its fitting rows; as a confirm finalist it
    is `unmeasured` and certification is withheld."""
    import orchestrator.optimize.synthetic as syn

    real = syn._observe

    # +inf, not a vanished key: the adapter contract already aborts an epoch
    # whose key disappears or turns null, and a NaN is the semantic
    # nan_response exception. A non-finite number of the right type is what
    # used to fall through silently.
    def drop_f2(surface, levels, **kw):
        obs = real(surface, levels, **kw)
        if levels.get("A") == 16 and levels.get("B") == 16:
            obs["f2"] = float("inf")
        return obs

    monkeypatch.setattr(syn, "_observe", drop_f2)
    r = run_synthetic_campaign(PARETO_SURFACES["pareto_convex"](), seed=1, parent_dir=tmp_path)
    par = r.report["pareto"]
    gone = [x for x in par.get("excluded_incomplete") or []
            if x["levels"] == {"A": 16, "B": 16}]
    assert gone and gone[0]["missing"] == ["f2"]
    assert all(f["levels"] != {"A": 16, "B": 16} for f in par["front"])
    seated = [f for p in Path(r.work_dir).glob("runs/iter-*/confirmation.json")
              for f in json.loads(p.read_text())["finalists"]
              if f["levels"] == {"A": 16, "B": 16}]
    assert seated, "the f1 extreme is seated as a finalist on this seed"
    assert all(f["status"] == "unmeasured" for f in seated)
    assert gone[0]["source"] == "confirm"
    assert r.report["certified"] is False
    assert "finalist_unmeasured" in r.report["certification_withheld"]
