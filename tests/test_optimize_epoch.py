"""A semantic exception ENDS the epoch; it does not cross the boundary and it
does not prevent a decision (paper: 'uncertainty weakens the claim; it need
not prevent a decision').
"""
from __future__ import annotations

import json

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES


def test_out_of_hull_optimum_ends_the_epoch_and_still_reports_an_action(tmp_path):
    res = run_synthetic_campaign(SURFACES["bowl_out_of_hull"](), seed=31, parent_dir=tmp_path)
    assert res.path[-1] == "exception"
    ends = list(res.work_dir.glob("epoch_end-*.json"))
    assert len(ends) == 1 and json.loads(ends[0].read_text())["state"] == "refine"
    assert res.report["epoch_ended"]
    assert res.report["recommendation"]["basis"] in ("measured", "baseline")
    assert res.recommendation                                   # an action was still returned


def test_nan_response_ends_the_epoch_without_fitting(tmp_path):
    res = run_synthetic_campaign(SURFACES["nan_at_corner"](), seed=32, parent_dir=tmp_path)
    assert res.path == ["screen", "exception"], res.path
    it = res.work_dir / "runs" / "iter-2"
    assert not (it / "effects.json").exists()
    assert json.loads((it / "findings.json").read_text())["experiment_valid"] is False


def test_next_epoch_recompiles_and_restarts_from_initial(tmp_path):
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.policy import current_state, read_policy
    from orchestrator.optimize.stage_runner import _load_or_compile_policy
    res = run_synthetic_campaign(SURFACES["nan_at_corner"](), seed=33, parent_dir=tmp_path)
    assert read_policy(res.work_dir)["epoch"] == 1
    # a fix happened out of band; the next run sees epoch_end-1.json and starts epoch 2
    pol2 = _load_or_compile_policy(synthetic_campaign(SURFACES["nan_at_corner"]()), res.work_dir)
    assert pol2["epoch"] == 2 and current_state(pol2, res.work_dir) == "screen"


def test_a_fixed_campaign_runs_a_clean_second_epoch_to_report(tmp_path, monkeypatch):
    """The paper's one way back, end to end and not by unit assertion.

    "A semantic exception ends the epoch... An agent may then revise the mechanism
    or interface, and a new compilation starts a new epoch." Epoch 1 ends on the
    NaN exception; the revision happens out of band (modelled here as the target
    no longer emitting a non-numeric metric, the same shape of fix an agent would
    make); the next run over the SAME work_dir must recompile and start over from
    ``initial``, not resume at the terminal ``exception``, and must reach
    ``report`` on its own merits.

    Driven through ``run_stage`` directly rather than through the harness because
    the harness builds a fresh work_dir per call, and one work_dir spanning two
    epochs is exactly what is under test.
    """
    from orchestrator.engine import Engine
    from orchestrator.iteration import IterationOutcome, setup_work_dir
    from orchestrator.optimize.harness import _all_pass, synthetic_campaign
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner

    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))

    def _drive(campaign, work_dir, runner, first, last):
        for i in range(first, last):
            out = run_stage(campaign, work_dir, iteration=i, config_runner=runner,
                            test_results=_all_pass(campaign), auto_approve=True)
            if out == IterationOutcome.COMPLETED:
                return
            eng = Engine(work_dir)
            if eng.phase != "DONE":
                eng.transition("DONE")
            eng.transition("DESIGN")

    broken = SURFACES["nan_at_corner"]()
    c1 = synthetic_campaign(broken)
    wd = setup_work_dir(c1["run_id"], repo_path=None, campaign=c1)
    _drive(c1, wd, make_synthetic_runner(broken, seed=50), 1, 6)

    assert (wd / "epoch_end-1.json").exists()
    assert json.loads((wd / "report.json").read_text())["epoch_ended"]

    # THE FIX, out of band. Same factor shape, no configuration that reports a
    # non-numeric objective — the revision an agent would make after reading
    # epoch_end-1.json's `next_epoch_requires`.
    fixed = SURFACES["drift"]()
    c2 = synthetic_campaign(fixed)
    c2["run_id"] = c1["run_id"]
    eng = Engine(wd)
    if eng.phase != "DONE":
        eng.transition("DONE")
    eng.transition("DESIGN")
    _drive(c2, wd, make_synthetic_runner(fixed, seed=51), 6, 12)

    rows = [json.loads(ln) for ln in
            (wd / "transitions.jsonl").read_text().splitlines() if ln.strip()]
    # BOTH epochs are in the log — it is the audit trail, not a scratchpad — and
    # each row names its own epoch.
    assert [(r["epoch"], r["from"], r["to"]) for r in rows][0] == (1, "screen", "exception")
    assert [r["epoch"] for r in rows[1:]] == [2] * (len(rows) - 1), rows
    # Epoch 2 restarted at `initial` rather than at epoch 1's terminal, and
    # finished on its own merits with no exception attached.
    assert rows[1]["from"] == "screen"
    rep = json.loads((wd / "report.json").read_text())
    assert rep["epoch"] == 2 and rep["path"][-1] == "report", rep["path"]
    assert "epoch_ended" not in rep, rep
    assert rep["recommendation"]["levels"], rep


