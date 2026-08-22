"""End-to-end tests for the optimization-kind stage runner.

No live LLM calls and no subprocesses: the config runner and the integrity
check are injected fakes, which is the seam that makes this testable at all
(see orchestrator/optimize/stage_runner.py's module docstring).

The load-bearing tests here are the ones covering checks that must fire even
under ``auto_approve=True`` — which is this kind's DEFAULT, so removing the
human must not remove the checks:

  * design-matrix fidelity drift  (the #246 spec-fidelity discipline,
    extended from locked_parameters to the pre-registered matrix)
  * a correctness-relation violation aborting before any design budget is
    spent
  * a held-out metric reaching a fitting input

And their counterpart: a *behavioral* violation must NOT abort. A
monotonicity break is a discovery, not a broken apparatus.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from orchestrator.optimize import artifacts
from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage


def _factor(fid: str, *, levels=(2, 16), grid=1) -> dict:
    return {
        "id": fid, "name": fid.lower(), "type": "numeric",
        "levels": list(levels), "grid": grid,
        "apply": f"--{fid.lower()}={{level}}",
        "manipulation": {"observable": f"cfg.{fid.lower()}", "op": "==",
                         "value": "{level}"},
        "relations": [
            {"id": f"R{fid}c", "kind": "correctness",
             "statement": f"{fid} at baseline reproduces baseline",
             "native_test": f"tests/prop_{fid.lower()}.py::test_noop"},
            {"id": f"R{fid}b", "kind": "behavioral",
             "statement": f"response is monotone in {fid}",
             "native_test": f"tests/prop_{fid.lower()}.py::test_monotone"},
        ],
    }


def _campaign(*, factor_ids=("A", "B", "C"), held_out=None,
              invariants=None) -> dict:
    response = {"primary": {"metric": "m", "direction": "maximize"}}
    if held_out:
        response["held_out"] = list(held_out)
    opt = {
        "response": response,
        "factors": [_factor(f) for f in factor_ids],
        # `shortlist_size: 1` is DELIBERATE and explicit. The default is now 3
        # (terminal discrimination over a shortlist), and every legacy confirm
        # test in this file was written against single-point confirmation —
        # "confirm replicates ONE configuration", "confirmed_at_levels equals
        # the recommendation", "replicates == 3 usable == 3". Pinning 1 here
        # keeps those assertions MEANING what they were written to mean instead
        # of silently reinterpreting them against a three-finalist design. The
        # tests that exercise the new behaviour override this to 3.
        "design": {"screen": {"resolution": 5, "center_points": 4},
                   "refine": {"kind": "central_composite", "center_points": 4},
                   "confirm": {"replicates": 3, "shortlist_size": 1}},
    }
    if invariants:
        opt["design_space"] = {"invariants": list(invariants)}
    return {
        "kind": "optimization",
        "run_id": "opt-test",
        "research_question": "does the compound beat the parts?",
        "prompts": {"methodology_layer": "prompts/methodology",
                    "domain_adapter_layer": None},
        "target_system": {"name": "sim", "description": "a simulated target"},
        "optimization": opt,
    }


def _all_tests_pass(campaign: dict) -> dict[str, bool]:
    """Native-test results with every declared relation passing."""
    out: dict[str, bool] = {}
    for f in campaign["optimization"]["factors"]:
        for r in f["relations"]:
            out[r["native_test"]] = True
    return out


def _runner(*, extra=None, drop_row=None, noise=0.0):
    """Fake config runner: a clean linear response plus an L5-style flip.

    ``noise`` adds a small SEED-DEPENDENT term, deterministic given the row's
    workload seed so the fixture stays reproducible. Zero by default, because
    most assertions here are about a response's SHAPE and a fixed value keeps
    them readable.

    A `confirm` assertion about the terminal BOUND must pass a non-zero value:
    with identical replicates the paired differences are constant, the variance
    is zero, and `terminal_regret_bound` now correctly returns `None` rather than
    certifying exact epsilon-optimality from no information. That refusal is the
    fix, not a fixture problem -- a real target's replicates differ, which is what
    the fresh-sample comparison exists to read.
    """
    def run(row):
        lv = row.levels
        a = float(lv.get("A", 0)); b = float(lv.get("B", 0))
        jitter = 0.0
        if noise:
            # Keyed on the REPLICATE index (plus the row's own levels so two
            # finalists do not share a jitter sequence), because the workload seed
            # is injected into `apply.env` downstream of `expand` and is not on the
            # row this stub sees. Deterministic, so the fixture is reproducible.
            h = (int(row.replicate) * 2654435761 + int(a) * 40503 + int(b) * 7919)
            jitter = noise * ((h % 2003) / 1001.0 - 1.0)
        obs = {
            "cfg": {k.lower(): v for k, v in lv.items()},
            # negative main effect on A, positive AB interaction: the compound
            # beats the parts, which is the landscape this feature exists for
            "m": 10.0 - 0.05 * a + 0.20 * b + 0.02 * a * b + jitter,
        }
        if extra:
            obs.update(extra(row) or {})
        return obs
    return run


def _init_work_dir(tmp_path: Path, campaign: dict) -> Path:
    from orchestrator.iteration import setup_work_dir

    return setup_work_dir("opt-test", repo_path=None, campaign=campaign)


@pytest.fixture()
def work_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    return None


def _advance_engine(wd) -> None:
    """Mirror run_campaign's between-iteration HUMAN_FINDINGS_GATE -> DONE -> DESIGN.

    ``_enter_phase`` returns False once the engine is PAST the requested
    phase, and the block it guards at DESIGN writes ``design_matrix.json``
    and runs ``_preflight_design``. A test that drives several iterations
    through ONE work_dir must advance the machine the way production does
    (see harness.run_synthetic_campaign, which carries the same note).
    """
    from orchestrator.engine import Engine

    engine = Engine(wd)
    if engine.phase != "DONE":
        engine.transition("DONE")
    engine.transition("DESIGN")


def _run(campaign, wd, *, stage="screen", iteration=2, runner=None,
         test_results=None, integrity_check=None):
    return run_stage(
        campaign, wd, iteration=iteration, stage=stage,
        config_runner=runner or _runner(),
        test_results=test_results if test_results is not None
        else _all_tests_pass(campaign),
        integrity_check=integrity_check,
        auto_approve=True,
    )


# ─── assertion 7: the spine — a screen stage completes and writes ─────────

def test_screen_stage_completes_and_writes_its_artifact_set(tmp_path, work_dir):
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    outcome = _run(c, wd)
    assert outcome is not None

    iter_dir = Path(wd) / "runs" / "iter-2"
    for name in ("design_matrix.json", "runs.jsonl", "effects.json",
                 "relations.json", "findings.json", "principle_updates.json"):
        assert (iter_dir / name).exists(), f"missing {name}"


def test_findings_and_principles_validate_against_the_existing_schemas(
    tmp_path, work_dir,
):
    import jsonschema

    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd)
    iter_dir = Path(wd) / "runs" / "iter-2"
    schemas = Path("orchestrator/schemas")
    jsonschema.validate(
        json.loads((iter_dir / "findings.json").read_text()),
        json.loads((schemas / "findings.schema.json").read_text()),
    )
    # principle_updates.json is a BARE LIST on disk (iteration._merge_principles
    # requires it); principles.schema.json describes the merged store's
    # {"principles": [...]} wrapper. Validate each entry against the
    # per-principle definition instead of the wrapper.
    updates = json.loads((iter_dir / "principle_updates.json").read_text())
    assert isinstance(updates, list) and updates
    pschema = json.loads((schemas / "principles.schema.json").read_text())
    entry_schema = dict(pschema["$defs"]["principle"])
    entry_schema["$defs"] = pschema["$defs"]
    for entry in updates:
        jsonschema.validate(entry, entry_schema)


def test_runs_jsonl_has_one_row_per_executed_config(tmp_path, work_dir):
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd)
    rows = artifacts.read_runs(Path(wd) / "runs" / "iter-2")
    matrix_payload = json.loads(
        (Path(wd) / "runs" / "iter-2" / "design_matrix.json").read_text(),
    )
    assert len(rows) == len(matrix_payload["rows"])
    assert {r["status"] for r in rows} == {"complete"}


# ─── assertion 15: fidelity drift hard-fails EVEN under auto-approve ──────

def test_matrix_fidelity_drift_hard_fails_even_with_auto_approve(
    tmp_path, work_dir,
):
    """The #246 discipline extended from locked_parameters to the matrix.

    A silently skipped or altered cell changes the design's real resolution,
    so tolerating drift would let the campaign overstate what it can
    estimate. auto_approve removes the human, so it must not remove this.
    """
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)

    # check_fidelity compares each run's recorded `levels` against the
    # planned row at the same row_index, so the drift must be injected into
    # what gets RECORDED — mutating telemetry only would test nothing.
    original_append = artifacts.append_run

    def drifting_append(iter_dir, row):
        row = dict(row)
        if row.get("row_index") == 0:
            row["levels"] = {k: 999 for k in row["levels"]}
        return original_append(iter_dir, row)

    import orchestrator.optimize.stage_runner as sr
    monkey = sr.artifacts
    saved = monkey.append_run
    monkey.append_run = drifting_append
    try:
        with pytest.raises(OptimizationAborted) as exc:
            _run(c, wd)
    finally:
        monkey.append_run = saved
    assert "design_matrix.json" in str(exc.value)


# ─── assertion 14: a correctness violation aborts before any runs ─────────

def test_correctness_relation_failure_at_verify_aborts_before_any_runs(
    tmp_path, work_dir,
):
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    results = _all_tests_pass(c)
    results["tests/prop_a.py::test_noop"] = False  # a conservation law broke

    with pytest.raises(OptimizationAborted) as exc:
        _run(c, wd, stage="verify", iteration=1, test_results=results)
    msg = str(exc.value)
    assert "correctness" in msg.lower()
    # no sweep may have executed
    assert not (Path(wd) / "runs" / "iter-1" / "runs.jsonl").exists()


def test_a_declared_relation_absent_from_results_is_a_failure(
    tmp_path, work_dir,
):
    """A typo'd native_test must never look satisfied."""
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    with pytest.raises(OptimizationAborted):
        _run(c, wd, stage="verify", iteration=1, test_results={})


# ─── assertion 16: a behavioral violation does NOT abort ──────────────────

def test_behavioral_violation_does_not_abort_and_reaches_findings(
    tmp_path, work_dir,
):
    """A monotonicity break is a discovery, not a broken apparatus.

    The motivating case is a lever measured -9.5% alone yet required for the
    winning compound. Halting here would make the campaign blind to exactly
    what it exists to find.
    """
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    results = _all_tests_pass(c)
    results["tests/prop_a.py::test_monotone"] = False  # behavioral only

    outcome = _run(c, wd, test_results=results)
    assert outcome is not None  # did NOT abort

    iter_dir = Path(wd) / "runs" / "iter-2"
    verdicts = json.loads((iter_dir / "relations.json").read_text())
    behavioral = [
        v for v in verdicts["verdicts"]
        if v["kind"] == "behavioral" and not v["passed"]
    ]
    assert behavioral, "the behavioral failure must be recorded"

    # `behavioral_violation` sits in `policy.OBSERVATION_KEYS` with NO
    # consuming `when` clause, deliberately — the violation is a discovery to
    # report, never a reason to end the epoch. That makes THIS the artifact
    # the evidence has to reach, and the assertion that keeps the vocabulary
    # entry's "unconsumed on purpose" note honest: the note in
    # `stage._behavioral_trigger_note` is folded into `StageDecision.rationale`,
    # which `run_stage` passes to `artifacts.project_findings` as `decision`,
    # which lands in `findings.json`'s `discrepancy_analysis` and in every
    # arm's `metadata.decision`. If the note ever stops reaching here, the
    # signal really would be silently dropped and the key really would need a
    # transition.
    findings = json.loads((iter_dir / "findings.json").read_text())
    rid = behavioral[0]["relation_id"]
    assert rid in findings["discrepancy_analysis"], findings["discrepancy_analysis"]
    assert "non-monotonicity" in findings["discrepancy_analysis"]
    assert any(
        rid in (a.get("metadata") or {}).get("decision", "")
        for a in findings["arms"]
    ), findings["arms"]
    # ...and the campaign advanced anyway: the finding is valid evidence, and
    # the transition out of this stage is the one it would have taken with no
    # violation at all.
    assert findings["experiment_valid"] is True
    trans = [
        json.loads(line)
        for line in (Path(wd) / "transitions.jsonl").read_text().splitlines()
        if line.strip()
    ]
    row = next(t for t in trans if t["iteration"] == 2)
    assert row["observations"]["behavioral_violation"] is True
    assert row["to"] != "exception", row


# ─── the held-out leakage guard, at the stage-runner seam ─────────────────

def test_held_out_metric_reaching_a_fitting_input_hard_fails(
    tmp_path, work_dir,
):
    c = _campaign(held_out=["oos"])
    wd = _init_work_dir(tmp_path, c)

    # A runner that leaks the held-out metric into the fitting response is
    # normally impossible (runner.execute_design splits it out), so drive
    # the guard directly with an outcome that carries it.
    from orchestrator.optimize.stage_runner import _fitting_responses

    class _O:
        status = "complete"
        row_index = 0
        response = {"m": 1.0, "oos": 99.0}

    with pytest.raises(OptimizationAborted) as exc:
        _fitting_responses([_O()], c["optimization"]["response"], "m")
    assert "held-out" in str(exc.value)


def test_primary_metric_also_declared_held_out_is_rejected(tmp_path):
    from orchestrator.optimize.stage_runner import _fitting_responses

    spec = {"primary": {"metric": "m", "direction": "maximize"},
            "held_out": ["m"]}
    with pytest.raises(OptimizationAborted) as exc:
        _fitting_responses([], spec, "m")
    assert "generalization check" in str(exc.value)


# ─── the correctness/behavioral split, enforced at the call site ──────────

def test_passing_a_correctness_verdict_as_behavioral_is_rejected():
    """stage.py does not inspect RelationVerdict.kind, so this seam must.

    Mis-wiring here would UNDER-react: behavioral triggers advance the
    stage, while a correctness failure must abort the campaign.
    """
    from orchestrator.optimize.relations import RelationVerdict
    from orchestrator.optimize.stage_runner import _assert_all_behavioral

    wrong = (RelationVerdict(
        relation_id="R1", factor_id="A", kind="correctness",
        native_test="t.py::c", passed=False, detail="conservation broke",
    ),)
    with pytest.raises(OptimizationAborted) as exc:
        _assert_all_behavioral(wrong)
    assert "behavioral" in str(exc.value)


