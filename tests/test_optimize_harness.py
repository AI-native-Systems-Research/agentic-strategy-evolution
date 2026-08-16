"""End-to-end oracle tests: a synthetic campaign's answer vs. the truth.

xfail(strict=True) marks encode behaviour the paper requires and the branch
does not yet deliver; each names the task that must flip it. A strict xfail
that starts passing FAILS the suite, so flipping is deliberate.
"""
from __future__ import annotations

import dataclasses
import json
import os

import pytest

from orchestrator.optimize import harness
from orchestrator.optimize.harness import run_synthetic_campaign, synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES


def _gap_pct(res):
    return abs(res.true_gap) / max(abs(res.true_best), 1e-9) * 100.0


def test_additive_surface_recommendation_is_within_two_percent_of_truth(tmp_path):
    res = run_synthetic_campaign(SURFACES["additive"](), seed=1, parent_dir=tmp_path)
    assert res.recommendation, res.report
    assert _gap_pct(res) <= 2.0, (res.recommendation, res.true_optimum)


def test_bowl_surface_confirms_near_the_interior_maximum(tmp_path):
    res = run_synthetic_campaign(SURFACES["bowl"](), seed=2, parent_dir=tmp_path)
    assert abs(res.recommendation["A"] - 9) <= 1 and abs(res.recommendation["B"] - 11) <= 1


@pytest.mark.xfail(strict=True, reason="Task 7: argmax over X_valid replaces the stationary point")
def test_saddle_surface_recommends_a_corner_not_the_saddle_point(tmp_path):
    res = run_synthetic_campaign(SURFACES["saddle"](), seed=3, parent_dir=tmp_path)
    assert _gap_pct(res) <= 2.0, (res.recommendation, res.true_optimum)


@pytest.mark.xfail(strict=True, reason="Task 7: choice factors enter the argmax instead of being held at levels[0]")
def test_choice_x_numeric_recommends_the_on_branch(tmp_path):
    """The `on` branch must be recommended BECAUSE the model chose it.

    The brief's assertion (``recommendation["C"] == "on"`` plus a 2% gap)
    XPASSes today, and strict xfail makes an unexpected pass a failure — so
    the assertion, not the marker, is what needed strengthening. Measured on
    this branch (seeds 4, 104, 204, all identical):

      * refine (iter-3) holds ``C`` at ``levels[0] == "off"`` for all eight
        runs — the whole refine stage measures the ANTI-optimal branch, which
        is exactly the ``levels[0]`` bug Task 7 names.
      * the quadratic over that branch solves to coded ``A = +45.8``, far
        outside the hull, so ``_read_confirm_at`` discards it and confirm
        falls back to ``_best_observed``, which reaches back to a SCREEN row
        and happens to be ``{A: 16, C: "on"}``.

    So the right answer arrives by accident of a fallback, with a gap of 0%.
    Asserting on the recommendation alone therefore cannot distinguish "the
    argmax included the choice factor" from "refine wasted itself on the
    wrong branch and a guard rescued the campaign". This test asserts the
    mechanism instead: refine must have EXPLORED ``C = "on"``, which is what
    Task 7's "refine's held-fixed level is the screen recommendation's level"
    rule delivers. The recommendation assertions are kept alongside it so
    the answer is still checked.
    """
    res = run_synthetic_campaign(SURFACES["choice_x_numeric"](), seed=4, parent_dir=tmp_path)
    assert res.recommendation["C"] == "on" and _gap_pct(res) <= 2.0
    refine_c = {
        json.loads(line)["levels"]["C"]
        for line in (res.work_dir / "runs" / "iter-3" / "runs.jsonl").read_text().splitlines()
        if line.strip()
    }
    assert "on" in refine_c, (
        f"refine explored C={sorted(refine_c)} only; the choice factor was "
        f"held at levels[0] instead of at the screen recommendation's level"
    )