def test_every_transition_the_runner_writes_records_its_epoch(tmp_path):
    """MUTATION-DRIVEN. The reader above is only half the mechanism.

    ``epoch_transitions`` reads a missing ``"epoch"`` as 1, which is right for the
    rows that predate the field — and which means dropping the field from
    ``_close_iteration``'s appended row is INVISIBLE to any test that has only one
    epoch's rows on disk, and to any test that writes the rows by hand. So assert
    it where production writes it: every row a real campaign records must name the
    epoch it ran under.
    """
    res = run_synthetic_campaign(SURFACES["additive"](), seed=34, parent_dir=tmp_path)
    rows = [json.loads(ln) for ln in
            (res.work_dir / "transitions.jsonl").read_text().splitlines() if ln.strip()]
    assert rows, "a completed campaign must have recorded transitions"
    assert all("epoch" in r for r in rows), rows
    assert {r["epoch"] for r in rows} == {1}, rows


def test_each_epochs_transitions_are_read_only_by_that_epoch(tmp_path):
    """The epoch field on a transition row must be READ, not merely written.

    MUTATION-DRIVEN. ``test_next_epoch_recompiles_and_restarts_from_initial``
    above survives two mutations that matter, because ``nan_at_corner`` ends
    epoch 1 with a single transition and both bugs happen to be invisible on one
    row:

      * omit ``"epoch"`` from the appended row — every row then defaults to
        epoch 1, and a single epoch-1 row is filtered out of epoch 2 either way;
      * compare with ``<=`` instead of ``<`` in ``_load_or_compile_policy``'s
        recompile trigger — the policy is then recompiled on EVERY call, which
        with one epoch on disk produces the same epoch number it already had.

    Both bite once TWO epochs have rows. This asserts the fact directly on a
    hand-built log rather than by running two campaigns, so it fails on the
    mechanism rather than on a surface's noise.
    """
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.policy import (
        append_transition,
        compile_policy,
        current_state,
        epoch_transitions,
    )
    c = synthetic_campaign(SURFACES["additive"]())
    wd = tmp_path / "wd"
    wd.mkdir()
    for epoch, frm, to in ((1, "screen", "refine"), (1, "refine", "exception"),
                           (2, "screen", "refine"), (2, "refine", "confirm")):
        append_transition(wd, {"iteration": epoch * 10, "epoch": epoch,
                               "from": frm, "to": to, "rule": {},
                               "observations": {}, "policy_hash": ""})
    e1, e2 = compile_policy(c, epoch=1), compile_policy(c, epoch=2)
    # Each epoch sees ONLY its own rows...
    assert [r["from"] for r in epoch_transitions(e1, wd)] == ["screen", "refine"]
    assert [r["from"] for r in epoch_transitions(e2, wd)] == ["screen", "refine"]
    assert [r["to"] for r in epoch_transitions(e1, wd)] == ["refine", "exception"]
    assert [r["to"] for r in epoch_transitions(e2, wd)] == ["refine", "confirm"]
    # ...so epoch 1 is still parked at its terminal exception while epoch 2 is
    # mid-flight at confirm. Reading the log unfiltered would give BOTH "confirm"
    # (the last row wins), which is the bug: epoch 1 would look resumable.
    assert current_state(e1, wd) == "exception"
    assert current_state(e2, wd) == "confirm"
    # A third epoch has no rows at all and therefore restarts CLEAN.
    assert current_state(compile_policy(c, epoch=3), wd) == e1["initial"]