def test_behavioral_verdicts_pass_the_call_site_guard():
    from orchestrator.optimize.relations import RelationVerdict
    from orchestrator.optimize.stage_runner import _assert_all_behavioral

    ok = (RelationVerdict(
        relation_id="R2", factor_id="A", kind="behavioral",
        native_test="t.py::m", passed=False, detail="monotonicity broke",
    ),)
    assert _assert_all_behavioral(ok) == ok


# ─── the runner seam is required, not optional ────────────────────────────

def test_missing_config_runner_fails_loudly(tmp_path, work_dir):
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    with pytest.raises(OptimizationAborted) as exc:
        run_stage(c, wd, iteration=2, stage="screen", config_runner=None,
                  test_results=_all_tests_pass(c), auto_approve=True)
    assert "config_runner" in str(exc.value)


# ─── the refine stage: design width must match the fitted factor ids ──────

def test_refine_stage_fits_only_the_refinable_factors(tmp_path, work_dir):
    """Regression: refine builds a CCD over the REFINABLE factors only.

    Passing every declared factor id to fit_effects misaligns the model
    matrix against the design's column width and raises IndexError. Every
    other test here exercises `screen`, where the two sets coincide — which
    is exactly why this went unnoticed until the refine path was driven.
    """
    c = _campaign(factor_ids=("A", "B"))
    # A carries >2 levels so it is refinable; B is 2-level so it is not.
    c["optimization"]["factors"][0]["levels"] = [1, 2, 4, 8]
    c["optimization"]["factors"][1]["levels"] = [0, 1]
    wd = _init_work_dir(tmp_path, c)

    outcome = _run(c, wd, stage="refine", iteration=3)
    assert outcome is not None

    iter_dir = Path(wd) / "runs" / "iter-3"
    effects = json.loads((iter_dir / "effects.json").read_text())
    labels = {e["label"] for e in effects["effects"]}
    # only the refinable factor may appear as a fitted main effect
    assert "A" in labels
    assert "B" not in labels, (
        "B is 2-level and absent from the refine design, so it must not "
        "appear as a fitted effect"
    )


def test_design_factor_ids_agrees_with_the_built_design_width(tmp_path):
    """The invariant behind the bug above, asserted directly."""
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.stage_runner import (
        _build_design,
        _design_factor_ids,
    )

    c = _campaign(factor_ids=("A", "B"))
    c["optimization"]["factors"][0]["levels"] = [1, 2, 4, 8]
    c["optimization"]["factors"][1]["levels"] = [0, 1]
    factors = parse_factors(c["optimization"]["factors"])
    cfg = c["optimization"]["design"]

    for stage in ("screen", "refine"):
        design = _build_design(factors, cfg, stage)
        ids = _design_factor_ids(factors, cfg, stage)
        assert len(ids) == len(design.points[0].coded), (
            f"{stage}: {len(ids)} factor ids against a design of width "
            f"{len(design.points[0].coded)}"
        )


# ─── the three Criticals from independent review ──────────────────────────

def test_the_final_stage_transitions_to_done_and_reports_completed(
    tmp_path, work_dir,
):
    """Otherwise run_campaign never stops.

    run_campaign only terminates on COMPLETED / ABORTED / REDESIGN. A
    CONTINUE from the last stage makes it call one more iteration, and the
    campaign never ends. The mechanism changed in Task 6 — the compiled
    policy routes ``confirm -> report`` on its registered round cap, rather
    than ``_is_final_stage`` recognising ``confirm`` as the last list entry —
    but the observable outcome asserted here is deliberately unchanged.

    TASK 9 note: confirm now needs a finalist to measure, so a screen stage
    runs first. Previously this drove confirm on an empty work_dir and got the
    design's geometric origin — a configuration nothing recommended and nothing
    had measured. That fallback is retired (see
    ``test_confirm_with_no_finalist_at_all_aborts_rather_than_inventing_one``);
    what this test is about is TERMINATION, so it now sets up the state a
    terminal stage actually reaches production in.
    """
    from orchestrator.engine import Engine
    from orchestrator.iteration import IterationOutcome

    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="screen", iteration=3)
    _advance_engine(wd)
    outcome = _run(c, wd, stage="confirm", iteration=4)
    assert outcome is IterationOutcome.COMPLETED
    assert Engine(wd).phase == "DONE"


def test_a_non_final_stage_reports_continue(tmp_path, work_dir):
    from orchestrator.iteration import IterationOutcome

    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    assert _run(c, wd, stage="screen", iteration=2) is IterationOutcome.CONTINUE


def test_an_explicit_stages_list_decides_which_stage_is_terminal(tmp_path):
    """Same claim as before Task 6, asked of the compiled policy.

    ``_is_final_stage`` answered this from the ``stages`` LIST's last entry —
    an index question. The policy answers it from what ``step`` routes to,
    which is the same answer for these three campaigns and a DIFFERENT
    (correct) one whenever the list order and the registered paths disagree.
    Asserting through ``step`` is what keeps the assertion about finality
    rather than about a list position.
    """
    from orchestrator.optimize.policy import compile_policy, step

    def _routes_to(campaign, state, **obs):
        # `round: 1` is the first confirm round under the 1-based convention
        # (_confirm_round); at the default confirm_max_rounds of 1 that is
        # already the registered cap, which is what makes one confirm
        # iteration terminal exactly as it was before Task 6.
        base = {"correctness_failed": False, "nan_response": False,
                "certified": False, "round": 1, "budget_remaining": 10 ** 9,
                "refinable_survivors": 0}
        return step(compile_policy(campaign), state, {**base, **obs})[0]

    default = _campaign()
    assert _routes_to(default, "confirm") == "report"
    # `_campaign`'s factors are all 2-level, so NOTHING is refinable and the
    # compiled policy omits the refine state entirely — a stronger and more
    # honest statement than `_is_final_stage(default, "refine") is False`,
    # which reported "not terminal" about a stage the campaign cannot run.
    assert "refine" not in compile_policy(default)["states"]
    assert _routes_to(default, "screen") == "confirm"

    refinable = _campaign()
    refinable["optimization"]["factors"][0]["levels"] = [1, 2, 4, 8]
    assert "refine" in compile_policy(refinable)["states"]
    # a refinable survivor routes screen -> refine, not to a terminal
    assert _routes_to(refinable, "screen", refinable_survivors=1) == "refine"
    assert _routes_to(refinable, "refine") == "confirm"

    short = _campaign()
    short["optimization"]["factors"][0]["levels"] = [1, 2, 4, 8]
    short["optimization"]["stages"] = ["verify", "screen", "confirm"]
    assert _routes_to(short, "confirm") == "report"
    # refine is dropped because the STAGES LIST omits it, even though a factor
    # is refinable — the explicit list still decides, as it always did.
    assert "refine" not in compile_policy(short)["states"]

    no_confirm = _campaign()
    no_confirm["optimization"]["stages"] = ["verify", "screen"]
    assert _routes_to(no_confirm, "screen") == "report"
    assert "confirm" not in compile_policy(no_confirm)["states"]


def test_a_partially_failed_sweep_refits_rather_than_emitting_nan_or_aborting(
    tmp_path, work_dir,
):
    """BEHAVIOUR REVERSED, deliberately, and the old claim was HALF right.

    The half that stands: one NaN among eight runs makes every effect estimate
    AND the intercept NaN, and the artifacts stay schema-valid because
    jsonschema accepts NaN as "number", so a campaign would emit a
    confident-looking, entirely-NaN effects.json with no error at all. A NaN
    must never reach ``fit_effects``. That is still asserted below.

    The half that was wrong: this test used to require the campaign to ABORT,
    and its own abort message named the better option it did not take ("or
    refit on the completed subset and report the reduced resolution"). Two
    guards over one condition disagreed, and the abort ran first, so the refit
    that ``run_stage`` already implemented was unreachable for exactly the rows
    it was written for. Measured on a real 14-hour campaign: 18 rows measured,
    15 valid, 3 failed (two wall-clock timeouts, one adapter crash), and all
    four attempted iterations threw away all 15 valid measurements — no
    recommendation and no residual-regret certificate were ever produced.

    So the invariant is unchanged (no NaN coefficient) and the RESPONSE to a
    partial design is now to fit the retained subset and record the loss.
    """
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)

    calls = {"n": 0}

    def flaky(row):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("benchmark crashed")
        lv = row.levels
        return {"cfg": {k.lower(): v for k, v in lv.items()},
                "m": 10.0 + float(lv.get("A", 0))}

    _run(c, wd, stage="screen", iteration=2, runner=flaky)

    eff = json.loads((Path(wd) / "runs" / "iter-2" / "effects.json").read_text())
    ests = [e["estimate"] for e in eff["effects"]] + [eff["intercept"]]
    assert ests, "no coefficients written"
    assert all(v == v for v in ests), (
        f"a NaN coefficient reached effects.json: {ests}"
    )

    fx = json.loads(
        (Path(wd) / "runs" / "iter-2" / "fit_exclusions.json").read_text(),
    )
    assert fx["planned_rows"] == fx["fitted_rows"] + len(fx["excluded_row_indices"])
    assert "failed_to_measure" in fx["excluded_by_reason"], fx


def test_locked_parameters_is_not_claimed_as_a_wired_check():
    """The docstring must not advertise a guarantee the code lacks.

    An earlier version listed locked_parameters as one of four hard-fails.
    It was never wired — the check lives in bundle validation and this path
    has no bundle. A docstring that overstates the guarantees is worse than
    an omission, because it stops the next reader from adding the check.
    """
    import orchestrator.optimize.stage_runner as sr

    doc = sr.__doc__ or ""
    assert "NOT YET WIRED" in doc
    assert "locked_parameters" in doc
    # and it must not be counted among the active checks
    assert "Four checks hard-fail" not in doc


def test_infeasible_and_rejected_rows_do_not_block_the_fit(tmp_path):
    """They are excluded from fitting, not treated as measurement failures.

    An `infeasible` row RAN and produced trustworthy numbers; it just
    violated a declared constraint, which is real information about the
    design space (spec §6.4). A constrained design will routinely have
    inadmissible corners, so aborting on one would make constraints
    unusable. `rejected` is likewise excluded rather than fatal. Only a row
    that produced no usable measurement blocks.
    """
    import math

    from orchestrator.optimize.stage_runner import _fitting_responses

    class _O:
        def __init__(self, idx, status, resp):
            self.row_index, self.status, self.response = idx, status, resp

    spec = {"primary": {"metric": "m", "direction": "maximize"}}
    for tolerated in ("infeasible", "rejected"):
        values = _fitting_responses(
            [_O(0, "complete", {"m": 1.0}), _O(1, tolerated, {"m": 2.0})],
            spec, "m",
        )
        assert not math.isnan(values[0])
        assert math.isnan(values[1]), (
            f"a {tolerated} row must be excluded from the fit, which the NaN "
            f"carries — not abort the campaign"
        )

    # A `failed` row is ALSO carried as NaN rather than aborting. It means
    # something different scientifically — a repairable hole in the design
    # rather than information about X_valid — and `fit_exclusions.json` records
    # which reason applied to which row. What it must NOT do is end the
    # campaign: `run_stage`'s partial-fit path drops it and refits.
    failed_values = _fitting_responses(
        [_O(0, "complete", {"m": 1.0}), _O(1, "failed", {})], spec, "m",
    )
    assert not math.isnan(failed_values[0])
    assert math.isnan(failed_values[1])


def test_a_non_numeric_primary_metric_aborts_cleanly(tmp_path):
    """Raw TypeError/ValueError from float() is not an acceptable failure.

    A target emitting a string, a structure, or null for the response metric
    is an instrumentation mismatch. It deserves a message naming the row and
    the offending value, not a stack trace from a float() call.
    """
    from orchestrator.optimize.stage_runner import _fitting_responses

    class _O:
        def __init__(self, idx, status, resp):
            self.row_index, self.status, self.response = idx, status, resp

    spec = {"primary": {"metric": "m", "direction": "maximize"}}
    for bad in ("fast", {}, []):
        with pytest.raises(OptimizationAborted) as exc:
            _fitting_responses([_O(0, "complete", {"m": bad})], spec, "m")
        assert "not a number" in str(exc.value)
        assert "row 0" in str(exc.value)


def test_a_null_primary_metric_is_carried_as_nan_under_a_distinct_reason(
    tmp_path,
):
    """`null` means the benchmark ran but could not compute the statistic.

    BEHAVIOUR REVERSED with the rest of the partial-fit reconciliation: this no
    longer aborts on a `complete` row. It is excluded from the fit like any
    unusable row, and it keeps a DISTINCT reason (`no_metric` rather than
    `failed_to_measure`) because the two point a reader at different places —
    the target ran successfully and only the statistic is missing, which
    implicates the instrumentation rather than the run.

    Not to be confused with a `complete` row reporting a genuine float NaN,
    which is a SEMANTIC exception routed to the policy's `nan_response` branch
    (`_primary_is_nan`) and is unchanged: `None` is an absent value, a float NaN
    is the target asserting the objective is not measurable there.
    """
    import math

    from orchestrator.optimize.stage_runner import (
        _exclusion_reason,
        _fitting_responses,
    )

    class _O:
        def __init__(self, idx, status, resp):
            self.row_index, self.status, self.response = idx, status, resp

    spec = {"primary": {"metric": "m", "direction": "maximize"}}
    values = _fitting_responses([_O(0, "complete", {"m": None})], spec, "m")
    assert math.isnan(values[0])
    assert _exclusion_reason(_O(0, "complete", {"m": None})) == "no_metric"

    values = _fitting_responses([_O(0, "infeasible", {"m": None})], spec, "m")
    assert math.isnan(values[0])
    assert _exclusion_reason(_O(0, "infeasible", {"m": None})) == "infeasible"


# ─── confirm actually confirms (F1 from the final whole-branch review) ─────

