"""End-to-end oracle tests: a synthetic campaign's answer vs. the truth.

xfail(strict=True) marks encode behaviour the paper requires and the branch
does not yet deliver; each names the task that must flip it. A strict xfail
that starts passing FAILS the suite, so flipping is deliberate.
"""
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

import pytest

from orchestrator.optimize import harness
from orchestrator.optimize.harness import run_synthetic_campaign, synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES


def _gap_pct(res):
    return abs(res.true_gap) / max(abs(res.true_best), 1e-9) * 100.0


def _levels_explored_at_stage(work_dir, stage: str, factor_id: str) -> set:
    """Every level of ``factor_id`` that ``stage`` actually ran.

    The stage is LOCATED by ``effects.json["stage"]`` rather than by iteration
    number. Hardcoding ``iter-3`` works only under the legacy index-driven
    schedule; Task 6 replaces that with ``current_state(policy, work_dir)``,
    and neither Task 6's brief nor Task 7's tells anyone to revisit this path.
    A hardcoded path would then raise ``FileNotFoundError`` inside an
    ``xfail(strict=True)`` test, which pytest reports as a perfectly ordinary
    XFAIL — the gate would disarm itself without failing anything. Deriving
    the iteration keeps the assertion pointed at the stage it is about, under
    any schedule.

    Fails loudly when the stage never ran, for the same reason: silence here
    is indistinguishable from the bug being fixed.
    """
    runs_root = Path(work_dir) / "runs"
    iters = sorted(
        (d for d in runs_root.iterdir() if d.name.startswith("iter-")),
        key=lambda d: int(d.name.split("-")[1]),
    )
    seen_stages = []
    for it in iters:
        effects = it / "effects.json"
        if not effects.exists():
            continue
        got = json.loads(effects.read_text()).get("stage")
        seen_stages.append(got)
        if got != stage:
            continue
        runs = it / "runs.jsonl"
        assert runs.exists(), f"{it.name} fitted a {stage} model but wrote no runs.jsonl"
        return {
            json.loads(line)["levels"][factor_id]
            for line in runs.read_text().splitlines() if line.strip()
        }
    raise AssertionError(
        f"no iteration ran stage {stage!r} (stages found: {seen_stages}); "
        f"this assertion cannot be evaluated, so it must not pass silently"
    )


def _read_recommendation(work_dir, *, stage: str | None = None) -> dict:
    """A campaign's ``recommendation.json`` — the LAST one, or a named stage's.

    Located by the artifact's own ``stage`` key rather than by iteration
    number, for the reason ``_levels_explored_at_stage`` documents: a
    hardcoded ``iter-N`` silently points at the wrong stage under any
    schedule change. Raises when the stage never wrote one, so a missing
    artifact cannot read as a satisfied assertion.
    """
    found: list[dict] = []
    for it in harness._latest_iter_dirs(Path(work_dir)):
        payload = harness._read_json(it / "recommendation.json")
        if payload and (stage is None or payload.get("stage") == stage):
            found.append(payload)
    if not found:
        raise AssertionError(
            f"no recommendation.json for stage {stage or '<any>'} under "
            f"{work_dir}; this assertion cannot be evaluated",
        )
    return found[-1]


def test_additive_surface_recommendation_is_within_two_percent_of_truth(tmp_path):
    res = run_synthetic_campaign(SURFACES["additive"](), seed=1, parent_dir=tmp_path)
    assert res.recommendation, res.report
    assert _gap_pct(res) <= 2.0, (res.recommendation, res.true_optimum)


def test_bowl_surface_confirms_near_the_interior_maximum(tmp_path):
    res = run_synthetic_campaign(SURFACES["bowl"](), seed=2, parent_dir=tmp_path)
    assert abs(res.recommendation["A"] - 9) <= 1 and abs(res.recommendation["B"] - 11) <= 1