def test_a_policy_already_at_the_current_epoch_is_not_recompiled(tmp_path):
    """MUTATION-DRIVEN, the other survivor: ``<`` must not be ``<=``.

    ``_load_or_compile_policy`` recompiles only when a NEWER epoch has begun. If
    it recompiled whenever the epoch merely matched, the hash check below it would
    never run — so ``policy.json`` edited inside an epoch would be silently
    overwritten instead of hard-failing, and the pre-registration guarantee would
    be gone while every epoch test still passed.
    """
    import json as _json

    import pytest

    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.policy import compile_policy, write_policy
    from orchestrator.optimize.stage_runner import (
        OptimizationAborted,
        _load_or_compile_policy,
    )
    c = synthetic_campaign(SURFACES["additive"]())
    wd = tmp_path / "wd"
    wd.mkdir()
    write_policy(wd, compile_policy(c, epoch=1))
    # Edit the registered policy INSIDE the epoch. No epoch_end file exists, so
    # `_epoch_index` is still 1 and the recompile branch must NOT fire — the hash
    # check must be reached and must refuse.
    pol = _json.loads((wd / "policy.json").read_text())
    pol["objective"]["delta_screen"] = 0.5
    (wd / "policy.json").write_text(_json.dumps(pol, indent=2, sort_keys=True))
    with pytest.raises(OptimizationAborted, match="edited after compilation"):
        _load_or_compile_policy(c, wd)


def test_stationary_in_hull_needs_the_curvature_sign_not_just_the_geometry(tmp_path):
    """MUTATION-DRIVEN. A stationary point is not an optimum.

    The epoch-ending guard reads ``stationary_in_hull``, so that observation has
    to mean "the declared ranges contain the OPTIMUM". On a surface with little
    real curvature the fitted quadratic's coefficients are noise, the solve
    inverts a near-singular Hessian, and the "stationary point" lands at coded
    -33 or +6575 (measured: ``SURFACES["additive"]`` seed 19,
    ``SURFACES["sla"]`` seed 5) — a purely geometric hull test then ends those
    campaigns' epochs even though their optima are at an in-range corner.

    Three branches, asserted directly because the end-to-end surfaces only
    exercise two of them: a plane (no quadratic terms at all) has no interior
    optimum, and a convex-under-maximize axis is a MINIMUM direction.
    """
    from orchestrator.optimize.effects import Effect, Fit
    from orchestrator.optimize.stage_runner import _stationary_in_hull

    def _fit(**curv):
        return Fit(intercept=0.0, effects=(), n_runs=12, quadratic=tuple(
            Effect(label=f"{k}^2", terms=(k, k), estimate=v)
            for k, v in curv.items()))

    concave, convex = _fit(A=-1.85, B=-1.82), _fit(A=+0.0036, B=-0.0075)

    # A plane has NO stationary point, so its argmax is at a hull boundary —
    # inside the hull. Ending the epoch here would end every campaign whose
    # refine fit came out linear.
    assert _stationary_in_hull(_fit(), None, "maximize") is True
    # Inside the hull: nothing to report either way.
    assert _stationary_in_hull(concave, {"A": 0.3, "B": -0.9}, "maximize") is True
    # Outside AND concave under maximize: a real optimum out of range.
    assert _stationary_in_hull(concave, {"A": 3.4, "B": 0.3}, "maximize") is False
    # Outside but CONVEX under maximize: a minimum direction, so moving toward it
    # makes the response worse. Not an optimum outside the ranges.
    assert _stationary_in_hull(convex, {"A": -33.7, "B": 57.8}, "maximize") is True
    # The sign flips with the objective's direction, both ways round.
    assert _stationary_in_hull(convex, {"A": -33.7}, "minimize") is False
    assert _stationary_in_hull(concave, {"A": 3.4}, "minimize") is True
    # A term the fit never estimated cannot carry an optimum out there either.
    assert _stationary_in_hull(_fit(B=-1.8), {"A": 3.4}, "maximize") is True


