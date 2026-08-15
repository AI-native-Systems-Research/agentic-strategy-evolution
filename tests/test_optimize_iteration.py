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
        "design": {"screen": {"resolution": 5, "center_points": 4},
                   "refine": {"kind": "central_composite", "center_points": 4},
                   "confirm": {"replicates": 3}},
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


def _runner(*, extra=None, drop_row=None):
    """Fake config runner: a clean linear response plus an L5-style flip."""
    def run(row):
        lv = row.levels
        a = float(lv.get("A", 0)); b = float(lv.get("B", 0))
        obs = {
            "cfg": {k.lower(): v for k, v in lv.items()},
            # negative main effect on A, positive AB interaction: the compound
            # beats the parts, which is the landscape this feature exists for
            "m": 10.0 - 0.05 * a + 0.20 * b + 0.02 * a * b,
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
    CONTINUE from the last stage makes it call one more iteration;
    stage_for_iteration then clamps past the end of the stage list and
    returns the final stage again, re-running it forever. That looks correct
    only when max_iterations happens to equal the stage count.
    """
    from orchestrator.engine import Engine
    from orchestrator.iteration import IterationOutcome

    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    outcome = _run(c, wd, stage="confirm", iteration=4)
    assert outcome is IterationOutcome.COMPLETED
    assert Engine(wd).phase == "DONE"


def test_a_non_final_stage_reports_continue(tmp_path, work_dir):
    from orchestrator.iteration import IterationOutcome

    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    assert _run(c, wd, stage="screen", iteration=2) is IterationOutcome.CONTINUE


def test_an_explicit_stages_list_decides_which_stage_is_terminal(tmp_path):
    from orchestrator.optimize.stage_runner import _is_final_stage

    default = _campaign()
    assert _is_final_stage(default, "confirm") is True
    assert _is_final_stage(default, "refine") is False

    short = _campaign()
    short["optimization"]["stages"] = ["verify", "screen", "confirm"]
    assert _is_final_stage(short, "confirm") is True
    assert _is_final_stage(short, "refine") is False

    no_confirm = _campaign()
    no_confirm["optimization"]["stages"] = ["verify", "screen"]
    assert _is_final_stage(no_confirm, "screen") is True
    assert _is_final_stage(no_confirm, "confirm") is False


def test_a_partially_failed_sweep_refuses_to_fit_rather_than_emit_nan(
    tmp_path, work_dir,
):
    """One non-complete run NaN-poisons every coefficient.

    Verified: one NaN among eight runs makes every effect estimate AND the
    intercept NaN, and the artifacts stay schema-valid because jsonschema
    accepts NaN as "number". So the campaign would emit a confident-looking,
    entirely-NaN effects.json with no error at all. Failing loudly is the
    only honest option short of refitting on the completed subset.
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

    with pytest.raises(OptimizationAborted) as exc:
        _run(c, wd, runner=flaky)
    msg = str(exc.value)
    assert "no usable measurement" in msg
    assert "NaN-poison" in msg


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

    with pytest.raises(OptimizationAborted):
        _fitting_responses(
            [_O(0, "complete", {"m": 1.0}), _O(1, "failed", {})], spec, "m",
        )


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


def test_a_null_primary_metric_on_a_complete_row_blocks_but_not_on_an_excluded_one(
    tmp_path,
):
    """`null` means the benchmark ran but could not compute the statistic.

    On a *complete* row that is a measurement failure and must block. On a
    row already excluded from the fit (infeasible/rejected) it is expected
    and must not.
    """
    import math

    from orchestrator.optimize.stage_runner import _fitting_responses

    class _O:
        def __init__(self, idx, status, resp):
            self.row_index, self.status, self.response = idx, status, resp

    spec = {"primary": {"metric": "m", "direction": "maximize"}}
    with pytest.raises(OptimizationAborted):
        _fitting_responses([_O(0, "complete", {"m": None})], spec, "m")

    values = _fitting_responses([_O(0, "infeasible", {"m": None})], spec, "m")
    assert math.isnan(values[0])


# ─── confirm actually confirms (F1 from the final whole-branch review) ─────

def test_confirm_replicates_one_configuration_rather_than_rerunning_the_screen(
    tmp_path, work_dir,
):
    """F1: confirm used to silently rebuild the screen design.

    So the campaign's final stage repeated stage 2 and reported COMPLETED
    while the guide claimed it reproduced the predicted optimum. That is the
    one defect on this branch that could mislead a researcher about their own
    result, which is why it is fixed rather than documented.
    """
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.stage_runner import _build_design

    c = _campaign()
    factors = parse_factors(c["optimization"]["factors"])
    cfg = c["optimization"]["design"]

    screen = _build_design(factors, cfg, "screen")
    confirm = _build_design(factors, cfg, "confirm")

    assert [p.coded for p in screen.points] != [p.coded for p in confirm.points]
    assert confirm.kind == "confirm"
    # one configuration, replicated
    assert len({p.coded for p in confirm.points}) == 1
    assert len(confirm.points) == cfg["confirm"]["replicates"]
    assert sorted(p.replicate for p in confirm.points) == [0, 1, 2]


def test_confirm_honours_the_refine_stages_solved_optimum(tmp_path, work_dir):
    """The loop must close: refine solves a point, confirm replicates THAT."""
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.stage_runner import _build_design

    c = _campaign()
    factors = parse_factors(c["optimization"]["factors"])
    cfg = dict(c["optimization"]["design"])
    cfg["confirm_at"] = {"A": 0.5, "B": -0.25, "C": 0.0}

    confirm = _build_design(factors, cfg, "confirm")
    assert confirm.points[0].coded == (0.5, -0.25, 0.0)


def test_confirm_writes_a_confirmation_record_and_no_effects(tmp_path, work_dir):
    """Confirm reports reproduction; it does not fit a model.

    A single replicated configuration has no distinct design points, so
    fitting raises "design matrix is singular" — correctly. What confirm
    claims is narrower and more useful: this exact configuration, replicated
    N times, produced this mean and this spread.
    """
    from orchestrator.iteration import IterationOutcome

    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
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
    import jsonschema

    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="confirm", iteration=4)

    findings = json.loads(
        (Path(wd) / "runs" / "iter-4" / "findings.json").read_text(),
    )
    schema = json.loads(Path("orchestrator/schemas/findings.schema.json").read_text())
    jsonschema.validate(findings, schema)
    assert findings["experiment_valid"] is True
    assert findings["arms"][0]["status"] == "CONFIRMED"
    assert "replicate" in findings["arms"][0]["observed"]


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