def test_confirm_at_shortlist_one_replicates_a_single_configuration(
    tmp_path, work_dir,
):
    """F1: confirm used to silently rebuild the screen design.

    So the campaign's final stage repeated stage 2 and reported COMPLETED
    while the guide claimed it reproduced the predicted optimum. That is the
    one defect on this branch that could mislead a researcher about their own
    result, which is why it is fixed rather than documented.

    TASK 9 rewrote this test's SUBJECT, not its claim. It used to compare
    ``_build_design(.., "confirm")`` against ``_build_design(.., "screen")`` at
    the level of coded coordinates. Confirm no longer builds a coded design at
    all — ``_confirm_rows`` returns real-level rows for a shortlist of
    finalists — so ``_build_design``'s confirm branch is gone and calling it
    raises. The claim asserted here is unchanged and now asserted on the
    artifact that actually ships: at ``shortlist_size: 1`` confirm runs ONE
    configuration ``replicates`` times, and it is not the screen matrix.
    """
    from orchestrator.optimize.stage_runner import _build_design

    c = _campaign()          # shortlist_size: 1, replicates: 3
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="screen", iteration=2)
    screen_rows = [
        dict(r["levels"])
        for r in json.loads(
            (Path(wd) / "runs" / "iter-2" / "design_matrix.json").read_text(),
        )["rows"]
    ]
    _advance_engine(wd)
    _run(c, wd, stage="confirm", iteration=3)

    payload = json.loads(
        (Path(wd) / "runs" / "iter-3" / "design_matrix.json").read_text(),
    )
    assert payload["kind"] == "shortlist_replicate"
    assert len(payload["finalists"]) == 1
    confirm_rows = [dict(r["levels"]) for r in payload["rows"]]
    assert len(confirm_rows) == c["optimization"]["design"]["confirm"]["replicates"]
    # one configuration, replicated
    assert all(lv == confirm_rows[0] for lv in confirm_rows)
    assert sorted(r["replicate"] for r in payload["rows"]) == [0, 1, 2]
    # ...and it is not a re-run of the screen matrix
    assert confirm_rows != screen_rows[:len(confirm_rows)]

    # `_build_design` no longer has a confirm branch to consult, and says so.
    with pytest.raises(OptimizationAborted, match="_build_design was called"):
        _build_design([], c["optimization"]["design"], "confirm")


def test_confirm_honours_the_previous_stages_recommendation(tmp_path, work_dir):
    """The loop must close: a stage recommends, confirm replicates THAT.

    Task 7 moved the handoff from ``confirm_at.json`` (the refine stage's
    stationary point, in CODED coordinates) to ``recommendation.json`` (the
    argmax over X_valid, in REAL levels). Asserted end to end rather than
    through ``_build_design``, because the design no longer carries the target
    at all — ``run_stage`` pins each row's ``levels`` and renders ``apply``
    from them, which is what makes the coordinate-discarding class of bug
    (``role="center"``) unexpressible here.
    """
    c = _campaign()
    c["optimization"]["stages"] = ["verify", "screen", "confirm"]
    wd = _init_work_dir(tmp_path, c)

    _run(c, wd, stage="screen", iteration=2)
    rec = json.loads(
        (Path(wd) / "runs" / "iter-2" / "recommendation.json").read_text(),
    )
    assert rec["levels"], rec

    _advance_engine(wd)
    _run(c, wd, stage="confirm", iteration=3)

    record = json.loads(
        (Path(wd) / "runs" / "iter-3" / "confirmation.json").read_text(),
    )
    assert record["confirmed_at_levels"] == rec["levels"], (
        f"confirm ran {record['confirmed_at_levels']} but the recommendation "
        f"was {rec['levels']}"
    )
    matrix_payload = json.loads(
        (Path(wd) / "runs" / "iter-3" / "design_matrix.json").read_text(),
    )
    # `confirm_source` (one string for the one target) became per-finalist
    # provenance in Task 9: the shortlist can draw its members from several
    # sources at once, so a single scalar can no longer say where they came
    # from. At `shortlist_size: 1` there is exactly one, and it is the model's.
    assert [f["why"] for f in matrix_payload["finalists"]] == [
        "screen recommendation",
    ]
    assert all(row["levels"] == rec["levels"] for row in matrix_payload["rows"])
    # And every replicate ACTUALLY ran there, not just the plan.
    for row in artifacts.read_runs(Path(wd) / "runs" / "iter-3"):
        assert row["levels"] == rec["levels"], row


def test_confirm_writes_a_confirmation_record_and_no_effects(tmp_path, work_dir):
    """Confirm reports reproduction; it does not fit a model.

    A single replicated configuration has no distinct design points, so
    fitting raises "design matrix is singular" — correctly. What confirm
    claims is narrower and more useful: this exact configuration, replicated
    N times, produced this mean and this spread.
    """
    from orchestrator.iteration import IterationOutcome

    c = _campaign()          # shortlist_size: 1
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="screen", iteration=3)
    _advance_engine(wd)
    outcome = _run(c, wd, stage="confirm", iteration=4)
    assert outcome is IterationOutcome.COMPLETED

    iter_dir = Path(wd) / "runs" / "iter-4"
    record = json.loads((iter_dir / "confirmation.json").read_text())
    assert record["replicates"] == 3
    assert record["usable_replicates"] == 3
    assert record["mean"] is not None
    assert "confirmed_at_levels" in record
    # no fit at confirm
    assert not (iter_dir / "effects.json").exists()


def test_confirm_findings_validate_and_report_reproduction(tmp_path, work_dir):
    """A single-finalist confirm cannot CERTIFY, and must not claim to.

    At ``shortlist_size: 1`` there is no challenger, so the terminal bound is
    ``0.0`` by the trivial branch and ``0.0 <= epsilon`` holds — which certifies
    on the strength of having nothing to compare against. That is honest as far
    as it goes: the paper scopes the terminal claim to the REALIZED shortlist,
    and a shortlist of one contains its own optimum trivially, so nothing here
    is false. It is also nearly vacuous, which is exactly why the default
    shortlist is 3 — the useful claim needs rivals.

    Contrast the ``sla`` case (``test_sla_surface_never_recommends_an_invalid_point``),
    where a bound of ``0.0`` over one survivor must NOT be certified. The
    difference is not the shortlist size: it is that ``sla`` got there by
    MEASURING finalists inadmissible, which is evidence the ``delta_screen``
    premise behind the global claim has failed. Here the author simply asked for
    one finalist, nothing was excluded, and the screening premise is untouched.

    Asserted here so a reader of a single-point campaign's findings knows what
    that CONFIRMED does and does not mean.
    """
    import jsonschema

    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="screen", iteration=3)
    _advance_engine(wd)
    _run(c, wd, stage="confirm", iteration=4)

    findings = json.loads(
        (Path(wd) / "runs" / "iter-4" / "findings.json").read_text(),
    )
    schema = json.loads(Path("orchestrator/schemas/findings.schema.json").read_text())
    jsonschema.validate(findings, schema)
    assert findings["experiment_valid"] is True
    assert findings["arms"][0]["status"] == "CONFIRMED"
    assert "fresh runs" in findings["arms"][0]["observed"]
    conf = json.loads(
        (Path(wd) / "runs" / "iter-4" / "confirmation.json").read_text(),
    )
    assert conf["terminal_bound"]["method"] == "trivial", (
        "a one-member shortlist has no challenger; the bound must say so rather "
        "than looking like a measured comparison"
    )


# ─── F4: the survivor-selection path, which nothing else exercises ────────

def test_a_noisy_runner_exercises_significance_and_survivor_selection(
    tmp_path, work_dir,
):
    """F4 from the final review: every other test here leaves this dead.

    The deterministic fake runner returns identical values at all four centre
    points, so pure-error variance is exactly 0.0, `have_se` is False, every
    `significant` is None, and `dropped_factors` always returns []. That
    means the whole screen-to-refine survivor-selection mechanism — the
    reason the stage rule exists at all — was never driven end to end.

    A tiny deterministic perturbation at the centre points is enough to give
    a real pure-error estimate without making the test flaky.
    """
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)

    nudge = iter([0.0, 0.004, -0.003, 0.005, -0.002, 0.001] * 8)

    def noisy(row):
        lv = row.levels
        a, b = float(lv.get("A", 0)), float(lv.get("B", 0))
        # A and B carry real effects; C carries none.
        base = 10.0 - 0.05 * a + 0.20 * b
        if row.role == "center":
            base += next(nudge)
        return {"cfg": {k.lower(): v for k, v in lv.items()}, "m": base}

    _run(c, wd, runner=noisy)

    effects = json.loads(
        (Path(wd) / "runs" / "iter-2" / "effects.json").read_text(),
    )
    by_label = {e["label"]: e for e in effects["effects"]}

    # a real pure-error estimate now exists, so significance is decidable
    assert effects["pure_error_var"] is not None
    assert effects["pure_error_var"] > 0
    assert by_label["B"]["significant"] is not None, (
        "with pure error available, significance must be decided rather than "
        "left unknown — that is the whole point of the centre points"
    )

    # and the decision actually discriminates: C has no planted effect
    assert by_label["B"]["significant"] is True
    assert by_label["C"]["significant"] is False

    findings = json.loads(
        (Path(wd) / "runs" / "iter-2" / "findings.json").read_text(),
    )
    arm_types = {a["arm_type"] for a in findings["arms"]}
    assert "h-control-negative" in arm_types, (
        "a factor found within noise must project as a negative-control arm, "
        "which only happens once significance is decidable"
    )


def test_the_recommendation_is_read_from_the_latest_iteration_numerically(tmp_path):
    """Lexicographic path sorting picks iter-2 over iter-10.

    "iter-10" sorts before "iter-2" as a string, so a lexicographic sort
    silently replicates a STALE recommendation on any campaign reaching
    double-digit iterations — a wrong answer with no error. Found by review of
    the confirm fix itself, on a path nothing drove; carried forward from
    ``confirm_at.json`` to ``recommendation.json`` because the hazard is in
    the directory names, not in the file.
    """
    from orchestrator.optimize.stage_runner import _read_recommendation

    for iteration, level in ((2, 2), (9, 8), (10, 16)):
        d = tmp_path / "runs" / f"iter-{iteration}"
        d.mkdir(parents=True)
        (d / "recommendation.json").write_text(
            json.dumps({"stage": "screen", "levels": {"A": level}}),
        )

    assert _read_recommendation(tmp_path)["levels"] == {"A": 16}


def test_the_recommendation_read_survives_a_non_numeric_iteration_directory(tmp_path):
    from orchestrator.optimize.stage_runner import _read_recommendation

    (tmp_path / "runs" / "iter-3").mkdir(parents=True)
    (tmp_path / "runs" / "iter-3" / "recommendation.json").write_text(
        '{"levels": {"A": 4}}',
    )
    (tmp_path / "runs" / "iter-bogus").mkdir(parents=True)
    (tmp_path / "runs" / "iter-bogus" / "recommendation.json").write_text(
        '{"levels": {"A": 99}}',
    )

    assert _read_recommendation(tmp_path)["levels"] == {"A": 4}


def test_no_recommendation_anywhere_reads_as_none_rather_than_raising(tmp_path):
    """Three callers branch on this: refine's held-fixed lookup, confirm's
    target, and the screen stage (which has no predecessor by construction).
    A missing artifact is the ordinary first-stage case, not an error."""
    from orchestrator.optimize.stage_runner import _read_recommendation

    assert _read_recommendation(tmp_path) is None          # no runs/ at all
    (tmp_path / "runs" / "iter-1").mkdir(parents=True)
    assert _read_recommendation(tmp_path) is None          # runs/, no artifact
    assert _read_recommendation(None) is None


def test_a_malformed_recommendation_is_skipped_for_an_older_readable_one(tmp_path):
    """A torn write must not blind the campaign to the recommendation it has.

    ``_write_json`` is not atomic across a crash, so the newest file is the
    one that can be half-written. Falling back to the previous iteration's
    recommendation is a stale-but-real answer; raising here would abort a
    campaign that has a perfectly usable one on disk.
    """
    from orchestrator.optimize.stage_runner import _read_recommendation

    (tmp_path / "runs" / "iter-2").mkdir(parents=True)
    (tmp_path / "runs" / "iter-2" / "recommendation.json").write_text(
        json.dumps({"stage": "screen", "levels": {"A": 8}}),
    )
    (tmp_path / "runs" / "iter-3").mkdir(parents=True)
    (tmp_path / "runs" / "iter-3" / "recommendation.json").write_text('{"levels":')

    assert _read_recommendation(tmp_path)["levels"] == {"A": 8}


def test_measured_infeasible_collects_infeasible_and_rejected_levels(tmp_path):
    """The exclusion set the argmax subtracts from X_valid.

    ``infeasible`` (a constraint said no) and ``rejected`` (the integrity
    check said no) are both direct evidence a configuration cannot be
    recommended. ``complete`` and ``failed`` rows are not: a completed row is
    admissible, and a failed one says nothing about admissibility.
    """
    from orchestrator.optimize.artifacts import append_run
    from orchestrator.optimize.stage_runner import _measured_infeasible

    iter_dir = tmp_path / "runs" / "iter-2"
    iter_dir.mkdir(parents=True)
    for idx, status in enumerate(
        ("complete", "infeasible", "rejected", "failed"),
    ):
        append_run(iter_dir, {
            "row_index": idx, "levels": {"A": idx}, "role": "corner",
            "replicate": 0, "status": status, "response": {"m": 1.0},
            "held_out": {}, "manipulation": [], "invariants": [],
            "duration_ms": 1, "error": "",
        })

    assert _measured_infeasible(tmp_path) == [{"A": 1}, {"A": 2}]
    assert _measured_infeasible(tmp_path / "nowhere") == []


def test_stage_for_iteration_rejects_a_non_positive_iteration():
    """Returning a stage for iteration 0 would hand back the TERMINAL stage,
    ending a campaign on what the caller thought was its first iteration.
    """
    from orchestrator.optimize.stage import stage_for_iteration

    for bad in (0, -1):
        with pytest.raises(ValueError, match="1-based"):
            stage_for_iteration({}, bad)
    assert stage_for_iteration({}, 1).value == "verify"
    assert stage_for_iteration({}, 4).value == "confirm"


# ─── design pre-flight: fail before the sweep, not after ──────────────────