def test_saddle_surface_recommends_a_corner_not_the_saddle_point(tmp_path):
    """FLIPPED BY TASK 7 (was xfail(strict=True)).

    A stationary point is where the gradient vanishes, which on this surface
    is the SADDLE at ``{A: 9, B: 11}`` — worth 10.0 against a true optimum of
    12.45. ``decide.recommend`` compares predictions over the candidate space
    instead, so the sign of the curvature is accounted for without ever
    forming a Hessian.

    The two axes are asserted separately because the surface is
    ``10 + 0.05(A-9)^2 - 0.05(B-11)^2``: it curves UP in A (so the argmax is
    pushed to an A corner, either one — the surface is symmetric about A=9)
    and DOWN in B (so the argmax sits at B's interior peak near 11, which a
    two-level screen pair could never have proposed). Getting both directions
    right is what says the curvature's sign was read rather than ignored.
    """
    res = run_synthetic_campaign(SURFACES["saddle"](), seed=3, parent_dir=tmp_path)
    assert _gap_pct(res) <= 2.0, (res.recommendation, res.true_optimum)
    # The discriminating half: the stationary point is still SOLVED and kept as
    # a diagnostic, and the recommendation must not be it.
    rec = _read_recommendation(res.work_dir)
    assert rec["stationary_point"], (
        "the stationary point must still be recorded — OPTIMUM_OUTSIDE_HULL "
        "fires from it and a reader needs to see what the quadratic claimed"
    )
    levels = rec["levels"]
    assert levels["A"] in (2, 16), (
        f"A curves UP, so its argmax is a corner; got {levels}"
    )
    assert abs(levels["B"] - 11) <= 1, (
        f"B curves DOWN, so its argmax is the interior peak near 11; got {levels}"
    )
    s = SURFACES["saddle"]()
    assert s.fn(levels) > s.fn({"A": 9, "B": 11}), (
        f"the recommendation must beat the saddle point itself: "
        f"{s.fn(levels)} vs {s.fn({'A': 9, 'B': 11})}"
    )


def test_choice_x_numeric_recommends_the_on_branch(tmp_path):
    """FLIPPED BY TASK 7 (was xfail(strict=True)).

    The `on` branch must be recommended BECAUSE the model chose it.

    The bare assertion (``recommendation["C"] == "on"`` plus a 2% gap) XPASSed
    before Task 7, so it cannot be the whole test: the right answer used to
    arrive by accident, from ``_best_observed`` reaching back to a screen row
    after an out-of-hull solve was discarded. What distinguishes mechanism
    from accident is the RECOMMENDATION ARTIFACT — ``recommendation.json``
    must show ``C`` among ``fitted_ids`` and carry a coding for it, i.e. the
    choice factor was a dimension of the argmax rather than a level held
    aside while the numerics were optimized around it. A gradient solve
    cannot produce that artifact at all: there is no derivative in a
    categorical direction.

    HISTORY, since this docstring previously asserted something else. It used
    to require that the REFINE stage explored ``C = "on"``, on a measurement
    that refine runs here at all. It does not, and has not since Task 6: A's
    entire effect on this surface lives in the A×C interaction, so its main
    effect over the screen pair is exactly zero, A is correctly dropped as
    insignificant, ``refinable_survivors`` is 0, and the compiled policy sends
    ``screen`` straight to ``confirm``. Verified on this branch and on its
    parent commit — the path is ``screen -> confirm -> report`` either way, so
    the refine assertion was unevaluatable rather than merely unmet. The
    refine held-fixed rule it was reaching for is real and is tested where it
    actually runs: ``test_refine_holds_a_choice_factor_at_the_screen_
    recommendation``, on ``additive``.
    """
    res = run_synthetic_campaign(SURFACES["choice_x_numeric"](), seed=4, parent_dir=tmp_path)
    assert res.recommendation["C"] == "on" and _gap_pct(res) <= 2.0
    rec = _read_recommendation(res.work_dir)
    assert "C" in rec["fitted_ids"], (
        f"the choice factor was not a dimension of the argmax: "
        f"fitted_ids={rec['fitted_ids']}"
    )
    assert rec["levels"]["C"] == "on"
    assert rec["coded"]["C"] == 1.0, (
        f"C entered the argmax as a coordinate, so it must carry the coding of "
        f"the level chosen (+1 == the screen pair's high level, 'on'); "
        f"got {rec['coded']}"
    )
    # And the choice was made against the ALTERNATIVE, not assumed: the "off"
    # branch is in the candidate space and predicts worse. `top_candidates` is
    # truncated to five and A has nine grid points, so the off-branch runner-up
    # need not appear there — this checks the space, not the shortlist.
    from orchestrator.optimize import decide
    from orchestrator.optimize.factors import parse_factors

    factors = parse_factors(list(SURFACES["choice_x_numeric"]().factors))
    space = decide.candidates(rec["fitted_ids"], factors, held_fixed={})
    assert {c.levels["C"] for c in space} == {"on", "off"}, (
        "both branches must be enumerable, or the argmax had no choice to make"
    )