def test_confirm_at_is_read_from_the_latest_iteration_numerically(tmp_path):
    """Lexicographic path sorting picks iter-2 over iter-10.

    "iter-10" sorts before "iter-2" as a string, so a lexicographic sort
    silently replicates a STALE optimum on any campaign reaching double-digit
    iterations — a wrong answer with no error. Found by review of the confirm
    fix itself, on a path nothing drove.
    """
    from orchestrator.optimize.stage_runner import _read_confirm_at

    for iteration, value in ((2, {"A": 0.1}), (9, {"A": 0.5}), (10, {"A": 0.9})):
        d = tmp_path / "runs" / f"iter-{iteration}"
        d.mkdir(parents=True)
        (d / "confirm_at.json").write_text(json.dumps(value))

    assert _read_confirm_at(tmp_path) == {"A": 0.9}


def test_confirm_at_survives_a_non_numeric_iteration_directory(tmp_path):
    from orchestrator.optimize.stage_runner import _read_confirm_at

    (tmp_path / "runs" / "iter-3").mkdir(parents=True)
    (tmp_path / "runs" / "iter-3" / "confirm_at.json").write_text('{"A": 0.4}')
    (tmp_path / "runs" / "iter-bogus").mkdir(parents=True)
    (tmp_path / "runs" / "iter-bogus" / "confirm_at.json").write_text('{"A": 0.0}')

    assert _read_confirm_at(tmp_path) == {"A": 0.4}


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