def test_design_preflight_rejects_a_level_outside_its_declared_range():
    """The reflective kind validates its bundle at DESIGN; this path did not.

    Verified on a live campaign: axial extrapolation produced MAXRUN = -112
    from a factor declared [64, 256], the target rejected 16 of 80 refine
    runs, and the NaN guard then discarded the whole stage — after doing all
    the work. Failing at DESIGN costs one phase; failing after the sweep
    costs the campaign.
    """
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.matrix import ConfigRow
    from orchestrator.optimize.stage_runner import _preflight_design

    factors = parse_factors([{
        "id": "MAXRUN", "name": "cap", "type": "numeric",
        "levels": [64, 256], "grid": 1,
        "apply": "--max-num-running-reqs={level}",
        "manipulation": {"observable": "applied.MAXRUN", "op": "==",
                         "value": "{level}"},
        "relations": [{"id": "R", "kind": "correctness", "statement": "s",
                       "native_test": "t.go::TestX"}],
    }])
    bad = [
        ConfigRow(row_index=0, levels={"MAXRUN": 160}, role="corner",
                  replicate=0, apply={"cli_args": [], "env": {}, "patches": []}),
        ConfigRow(row_index=1, levels={"MAXRUN": -112}, role="axial",
                  replicate=0, apply={"cli_args": [], "env": {}, "patches": []}),
    ]
    with pytest.raises(OptimizationAborted) as exc:
        _preflight_design(bad, factors, {}, Path("/tmp"))
    msg = str(exc.value)
    assert "outside its declared range" in msg
    assert "-112" in msg
    assert "row 1" in msg
    # the in-range row must NOT be reported
    assert "row 0" not in msg


def test_design_preflight_passes_a_clean_matrix():
    from orchestrator.optimize.design import full_factorial
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.matrix import expand
    from orchestrator.optimize.stage_runner import _preflight_design

    factors = parse_factors([{
        "id": "MAXRUN", "name": "cap", "type": "numeric",
        "levels": [64, 256], "grid": 1,
        "apply": "--max-num-running-reqs={level}",
        "manipulation": {"observable": "applied.MAXRUN", "op": "==",
                         "value": "{level}"},
        "relations": [{"id": "R", "kind": "correctness", "statement": "s",
                       "native_test": "t.go::TestX"}],
    }])
    rows = expand(full_factorial(("MAXRUN",)), factors)
    _preflight_design(rows, factors, {}, Path("/tmp"))   # must not raise


def test_refine_refuses_to_fabricate_a_design_when_nothing_is_refinable():
    """`refinable or ids` silently built a CCD over every factor.

    Verified on a live campaign: six two-level factors (four `choice`, two
    `numeric`) meant NOTHING was refinable, but refine ran anyway and fitted
    quadratic terms for the categorical factors. Two came out exactly 0.0,
    the Hessian went singular, solve_stationary_point returned None, no
    confirm target was written, and `confirm` replicated the ORIGIN. The
    campaign had already observed the true optimum (117.854) and then
    confirmed a 73.476 centre point instead.

    Task 7 retired that handoff (confirm replicates ``recommendation.json``
    now), but the reason to refuse here is unchanged: a quadratic term for a
    categorical factor is meaningless whatever consumes it.
    """
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.stage_runner import _build_design

    c = _campaign(factor_ids=("A", "B"))
    for f in c["optimization"]["factors"]:
        f["levels"] = [64, 256]          # two levels: not refinable
    factors = parse_factors(c["optimization"]["factors"])
    cfg = c["optimization"]["design"]

    with pytest.raises(OptimizationAborted) as exc:
        _build_design(factors, cfg, "refine")
    msg = str(exc.value)
    assert "nothing to refine" in msg
    assert "MORE THAN two levels" in msg
    assert "screen -> confirm" in msg


def test_design_factor_ids_is_empty_at_refine_when_nothing_is_refinable():
    """No silent fallback to the full factor list."""
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.stage_runner import _design_factor_ids

    c = _campaign(factor_ids=("A", "B"))
    for f in c["optimization"]["factors"]:
        f["levels"] = [64, 256]
    factors = parse_factors(c["optimization"]["factors"])
    assert _design_factor_ids(factors, c["optimization"]["design"], "refine") == ()
    # screen still spans everything
    assert len(_design_factor_ids(factors, c["optimization"]["design"], "screen")) == 2


def test_confirm_replicates_the_best_observed_config_when_there_is_no_recommendation(
    tmp_path, work_dir,
):
    """Replicating the ORIGIN was actively misleading.

    On a live campaign the screen stage observed goodput 117.854 and confirm
    reproduced a 73.476 centre point — the campaign found the right answer
    and reported the wrong one. With nothing recommending a configuration,
    the honest thing to reproduce is the best one actually measured.

    BEHAVIOUR CHANGE, Task 7. The trigger for this fallback used to be "no
    fitted stationary point", which a screen-only campaign always met — so
    this test drove it by running screen and then confirm. Every fitting stage
    now writes ``recommendation.json``, so a screen-only campaign has a
    recommendation and confirm replicates THAT (see
    ``test_confirm_honours_the_previous_stages_recommendation``). The fallback
    survives for the case that genuinely has nothing to go on: measurements on
    disk from an earlier iteration but no recommendation with them, which is
    what a resumed or hand-assembled work_dir looks like. Driven by writing
    the runs directly, because the production path can no longer produce it.
    """
    from orchestrator.iteration import IterationOutcome
    from orchestrator.optimize.artifacts import append_run
    from orchestrator.optimize.stage_runner import _best_observed

    c = _campaign()
    c["optimization"]["stages"] = ["verify", "screen", "confirm"]
    wd = _init_work_dir(tmp_path, c)

    # Measurements with no recommendation beside them.
    iter_dir = Path(wd) / "runs" / "iter-2"
    iter_dir.mkdir(parents=True, exist_ok=True)
    for idx, (levels, value) in enumerate((
        ({"A": 2, "B": 2, "C": 2}, 10.0),
        ({"A": 16, "B": 16, "C": 16}, 42.0),
        ({"A": 2, "B": 16, "C": 2}, 11.0),
    )):
        append_run(iter_dir, {
            "row_index": idx, "levels": levels, "role": "corner",
            "replicate": 0, "status": "complete", "response": {"m": value},
            "held_out": {}, "manipulation": [], "invariants": [],
            "duration_ms": 1, "error": "",
        })
    best = _best_observed(wd, "m")
    assert best is not None and math.isclose(best["m"], 42.0)

    outcome = _run(c, wd, stage="confirm", iteration=3)
    assert outcome is IterationOutcome.COMPLETED

    record = json.loads(
        (Path(wd) / "runs" / "iter-3" / "confirmation.json").read_text(),
    )
    assert record["confirmed_at_levels"] == best["levels"], (
        "confirm must replicate the best OBSERVED configuration, not the "
        "geometric origin"
    )
    matrix_payload = json.loads(
        (Path(wd) / "runs" / "iter-3" / "design_matrix.json").read_text(),
    )
    assert [f["why"] for f in matrix_payload["finalists"]] == [
        "best measured valid configuration",
    ]


def test_best_observed_ignores_non_complete_rows(tmp_path, work_dir):
    """A rejected or failed row is not a candidate winner."""
    from orchestrator.optimize.artifacts import append_run
    from orchestrator.optimize.stage_runner import _best_observed

    iter_dir = tmp_path / "runs" / "iter-1"
    iter_dir.mkdir(parents=True)
    for idx, (status, value) in enumerate(
        [("complete", 10.0), ("failed", 999.0), ("rejected", 888.0),
         ("infeasible", 777.0)],
    ):
        append_run(iter_dir, {
            "row_index": idx, "levels": {"A": idx}, "role": "corner",
            "replicate": 0, "status": status, "response": {"m": value},
            "held_out": {}, "manipulation": [], "invariants": [],
            "duration_ms": 1, "error": "",
        })
    best = _best_observed(tmp_path, "m")
    assert best is not None
    assert math.isclose(best["m"], 10.0), (
        "only a `complete` row may win; a failed row scoring 999 must not"
    )


def test_confirm_flags_a_fitted_optimum_that_loses_to_an_observed_corner(
    tmp_path, work_dir, caplog,
):
    """A model's predicted optimum is an extrapolation and can be WORSE.

    "The prediction reproduced" and "this is the best configuration found"
    are different claims. When the surface is mis-specified the predicted
    point can land below a corner the screen already measured; replicating it
    then yields tight agreement between replicates and a status of CONFIRMED,
    while the campaign quietly reports an inferior configuration as its
    optimum. confirmation.json must record both facts so the artifact stays
    honest when they disagree.

    Task 7 note: the disagreement is driven by the RUNNER (which scores 10
    below the observed best wherever confirm runs), not by pinning confirm at
    a poor configuration. A ``confirm_at.json`` written here used to do the
    pinning; that file is no longer read by anything, and the runner alone is
    what this test needs — the check under test compares the confirm mean
    against ``_best_observed``, and is indifferent to how they came to differ.
    """
    import logging

    from orchestrator.optimize.stage_runner import _best_observed

    c = _campaign()
    c["optimization"]["stages"] = ["verify", "screen", "confirm"]
    wd = _init_work_dir(tmp_path, c)

    _run(c, wd, stage="screen", iteration=2)
    best = _best_observed(wd, "m")
    assert best is not None

    def poor(row):
        return {
            "cfg": {k.lower(): v for k, v in row.levels.items()},
            "m": best["m"] - 10.0,
        }

    with caplog.at_level(logging.WARNING):
        _run(c, wd, stage="confirm", iteration=3, runner=poor)

    record = json.loads(
        (Path(wd) / "runs" / "iter-3" / "confirmation.json").read_text(),
    )
    assert record["confirmed_is_best_observed"] is False
    assert math.isclose(record["best_observed"]["m"], best["m"], rel_tol=1e-9)
    assert record["regression_vs_best_observed"]["absolute"] > 0
    assert "WORSE" in caplog.text


def test_confirm_marks_the_winner_as_best_observed_when_it_is(
    tmp_path, work_dir,
):
    """The happy path must be labelled too, not just the regression."""
    c = _campaign()
    c["optimization"]["stages"] = ["verify", "screen", "confirm"]
    wd = _init_work_dir(tmp_path, c)

    _run(c, wd, stage="screen", iteration=2)
    _run(c, wd, stage="confirm", iteration=3)

    record = json.loads(
        (Path(wd) / "runs" / "iter-3" / "confirmation.json").read_text(),
    )
    assert record["confirmed_is_best_observed"] is True
    assert "regression_vs_best_observed" not in record


def test_best_observed_respects_minimize_direction(tmp_path, work_dir):
    """"Best" under minimize is the SMALLEST measured value, not the largest.

    ``_best_observed`` took no direction until Task 9, so it always returned the
    argmax. Three consumers now read it — the shortlist's measured finalist,
    ``_finish_confirm``'s regression check, and ``report.json``'s ``measured``
    rung — and every one of them would have handed a minimising campaign its
    WORST measured configuration as the answer.
    """
    from orchestrator.optimize.artifacts import append_run
    from orchestrator.optimize.stage_runner import _best_observed

    iter_dir = tmp_path / "runs" / "iter-1"
    iter_dir.mkdir(parents=True)
    for idx, value in enumerate((10.0, 3.0, 42.0)):
        append_run(iter_dir, {
            "row_index": idx, "levels": {"A": idx}, "role": "corner",
            "replicate": 0, "status": "complete", "response": {"m": value},
            "held_out": {}, "manipulation": [], "invariants": [],
            "duration_ms": 1, "error": "",
        })
    assert _best_observed(tmp_path, "m")["m"] == 42.0
    assert _best_observed(tmp_path, "m", direction="maximize")["m"] == 42.0
    assert _best_observed(tmp_path, "m", direction="minimize")["m"] == 3.0


def test_confirm_respects_minimize_direction(tmp_path, work_dir):
    """For a minimize objective, LOWER must count as beating the best."""
    from orchestrator.optimize.stage_runner import _best_observed

    c = _campaign()
    c["optimization"]["response"]["primary"]["direction"] = "minimize"
    c["optimization"]["stages"] = ["verify", "screen", "confirm"]
    wd = _init_work_dir(tmp_path, c)

    _run(c, wd, stage="screen", iteration=2)
    # Direction-correct: under minimize the configuration to beat is the
    # SMALLEST measured value. Passing the default here (as this test did before
    # Task 9) compares the confirm mean against the largest measurement instead,
    # which any confirm run trivially beats — so the assertion below held
    # without exercising the direction logic at all.
    best = _best_observed(wd, "m", direction="minimize")
    assert best is not None

    _run(
        c, wd, stage="confirm", iteration=3,
        runner=lambda row: {
            "cfg": {k.lower(): v for k, v in row.levels.items()},
            "m": best["m"] - 5.0,
        },
    )
    record = json.loads(
        (Path(wd) / "runs" / "iter-3" / "confirmation.json").read_text(),
    )
    assert record["confirmed_is_best_observed"] is True


def test_confirm_never_runs_a_level_outside_its_declared_range(
    tmp_path, work_dir,
):
    """The out-of-hull defect, closed STRUCTURALLY rather than by a guard.

    History. ``decide_after_refine`` detects an out-of-hull stationary point
    and raises OPTIMUM_OUTSIDE_HULL, but Trigger is documented as
    reported-not-acted-on — so confirm read the same solve off disk and
    replicated it anyway: the system diagnosed the problem, wrote it into
    findings, then did the thing it had just warned against. Observed on a
    real campaign: the surface was monotone in both refined factors (no
    interior optimum exists), the solve landed at coded BANDCAP=+1.62 /
    THRESH=-2.30, and confirm reproduced 112.4997 while a MEASURED corner
    stood at 182.2159. The repair at the time was a hull check inside
    ``_read_confirm_at``, which returned None so confirm fell back to the best
    observed configuration.

    Task 7 retires both the coded handoff and the check. Confirm replicates
    ``recommendation.json``'s ``levels``, and every candidate level comes from
    ``decode_coded``, which CLAMPS to the declared range — so there is no
    coordinate for a hull check to reject. This asserts the property the check
    existed to protect, on the whole pipeline rather than on the reader: every
    level confirm runs is one the author declared runnable.

    The diagnostic is NOT dropped: the stationary point is still solved, still
    recorded (``recommendation.json["stationary_point"]``), and still raises
    the trigger. See ``test_the_stationary_point_survives_as_a_diagnostic``.
    """
    c = _campaign()
    # A and B carry >2 levels so refine has something to refine; C stays
    # 2-level and is held fixed there.
    c["optimization"]["factors"][0]["levels"] = [2, 4, 8, 16]
    c["optimization"]["factors"][1]["levels"] = [2, 4, 8, 16]
    wd = _init_work_dir(tmp_path, c)

    _run(c, wd, stage="screen", iteration=2)
    _advance_engine(wd)
    _run(c, wd, stage="refine", iteration=3)
    _advance_engine(wd)
    _run(c, wd, stage="confirm", iteration=4)

    declared = {f["id"]: list(f["levels"]) for f in c["optimization"]["factors"]}
    for row in artifacts.read_runs(Path(wd) / "runs" / "iter-4"):
        for fid, level in row["levels"].items():
            lo, hi = min(declared[fid]), max(declared[fid])
            assert lo <= level <= hi, (
                f"confirm ran {fid}={level!r}, outside the declared range "
                f"[{lo}, {hi}] — an extrapolation the author never authorised"
            )