def test_refine_holds_a_choice_factor_at_the_screen_recommendation(tmp_path):
    """Task 7's rule 3, on a surface where refine actually runs.

    ``refine``'s design spans only the refinable factors, so every ``choice``
    factor is held at a single level for the whole stage. Holding it at
    ``levels[0]`` picks a level by DECLARATION ORDER — and on ``additive``
    that is ``C = "off"``, the branch worth 2.0 less than the other. Measured
    on the parent commit: all eight refine runs sat at ``"off"``, so refine
    fitted its quadratic over the wrong branch. Holding at the screen
    recommendation's level instead puts refine on ``"on"``, which is the
    level the screen's own argmax chose.

    The stage is LOCATED by ``effects.json["stage"]``, never hardcoded — see
    ``_levels_explored_at_stage``.
    """
    res = run_synthetic_campaign(SURFACES["additive"](), seed=23, parent_dir=tmp_path)
    assert "refine" in res.path, res.path
    assert _levels_explored_at_stage(res.work_dir, "refine", "C") == {"on"}, (
        "refine held the choice factor at levels[0] ('off') instead of at the "
        "screen recommendation's level"
    )
    screen_rec = _read_recommendation(res.work_dir, stage="screen")
    assert screen_rec["levels"]["C"] == "on"
    refine_rec = _read_recommendation(res.work_dir, stage="refine")
    assert refine_rec["held_fixed"] == {"C": "on"}, refine_rec["held_fixed"]