def test_only_a_nan_on_a_complete_row_is_a_semantic_exception():
    """MUTATION-DRIVEN. Dropping the ``status == "complete"`` scope must fail.

    ``infeasible`` / ``rejected`` rows are trustworthy measurements of an
    INADMISSIBLE configuration — real information about the design space (spec
    §6.4) — and a constrained design routinely has such corners. Routing one to
    ``exception`` would make constraints unusable. Only a row the target ran to
    COMPLETION while reporting a non-numeric objective is the semantic defect
    that ends the epoch. Nothing in the synthetic oracle produces a NaN on a
    non-complete row, so the scope needs asserting directly.
    """
    from orchestrator.optimize.stage_runner import _primary_is_nan

    class _O:
        def __init__(self, status, response):
            self.status, self.response, self.row_index = status, response, 0

    nan = float("nan")
    assert _primary_is_nan(_O("complete", {"m": nan}), "m") is True
    # Everything else is a DIFFERENT failure class, with different handling.
    assert _primary_is_nan(_O("complete", {"m": 1.0}), "m") is False
    assert _primary_is_nan(_O("complete", {}), "m") is False            # unmeasured
    assert _primary_is_nan(_O("complete", {"m": None}), "m") is False   # emitted empty
    assert _primary_is_nan(_O("complete", {"m": "nan"}), "m") is False  # instrumentation
    assert _primary_is_nan(_O("complete", {"m": {"v": 1}}), "m") is False


def test_a_nan_on_an_infeasible_row_does_not_end_the_epoch(tmp_path):
    """The scope, asserted BEHAVIOURALLY rather than by mirroring the predicate.

    ``nan_at_corner`` emits NaN at ``{A: 16, B: 16}``. Add a constraint that makes
    that same corner INADMISSIBLE and the row comes back ``infeasible`` carrying
    the NaN — the one combination that separates "a semantic defect in the
    objective's definition" from "a trustworthy measurement of a configuration
    outside ``X_valid``". The campaign must run to ``report``: excluding the corner
    from the fit is already the registered handling (spec §6.4), and ending the
    epoch instead would make declared constraints unusable.
    """
    res = run_synthetic_campaign(
        SURFACES["nan_at_corner"](), seed=40, parent_dir=tmp_path,
        campaign_overrides={"response": {
            "primary": {"metric": "m", "direction": "maximize"},
            # `cfg.a` is echoed back by the synthetic target, so this makes the
            # A=16 corner — the one that also emits NaN — inadmissible.
            "constraints": [{"metric": "cfg.a", "op": "<=", "value": 15}],
        }},
    )
    assert res.path[-1] == "report", res.path
    assert "exception" not in res.path, res.path
    assert not list(res.work_dir.glob("epoch_end-*.json"))
    rows = [json.loads(ln) for ln in
            (res.work_dir / "runs" / "iter-2" / "runs.jsonl").read_text().splitlines()
            if ln.strip()]
    nan_infeasible = [r for r in rows if r["status"] == "infeasible"
                      and r["response"].get("m") != r["response"].get("m")]
    assert nan_infeasible, (
        "this test is only discriminating if a row really did come back "
        f"infeasible WITH a NaN response; got {rows}"
    )


def test_lack_of_fit_sends_confirm_measured_candidates_only(tmp_path):
    # a saddle fitted with a plane at screen: refine's quadratic fits, but force
    # inadequacy by giving refine too few centre points to test LOF -> the rule
    # must not fire; instead assert the flag round-trips when set by hand.
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.policy import compile_policy
    from orchestrator.optimize.stage_runner import _confirm_rows
    s = SURFACES["additive"]()
    c = synthetic_campaign(s)
    pol = compile_policy(c)
    wd = tmp_path / "wd"; (wd / "runs" / "iter-2").mkdir(parents=True)
    (wd / "runs" / "iter-2" / "recommendation.json").write_text(json.dumps(
        {"levels": {"A": 2, "B": 16, "C": "on"}, "model_adequate": False, "top_candidates": []}))
    (wd / "runs" / "iter-2" / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"row_index": 0, "status": "complete", "levels": {"A": 16, "B": 16, "C": "on"}, "response": {"m": 20.0}},
        {"row_index": 1, "status": "complete", "levels": {"A": 2, "B": 2, "C": "off"}, "response": {"m": 1.0}},
    ]))
    rows, payload = _confirm_rows(pol, wd, parse_factors(c["optimization"]["factors"]), "m", "maximize", 3)
    keys = [f["levels"] for f in payload["finalists"]]
    assert {"A": 2, "B": 16, "C": "on"} not in keys          # the model's pick is not trusted
    assert {"A": 16, "B": 16, "C": "on"} in keys              # measured leaders are