def test_confirm_refuses_a_target_that_names_no_level_for_every_factor(
    tmp_path, work_dir,
):
    """A partial target drops a flag SILENTLY, which is the worst shape of bug.

    ``matrix.render_apply`` renders nothing for a factor it is given no level
    for, so a confirm target missing one id produces a command line missing
    that flag — the exact "the following arguments are required" failure the
    held-fixed block exists to prevent, and invisible in ``runs.jsonl`` because
    the row's ``levels`` would simply lack the key. Both real sources cover
    every factor by construction, so this can only happen when the campaign's
    factor list changed under a resumed work_dir.
    """
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)

    iter_dir = Path(wd) / "runs" / "iter-2"
    iter_dir.mkdir(parents=True, exist_ok=True)
    (iter_dir / "recommendation.json").write_text(
        json.dumps({"stage": "screen", "levels": {"A": 16, "B": 16}}),   # no C
    )

    with pytest.raises(OptimizationAborted, match="names no level for"):
        _run(c, wd, stage="confirm", iteration=3)


def test_the_stationary_point_survives_as_a_diagnostic(tmp_path, work_dir):
    """It no longer decides what runs, and it must still be reported.

    ``decide_after_refine`` reads it to raise OPTIMUM_OUTSIDE_HULL — "the
    ranges were too narrow to contain the optimum" is worth telling an author
    whether or not anything replicates the point — so dropping the solve would
    silently drop that finding too.
    """
    c = _campaign()
    c["optimization"]["factors"][0]["levels"] = [2, 4, 8, 16]
    c["optimization"]["factors"][1]["levels"] = [2, 4, 8, 16]
    wd = _init_work_dir(tmp_path, c)

    _run(c, wd, stage="screen", iteration=2)
    _advance_engine(wd)
    _run(c, wd, stage="refine", iteration=3)

    rec = json.loads(
        (Path(wd) / "runs" / "iter-3" / "recommendation.json").read_text(),
    )
    assert rec["stage"] == "refine"
    assert rec["stationary_point"], (
        "the refine stage must still solve and record the stationary point"
    )
    assert set(rec["stationary_point"]) == set(rec["fitted_ids"])
    # And it is a DIAGNOSTIC: the levels that will run are the argmax's, in
    # real units, for every factor — including the ones refine held fixed.
    assert set(rec["levels"]) == {f["id"] for f in c["optimization"]["factors"]}


def test_confirm_replicates_the_recommendation_not_the_geometric_centre(
    tmp_path, work_dir,
):
    """The bug this replaces: confirm ran the MIDPOINT of every range.

    ``matrix._decode_level`` treats ``role="center"`` as "ignore the coded
    coordinates, use the midpoint of every declared range" — correct for a
    genuine replicated centre point, catastrophic for a target point carried
    as coordinates. A point at coded +0.9 of [64, 256] ran 160 (the midpoint)
    instead of 246, and the campaign reported "the predicted optimum
    reproduced" about a configuration the fit never predicted.

    Confirm no longer carries coordinates at all — ``run_stage`` writes the
    recommendation's real ``levels`` onto every row — so this asserts the
    outcome directly: what ran is the recommendation, and it is not the
    midpoint.
    """
    from orchestrator.optimize.factors import decode_coded, parse_factors

    c = _campaign()
    wd = _init_work_dir(tmp_path, c)

    # A response that peaks hard at the high corner, so the argmax is nowhere
    # near the midpoint and the two are distinguishable.
    def high_corner(row):
        lv = row.levels
        return {
            "cfg": {k.lower(): v for k, v in lv.items()},
            "m": float(lv.get("A", 0)) + float(lv.get("B", 0)) + float(lv.get("C", 0)),
        }

    _run(c, wd, stage="screen", iteration=2, runner=high_corner)
    _advance_engine(wd)
    _run(c, wd, stage="confirm", iteration=3, runner=high_corner)

    rec = json.loads(
        (Path(wd) / "runs" / "iter-2" / "recommendation.json").read_text(),
    )
    factors = parse_factors(c["optimization"]["factors"])
    mid = {f.id: decode_coded(f, 0.0) for f in factors}
    assert rec["levels"] != mid, rec["levels"]

    ran = [row["levels"] for row in artifacts.read_runs(Path(wd) / "runs" / "iter-3")]
    assert ran, "confirm produced no rows"
    assert all(levels == rec["levels"] for levels in ran), (
        f"confirm ran {ran} instead of the recommendation {rec['levels']}"
    )
    assert all(levels != mid for levels in ran), (
        f"confirm ran the geometric centre {mid} — the target was discarded"
    )


def test_confirm_with_no_finalist_at_all_aborts_rather_than_inventing_one(
    tmp_path, work_dir,
):
    """BEHAVIOUR CHANGE, Task 9, and the change is the point.

    This test used to assert the opposite: with no recommendation and no
    completed run, confirm expanded the design's own ORIGIN (coded 0.0 → the
    midpoint of every declared range) and measured that. It was documented as
    "the last resort, not the normal path", but the geometric centre of a
    declared range is not a configuration anyone chose — nothing predicted it,
    nothing measured it, and the author never named it. Measuring it and then
    reporting the result as the campaign's answer is exactly the failure that
    ``role="center"`` produced on a live campaign (a stationary point at coded
    +0.9 of [64, 256] ran 160 instead of 246, reported as "the predicted
    optimum reproduced").

    The terminal state has a REAL last resort now — ``known_valid_baseline``,
    which the author declares and the validator checks. With neither that nor a
    recommendation nor a measurement, there is genuinely nothing legal to
    discriminate between, and saying so beats inventing a midpoint. The abort
    message names all three ways to fix it.
    """
    c = _campaign()
    c["optimization"]["stages"] = ["verify", "screen", "confirm"]
    wd = _init_work_dir(tmp_path, c)
    with pytest.raises(OptimizationAborted, match="no finalist to measure"):
        _run(c, wd, stage="confirm", iteration=3)


def test_confirm_falls_back_to_the_declared_baseline_with_nothing_else(
    tmp_path, work_dir,
):
    """The bottom rung of the ladder is reachable at the SHORTLIST too.

    ``known_valid_baseline`` is not only ``report.json``'s last resort: a
    terminal stage with nothing to compare must still measure something, and the
    one configuration the author certified as valid is the honest choice.
    """
    c = _campaign()
    c["optimization"]["stages"] = ["verify", "screen", "confirm"]
    c["optimization"]["known_valid_baseline"] = {"A": 2, "B": 2, "C": 2}
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="confirm", iteration=3)

    payload = json.loads(
        (Path(wd) / "runs" / "iter-3" / "design_matrix.json").read_text(),
    )
    assert [f["why"] for f in payload["finalists"]] == ["known_valid_baseline"]
    assert all(row["levels"] == {"A": 2, "B": 2, "C": 2} for row in payload["rows"])


def test_execution_uses_the_recorded_run_order(tmp_path, work_dir):
    """The artifact's `run_order` must be the order actually executed.

    matrix_payload records a seeded permutation and expand's docstring tells
    callers to consult it; nothing did, so design_matrix.json asserted a
    randomization that never happened. Run-order randomization is what protects
    a factorial against drift confounding, so an artifact claiming a guarantee
    the run did not provide is worse than one claiming nothing.
    """
    import json as _json

    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    seen: list[int] = []

    def runner(row):
        seen.append(row.row_index)
        lv = row.levels
        return {
            "cfg": {k.lower(): v for k, v in lv.items()},
            "m": 10.0 + float(lv.get("A", 0)),
        }

    _run(c, wd, stage="screen", iteration=2, runner=runner)
    dm = _json.loads(
        (Path(wd) / "runs" / "iter-2" / "design_matrix.json").read_text(),
    )
    assert seen == dm["run_order"], (
        "executed order did not match the pre-registered run_order"
    )
    assert seen != sorted(seen), "run_order was not actually a permutation"


def test_responses_stay_aligned_with_their_design_rows(tmp_path, work_dir):
    """Randomized execution must not misalign responses with design points.

    `_fitting_responses` walks outcomes positionally and `fit_effects` pairs
    value i with design.points[i]. If outcomes were left in execution order
    every coefficient would be silently wrong — a far worse defect than the
    provenance gap that motivated randomizing execution.
    """
    import json as _json

    c = _campaign()
    wd = _init_work_dir(tmp_path, c)

    # response is a strict function of the levels, so a misalignment shows up as
    # a row whose recorded response disagrees with its own levels.
    def runner(row):
        lv = row.levels
        return {
            "cfg": {k.lower(): v for k, v in lv.items()},
            "m": 100.0 * float(lv.get("A", 0)) + float(lv.get("B", 0)),
        }

    _run(c, wd, stage="screen", iteration=2, runner=runner)
    rows = [
        _json.loads(line)
        for line in (Path(wd) / "runs" / "iter-2" / "runs.jsonl").read_text().splitlines()
        if line.strip()
    ]
    for r in rows:
        if r.get("status") != "complete":
            continue
        lv = r["levels"]
        expected = 100.0 * float(lv["A"]) + float(lv["B"])
        assert math.isclose(r["response"]["m"], expected, rel_tol=1e-9), (
            f"row {r['row_index']} response {r['response']['m']} does not match "
            f"its own levels {lv} — responses and design rows are misaligned"
        )


def test_infeasible_row_does_not_nan_poison_the_fit(tmp_path, work_dir, caplog):
    """One infeasible corner must not turn every coefficient into NaN.

    `_fitting_responses` carries NaN for any non-complete row, and the abort
    guard deliberately exempts `infeasible`/`rejected` — a constrained design
    routinely has inadmissible corners and aborting on one would make
    constraints unusable. But those NaNs flowed into fit_effects, where a SINGLE
    NaN makes EVERY coefficient NaN while still returning a schema-valid Fit.
    Verified before the fix: [0.1875, -0.5625, -0.0625, 0.1875] became
    [nan, nan, nan, nan] with no error raised and no warning logged.

    The existing coverage only asserted the NaN was *carried*, not what the fit
    did with it, which is why this survived.
    """
    import logging

    c = _campaign()
    wd = _init_work_dir(tmp_path, c)

    # make one corner infeasible via an invariant the row violates
    c["optimization"]["design_space"] = {
        "invariants": [
            {"observable": "guard", "op": "==", "value": 1},
        ],
    }

    def runner(row):
        lv = row.levels
        return {
            "cfg": {k.lower(): v for k, v in lv.items()},
            # exactly ONE row violates the invariant
            "guard": 0 if row.row_index == 3 else 1,
            "m": 10.0 - 0.05 * float(lv.get("A", 0)) + 0.2 * float(lv.get("B", 0)),
        }

    with caplog.at_level(logging.WARNING):
        _run(c, wd, stage="screen", iteration=2, runner=runner)

    eff = json.loads((Path(wd) / "runs" / "iter-2" / "effects.json").read_text())
    ests = [
        t.get("estimate") for t in (eff.get("terms") or eff.get("effects") or [])
        if t.get("estimate") is not None
    ]
    assert ests, "no estimates written"
    assert not all(e != e for e in ests), (
        "every coefficient is NaN — the infeasible row poisoned the fit"
    )
    assert any(e == e for e in ests), "no finite coefficient survived"


def test_fit_exclusions_are_recorded_when_rows_are_dropped(tmp_path, work_dir):
    """A reduced-resolution fit must say which rows it dropped and why."""
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    c["optimization"]["design_space"] = {
        "invariants": [{"observable": "guard", "op": "==", "value": 1}],
    }

    def runner(row):
        lv = row.levels
        return {
            "cfg": {k.lower(): v for k, v in lv.items()},
            "guard": 0 if row.row_index == 3 else 1,
            "m": 10.0 + 0.2 * float(lv.get("B", 0)),
        }

    _run(c, wd, stage="screen", iteration=2, runner=runner)
    p = Path(wd) / "runs" / "iter-2" / "fit_exclusions.json"
    if p.exists():
        rec = json.loads(p.read_text())
        assert rec["fitted_rows"] < rec["planned_rows"]
        assert rec["excluded_row_indices"]
        assert "complete" in rec["reason"]


# ─── Task 6: the compiled policy drives the epoch, not the iteration index ──

def test_verify_compiles_and_writes_the_policy(tmp_path, work_dir):
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="verify", iteration=1)
    pol = json.loads((Path(wd) / "policy.json").read_text())
    assert pol["initial"] == "screen"
    assert (Path(wd) / "policy.sha256").exists()