@pytest.mark.xfail(strict=True, reason="Task 9: finalists measured infeasible at confirm are excluded from the recommendation")
def test_sla_surface_never_recommends_an_invalid_point(tmp_path):
    """Feasible is necessary but not sufficient — it must be the valid ARGMAX.

    The brief's assertion (feasibility alone) XPASSes today, and strict xfail
    makes an unexpected pass a failure. Measured on this branch (seeds 5, 105,
    205, all identical): the campaign recommends ``{A: 16, B: 2}``, which is
    feasible (``p99_ms = 34 <= 40``) but 6.12% below the true constrained
    optimum ``{A: 16, B: 8}`` (19.6). Feasibility comes for free because
    ``_best_observed`` already filters to ``status == "complete"`` and the
    runner marks the constraint-violating rows ``infeasible`` — so the
    brief's assertion tests a filter that already exists, not the exclusion
    Task 9 adds.

    The paper's claim is the argmax over X_valid, so the gap bound is the
    discriminating half. Both halves are asserted: Task 9's shortlist confirm
    must land on a point that is BOTH valid and within 2% of the constrained
    truth.
    """
    s = SURFACES["sla"]()
    res = run_synthetic_campaign(
        s, seed=5, parent_dir=tmp_path,
        campaign_overrides={"response": {"primary": {"metric": "m", "direction": "maximize"},
                                          "constraints": [{"metric": "p99_ms", "op": "<=", "value": 40}]}},
    )
    assert not s.invalid(res.recommendation), res.recommendation
    assert _gap_pct(res) <= 2.0, (res.recommendation, res.true_optimum)


@pytest.mark.xfail(strict=True, reason="Task 11: an out-of-hull optimum ends the epoch instead of confirming anyway")
def test_bowl_out_of_hull_ends_the_epoch(tmp_path):
    res = run_synthetic_campaign(SURFACES["bowl_out_of_hull"](), seed=6, parent_dir=tmp_path)
    assert res.path[-1] == "exception"


@pytest.mark.xfail(strict=True, reason="Task 11: a NaN response is a semantic exception, not a fit over the remaining rows")
def test_nan_corner_ends_the_epoch(tmp_path):
    res = run_synthetic_campaign(SURFACES["nan_at_corner"](), seed=7, parent_dir=tmp_path)
    assert res.path[-1] == "exception"


# ── the harness's own contract ───────────────────────────────────────────
#
# Thirteen later tasks import these interfaces, so a silent change to any of
# them would be measured as a change in the machinery under test. These
# assertions pin the seams themselves.


#: Surfaces whose factor set cannot support the DEFAULT ``design.refine``,
#: because validator rule 4 requires >= 2 refinable factors (numeric with more
#: than two levels) and these declare fewer. Measured, not assumed — see
#: ``test_the_default_campaign_is_valid_except_where_refine_has_too_few_factors``.
#: A test needing any of them must drop refine from ``stages``.
_REFINE_UNSUPPORTED = {
    "choice_x_numeric": 1,   # A is refinable; C is a choice factor
    "drift": 0,              # both factors are 2-level numerics
    "interaction_only": 0,   # all four factors are 2-level numerics
    "nan_at_corner": 0,      # both factors are 2-level numerics
}


def test_the_default_campaign_is_valid_except_where_refine_has_too_few_factors():
    """The dict the harness feeds run_stage, measured against the validator.

    ``run_stage`` does NOT validate, so nothing in the pipeline would notice a
    malformed campaign — every later assertion would be measured against an
    experiment the validator would have rejected. This test is the only place
    the two are compared.

    The finding it pins: the default ``design.refine`` block is unsupportable
    on four of the nine surfaces, because rule 4 requires at least two
    refinable factors and those surfaces declare 0 or 1. ``choice_x_numeric``
    is the consequential one — its xfail test is ABOUT refine's held-fixed
    level, and it runs a refine stage the validator would reject. Recorded
    rather than papered over: the fix belongs to whichever task owns the
    default (see the task-3 report), not to an assertion that pretends the
    campaign is clean.
    """
    from orchestrator.validate import validate_optimization_campaign

    offenders = {}
    for key in sorted(SURFACES):
        problems = [p for p in validate_optimization_campaign(synthetic_campaign(SURFACES[key]()))
                    if not p.startswith("WARN:")]
        if problems:
            offenders[key] = problems
    assert sorted(offenders) == sorted(_REFINE_UNSUPPORTED), sorted(offenders)
    for key, problems in offenders.items():
        assert len(problems) == 1, (key, problems)
        assert "design.refine is set but only" in problems[0], (key, problems[0])
        assert f"only {_REFINE_UNSUPPORTED[key]} factor(s) are refinable" in problems[0]


