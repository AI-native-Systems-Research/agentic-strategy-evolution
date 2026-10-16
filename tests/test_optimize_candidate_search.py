"""The candidate search that replaces enumeration above ``decide.CANDIDATE_CAP``.

The candidate space is the product of the fitted factors' axes (up to 9 coded
points per refinable numeric factor), so it is exponential in the number of
knobs: 9^12 = 2.8e11 at twelve. At or below the cap it is still enumerated
exactly; above it ``decide._scored`` runs a seeded multi-start coordinate
ascent. These tests pin, on fitted models built directly:

  (a) the search agrees with enumeration where both can run, and is never
      worse than the best configuration it was seeded with;
  (b) at 12 and 16 knobs it reaches a planted grid optimum, in seconds;
  (c) measured-inadmissible and confidently-infeasible points are excluded at
      every evaluated point, exactly as in enumeration;
  (d) at or under the cap nothing changes -- enumeration, and no
      ``candidate_space`` in ``recommendation.json``;
  (e) above the cap a full campaign writes a schema-valid ``candidate_space``,
      says so in ``report.md``, and still finds the answer.

Every test is behavioural: answers, artifacts and wall-clock, never which
helper ran.
"""
from __future__ import annotations

import dataclasses
import itertools
import json
import random
import time
from pathlib import Path

import jsonschema
import pytest

from orchestrator.optimize import decide, pareto
from orchestrator.optimize.constraint_models import (
    ConstraintModel,
    ObjectiveModel,
    confidently_infeasible,
)
from orchestrator.optimize.effects import Effect, Fit
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.invariants import check_candidate_space
from orchestrator.optimize.synthetic import _numeric

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "orchestrator" / "schemas"
                     / "recommendation.schema.json").read_text())


def _factors(k: int):
    """``k`` refinable numerics (5 declared levels), so each axis has 9 points."""
    return parse_factors([_numeric(f"X{i:02d}", levels=(1, 5, 9, 13, 17))
                          for i in range(k)])


def _ids(k: int) -> list[str]:
    return [f"X{i:02d}" for i in range(k)]


def _random_quadratic(k: int, rng: random.Random, *, se: float | None = None) -> Fit:
    """A full quadratic (mains, every 2fi, pure quadratics) with random signs:
    indefinite in general, so the argmax can sit anywhere, corners included."""
    ids = _ids(k)
    eff = [Effect(i, (i,), rng.gauss(0, 1), se=se) for i in ids]
    eff += [Effect(a + b, (a, b), rng.gauss(0, 0.5), se=se)
            for a, b in itertools.combinations(ids, 2)]
    quad = [Effect(i + i, (i, i), rng.gauss(0, 1), se=se) for i in ids]
    return Fit(rng.gauss(0, 1), tuple(eff), 30, quadratic=tuple(quad),
               pure_error_var=None if se is None else 0.01,
               pure_error_df=0 if se is None else 10)


def _planted(k: int, rng: random.Random, target: dict, *, inter: float = 0.5,
             se: float | None = None) -> Fit:
    """``y = -sum a_i (x_i - t_i)^2 + sum b_ij (x_i - t_i)(x_j - t_j)``, expanded
    into fitted terms; diagonally dominant, so ``target`` (a grid point) is the
    unique maximum. ``inter`` scales the interactions."""
    ids = _ids(k)
    t = target
    a = {i: rng.uniform(0.5, 2.0) for i in ids}
    b = {(p, q): rng.uniform(-inter, inter) * min(a[p], a[q]) * 2 / (k - 1)
         for p, q in itertools.combinations(ids, 2)}
    b0 = -sum(a[i] * t[i] ** 2 for i in ids) + sum(v * t[p] * t[q] for (p, q), v in b.items())
    lin = {i: 2 * a[i] * t[i] for i in ids}
    for (p, q), v in b.items():
        lin[p] -= v * t[q]
        lin[q] -= v * t[p]
    eff = [Effect(i, (i,), lin[i], se=se) for i in ids]
    eff += [Effect(p + q, (p, q), v, se=se) for (p, q), v in b.items()]
    quad = [Effect(i + i, (i, i), -a[i], se=se) for i in ids]
    return Fit(b0, tuple(eff), 30, quadratic=tuple(quad),
               pure_error_var=None if se is None else 0.01,
               pure_error_df=0 if se is None else 10)