@pytest.mark.xfail(strict=True, reason="Task 9: finalists measured infeasible at confirm are excluded from the recommendation")
def test_sla_surface_never_recommends_an_invalid_point(tmp_path):
    """Feasible is necessary but not sufficient — it must be the valid ARGMAX.

    WHICH HALF FAILS MOVED IN TASK 7, so both halves are stated. Before Task
    7 the campaign recommended ``{A: 16, B: 2}``: feasible (``p99_ms = 34 <=
    40``) but 6.12% below the true constrained optimum ``{A: 16, B: 8}``
    (19.6). Feasibility came for free — ``_best_observed`` filters to
    ``status == "complete"`` and the runner marks constraint violations
    ``infeasible`` — so the feasibility assertion tested an existing filter
    rather than the exclusion Task 9 adds, and only the gap bound was
    discriminating.

    Task 7 replaced that fallback with the argmax, which now recommends
    ``{A: 16, B: 14}`` — closer in objective and INFEASIBLE (``p99_ms = 46``).
    So the feasibility assertion is now the failing one. That is the honest
    state of the mechanism rather than a regression: ``decide.recommend``
    excludes points the campaign has MEASURED infeasible, and B=14 was never
    measured. Making the recommendation respect a constraint it can only
    predict is exactly Task 9's shortlist-confirm work — measure the finalists
    and exclude the ones that violate.
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
    refinable factors and those surfaces declare 0 or 1. Recorded rather than
    papered over: the fix belongs to whichever task owns the default (see the
    task-3 report), not to an assertion that pretends the campaign is clean.

    Task 7 note. ``choice_x_numeric`` used to be called out here as the
    consequential case, because its test asserted something about the refine
    stage on a campaign the validator would reject. It no longer does — refine
    never runs on that surface under the compiled policy (A's whole effect is
    in the A×C interaction, so its main effect is null and it is dropped as
    insignificant), and Task 7's refine held-fixed rule is tested on
    ``additive`` instead, where refine genuinely runs and the validator is
    satisfied. The offender list below is unchanged; only the reading of which
    entry matters is.
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
    """``inf``, not a number a later assertion could pass by accident.

    BEHAVIOUR CHANGE, Task 6. Before the compiled policy this test used
    ``drift`` (all 2-level numerics) under the DEFAULT schedule: the index
    schedule handed iteration 3 to ``refine`` regardless, ``_build_design``
    aborted with "refine has nothing to refine", and the campaign produced no
    recommendation. ``compile_policy`` cannot make that mistake —
    ``refine_on`` requires ``any(is_refinable(f))``, so ``drift``'s policy has
    no ``refine`` state at all and ``screen`` defaults straight to ``confirm``.
    The abort is gone because the schedule that caused it is gone, which is the
    point of the change.

    So the ``inf`` contract is driven by an abort that Task 6 does NOT remove:
    ``nan_at_corner`` makes one configuration emit NaN, and
    ``_fitting_responses`` still refuses to fit on an unmeasured row (rule 8
    keeps that behaviour; Task 11 is what routes it to ``exception`` instead).
    Asserting the contract via ``drift``'s old refine abort would be asserting
    a defect that no longer exists.
    """
    res = run_synthetic_campaign(
        SURFACES["nan_at_corner"](), seed=12, parent_dir=tmp_path,
    )
    assert res.recommendation == {}
    assert res.true_gap == float("inf")
    assert res.path[-1].startswith("aborted:")


def test_a_surface_with_nothing_refinable_no_longer_aborts_at_refine(tmp_path):
    """The index schedule's worst failure mode, structurally removed.

    ``stage_for_iteration`` handed iteration 3 to ``refine`` whether or not any
    factor could carry curvature, so every all-2-level surface died with
    "refine has nothing to refine" under the DEFAULT schedule and the
    documented workaround was to hand-edit ``stages``. ``compile_policy`` omits
    the state instead, so ``screen`` defaults to ``confirm`` and the campaign
    reaches its answer with no author intervention.

    The ``refine_on`` assertion below is the one that pins THAT mechanism.
    Mutation-verified during review: the path/outcome assertions alone still
    pass with ``refine_on`` reverted to always-include, because ``drift`` has
    zero refinable SURVIVORS too, so the ``{"refinable_survivors": {">": 0}}``
    guard already defaults screen to confirm for an unrelated reason. Reading
    the compiled policy off disk is what distinguishes "the state was never
    compiled" from "the state was compiled and the guard skipped it".
    """
    res = run_synthetic_campaign(SURFACES["drift"](), seed=22, parent_dir=tmp_path)
    assert res.path == ["screen", "confirm", "report"], res.path
    assert res.recommendation, res.report
    assert not any(p.startswith("aborted:") for p in res.path)
    states = json.loads((res.work_dir / "policy.json").read_text())["states"]
    assert "refine" not in states, (
        f"compile_policy registered a refine state on a surface where nothing "
        f"is refinable; states={sorted(states)}"
    )


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
        # Task 6: ``path`` comes from ``transitions.jsonl``, which records the
        # EPOCH's transitions. ``verify`` is pre-epoch (it is what compiles the
        # policy, so it cannot be a state inside it) and therefore no longer
        # appears; ``report`` is the terminal the policy routed to and now does.
        # The stages that spent runs are unchanged.
        assert res.path == ["screen", "confirm", "report"], (key, res.path)
        assert s.fn(res.recommendation) == pytest.approx(res.true_best, abs=1e-9), (
            key, res.recommendation
        )


def test_the_recommendation_basis_names_the_artifact_it_came_from(tmp_path):
    """Task 6 makes ``report.json`` the source; the confirm fallback is now dead.

    Recording WHICH artifact answered is what lets a later task tell "the policy
    produced a recommendation" from "the legacy confirm fallback did". Before
    Task 6 the only source was ``runs/iter-N/confirmation.json`` (basis
    ``confirmation.json``); now the policy's terminal writes ``report.json``,
    whose ``basis`` says where the LEVELS inside it came from —
    ``terminal_best`` when the confirm state handed them over,
    ``measured``/``baseline`` on the fallback paths in ``_run_report``.

    The regret fields stay ``None``: Task 9 owns the residual-regret
    certificate, and ``_run_report`` deliberately writes no number it cannot
    justify rather than a placeholder a reader could mistake for a measurement.
    """
    res = run_synthetic_campaign(SURFACES["bowl"](), seed=14, parent_dir=tmp_path)
    assert res.basis == "terminal_best"
    assert res.report["recommendation"]["levels"] == res.recommendation
    assert res.report["policy_hash"] and res.report["epoch"] == 1
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
    recorded transition is evidence. ``run_stage`` now writes the log itself, so
    the natural path IS the recorded one — the override is still exercised by
    replacing the log with a different history and re-reading it.
    """
    res = run_synthetic_campaign(SURFACES["bowl"](), seed=16, parent_dir=tmp_path)
    assert res.path == ["screen", "refine", "confirm", "report"]
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