def test_epoch_iterations_follow_transitions_not_the_iteration_index(
    tmp_path, work_dir,
):
    from orchestrator.iteration import IterationOutcome

    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="verify", iteration=1)
    _advance_engine(wd)
    # NO `stage=` from here on: which state each iteration runs must come from
    # the recorded transitions, not from the iteration index.
    out2 = run_stage(c, wd, iteration=2, config_runner=_runner(),
                     test_results=_all_tests_pass(c), auto_approve=True)
    trans = [
        json.loads(line)
        for line in (Path(wd) / "transitions.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert trans[0]["from"] == "screen"
    assert trans[0]["to"] in ("refine", "confirm")
    assert "policy_hash" in json.loads(
        (Path(wd) / "runs" / "iter-2" / "design_matrix.json").read_text(),
    )
    # keep going until the policy reports; the harness does the same
    it, outcome = 3, out2
    while outcome != IterationOutcome.COMPLETED and it < 8:
        _advance_engine(wd)
        outcome = run_stage(c, wd, iteration=it, config_runner=_runner(),
                            test_results=_all_tests_pass(c), auto_approve=True)
        it += 1
    assert outcome == IterationOutcome.COMPLETED
    assert (Path(wd) / "report.json").exists()
    trans = [
        json.loads(line)
        for line in (Path(wd) / "transitions.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert trans[-1]["to"] == "report"


def test_editing_policy_json_after_compilation_hard_fails(tmp_path, work_dir):
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="verify", iteration=1)
    p = Path(wd) / "policy.json"
    pol = json.loads(p.read_text())
    pol["objective"]["delta_terminal"] = 0.4
    p.write_text(json.dumps(pol))
    with pytest.raises(OptimizationAborted, match="edited after compilation"):
        run_stage(c, wd, iteration=2, config_runner=_runner(),
                  test_results=_all_tests_pass(c), auto_approve=True)


def test_explicit_confirm_stage_still_reports_completed(tmp_path, work_dir):
    # legacy calling convention used throughout this file
    from orchestrator.iteration import IterationOutcome

    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="screen", iteration=3)   # confirm needs a finalist (Task 9)
    _advance_engine(wd)
    assert _run(c, wd, stage="confirm", iteration=4) == IterationOutcome.COMPLETED
    assert (Path(wd) / "report.json").exists()


def test_the_transition_row_records_the_closed_observation_vocabulary(
    tmp_path, work_dir,
):
    """Every guard key the policy can read must be present in the row.

    `step` treats a missing observation as "unknown is not a fact", so a
    dropped key silently strands the branch it guards. The row on disk is
    the only durable evidence of what the interpreter actually saw.
    """
    from orchestrator.optimize.policy import read_transitions

    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="verify", iteration=1)
    _run(c, wd, stage="screen", iteration=2)
    rows = read_transitions(wd)
    obs = rows[-1]["observations"]
    for key in ("correctness_failed", "nan_response", "budget_remaining",
                "round", "certified"):
        assert key in obs, f"{key} missing from the recorded observations"
    assert obs["round"] == 0, (
        "screen never self-loops, so it has no rounds to count"
    )
    assert obs["budget_remaining"] == 10 ** 9, (
        "with no declared max_runs the budget is unbounded, not zero"
    )


def test_a_state_outside_the_compiled_policy_fails_with_a_named_mismatch(
    tmp_path, work_dir,
):
    """`step` would raise a bare ValueError about a missing default transition.

    Reachable by forcing a stage the policy does not register — here `refine`
    on a campaign whose stages list omits it. The symptom ("no default
    transition from 'refine'") does not name the cause, and the cause is a
    campaign-authoring mistake a reader can act on.
    """
    c = _campaign()
    # A is refinable, so `_build_design` would happily build a CCD — the only
    # reason refine is not runnable here is the explicit stages list.
    c["optimization"]["factors"][0]["levels"] = [1, 2, 4, 8]
    c["optimization"]["factors"][1]["levels"] = [1, 2, 4, 8]
    c["optimization"]["stages"] = ["verify", "screen", "confirm"]
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="verify", iteration=1)
    _advance_engine(wd)
    with pytest.raises(OptimizationAborted, match="registers only"):
        _run(c, wd, stage="refine", iteration=3)


def test_refinable_survivors_counts_only_the_factors_that_can_carry_curvature(
    tmp_path, work_dir,
):
    """``len(decision.surviving)`` is the WRONG count for the screen guard.

    The compiled ``screen -> refine`` guard is
    ``{"refinable_survivors": {">": 0}}``, and the question it asks is how many
    survivors carry CURVATURE — ``is_refinable``: numeric with MORE THAN two
    levels. A survivor set made of ``choice`` and 2-level numeric factors has
    none, and routing it to ``refine`` sends the campaign into a stage
    ``_build_design`` correctly refuses to build ("refine has nothing to
    refine").

    Mutation-verified during review: dropping the ``is_refinable`` filter from
    ``observations_from_decision``'s call — i.e. passing
    ``refinable_survivors=len(decision.surviving)`` — left the whole optimize
    suite green, so nothing caught it. This is the test that does.

    A MIX is what discriminates: the deterministic ``_runner`` gives zero
    pure-error variance, so every ``significant`` is None and all three factors
    survive as "unknown" (``decide_after_screen`` never drops an unmeasured
    effect). Only A is refinable, so the filtered count is 1 while the raw
    survivor count is 3.
    """
    from orchestrator.optimize.factors import is_refinable, parse_factors
    from orchestrator.optimize.policy import read_transitions

    c = _campaign()
    c["optimization"]["factors"][0]["levels"] = [1, 2, 4, 8]   # A: refinable
    # B and C keep the 2-level default, so neither can carry curvature.
    factors = parse_factors(c["optimization"]["factors"])
    refinable_ids = {f.id for f in factors if is_refinable(f)}
    assert refinable_ids == {"A"}, (
        f"the fixture must present a MIX for this test to discriminate; "
        f"refinable={sorted(refinable_ids)}"
    )

    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="verify", iteration=1)
    _advance_engine(wd)
    _run(c, wd, stage="screen", iteration=2)

    row = read_transitions(wd)[-1]
    surviving = row["rule"] and row["observations"]
    assert surviving["refinable_survivors"] == 1, (
        f"expected only A counted; got "
        f"{surviving['refinable_survivors']}. A count of 3 means the "
        f"is_refinable filter was dropped and the raw survivor count leaked "
        f"into the screen -> refine guard."
    )
    # And the guard it feeds still fires, so the filter is not merely cosmetic:
    # one refinable survivor is enough to reach refine.
    assert row["to"] == "refine", row


def test_no_refinable_survivor_routes_screen_past_refine(tmp_path, work_dir):
    """The other side of the filter: an all-2-level survivor set skips refine.

    Same campaign shape as above with A's extra levels removed, so EVERY
    survivor is a 2-level numeric. ``refinable_survivors`` must then be 0 and
    the guard must not fire — otherwise the campaign is routed into a refine
    stage that aborts. Paired with the test above, this pins both directions of
    the filter rather than only the one that happens to fire.
    """
    from orchestrator.optimize.policy import read_transitions

    c = _campaign()   # all factors 2-level: nothing refinable
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="verify", iteration=1)
    _advance_engine(wd)
    _run(c, wd, stage="screen", iteration=2)

    row = read_transitions(wd)[-1]
    assert row["observations"]["refinable_survivors"] == 0, row["observations"]
    assert row["to"] == "confirm", row


# ─── Task 9: terminal discrimination over a shortlist of finalists ─────────
#
# The claim the campaign makes at the end changes here. Before: "this one
# configuration, replicated N times, reproduced its predicted value" — a
# statement about repeatability whose "and it is the best" half rested entirely
# on the fitted surface. After: "these |S| configurations were each measured
# freshly and compared with each other, and this one won by at least this
# much" — a comparison the response model plays no part in (spec §3.3, paper
# §Design). The tests below are about that difference, so they assert on
# multiple DISTINCT finalists and on measurements overruling predictions.

def test_confirm_compares_a_shortlist_of_finalists_with_fresh_replicates(
    tmp_path, work_dir,
):
    """The shape of the terminal claim: |S| finalists x fresh replicates.

    ``n == replicates`` per finalist is the load-bearing part — it says every
    finalist was measured the full number of times AFRESH, rather than the
    shortlist being a relabelling of one configuration's replicates.
    """
    c = _campaign()
    c["optimization"]["design"]["confirm"] = {"replicates": 3, "shortlist_size": 3}
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="verify", iteration=1)
    _advance_engine(wd)
    _run(c, wd, stage="screen", iteration=2)
    _advance_engine(wd)
    # noise: real replicates differ, which is what a paired terminal bound reads.
    _run(c, wd, stage="confirm", iteration=3, runner=_runner(noise=0.05))

    conf = json.loads((wd / "runs" / "iter-3" / "confirmation.json").read_text())
    assert len(conf["finalists"]) == 3 and all(f["n"] == 3 for f in conf["finalists"])
    # Distinct configurations, not one repeated: a shortlist of three copies
    # would satisfy every count above while measuring nothing new.
    keys = [json.dumps(f["levels"], sort_keys=True) for f in conf["finalists"]]
    assert len(set(keys)) == 3, keys
    assert conf["residual_regret_terminal"] is not None
    assert conf["best"] in {f["key"] for f in conf["finalists"]}
    assert set(conf["bounds"]) == {f["key"] for f in conf["finalists"]} - {conf["best"]}

    rep = json.loads((wd / "report.json").read_text())
    assert rep["recommendation"]["basis"] in ("certified", "terminal_best")
    assert rep["residual_regret_terminal"] == conf["residual_regret_terminal"]
    # Spec §3.5: the two bounds are reported separately, never collapsed.
    assert rep["delta_screen"] == 0.05 and rep["delta_terminal"] == 0.05
    assert "residual_regret_model" in rep


def test_every_finalist_is_measured_once_before_any_is_measured_twice(
    tmp_path, work_dir,
):
    """Run order is randomized WITHIN each replicate block, not across the matrix.

    A whole-matrix shuffle could schedule all three of one finalist's runs
    before another finalist's first, which loads any machine drift onto whoever
    ran late. The terminal comparison is the least able of all the stages to
    absorb that: it compares finalists DIRECTLY rather than through a fitted
    surface that could have a drift term.
    """
    c = _campaign()
    c["optimization"]["design"]["confirm"] = {"replicates": 3, "shortlist_size": 3}
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="screen", iteration=2)
    _advance_engine(wd)

    order: list[int] = []
    def recording(row):
        order.append(row.apply["finalist"])
        return _runner()(row)

    _run(c, wd, stage="confirm", iteration=3, runner=recording)
    assert len(order) == 9
    for block in (order[0:3], order[3:6], order[6:9]):
        assert sorted(block) == [0, 1, 2], (
            f"block {block} does not contain every finalist exactly once"
        )
    assert order[0:3] != order[3:6] or order[3:6] != order[6:9], (
        "no block was permuted at all; the per-block seed is not being used"
    )


def test_a_finalist_measured_infeasible_is_excluded_from_the_recommendation(
    tmp_path, work_dir,
):
    """MEASURED invalidity overrules PREDICTION — the whole point of the stage.

    The fitted surface has no idea a configuration is inadmissible: it fits the
    objective, not the constraint. So the model's argmax can be a configuration
    that violates a declared constraint, and only a measurement can say so. A
    finalist with any invalid replicate is excluded outright rather than
    averaged over its survivors, and the report's recommendation therefore
    satisfies the constraint.

    HOW THE CONFLICT IS ARRANGED, and why it has to be arranged this carefully.
    ``decide.ranked`` already drops configurations the campaign has MEASURED
    infeasible, so a constraint the screen stage already violated cannot produce
    this case — the recommendation would simply avoid it. The gap Task 9 closes
    is the one the screen cannot see: the fit interpolates INTO A's interior
    (A has four levels, so the candidate axis has interior points), and the
    constrained metric ``p99`` blows up exactly there — strictly between the
    screen's ±1 levels of 2 and 16, so no screen row samples it. The fitted
    surface has no ``p99`` term at all; only a measurement can say the
    interpolated candidate is inadmissible. That is the real ``SURFACES["sla"]``
    shape, and it is the case the harness's ``sla`` test exercises end to end.
    """
    def sla_runner(row):
        lv = row.levels
        a, b = float(lv.get("A", 0)), float(lv.get("B", 0))
        return {
            "cfg": {k.lower(): v for k, v in lv.items()},
            "m": 20.0 - 0.05 * (a - 9) ** 2 + 0.20 * b,
            # Violated only strictly INSIDE the screen's ±1 levels (2 and 16),
            # so every screen row is feasible and only an interpolated
            # candidate can trip it.
            "p99": 100.0 if 3 <= a <= 15 else 10.0,
        }

    c = _campaign()
    c["optimization"]["factors"][0]["levels"] = [2, 4, 8, 16]
    c["optimization"]["stages"] = ["verify", "screen", "confirm"]
    c["optimization"]["response"]["constraints"] = [
        {"metric": "p99", "op": "<", "value": 50},
    ]
    c["optimization"]["design"]["confirm"] = {"replicates": 2, "shortlist_size": 3}
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="verify", iteration=1, runner=sla_runner)
    _advance_engine(wd)
    _run(c, wd, stage="screen", iteration=2, runner=sla_runner)
    _advance_engine(wd)
    _run(c, wd, stage="confirm", iteration=3, runner=sla_runner)

    conf = json.loads((wd / "runs" / "iter-3" / "confirmation.json").read_text())
    # "infeasible", not the retired "excluded": the finalist status vocabulary
    # distinguishes a config MEASURED inadmissible from one the instrument could
    # not measure at all ("unmeasured"), because the two carry opposite authoring
    # consequences — strike the configuration off vs re-run it with more budget.
    # On the sla surface the exclusion is a real p99 constraint violation, so
    # `infeasible` is the value under test here.
    excluded = [f for f in conf["finalists"] if f["status"] == "infeasible"]
    assert excluded, conf["finalists"]
    assert conf["excluded_infeasible"], conf
    # ...and nothing landed in the unmeasured bucket, which would mean the
    # instrument failed rather than the constraint binding.
    assert not conf["excluded_unmeasured"], conf
    # The excluded finalist is one the MODEL put on the shortlist, which is the
    # whole point: prediction proposed it, measurement removed it.
    assert all(3 <= f["levels"]["A"] <= 15 for f in excluded), excluded
    assert conf["best"] is not None, "the surviving finalists must still decide"

    rep = json.loads((wd / "report.json").read_text())
    levels = rep["recommendation"]["levels"]
    observed = sla_runner(type("R", (), {"levels": levels})())
    assert observed["p99"] < 50, (
        f"the report recommends {levels}, which measures p99={observed['p99']} "
        f"against a declared constraint of p99 < 50"
    )


def test_report_falls_back_to_the_known_valid_baseline_when_nothing_is_valid(
    tmp_path, work_dir,
):
    """The bottom rung (spec §3.6 item 4). Always act.

    Under ``m < -1`` EVERY configuration the campaign can run is infeasible.
    Nothing measured is valid, so ``_best_observed`` is None (it filters to
    ``complete``); no fitting stage can have run at all (a design with every row
    infeasible is singular, which is why this drives verify -> confirm directly,
    the shape a campaign reaching a hostile target actually takes); and the
    baseline's own replicates come back infeasible too, so the shortlist has no
    surviving finalist. Every rung above ``baseline`` is therefore genuinely
    unavailable rather than merely skipped, and the report still returns a
    configuration — the author's — and labels it honestly.
    """
    c = _campaign()
    c["optimization"]["known_valid_baseline"] = {"A": 2, "B": 2, "C": 2}
    c["optimization"]["stages"] = ["verify", "screen", "confirm"]
    c["optimization"]["response"]["constraints"] = [
        {"metric": "m", "op": "<", "value": -1},
    ]
    c["optimization"]["design"]["confirm"] = {"replicates": 2, "shortlist_size": 3}
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="verify", iteration=1)
    _advance_engine(wd)
    _run(c, wd, stage="confirm", iteration=2)

    conf = json.loads((wd / "runs" / "iter-2" / "confirmation.json").read_text())
    assert conf["best"] is None and conf["residual_regret_terminal"] is None
    assert [f["why"] for f in conf["finalists"]] == ["known_valid_baseline"]

    rep = json.loads((wd / "report.json").read_text())
    assert rep["recommendation"] == {
        "levels": {"A": 2, "B": 2, "C": 2}, "basis": "baseline",
    }
    assert rep["known_valid_baseline"] == {"A": 2, "B": 2, "C": 2}
    assert rep["certified"] is False
    assert rep["residual_regret_terminal"] is None