def _grid_target(k: int, rng: random.Random) -> dict:
    codes = [c for c, _ in decide._axis(_factors(1)[0])]
    return {i: rng.choice(codes) for i in _ids(k)}


# ─── (a) agreement with enumeration, and never worse than the pool ──────────


def test_search_finds_the_enumerated_argmax_on_random_quadratics():
    """Forced on (``cap=0``) with a deliberately tiny uniform sample, so the
    ascent rather than the sample does the work: over 180 random indefinite
    quadratics at k = 3, 4, 5 and both directions, the search names the
    enumerated argmax in at least 97% of cases (measured: 357/360 at sample 50),
    and where it misses, the shortfall is a small fraction of the optimum."""
    hits = n = 0
    shortfall = []
    for k in (3, 4, 5):
        fs = _factors(k)
        for s in range(30):
            fit = _random_quadratic(k, random.Random(1000 * k + s))
            for d in ("maximize", "minimize"):
                kw = dict(direction=d, fitted_ids=_ids(k), held_fixed={})
                ex = decide.recommend(fit, fs, **kw)
                se = decide.recommend(fit, fs, cap=0, sample=50, **kw)
                n += 1
                if ex.levels == se.levels:
                    hits += 1
                else:
                    shortfall.append(abs(ex.predicted - se.predicted)
                                     / max(abs(ex.predicted), 1e-9))
    assert hits >= 0.97 * n, (hits, n)
    assert max(shortfall, default=0.0) < 0.05, sorted(shortfall)[-5:]


@pytest.mark.parametrize("k", [3, 4, 5, 12])
def test_search_is_never_worse_than_the_best_configuration_it_was_seeded_with(k):
    """Every seeded configuration is a start candidate and the ascent only moves
    uphill, so the answer is at least as good as the best seed. Property over
    random models and random seed configurations."""
    fs = _factors(k)
    axis = [lv for _c, lv in decide._axis(fs[0])]
    for s in range(20):
        rng = random.Random(7 * k + s)
        fit = _random_quadratic(k, rng)
        seeds = [{fid: rng.choice(axis) for fid in _ids(k)} for _ in range(12)]
        for d in ("maximize", "minimize"):
            sign = 1.0 if d == "maximize" else -1.0
            rec = decide.recommend(fit, fs, direction=d, fitted_ids=_ids(k),
                                   held_fixed={}, cap=0, sample=0, seed_levels=seeds)
            code = {lv: c for c, lv in decide._axis(fs[0])}
            best_seed = max(sign * decide.predict(fit, {fid: code[v] for fid, v in sd.items()})
                            for sd in seeds)
            assert sign * rec.predicted >= best_seed - 1e-12


def test_search_is_deterministic():
    """Same fit, same exclusions, same seed: the same evaluated set and the same
    ranking -- so a searched campaign's artifacts are reproducible."""
    k = 12
    fs = _factors(k)
    fit = _random_quadratic(k, random.Random(3))
    kw = dict(direction="maximize", fitted_ids=_ids(k), held_fixed={}, top=None)
    a, b = decide.ranked(fit, fs, **kw), decide.ranked(fit, fs, **kw)
    assert [c.levels for c in a] == [c.levels for c in b]
    assert a.space == b.space


# ─── (b) scale: 12 and 16 knobs ─────────────────────────────────────────────


@pytest.mark.parametrize("k", [12, 16])
def test_search_reaches_a_planted_optimum_at_many_knobs_in_seconds(k):
    """A planted grid optimum among 9^12 = 2.8e11 (9^16 = 1.9e15) candidates is
    found on every seed, and each ``ranked(top=None)`` takes well under the
    stated 5 s (measured ~0.2 s at k=12, ~0.35 s at k=16)."""
    fs = _factors(k)
    worst = 0.0
    for s in range(6):
        rng = random.Random(s)
        target = _grid_target(k, rng)
        fit = _planted(k, rng, target)
        t0 = time.perf_counter()
        r = decide.ranked(fit, fs, direction="maximize", fitted_ids=_ids(k),
                          held_fixed={}, top=None)
        worst = max(worst, time.perf_counter() - t0)
        assert r[0].coded == pytest.approx(target), s
        assert r.space.exhaustive is False
        assert r.space.size == 9 ** k
        assert r.space.method == "sampled_coordinate_ascent"
        assert len(r) <= r.space.evaluated < 9 ** k
    assert worst < 5.0, worst


