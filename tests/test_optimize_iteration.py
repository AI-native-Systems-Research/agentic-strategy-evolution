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