def test_the_model_rung_refuses_a_recommendation_measured_infeasible(
    tmp_path, work_dir,
):
    """``basis: model`` must never name a configuration the campaign watched fail.

    ``decide.ranked`` excludes measured-infeasible points when it PRODUCES a
    recommendation, but ``report.json`` may be reading a recommendation written
    before the run that invalidated it — which is exactly what happens when
    confirm measures the model's argmax infeasible. Asserted directly on the
    predicate, because arranging that ordering end to end and arranging it for
    the right reason are different things.
    """
    from orchestrator.optimize.artifacts import append_run
    from orchestrator.optimize.stage_runner import _measured_infeasible_contains

    iter_dir = tmp_path / "runs" / "iter-1"
    iter_dir.mkdir(parents=True)
    append_run(iter_dir, {
        "row_index": 0, "levels": {"A": 16, "B": 16.0}, "role": "corner",
        "replicate": 0, "status": "infeasible", "response": {"m": 1.0},
        "held_out": {}, "manipulation": [], "invariants": [],
        "duration_ms": 1, "error": "",
    })
    # Same configuration, int-vs-float across a JSON round trip.
    assert _measured_infeasible_contains(tmp_path, {"A": 16.0, "B": 16})
    # A different configuration, and a superset, are not it.
    assert not _measured_infeasible_contains(tmp_path, {"A": 16, "B": 2})
    assert not _measured_infeasible_contains(tmp_path, {"A": 16, "B": 16, "C": 2})
    assert not _measured_infeasible_contains(tmp_path, {})


def test_a_second_confirm_round_carries_forward_only_live_challengers(
    tmp_path, work_dir,
):
    """Round r+1 measures the winner plus whoever could still change the answer.

    A finalist whose bound already came in at or below epsilon cannot alter the
    epsilon-optimal decision no matter how many more runs it gets (paper, Fig.
    2), so spending the next round's budget on it buys nothing. Driven through
    ``_confirm_rows`` against a hand-written previous round, because arranging a
    genuine two-round campaign end to end would make WHICH finalists carry
    forward depend on the noise rather than on the rule.
    """
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.policy import append_transition, compile_policy
    from orchestrator.optimize.stage_runner import _confirm_rows

    c = _campaign()
    c["optimization"]["design"]["confirm"] = {"replicates": 2, "shortlist_size": 3}
    pol = compile_policy(c)
    wd = tmp_path / "wd"
    (wd / "runs" / "iter-3").mkdir(parents=True)
    (wd / "runs" / "iter-3" / "confirmation.json").write_text(json.dumps({
        "round": 1, "best": "f0", "epsilon": 0.5,
        "bounds": {"f1": 0.9, "f2": 0.1},
        "finalists": [
            {"key": "f0", "levels": {"A": 16, "B": 16, "C": 16}, "status": "ok"},
            {"key": "f1", "levels": {"A": 16, "B": 2, "C": 16}, "status": "ok"},
            {"key": "f2", "levels": {"A": 2, "B": 16, "C": 16}, "status": "ok"},
        ],
    }))
    append_transition(wd, {"iteration": 3, "from": "confirm", "to": "confirm",
                           "rule": {}, "observations": {}, "policy_hash": ""})

    rows, payload = _confirm_rows(
        pol, wd, parse_factors(c["optimization"]["factors"]), "m", "maximize", 4,
    )
    assert payload["round"] == 2
    carried = [f["levels"] for f in payload["finalists"]]
    assert {"A": 16, "B": 16, "C": 16} in carried, "the winner must be re-measured"
    assert {"A": 16, "B": 2, "C": 16} in carried, "a bound above epsilon stays live"
    assert {"A": 2, "B": 16, "C": 16} not in carried, (
        "f2's bound was 0.1 <= epsilon 0.5, so it cannot change the decision and "
        "must not consume round 2's budget"
    )
    assert len(rows) == len(carried) * 2


def test_a_second_round_keeps_a_finalist_whose_bound_was_not_computable(
    tmp_path, work_dir,
):
    """``None`` is UNKNOWN, not "small".

    A challenger whose bound could not be computed (a finalist with fewer than
    two usable replicates) has not been shown to be out of contention, so
    retiring it would silently narrow the shortlist on the strength of a missing
    number — the same "unknown is not zero" rule the certificate itself follows.
    """
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.policy import append_transition, compile_policy
    from orchestrator.optimize.stage_runner import _confirm_rows

    c = _campaign()
    c["optimization"]["design"]["confirm"] = {"replicates": 2, "shortlist_size": 3}
    pol = compile_policy(c)
    wd = tmp_path / "wd"
    (wd / "runs" / "iter-3").mkdir(parents=True)
    (wd / "runs" / "iter-3" / "confirmation.json").write_text(json.dumps({
        "round": 1, "best": "f0", "epsilon": 0.5, "bounds": {"f1": None},
        "finalists": [
            {"key": "f0", "levels": {"A": 16, "B": 16, "C": 16}, "status": "ok"},
            {"key": "f1", "levels": {"A": 16, "B": 2, "C": 16}, "status": "ok"},
        ],
    }))
    append_transition(wd, {"iteration": 3, "from": "confirm", "to": "confirm",
                           "rule": {}, "observations": {}, "policy_hash": ""})
    _rows, payload = _confirm_rows(
        pol, wd, parse_factors(c["optimization"]["factors"]), "m", "maximize", 4,
    )
    assert {"A": 16, "B": 2, "C": 16} in [f["levels"] for f in payload["finalists"]]


def test_an_excluded_finalist_does_not_come_back_in_the_next_round(
    tmp_path, work_dir,
):
    """Measured invalidity is not re-litigated. It was measured; it is out."""
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.policy import append_transition, compile_policy
    from orchestrator.optimize.stage_runner import _confirm_rows

    c = _campaign()
    c["optimization"]["design"]["confirm"] = {"replicates": 2, "shortlist_size": 3}
    pol = compile_policy(c)
    wd = tmp_path / "wd"
    (wd / "runs" / "iter-3").mkdir(parents=True)
    (wd / "runs" / "iter-3" / "confirmation.json").write_text(json.dumps({
        "round": 1, "best": "f0", "epsilon": 0.5, "bounds": {},
        "finalists": [
            {"key": "f0", "levels": {"A": 16, "B": 16, "C": 16}, "status": "ok"},
            {"key": "f1", "levels": {"A": 2, "B": 2, "C": 2},
             "status": "infeasible"},
        ],
    }))
    append_transition(wd, {"iteration": 3, "from": "confirm", "to": "confirm",
                           "rule": {}, "observations": {}, "policy_hash": ""})
    _rows, payload = _confirm_rows(
        pol, wd, parse_factors(c["optimization"]["factors"]), "m", "maximize", 4,
    )
    assert [f["levels"] for f in payload["finalists"]] == [
        {"A": 16, "B": 16, "C": 16},
    ]


def test_a_round_whose_whole_carry_over_was_excluded_still_filters_the_ladder(
    tmp_path, work_dir,
):
    """The all-excluded carry-over path, which the ``sla`` surface never reaches.

    When round r > 1's carry-over yields NO finalist — every carried candidate was
    excluded, so there is no ``status == "ok"`` survivor and no winner — control
    falls through to the round-1 ladder (``recommendation.levels`` →
    ``_best_observed`` → ``top_candidates``). That ladder originally did no
    measured-invalid filtering (only the top-up branch did), so such a round would
    re-seat the exact configurations an earlier round had already proved
    inadmissible and burn its whole budget re-measuring known-bad points.

    ``SURFACES["sla"]`` does not exercise this: ``{A: 16, B: 2}`` always survives
    there, so the carry-over is never empty. The gap was found by reading rather
    than by running, which is why it gets its own test rather than being assumed
    covered by the end-to-end case.

    The fix moved the filter into ``_add``, so EVERY seeding path is filtered.
    Here the recommendation and the first two top candidates are all on disk as
    measured-infeasible, and the shortlist must skip past them to the one
    candidate that is not.
    """
    from orchestrator.optimize.artifacts import append_run
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.policy import append_transition, compile_policy
    from orchestrator.optimize.stage_runner import _confirm_rows

    c = _campaign()
    c["optimization"]["design"]["confirm"] = {"replicates": 2, "shortlist_size": 3}
    pol = compile_policy(c)
    wd = tmp_path / "wd"

    bad_rec = {"A": 16, "B": 16, "C": 16}
    bad_top = {"A": 16, "B": 2, "C": 16}
    good_top = {"A": 2, "B": 16, "C": 2}

    # Round 1's runs: the recommendation and one top candidate measured
    # inadmissible; nothing completed, so `_best_observed` finds nothing either.
    iter3 = wd / "runs" / "iter-3"
    iter3.mkdir(parents=True)
    for idx, levels in enumerate((bad_rec, bad_top)):
        append_run(iter3, {
            "row_index": idx, "levels": levels, "role": "confirm",
            "replicate": 0, "status": "infeasible", "response": {"m": 1.0},
            "held_out": {}, "manipulation": [], "invariants": [],
            "duration_ms": 1, "error": "",
        })
    # ...and a recommendation that still names the bad one, because the fitting
    # stage that wrote it ran BEFORE those measurements existed.
    (iter3 / "recommendation.json").write_text(json.dumps({
        "stage": "screen", "levels": bad_rec,
        "top_candidates": [{"levels": bad_rec}, {"levels": bad_top},
                           {"levels": good_top}],
    }))
    # Round 1's confirmation: EVERY finalist excluded, so no winner carries over.
    (iter3 / "confirmation.json").write_text(json.dumps({
        "round": 1, "best": None, "epsilon": 0.5, "bounds": {},
        "finalists": [
            {"key": "f0", "levels": bad_rec, "status": "infeasible"},
            {"key": "f1", "levels": bad_top, "status": "infeasible"},
        ],
    }))
    append_transition(wd, {"iteration": 3, "from": "confirm", "to": "confirm",
                           "rule": {}, "observations": {}, "policy_hash": ""})

    _rows, payload = _confirm_rows(
        pol, wd, parse_factors(c["optimization"]["factors"]), "m", "maximize", 4,
    )
    assert payload["round"] == 2
    seated = [f["levels"] for f in payload["finalists"]]
    assert bad_rec not in seated, (
        "the round-1 ladder re-seated the recommendation even though the campaign "
        "had already measured it infeasible"
    )
    assert bad_top not in seated, seated
    assert seated == [good_top], seated


def test_round_one_also_refuses_a_recommendation_already_measured_infeasible(
    tmp_path, work_dir,
):
    """The filter is unconditional, and round 1 is not exempt.

    A screen stage with infeasible corners, or a resumed work_dir, can put
    measured-invalid rows on disk before the FIRST confirm round ever runs. There
    was never a reason to seat one, so the filter in ``_add`` applies from round 1
    rather than only after a carry-over.
    """
    from orchestrator.optimize.artifacts import append_run
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.policy import compile_policy
    from orchestrator.optimize.stage_runner import _confirm_rows

    c = _campaign()
    c["optimization"]["design"]["confirm"] = {"replicates": 2, "shortlist_size": 2}
    pol = compile_policy(c)
    wd = tmp_path / "wd"
    iter2 = wd / "runs" / "iter-2"
    iter2.mkdir(parents=True)
    append_run(iter2, {
        "row_index": 0, "levels": {"A": 16, "B": 16, "C": 16}, "role": "corner",
        "replicate": 0, "status": "infeasible", "response": {"m": 99.0},
        "held_out": {}, "manipulation": [], "invariants": [],
        "duration_ms": 1, "error": "",
    })
    (iter2 / "recommendation.json").write_text(json.dumps({
        "stage": "screen", "levels": {"A": 16, "B": 16, "C": 16},
        "top_candidates": [{"levels": {"A": 2, "B": 16, "C": 2}}],
    }))
    _rows, payload = _confirm_rows(
        pol, wd, parse_factors(c["optimization"]["factors"]), "m", "maximize", 3,
    )
    assert payload["round"] == 1
    assert [f["levels"] for f in payload["finalists"]] == [
        {"A": 2, "B": 16, "C": 2},
    ]


def test_the_baseline_is_the_one_rung_exempt_from_the_measured_invalid_filter(
    tmp_path, work_dir,
):
    """``known_valid_baseline`` is seated even after measuring invalid.

    Every other rung is filtered, but the bottom one must not be. It is the
    author's declared "this configuration works", it is reached only when nothing
    else is left, and dropping it on a contrary measurement would leave the
    campaign with NOTHING legal to return — strictly worse than measuring it again
    and recording the contradiction. ``_finish_confirm`` still excludes it if it
    measures invalid, and ``_run_report`` still returns it as ``basis: baseline``,
    so nothing is being claimed about it that the measurements deny.
    """
    from orchestrator.optimize.artifacts import append_run
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.policy import compile_policy
    from orchestrator.optimize.stage_runner import _confirm_rows

    baseline = {"A": 2, "B": 2, "C": 2}
    c = _campaign()
    c["optimization"]["known_valid_baseline"] = baseline
    c["optimization"]["design"]["confirm"] = {"replicates": 2, "shortlist_size": 3}
    pol = compile_policy(c)
    wd = tmp_path / "wd"
    iter2 = wd / "runs" / "iter-2"
    iter2.mkdir(parents=True)
    append_run(iter2, {
        "row_index": 0, "levels": baseline, "role": "confirm",
        "replicate": 0, "status": "infeasible", "response": {"m": 1.0},
        "held_out": {}, "manipulation": [], "invariants": [],
        "duration_ms": 1, "error": "",
    })
    _rows, payload = _confirm_rows(
        pol, wd, parse_factors(c["optimization"]["factors"]), "m", "maximize", 3,
    )
    assert [f["levels"] for f in payload["finalists"]] == [baseline]
    assert [f["why"] for f in payload["finalists"]] == ["known_valid_baseline"]