def test_sixteen_knob_recommend_ranked_and_predicted_front_finish_in_seconds():
    """The whole fitting-stage path at 16 knobs and two objectives: the primary
    argmax, the full ranked set, and the predicted front over it. Requirement:
    seconds, not minutes (measured ~1.5 s in total). The front must reach each
    objective's planted optimum -- its extremes."""
    k = 16
    fs = _factors(k)
    rng = random.Random(11)
    t1, t2 = _grid_target(k, rng), _grid_target(k, rng)
    f1 = _planted(k, rng, t1, se=0.01)
    f2 = _planted(k, rng, t2, se=0.01)
    objs = [pareto.Objective("a", "maximize", {}), pareto.Objective("b", "maximize", {})]
    models = {"a": ObjectiveModel("a", "maximize", f1, ""),
              "b": ObjectiveModel("b", "maximize", f2, "")}
    t0 = time.perf_counter()
    kw = dict(direction="maximize", fitted_ids=_ids(k), held_fixed={})
    rec = decide.recommend(f1, fs, **kw)
    scored = decide.ranked(f1, fs, top=None, objectives=((f1, "maximize"), (f2, "maximize")),
                           **kw)
    front, n_nd = pareto.predicted_front(scored, models, objs, delta=0.05)
    elapsed = time.perf_counter() - t0
    assert elapsed < 10.0, elapsed
    assert rec.coded == pytest.approx(t1)
    nd = [p for p in front if p.status == "nondominated"]
    assert n_nd >= 3
    assert any(p.coded == pytest.approx(t1) for p in nd)
    assert any(p.coded == pytest.approx(t2) for p in nd)


# ─── (c) exclusions at every evaluated point ────────────────────────────────


def test_search_never_returns_a_confidently_infeasible_candidate():
    """A constraint model that confidently rejects every coded X00 > 0 moves a
    planted optimum at X00 = +1 to the best feasible X00 (0), and NO evaluated
    candidate the search returns is confidently infeasible."""
    k = 12
    fs = _factors(k)
    rng = random.Random(5)
    target = {**_grid_target(k, rng), "X00": 1.0}
    fit = _planted(k, rng, target, inter=0.0)
    cfit = Fit(0.0, (Effect("X00", ("X00",), 10.0, se=1e-3),), 30,
               pure_error_var=1e-6, pure_error_df=10)
    cm = [ConstraintModel("lat", "<=", 0.0, cfit, "")]
    r = decide.ranked(fit, fs, direction="maximize", fitted_ids=_ids(k), held_fixed={},
                      top=None, constraint_models=cm, constraint_delta=0.05)
    assert not r.space.exhaustive
    assert all(not confidently_infeasible(cm, c.coded, delta=0.05) for c in r)
    assert r[0].coded["X00"] == 0.0
    assert r[0].coded == pytest.approx({**target, "X00": 0.0})


def test_search_never_returns_a_measured_inadmissible_configuration():
    """``exclude_levels`` -- a configuration measured infeasible -- is never
    recommended, even when it is the model's planted optimum."""
    k = 12
    fs = _factors(k)
    rng = random.Random(9)
    target = _grid_target(k, rng)
    fit = _planted(k, rng, target)
    best = decide.recommend(fit, fs, direction="maximize", fitted_ids=_ids(k), held_fixed={})
    assert best.coded == pytest.approx(target)
    r = decide.ranked(fit, fs, direction="maximize", fitted_ids=_ids(k), held_fixed={},
                      top=None, exclude_levels=[best.levels])
    assert all(c.levels != best.levels for c in r)
    assert r[0].levels != best.levels


# ─── (d) at or under the cap: unchanged ─────────────────────────────────────


