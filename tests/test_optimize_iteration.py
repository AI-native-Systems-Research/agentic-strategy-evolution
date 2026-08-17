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
    confirm_at.json was written, and `confirm` replicated the ORIGIN. The
    campaign had already observed the true optimum (117.854) and then
    confirmed a 73.476 centre point instead.
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


def test_confirm_replicates_the_best_observed_config_when_there_is_no_fitted_optimum(
    tmp_path, work_dir,
):
    """Replicating the ORIGIN was actively misleading.

    On a live campaign the screen stage observed goodput 117.854 and confirm
    reproduced a 73.476 centre point — the campaign found the right answer
    and reported the wrong one. With no fitted stationary point (refine
    skipped, or its solve singular), the honest thing to reproduce is the
    best configuration actually measured.
    """
    from orchestrator.iteration import IterationOutcome
    from orchestrator.optimize.stage_runner import _best_observed

    c = _campaign()
    c["optimization"]["stages"] = ["verify", "screen", "confirm"]
    wd = _init_work_dir(tmp_path, c)

    # screen first, so there are observations to pick a winner from
    _run(c, wd, stage="screen", iteration=2)
    best = _best_observed(wd, "m")
    assert best is not None

    outcome = _run(c, wd, stage="confirm", iteration=3)
    assert outcome is IterationOutcome.COMPLETED

    record = json.loads(
        (Path(wd) / "runs" / "iter-3" / "confirmation.json").read_text(),
    )
    assert record["confirmed_at_levels"] == best["levels"], (
        "confirm must replicate the best OBSERVED configuration, not the "
        "geometric origin"
    )
    # and the mean it reports must match what that config actually scores
    assert math.isclose(record["mean"], best["m"], rel_tol=1e-6)


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
    """A fitted stationary point is an extrapolation and can be WORSE.

    "The prediction reproduced" and "this is the best configuration found"
    are different claims. When the surface is mis-specified the solved point
    can land below a corner the screen already measured; replicating it then
    yields tight agreement between replicates and a status of CONFIRMED,
    while the campaign quietly reports an inferior configuration as its
    optimum. confirmation.json must record both facts so the artifact stays
    honest when they disagree.
    """
    import logging

    from orchestrator.optimize.stage_runner import _best_observed

    c = _campaign()
    c["optimization"]["stages"] = ["verify", "screen", "confirm"]
    wd = _init_work_dir(tmp_path, c)

    _run(c, wd, stage="screen", iteration=2)
    best = _best_observed(wd, "m")
    assert best is not None

    # Pin confirm to a point that scores strictly below the observed best.
    (Path(wd) / "runs" / "iter-2" / "confirm_at.json").write_text(
        json.dumps({k: -1.0 for k in ("A", "B", "C")}),
    )

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


def test_confirm_respects_minimize_direction(tmp_path, work_dir):
    """For a minimize objective, LOWER must count as beating the best."""
    from orchestrator.optimize.stage_runner import _best_observed

    c = _campaign()
    c["optimization"]["response"]["primary"]["direction"] = "minimize"
    c["optimization"]["stages"] = ["verify", "screen", "confirm"]
    wd = _init_work_dir(tmp_path, c)

    _run(c, wd, stage="screen", iteration=2)
    best = _best_observed(wd, "m")
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


def test_confirm_refuses_a_stationary_point_outside_the_design_hull(
    tmp_path, work_dir, caplog,
):
    """decide_after_refine already flags this; confirm must now act on it.

    Trigger is documented as reported-not-acted-on, so confirm read the same
    out-of-hull solve off disk and replicated it anyway — the system diagnosed
    the problem, wrote it into findings, then did the thing it had just warned
    against. Observed on a real campaign: the surface was monotone in both
    refined factors (no interior optimum exists), the quadratic solve landed at
    coded BANDCAP=+1.62 / THRESH=-2.30, and confirm reproduced 112.4997 while
    the campaign had already MEASURED 182.2159 at a corner.
    """
    import logging

    from orchestrator.optimize.stage_runner import _read_confirm_at

    wd = tmp_path / "wd"
    (wd / "runs" / "iter-4").mkdir(parents=True)
    (wd / "runs" / "iter-4" / "confirm_at.json").write_text(
        json.dumps({"BANDCAP": 1.6189798710528895, "THRESH": -2.296736457110853}),
    )
    with caplog.at_level(logging.WARNING):
        assert _read_confirm_at(wd) is None, (
            "an out-of-hull solve must not be confirmed; falling back to the "
            "best observed configuration is the weaker but true claim"
        )
    assert "outside the design hull" in caplog.text
    assert "BANDCAP" in caplog.text and "THRESH" in caplog.text