def test_dropping_refine_makes_every_surface_a_valid_campaign():
    """The escape hatch is valid, not merely runnable.

    Whichever task fixes the default will want this: with refine dropped, all
    nine surfaces pass the validator with no hard error, so a schedule of
    verify -> screen -> confirm is a sound fallback for the four above.
    """
    from orchestrator.validate import validate_optimization_campaign

    for key in sorted(SURFACES):
        campaign = synthetic_campaign(
            SURFACES[key](),
            design={"screen": {"resolution": 5, "center_points": 4},
                    "confirm": {"replicates": 3}},
            stages=["verify", "screen", "confirm"],
        )
        problems = [p for p in validate_optimization_campaign(campaign)
                    if not p.startswith("WARN:")]
        assert problems == [], (key, problems)


def test_campaign_overrides_replace_a_whole_optimization_key():
    campaign = synthetic_campaign(
        SURFACES["sla"](), stages=["verify", "screen", "confirm"],
    )
    assert campaign["optimization"]["stages"] == ["verify", "screen", "confirm"]
    # untouched keys survive
    assert campaign["optimization"]["response"]["primary"]["metric"] == "m"


def test_the_run_id_is_unique_per_seed_so_two_seeds_do_not_collide(tmp_path):
    """Two seeds under one parent_dir must not share a work_dir.

    ``setup_work_dir`` refuses to clobber a same-named campaign, and a shared
    work_dir would also let seed 1's runs.jsonl feed seed 2's
    ``_best_observed`` — a cross-contaminated oracle.
    """
    a = run_synthetic_campaign(SURFACES["additive"](), seed=1, parent_dir=tmp_path)
    b = run_synthetic_campaign(SURFACES["additive"](), seed=2, parent_dir=tmp_path)
    assert a.work_dir != b.work_dir
    assert a.work_dir.is_relative_to(tmp_path) and b.work_dir.is_relative_to(tmp_path)


def test_the_campaign_parent_env_var_is_restored(tmp_path, monkeypatch):
    """Leaking NOUS_CAMPAIGN_PARENT would relocate every later campaign.

    A test that ran the harness and then exercised an unrelated campaign
    would silently write into the first test's tmp_path.
    """
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", "/sentinel/value")
    run_synthetic_campaign(SURFACES["additive"](), seed=8, parent_dir=tmp_path)
    assert os.environ["NOUS_CAMPAIGN_PARENT"] == "/sentinel/value"


def test_the_env_var_is_removed_again_when_it_was_not_set(tmp_path, monkeypatch):
    monkeypatch.delenv("NOUS_CAMPAIGN_PARENT", raising=False)
    run_synthetic_campaign(SURFACES["additive"](), seed=9, parent_dir=tmp_path)
    assert "NOUS_CAMPAIGN_PARENT" not in os.environ


def test_the_result_is_a_frozen_value_type(tmp_path):
    res = run_synthetic_campaign(SURFACES["additive"](), seed=10, parent_dir=tmp_path)
    with pytest.raises(dataclasses.FrozenInstanceError):
        res.recommendation = {}


def test_no_recommendation_gives_an_infinite_gap_rather_than_a_plausible_one(tmp_path):
    """``drift`` is built from 2-level numerics, so the default schedule's
    refine stage aborts with "nothing to refine" and no confirmation is
    written. The gap must then be ``inf``, not a number a later assertion
    could pass by accident.
    """
    res = run_synthetic_campaign(SURFACES["drift"](), seed=12, parent_dir=tmp_path)
    assert res.recommendation == {}
    assert res.true_gap == float("inf")
    assert res.path[-1].startswith("aborted:")


def test_skipping_refine_lets_a_two_level_surface_reach_its_optimum(tmp_path):
    """The documented escape hatch for ``drift`` / ``interaction_only``.

    Tie-safe by construction: ``interaction_only``'s optimum is tied 162 ways
    (its ``fn`` never reads C or D), so the response is asserted, never the
    levels.
    """
    stages = {"stages": ["verify", "screen", "confirm"]}
    for key in ("drift", "interaction_only"):
        s = SURFACES[key]()
        res = run_synthetic_campaign(
            s, seed=13, parent_dir=tmp_path / key, campaign_overrides=stages,
        )
        assert res.path == ["verify", "screen", "confirm"], (key, res.path)
        assert s.fn(res.recommendation) == pytest.approx(res.true_best, abs=1e-9), (
            key, res.recommendation
        )