def test_at_or_under_the_cap_the_space_is_enumerated_exactly():
    """Under the cap, ``ranked(top=None)`` is every candidate of the product,
    scored by ``predict``, and records itself exhaustive."""
    k = 4
    fs = _factors(k)
    fit = _random_quadratic(k, random.Random(1))
    r = decide.ranked(fit, fs, direction="maximize", fitted_ids=_ids(k), held_fixed={},
                      top=None)
    assert r.space == decide.CandidateSpace(True, 9 ** k, 9 ** k, "enumeration", None)
    enum = decide.candidates(_ids(k), fs, held_fixed={})
    assert sorted(json.dumps(c.levels, sort_keys=True) for c in r) == sorted(
        json.dumps(c.levels, sort_keys=True) for c in enum)
    assert max(decide.predict(fit, c.coded) for c in enum) == r[0].predicted


def test_the_cap_keeps_every_oracle_surface_and_a_26k_campaign_exhaustive():
    """The cap is chosen so every campaign this kind has run is enumerated: four
    refinable knobs plus a two-level and a choice (~26k) is under it."""
    from orchestrator.optimize.synthetic import PARETO_SURFACES, SURFACES

    for mk in list(SURFACES.values()) + list(PARETO_SURFACES.values()):
        surf = mk()
        fs = parse_factors(list(surf.factors))
        assert decide.space_size([f.id for f in fs], fs) <= decide.CANDIDATE_CAP
    fs = _factors(4) + parse_factors([_numeric("T", levels=(1, 2)), _numeric("U", levels=(1, 2))])
    assert decide.space_size([f.id for f in fs], fs) == 26244 <= decide.CANDIDATE_CAP


def test_an_enumerated_campaign_writes_no_candidate_space(tmp_path):
    """Byte-identity under the cap at the artifact: ``candidate_space`` appears
    only when the space was searched."""
    from orchestrator.optimize.harness import run_synthetic_campaign
    from orchestrator.optimize.report_md import render_report_markdown
    from orchestrator.optimize.synthetic import SURFACES

    res = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path)
    recs = list(Path(res.work_dir).glob("runs/iter-*/recommendation.json"))
    assert recs
    assert all("candidate_space" not in json.loads(p.read_text()) for p in recs)
    assert "searched, not enumerated" not in render_report_markdown(Path(res.work_dir))


# ─── (e) above the cap: recorded, schema-valid, still right ─────────────────


@pytest.mark.parametrize("surface", ["bowl", "choice_x_numeric", "sla"])
def test_a_searched_campaign_records_candidate_space_and_still_finds_the_optimum(
        tmp_path, monkeypatch, surface):
    """With the cap forced below the space, every fitting stage writes a
    schema-valid ``candidate_space``, ``report.md`` says the space was searched,
    and the campaign's answer is as good as the enumerated campaign's."""
    from orchestrator.optimize.harness import run_synthetic_campaign
    from orchestrator.optimize.report_md import render_report_markdown
    from orchestrator.optimize.synthetic import SURFACES

    base = run_synthetic_campaign(SURFACES[surface](), seed=2, parent_dir=tmp_path / "e")
    monkeypatch.setattr(decide, "CANDIDATE_CAP", 1)
    res = run_synthetic_campaign(SURFACES[surface](), seed=2, parent_dir=tmp_path / "s")
    recs = sorted(Path(res.work_dir).glob("runs/iter-*/recommendation.json"))
    assert recs
    for p in recs:
        doc = json.loads(p.read_text())
        jsonschema.validate(doc, SCHEMA)
        cs = doc["candidate_space"]
        assert cs["exhaustive"] is False and cs["method"] == "sampled_coordinate_ascent"
        assert 1 <= cs["evaluated"] and cs["seed"] == decide.SEARCH_SEED
        assert "NOT over all of X_valid" in doc["residual_regret_model"]["detail"]
        assert check_candidate_space(doc) == []
    assert "Candidate space searched, not enumerated" in render_report_markdown(
        Path(res.work_dir))
    assert res.true_gap <= base.true_gap + 1e-9, (res.true_gap, base.true_gap)