def test_every_measurement_iteration_pre_registers_its_design_matrix(tmp_path):
    """The harness must advance the engine the way run_campaign does.

    `_enter_phase` returns False when the engine's phase is already PAST the
    requested one, and the DESIGN block it guards writes
    ``design_matrix.json`` AND runs ``_preflight_design``. Without the
    between-iteration ``DONE -> DESIGN`` transition the engine stays parked at
    HUMAN_FINDINGS_GATE after iteration 1, so both are skipped from iteration
    2 onward — measured on `bowl` seed 3: design_matrix.json was absent from
    ALL FOUR iteration directories and the pre-flight never ran once.

    Nothing asserted it, which is exactly why it went unnoticed. Two concrete
    costs: `check_fidelity` compares executed runs against a pre-registered
    matrix that was never written, and Task 6's own test reads
    ``runs/iter-2/design_matrix.json`` while its brief says harness.py needs
    no change.

    Every iteration that MEASURED something (has runs.jsonl) must therefore
    have pre-registered what it was going to run. `verify` measures nothing
    and correctly writes neither.
    """
    res = run_synthetic_campaign(SURFACES["bowl"](), seed=3, parent_dir=tmp_path)
    # Task 6: the path is the EPOCH's recorded transitions. `verify` is
    # pre-epoch (it compiles the policy, so it is not a state inside it) and
    # `report` is the terminal the policy routed to.
    assert res.path == ["screen", "refine", "confirm", "report"], res.path

    measured, registered = [], []
    for it in harness._latest_iter_dirs(res.work_dir):
        if (it / "runs.jsonl").exists():
            measured.append(it.name)
        if (it / "design_matrix.json").exists():
            registered.append(it.name)
    assert measured == ["iter-2", "iter-3", "iter-4"], measured
    assert registered == measured, (
        f"iterations that measured {measured} but pre-registered {registered}; "
        f"the engine was not advanced between iterations, so _enter_phase "
        f"skipped the DESIGN block (design_matrix.json + _preflight_design)"
    )
    # The matrices must describe the stage that ran, not a stale re-render.
    kinds = [json.loads((res.work_dir / "runs" / n / "design_matrix.json").read_text())["kind"]
             for n in registered]
    assert kinds == ["full", "central_composite", "confirm"], kinds


