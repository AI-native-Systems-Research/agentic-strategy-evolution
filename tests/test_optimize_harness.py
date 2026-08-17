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

      * the refine iteration holds ``C`` at ``levels[0] == "off"`` for all
        eight runs — the whole refine stage measures the ANTI-optimal branch,
        which is exactly the ``levels[0]`` bug Task 7 names.
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

    The refine iteration is LOCATED by ``effects.json["stage"]``, never
    hardcoded — see ``_levels_explored_at_stage``.
    """
    res = run_synthetic_campaign(SURFACES["choice_x_numeric"](), seed=4, parent_dir=tmp_path)
    assert res.recommendation["C"] == "on" and _gap_pct(res) <= 2.0
    refine_c = _levels_explored_at_stage(res.work_dir, "refine", "C")
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