def test_the_recommendation_basis_names_the_artifact_it_came_from(tmp_path):
    """Today's only source is ``confirmation.json``; Task 9 adds report.json.

    Recording WHICH artifact answered is what lets a later task tell "the
    policy produced a recommendation" from "the legacy confirm fallback did".
    """
    res = run_synthetic_campaign(SURFACES["bowl"](), seed=14, parent_dir=tmp_path)
    assert res.basis == "confirmation.json"
    assert res.report == {}
    assert res.residual_regret is None and res.residual_regret_terminal is None


def test_the_recommendation_comes_from_the_LAST_confirmation_not_the_first(tmp_path):
    """``_latest_iter_dirs`` sorts numerically, so iter-10 beats iter-2.

    Lexicographic order would return a stale confirmation on any campaign
    reaching double digits — a silently wrong answer from the oracle itself.
    """
    res = run_synthetic_campaign(SURFACES["bowl"](), seed=15, parent_dir=tmp_path)
    stale = res.work_dir / "runs" / "iter-2"
    (stale / "confirmation.json").write_text(
        json.dumps({"confirmed_at_levels": {"A": 2, "B": 2}}),
    )
    later = res.work_dir / "runs" / "iter-10"
    later.mkdir(parents=True, exist_ok=True)
    (later / "confirmation.json").write_text(
        json.dumps({"confirmed_at_levels": {"A": 9, "B": 11}}),
    )
    assert harness._latest_iter_dirs(res.work_dir)[-1].name == "iter-10"
    for it in reversed(harness._latest_iter_dirs(res.work_dir)):
        conf = harness._read_json(it / "confirmation.json")
        if conf and conf.get("confirmed_at_levels"):
            assert conf["confirmed_at_levels"] == {"A": 9, "B": 11}
            break
    else:  # pragma: no cover - the loop always finds iter-10
        pytest.fail("no confirmation found")


def test_a_transitions_log_overrides_the_inferred_path(tmp_path):
    """Task 6 records transitions.jsonl; a recorded path must win.

    An inferred path is a guess from which artifact each iteration wrote; a
    recorded transition is evidence. The reader is exercised directly because
    nothing writes the file yet.
    """
    res = run_synthetic_campaign(SURFACES["bowl"](), seed=16, parent_dir=tmp_path)
    assert res.path == ["verify", "screen", "refine", "confirm"]
    (res.work_dir / "transitions.jsonl").write_text(
        '{"from": "verify", "to": "screen"}\n'
        '{"from": "screen", "to": "exception"}\n',
    )
    again = run_synthetic_campaign(
        SURFACES["bowl"](), seed=16, parent_dir=tmp_path,
    )
    assert again.path == ["verify", "screen", "exception"]


def test_the_gap_sign_means_worse_than_truth_in_both_directions(tmp_path):
    """A positive ``true_gap`` must mean "worse than optimal" either way.

    ``_gap_pct`` takes an absolute value, so the sign is the only thing that
    tells a later task whether the recommendation beat the stated truth —
    which happens on ``sla`` without its constraint, where the campaign
    recommends a point OUTSIDE X_valid and so "beats" the constrained best.
    """
    s = SURFACES["sla"]()
    res = run_synthetic_campaign(s, seed=17, parent_dir=tmp_path)
    assert s.invalid(res.recommendation), res.recommendation
    assert res.true_gap < 0, res.true_gap


def test_the_harness_makes_no_llm_call_and_no_subprocess(tmp_path, monkeypatch):
    """The campaign must be arithmetic: no dispatcher, no shell.

    ``build`` is never declared, ``verify`` is handed passing test_results,
    and the config runner is in-process. Any of those regressing would spend
    tokens on every CI run of thirteen later tasks' test suites.
    """
    import subprocess

    def _boom(*a, **k):  # pragma: no cover - the point is that it never runs
        raise AssertionError(f"the harness shelled out: {a!r} {k!r}")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    res = run_synthetic_campaign(SURFACES["additive"](), seed=18, parent_dir=tmp_path)
    assert res.recommendation