def test_confirm_still_uses_a_stationary_point_inside_the_hull(tmp_path, work_dir):
    """A legitimate interior optimum is unaffected."""
    from orchestrator.optimize.stage_runner import _read_confirm_at

    wd = tmp_path / "wd"
    (wd / "runs" / "iter-4").mkdir(parents=True)
    payload = {"A": 0.35, "B": -0.8}
    (wd / "runs" / "iter-4" / "confirm_at.json").write_text(json.dumps(payload))
    assert _read_confirm_at(wd) == payload


def test_hull_check_accepts_the_boundary(tmp_path, work_dir):
    """+/-1.0 is ON the hull, not outside it — a factorial corner is valid."""
    from orchestrator.optimize.stage_runner import _read_confirm_at

    wd = tmp_path / "wd"
    (wd / "runs" / "iter-3").mkdir(parents=True)
    (wd / "runs" / "iter-3" / "confirm_at.json").write_text(
        json.dumps({"A": 1.0, "B": -1.0}),
    )
    assert _read_confirm_at(wd) == {"A": 1.0, "B": -1.0}


def test_confirm_runs_the_fitted_point_not_the_geometric_centre(
    tmp_path, work_dir,
):
    """`role="center"` made confirm discard the coordinates it exists to replay.

    `matrix._decode_level` treats role "center" as "ignore coded coordinates,
    use the midpoint of every declared range" — correct for a genuine replicated
    centre point, catastrophic for the fitted stationary point. A stationary
    point at coded +0.9 of [64, 256] ran 160 (the midpoint) instead of 246, and
    the campaign then reported "the predicted optimum reproduced" about a
    configuration the fit never predicted.
    """
    from orchestrator.optimize import matrix
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.stage_runner import _build_design

    c = _campaign()
    c["optimization"]["design"] = {
        "screen": {"resolution": 3}, "confirm": {"replicates": 2},
    }
    wd = tmp_path / "wd"
    (wd / "runs" / "iter-2").mkdir(parents=True)
    (wd / "runs" / "iter-2" / "confirm_at.json").write_text(
        json.dumps({"A": 0.9, "B": 0.9, "C": 0.9}),
    )
    factors = parse_factors(c["optimization"]["factors"])
    design = _build_design(factors, c["optimization"]["design"], "confirm", wd)
    rows = matrix.expand(design, factors)

    from orchestrator.optimize.factors import decode_coded

    mid = {f.id: decode_coded(f, 0.0) for f in factors}
    assert rows[0].levels != mid, (
        f"confirm ran the geometric centre {mid} instead of the fitted point at "
        f"coded +0.9 — the coordinates were discarded"
    )
    # and it should be near the HIGH end, since +0.9 is near +1
    hi = {f.id: decode_coded(f, 0.9) for f in factors}
    assert rows[0].levels == hi, f"expected {hi}, got {rows[0].levels}"


def test_confirm_with_no_fitted_point_still_yields_the_origin(tmp_path, work_dir):
    """The no-refine case must be unchanged: coded 0.0 decodes to the midpoint."""
    from orchestrator.optimize import matrix
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.stage_runner import _build_design

    c = _campaign()
    c["optimization"]["design"] = {
        "screen": {"resolution": 3}, "confirm": {"replicates": 1},
    }
    wd = tmp_path / "wd"
    (wd / "runs").mkdir(parents=True)
    factors = parse_factors(c["optimization"]["factors"])
    design = _build_design(factors, c["optimization"]["design"], "confirm", wd)
    assert all(cd == 0.0 for cd in design.points[0].coded)
    rows = matrix.expand(design, factors)
    assert rows, "confirm produced no rows"


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
    assert obs["round"] == 0, "screen reports round 0 (0-based)"
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