def test_the_engine_ends_at_done_and_every_iteration_reached_the_ledger(tmp_path):
    """Mirror of run_campaign's HUMAN_FINDINGS_GATE -> DONE -> DESIGN.

    Asserted through the ledger rather than the live phase mid-run, because
    the final stage legitimately ends at DONE. The measured shape (`additive`,
    seed 19) is a ``baseline`` row from the template plus one row per
    MEASUREMENT iteration — iteration 1 is `verify`, which writes no
    findings.json, so `append_ledger_row` logs "No findings.json for
    iteration 1 — skipping" and the baseline row is the template's, not
    verify's.

    A stuck engine still appends ledger rows, so the design-matrix test above
    is the load-bearing one for the phase advance; this pins that no
    iteration was dropped outright and that the run terminates properly.
    """
    from orchestrator.engine import Engine

    res = run_synthetic_campaign(SURFACES["additive"](), seed=19, parent_dir=tmp_path)
    # Task 6: the path is the EPOCH's recorded transitions. `verify` is
    # pre-epoch (it compiles the policy, so it is not a state inside it) and
    # `report` is the terminal the policy routed to.
    assert res.path == ["screen", "refine", "confirm", "report"], res.path
    assert Engine(res.work_dir).phase == "DONE"

    ledger = json.loads((res.work_dir / "ledger.json").read_text())
    rows = ledger["iterations"] if isinstance(ledger, dict) else ledger
    ids = [r.get("candidate_id") for r in rows]
    assert ids == ["baseline", "iter-2", "iter-3", "iter-4"], ids


def test_the_refine_stage_is_located_by_effects_json_not_by_iteration_number(tmp_path):
    """`_levels_explored_at_stage` must survive a schedule change.

    Task 6 replaces index-driven staging with a compiled policy, so any
    hardcoded ``iter-N`` in this file would silently point at the wrong
    stage — or at nothing, which inside an xfail(strict=True) test reads as
    an ordinary XFAIL and disarms the gate. This pins the lookup to the
    artifact's own ``stage`` key.
    """
    res = run_synthetic_campaign(SURFACES["bowl"](), seed=20, parent_dir=tmp_path)

    # Both stages are found, and each is found where its own artifact says.
    assert _levels_explored_at_stage(res.work_dir, "screen", "A") == {2, 9, 16}
    assert _levels_explored_at_stage(res.work_dir, "refine", "A") == {2, 9, 16}

    # The per-factor level SETS coincide on this surface (axial points at coded
    # +/-1 snap to the declared extremes on a grid of 1), so the discriminator
    # is the COMBINATIONS: the central composite runs the four axial pairs the
    # two-level screen never does. Asserted so that a helper silently reading
    # the wrong iteration cannot pass.
    def _pairs(stage):
        it = next(
            d for d in harness._latest_iter_dirs(res.work_dir)
            if (d / "effects.json").exists()
            and json.loads((d / "effects.json").read_text()).get("stage") == stage
        )
        return {
            (json.loads(line)["levels"]["A"], json.loads(line)["levels"]["B"])
            for line in (it / "runs.jsonl").read_text().splitlines() if line.strip()
        }

    assert _pairs("refine") - _pairs("screen") == {(2, 9), (9, 2), (9, 16), (16, 9)}


def test_locating_a_stage_that_never_ran_fails_loudly(tmp_path):
    """Silence must not be mistaken for success.

    `drift` aborts before any refine stage under the default schedule, so the
    helper has nothing to read. It must raise rather than return an empty set
    that an `in` assertion would quietly fail — or, worse, that a `not in`
    assertion would quietly pass.
    """
    res = run_synthetic_campaign(SURFACES["drift"](), seed=21, parent_dir=tmp_path)
    with pytest.raises(AssertionError, match="no iteration ran stage 'refine'"):
        _levels_explored_at_stage(res.work_dir, "refine", "A")


def test_harness_path_comes_from_transitions_log(tmp_path):
    """Task 6: run_stage records transitions.jsonl, so the path is evidence.

    The reader in ``run_synthetic_campaign`` already prefers the log over the
    artifact-inferred path (``test_a_transitions_log_overrides_the_inferred_path``
    drove it with a hand-written file). This is the first test where the log is
    written by the code under test rather than by the test.
    """
    res = run_synthetic_campaign(SURFACES["additive"](), seed=11, parent_dir=tmp_path)
    assert res.path[0] == "screen" and res.path[-1] == "report"
    assert (res.work_dir / "transitions.jsonl").exists()