def test_a_searched_multi_objective_campaign_keeps_its_front(tmp_path, monkeypatch):
    """Multi-objective, search forced: the predicted front is built from the
    evaluated set, recorded as such, and the campaign's reported front covers
    the true front as well as the enumerated campaign's does."""
    from orchestrator.optimize.harness import evaluate_pareto_campaign
    from orchestrator.optimize.synthetic import PARETO_SURFACES

    base = evaluate_pareto_campaign(PARETO_SURFACES["pareto_convex"](), seed=1,
                                    parent_dir=tmp_path / "e")
    monkeypatch.setattr(decide, "CANDIDATE_CAP", 1)
    res = evaluate_pareto_campaign(PARETO_SURFACES["pareto_convex"](), seed=1,
                                   parent_dir=tmp_path / "s")
    recs = list(Path(res["work_dir"]).glob("runs/iter-*/recommendation.json"))
    assert recs
    for p in recs:
        doc = json.loads(p.read_text())
        jsonschema.validate(doc, SCHEMA)
        assert doc["candidate_space"]["exhaustive"] is False
        assert check_candidate_space(doc) == []
        assert doc["predicted_front"]
    assert res["coverage"] >= base["coverage"] - 1e-9, (res["coverage"], base["coverage"])


def test_candidate_space_schema_rejects_an_exhaustive_record():
    """The record exists to flag a non-exhaustive search: ``exhaustive: true``
    would contradict its presence, so the schema refuses it."""
    good = {"exhaustive": False, "size": 9 ** 12, "evaluated": 4730,
            "method": "sampled_coordinate_ascent", "seed": 0,
            "constraint_models_applied": None}
    sub = SCHEMA["properties"]["candidate_space"]
    jsonschema.validate(good, sub)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**good, "exhaustive": True}, sub)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**good, "method": "enumeration"}, sub)


def test_ranked_shortlist_is_a_plain_list_and_the_whole_set_carries_the_record():
    k = 12
    fs = _factors(k)
    fit = _random_quadratic(k, random.Random(2))
    kw = dict(direction="maximize", fitted_ids=_ids(k), held_fixed={})
    top = decide.ranked(fit, fs, top=5, **kw)
    whole = decide.ranked(fit, fs, top=None, **kw)
    assert [c.levels for c in top] == [c.levels for c in whole[:5]]
    assert dataclasses.asdict(whole.space)["evaluated"] >= len(whole)


# ─── review fixes: a narrow feasible region the pool misses ─────────────────


def _narrow_feasible(k: int = 5):
    """Primary ``-sum x`` (best at every factor's LOW end) against a constraint
    ``sum x >= 4.9`` with a tiny SE: confidently feasible only at the all-HIGH
    corner, a region no uniform sample of 59,049 points is likely to hit."""
    ids = _ids(k)
    fit = Fit(0.0, tuple(Effect(i, (i,), -1.0) for i in ids), 30)
    cfit = Fit(0.0, tuple(Effect(i, (i,), 1.0, se=1e-4) for i in ids), 30,
               pure_error_var=1e-8, pure_error_df=10)
    return ids, fit, [ConstraintModel("thr", ">=", 4.9, cfit, "")]


def test_search_finds_a_narrow_feasible_region_enumeration_finds():
    """Reviewer repro (k=5, 59,049 > cap). Enumeration recommends the feasible
    all-17 corner; the search must too -- it may NOT drop the constraint models
    just because its pool held no feasible point, since the whole space is not
    infeasible. The record says the models were applied."""
    ids, fit, cm = _narrow_feasible()
    fs = _factors(len(ids))
    kw = dict(direction="maximize", fitted_ids=ids, held_fixed={},
              constraint_models=cm, constraint_delta=0.05)
    ex = decide.recommend(fit, fs, cap=10 ** 6, **kw)
    assert set(ex.levels.values()) == {17}
    r = decide.ranked(fit, fs, top=None, **kw)
    assert not r.space.exhaustive
    assert r.space.constraint_models_applied is True
    assert confidently_infeasible(cm, r[0].coded, delta=0.05) == []
    assert r[0].levels == ex.levels
    assert all(confidently_infeasible(cm, c.coded, delta=0.05) == [] for c in r)


def test_search_drops_constraint_models_only_when_nothing_feasible_is_found():
    """A constraint no point of the space can satisfy (``sum x >= 6`` over coded
    x in [-1, 1]^5): as in enumeration the exclusion is not applied, and the
    record says so."""
    ids, fit, cm = _narrow_feasible()
    cm = [dataclasses.replace(cm[0], value=6.0)]
    r = decide.ranked(fit, _factors(len(ids)), direction="maximize", fitted_ids=ids,
                      held_fixed={}, top=None, constraint_models=cm)
    assert r.space.constraint_models_applied is False
    assert set(r[0].levels.values()) == {1}