def test_the_shortlist_always_contains_the_best_measured_configuration(
    tmp_path, work_dir,
):
    """Spec §3.6 rung 3, moved from the report INTO the comparison.

    "Never return the largest noisy observation" is only achievable if the best
    measured configuration is one of the things being re-measured. Putting it in
    the shortlist is what makes the terminal winner never worse than something
    the campaign already saw — a report-time comparison could only NOTICE the
    regression, not prevent it.
    """
    from orchestrator.optimize.stage_runner import _best_observed

    c = _campaign()
    c["optimization"]["design"]["confirm"] = {"replicates": 2, "shortlist_size": 3}
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="screen", iteration=2)
    best = _best_observed(wd, "m", direction="maximize")
    assert best is not None
    _advance_engine(wd)
    _run(c, wd, stage="confirm", iteration=3)

    payload = json.loads(
        (Path(wd) / "runs" / "iter-3" / "design_matrix.json").read_text(),
    )
    assert best["levels"] in [f["levels"] for f in payload["finalists"]], (
        f"the best measured configuration {best['levels']} is not on the "
        f"shortlist {[f['levels'] for f in payload['finalists']]}"
    )


def test_the_shortlist_record_is_written_under_its_spec_name(tmp_path, work_dir):
    """Spec §3.9's artifact table names ``shortlist.json`` for this stage."""
    c = _campaign()
    c["optimization"]["design"]["confirm"] = {"replicates": 2, "shortlist_size": 3}
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="screen", iteration=2)
    _advance_engine(wd)
    _run(c, wd, stage="confirm", iteration=3)

    short = json.loads((Path(wd) / "runs" / "iter-3" / "shortlist.json").read_text())
    conf = json.loads(
        (Path(wd) / "runs" / "iter-3" / "confirmation.json").read_text(),
    )
    assert short["finalists"] == conf["finalists"]
    assert short["best"] == conf["best"] and short["bounds"] == conf["bounds"]


def test_confirm_findings_report_partially_confirmed_when_the_bound_is_too_wide(
    tmp_path, work_dir,
):
    """Three statuses, not two.

    A winner with a bound wider than epsilon is neither CONFIRMED (that would
    overstate the claim, which is precisely what spec §3.5 forbids when it
    refuses to collapse the two deltas) nor REFUTED (that would throw away a
    real measured result). ``epsilon: {abs: 0}`` plus a NOISY runner forces the
    middle case: with real run-to-run variation the challengers' upper bounds
    are strictly positive, so no bound can be at or below zero and nothing can
    certify — while a winner is still identified. (The deterministic fake runner
    would not do: identical replicates give variance 0, the bound collapses to
    the point estimate, and ``0.0 <= 0.0`` certifies.)
    """
    import jsonschema

    c = _campaign()
    c["optimization"]["design"]["confirm"] = {"replicates": 3, "shortlist_size": 3}
    c["optimization"]["policy"] = {"epsilon": {"abs": 0.0}}
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="screen", iteration=2, runner=_noisy_runner())
    _advance_engine(wd)
    _run(c, wd, stage="confirm", iteration=3, runner=_noisy_runner())

    conf = json.loads(
        (Path(wd) / "runs" / "iter-3" / "confirmation.json").read_text(),
    )
    assert conf["certified"] is False and conf["best"] is not None
    findings = json.loads(
        (Path(wd) / "runs" / "iter-3" / "findings.json").read_text(),
    )
    jsonschema.validate(
        findings,
        json.loads(Path("orchestrator/schemas/findings.schema.json").read_text()),
    )
    assert findings["arms"][0]["status"] == "PARTIALLY_CONFIRMED"
    assert findings["experiment_valid"] is True
    rep = json.loads((Path(wd) / "report.json").read_text())
    assert rep["recommendation"]["basis"] == "terminal_best"
    assert rep["certified"] is False


def test_the_terminal_bound_is_not_the_model_bound_under_another_name(
    tmp_path, work_dir,
):
    """Spec §3.5: two bounds, different assumptions, never collapsed.

    They are computed from disjoint inputs — the model bound from fitted
    coefficients and their standard errors, the terminal bound from finalist
    sample means and variances — so reporting the same number for both would
    mean one of the two was not actually computed.
    """
    c = _campaign()
    c["optimization"]["design"]["confirm"] = {"replicates": 3, "shortlist_size": 3}
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="screen", iteration=2, runner=_noisy_runner())
    _advance_engine(wd)
    _run(c, wd, stage="confirm", iteration=3, runner=_noisy_runner())

    rep = json.loads((Path(wd) / "report.json").read_text())
    model, terminal = rep["residual_regret_model"], rep["residual_regret_terminal"]
    assert model is not None and terminal is not None
    assert model != terminal, (
        "the two bounds came out identical, which means one of them is the "
        "other under a different key"
    )
    conf = json.loads(
        (Path(wd) / "runs" / "iter-3" / "confirmation.json").read_text(),
    )
    assert conf["terminal_bound"]["method"] == "bonferroni_one_sided_welch_t"
    rec = json.loads(
        (Path(wd) / "runs" / "iter-2" / "recommendation.json").read_text(),
    )
    assert rec["residual_regret_model"]["method"] == "bonferroni_one_sided_t"


def _noisy_runner():
    """A runner with real run-to-run variation, so both bounds are computable.

    The deterministic fake returns identical values at every centre point, so
    pure error is exactly 0 and the MODEL bound comes back ``None`` — which
    would make the comparison above vacuous rather than failing.
    """
    import random as _random
    rng = _random.Random(1234)

    def run(row):
        lv = row.levels
        a, b = float(lv.get("A", 0)), float(lv.get("B", 0))
        return {
            "cfg": {k.lower(): v for k, v in lv.items()},
            "m": 10.0 - 0.05 * a + 0.20 * b + 0.02 * a * b + rng.gauss(0, 0.4),
        }
    return run


# ─── the three target-adapter guards, through run_stage ────────────────────
#
# `policy.json` is content-hashed and a mid-epoch edit hard-aborts, because a
# pre-registered policy that changed inside an epoch is not a pre-registration.
# A pre-registered design assumes the MEASUREMENT INSTRUMENT is fixed too, and
# nothing enforced that until these guards. These tests assert what the epoch
# does about it: the contract file that lands at the work-dir ROOT (epoch-scoped,
# so `screen` and `confirm` share it), the abort a drifted adapter produces, and
# the row status a stale or self-contradictory response earns.


def test_adapter_contract_is_captured_at_the_work_dir_root(tmp_path, work_dir):
    """Epoch-scoped, beside policy.json -- not under runs/iter-N/.

    An epoch spans several iterations, and an adapter edited BETWEEN two of them
    is the interval the real defect occupied; an iteration-scoped fingerprint
    would see nothing.
    """
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd)

    doc = json.loads((Path(wd) / "adapter_contract.json").read_text())
    assert set(doc["keys"]) == {"cfg", "m"}
    assert doc["keys"]["m"] == "float"
    assert doc["captured_at"]["stage"] == "screen"
    assert (Path(wd) / "adapter_contract.sha256").exists()
    assert not (Path(wd) / "runs" / "iter-2" / "adapter_contract.json").exists()


def test_adapter_drift_mid_sweep_aborts_the_campaign(tmp_path, work_dir):
    """DEFECT 7: the adapter's output schema changed underneath the design.

    A drifted contract is a campaign-level abort, not a semantic exception: the
    exception branch ends the epoch and still returns an action from the fitted
    surface, and here the surface would be fitted over rows measured by two
    different instruments, so there is no action to certify.
    """
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    seen: list[int] = []

    def _grows_a_key(row):
        seen.append(row.row_index)
        # The author "improved" the adapter after the first few rows.
        return {"backlog_slope": 0.4} if len(seen) > 3 else {}

    with pytest.raises(OptimizationAborted) as exc:
        _run(c, wd, runner=_runner(extra=_grows_a_key))

    msg = str(exc.value)
    assert "CHANGED MID-EPOCH" in msg
    assert "backlog_slope" in msg
    assert "EPOCH BOUNDARY, NOT AN EDIT" in msg
    # The rows measured BEFORE the change survive on disk: runs.jsonl is
    # append-only, and they are what tells an author where the change landed.
    rows = artifacts.read_runs(Path(wd) / "runs" / "iter-2")
    assert len(rows) >= 3


def test_a_null_where_a_value_was_aborts_the_campaign(tmp_path, work_dir):
    """DEFECT 7 verbatim: a key present, its value null.

    The real consequence was a `None` reaching `float(raw)` and a `>=` against a
    float, killing an iteration at fit time after ~2 hours of measurement. Caught
    on the first row after the change instead.
    """
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    seen: list[int] = []

    def _nulls_a_key(row):
        seen.append(row.row_index)
        return {"slope": None if len(seen) > 3 else 0.01}

    with pytest.raises(OptimizationAborted) as exc:
        _run(c, wd, runner=_runner(extra=_nulls_a_key))

    assert "slope: float -> null" in str(exc.value)
    assert "an unknown is not a measurement" in str(exc.value)


def test_a_self_check_violation_fails_only_its_own_row(tmp_path, work_dir):
    """DEFECT 2: 8 of 12 rows reported a value their own diagnostic refuted.

    A row failure, not a campaign abort -- the sound rows must survive, and the
    violated row must be recorded with its reason and its verdicts.
    """
    c = _campaign()
    c["optimization"]["response"]["self_check"] = [
        {"metric": "backlog_slope", "op": "<=", "value": 0.060},
    ]
    wd = _init_work_dir(tmp_path, c)

    def _one_bad_row(row):
        return {"backlog_slope": 0.1234 if row.row_index == 1 else 0.01}

    # THE DOCSTRING'S OWN CLAIM, now actually delivered. This used to assert a
    # campaign ABORT — contradicting the line above it ("A row failure, not a
    # campaign abort -- the sound rows must survive"), because
    # `_fitting_responses` aborted on any row that produced no usable
    # measurement before the partial-fit path could drop it. The point of a
    # per-row self-check is that 8 sound rows out of 12 are still 8 sound rows;
    # the fit runs on them, the reduced resolution is recorded, and the violated
    # row keeps its reason and its verdicts.
    _run(c, wd, stage="screen", iteration=2, runner=_runner(extra=_one_bad_row))
    eff = json.loads((Path(wd) / "runs" / "iter-2" / "effects.json").read_text())
    assert all(e["estimate"] == e["estimate"] for e in eff["effects"]), eff
    fx = json.loads(
        (Path(wd) / "runs" / "iter-2" / "fit_exclusions.json").read_text(),
    )
    assert fx["excluded_row_indices"] == [1], fx
    assert fx["excluded_reasons"]["1"] == "failed_to_measure", fx

    rows = {r["row_index"]: r for r in
            artifacts.read_runs(Path(wd) / "runs" / "iter-2")}
    assert rows[1]["status"] == "failed"
    assert "response.self_check violated" in rows[1]["error"]
    assert [r["status"] for i, r in rows.items() if i != 1] == \
        ["complete"] * (len(rows) - 1)
    # Verdicts recorded on the PASSING rows too, so a reader can tell "the
    # invariant held" from "no invariant was declared" (guide SS7.7).
    assert rows[0]["self_check"][0]["ok"] is True
    assert rows[1]["self_check"][0]["ok"] is False


def test_a_campaign_with_no_self_check_records_an_empty_verdict_list(
    tmp_path, work_dir,
):
    """Declaring none behaves exactly as before: every row complete."""
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd)

    rows = artifacts.read_runs(Path(wd) / "runs" / "iter-2")
    assert {r["status"] for r in rows} == {"complete"}
    assert all(r["self_check"] == [] for r in rows)


def test_a_stale_byte_identical_response_fails_the_row(tmp_path, work_dir):
    """DEFECT 1: an adapter serving a cached result across different levels.

    The real one re-read a metrics file it failed to overwrite when the target
    exited non-zero, so a level that PANICKED was recorded as "no effect,
    identical to baseline" -- and three factors were briefly believed live.

    The manipulation predicate here reads ``applied.*`` (the rendered
    configuration Nous itself knows), which is the form
    ``runner._applied_namespace`` exists for and the only form available to the
    majority of targets -- they emit metrics only, with no config echo. So the
    predicates pass on a stale row and the freshness guard is what catches it.
    """
    c = _campaign()
    for f in c["optimization"]["factors"]:
        f["manipulation"] = {"observable": f"applied.{f['id']}", "op": "==",
                             "value": "{level}"}
    wd = _init_work_dir(tmp_path, c)

    def _serves_a_cached_result(row):
        # Metrics only, and always the SAME object: a file the adapter never
        # overwrote, re-read on every invocation.
        return {"m": 10.0, "slope": 0.01}

    with pytest.raises(OptimizationAborted):
        # `_fitting_responses` then refuses to fit on the excluded rows, which is
        # the right end state: the epoch stops rather than fitting a surface over
        # measurements that were never taken.
        _run(c, wd, runner=_serves_a_cached_result)

    rows = artifacts.read_runs(Path(wd) / "runs" / "iter-2")
    stale = [r for r in rows if "BYTE-IDENTICAL" in (r["error"] or "")]
    assert stale, [r["error"] for r in rows]
    assert all(r["status"] == "failed" for r in stale)
    # Row 0 established the reference and is kept; every later row whose levels
    # differ from its predecessor's is failed, so a whole sweep of stale reads
    # cannot pass itself off as a flat response surface.
    assert rows[0]["status"] == "complete"


def test_a_config_echo_shields_a_stale_row_from_the_freshness_guard(
    tmp_path, work_dir,
):
    """The freshness guard's honest limit, asserted rather than implied.

    An adapter that echoes its own configuration back emits a response object
    that differs on every row BY CONSTRUCTION, so no two rows are ever
    byte-identical and guard 2 can never fire -- even when every metric in the
    object is stale. That is not a bug in the guard: Nous observes only what the
    adapter returns, and an object that differs per row IS evidence the adapter
    did something per row. It IS a limit worth pinning down, because the
    mitigation is a different guard: the config echo makes the manipulation
    predicate strictly stronger (it confirms the flag was RECEIVED, not merely
    sent), and a stale-metrics adapter that echoes config is caught by
    ``response.self_check`` or by ``--liveness``'s effect-size measurement
    instead -- a factor whose objective never moves reads as a dead axis.
    """
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)

    def _echoes_config_but_serves_stale_metrics(row):
        return {"cfg": {k.lower(): v for k, v in row.levels.items()},
                "m": 10.0, "slope": 0.01}

    _run(c, wd, runner=_echoes_config_but_serves_stale_metrics)

    rows = artifacts.read_runs(Path(wd) / "runs" / "iter-2")
    assert {r["status"] for r in rows} == {"complete"}
    assert not any("BYTE-IDENTICAL" in (r["error"] or "") for r in rows)
