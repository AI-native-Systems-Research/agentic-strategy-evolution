"""``optimization.run_timeout_sec``: the per-run ceiling, declarable at last.

The measurement seam carried a hardcoded 600-second subprocess ceiling with no
authoring surface to change it. That is fine for a target whose objective
evaluation is one benchmark invocation, and wrong for a target whose single
LEGITIMATE measurement is a compound one -- observed on a live campaign whose
one objective evaluation is a capacity bisection over ~5 simulator runs. That
row died with ``RuntimeError: config run failed: Command '[...]' timed out
after 600 seconds`` and the campaign had no supported way to say so.

Every workaround available at that point degraded the science rather than the
schedule: a shorter simulation horizon means a noisier slope statistic, a
looser bisection tolerance means a coarser objective value, and caching results
across invocations would be a covert channel between arms the design registered
as independent. So the ceiling becomes declarable and the failure stays loud --
the two claims this file is the oracle for.

These tests assert on what a target process ACTUALLY got: a script that sleeps
past a small ceiling must fail, one that finishes under it must succeed, and
the resolved ceiling must be readable back out of the pre-registration record.
Nothing here asserts that ``subprocess.run`` was called with a ``timeout=``
keyword; a ceiling that is recorded but not enforced is precisely the defect.
No subprocess reaches an LLM -- the "target" is a two-line shell script.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.matrix import render_apply
from orchestrator.optimize.runner import make_config_runner

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "orchestrator" / "schemas" / "campaign.schema.yaml"


# --- fixtures ---------------------------------------------------------------

_SLEEPY_TARGET = """#!/bin/sh
# A target whose single measurement is slow on purpose. The compound-measurement
# case this field exists for is not distinguishable from a hang by anything the
# runner can see, so the only honest oracle is a process that really does take
# longer than the ceiling under test.
sleep {seconds}
printf '{{"m": 1.0}}\\n'
"""


def _sleepy_target(tmp_path: Path, seconds: float) -> Path:
    script = tmp_path / f"sleepy_{str(seconds).replace('.', '_')}.sh"
    script.write_text(_SLEEPY_TARGET.format(seconds=seconds))
    script.chmod(0o755)
    return script


def _factor() -> list:
    return parse_factors([{
        "id": "F", "name": "flag", "type": "choice", "levels": ["0", "1"],
        "apply": "--flag={level}",
        "manipulation": {"observable": "applied.flag", "op": "==",
                         "value": "{level}"},
        "relations": [{"id": "R1", "kind": "correctness", "statement": "s",
                       "native_test": "t.py::test_present"}],
    }])


class _Row:
    """The minimal duck-typed row ``make_config_runner``'s closure consumes."""

    row_index = 0
    replicate = 0
    role = "corner"

    def __init__(self, levels: dict, apply: dict):
        self.levels = dict(levels)
        self.apply = dict(apply)


def _campaign(repo: Path, *, run_cmd: str, **opt_over) -> dict:
    opt = {
        "response": {"primary": {"metric": "m", "direction": "maximize"}},
        "factors": [{
            "id": "F", "name": "flag", "type": "choice", "levels": ["0", "1"],
            "apply": "--flag={level}",
            "manipulation": {"observable": "applied.flag", "op": "==",
                             "value": "{level}"},
            "relations": [{"id": "R1", "kind": "correctness", "statement": "s",
                           "native_test": "t.py::test_present"}],
        }],
        "stages": ["verify", "screen", "confirm"],
        "design": {"screen": {"resolution": 3}, "confirm": {"replicates": 1}},
        "run_command": run_cmd,
    }
    opt.update(opt_over)
    return {
        "kind": "optimization", "run_id": "rt",
        "research_question": "does the ceiling hold?",
        "prompts": {"methodology_layer": "prompts/methodology",
                    "domain_adapter_layer": None},
        "target_system": {"name": "T", "description": "a slow target",
                          "repo_path": str(repo)},
        "optimization": opt,
    }


# --- 1. the declared ceiling is the one the process actually got ------------

def test_a_run_past_the_declared_ceiling_fails_and_one_under_it_succeeds(
    tmp_path: Path,
):
    """The ceiling is enforced at the value declared, in both directions.

    Both halves matter. Only the failing half proves a ceiling exists at all;
    only the passing half proves it is the DECLARED one rather than something
    smaller that happens to trip the same target.
    """
    factors = _factor()
    row = _Row({"F": "0"}, render_apply(factors, {"F": "0"}))

    slow = make_config_runner(
        f"sh {_sleepy_target(tmp_path, 5)}",
        cwd=tmp_path, metric_path="m", timeout=1,
    )
    with pytest.raises(RuntimeError) as exc:
        slow(row)
    assert "timed out" in str(exc.value).lower(), (
        "the timeout must surface as the run's own failure, naming the ceiling"
    )

    quick = make_config_runner(
        f"sh {_sleepy_target(tmp_path, 0.1)}",
        cwd=tmp_path, metric_path="m", timeout=5,
    )
    assert quick(row)["m"] == 1.0, (
        "a run that finishes inside the declared ceiling must return its "
        "observation -- a ceiling that also kills compliant runs is not a "
        "declarable ceiling, it is a shorter hardcoded one"
    )


def test_a_campaign_declaring_run_timeout_sec_gets_that_ceiling_on_its_runs(
    tmp_path: Path,
):
    """End to end from the campaign dict: a 1-second ceiling kills a 5s target.

    This is the claim the gap was about. ``make_config_runner`` already took a
    ``timeout``; nothing carried a campaign-declared value to it, so the only
    reachable value was the 600-second default. Asserted through the real
    ``--smoke`` probe, which is the shortest path from a campaign dict to a
    launched run subprocess that does not require a full epoch.
    """
    from orchestrator.cli import _smoke_check_optimization

    repo = tmp_path / "repo"
    repo.mkdir()
    campaign = _campaign(
        repo, run_cmd=f"sh {_sleepy_target(tmp_path, 5)}", run_timeout_sec=1,
    )
    started = time.monotonic()
    issues = _smoke_check_optimization(campaign)
    elapsed = time.monotonic() - started

    assert any("timed out" in i.lower() for i in issues), issues
    assert elapsed < 60, (
        f"the probe took {elapsed:.1f}s, so the declared 1-second ceiling was "
        f"not the one applied -- the hardcoded 600 was"
    )


# --- 2. omitting the field changes nothing ---------------------------------

def test_omitting_run_timeout_sec_keeps_the_historical_600_second_ceiling():
    """Strict backward compatibility: absence resolves to exactly 600.

    Every campaign authored before this field existed ran at 600 seconds, and a
    pre-registered design whose ceiling silently moved would make its own
    ``runs.jsonl`` unreadable against the epoch that produced it. So absence is
    not "unbounded" and not "some new default" -- it is 600.
    """
    from orchestrator.optimize.runner import DEFAULT_RUN_TIMEOUT_SEC
    from orchestrator.optimize.stage_runner import resolve_run_timeout

    assert DEFAULT_RUN_TIMEOUT_SEC == 600
    assert resolve_run_timeout({}) == 600
    assert resolve_run_timeout({"run_command": "./bench"}) == 600
    assert resolve_run_timeout({"run_timeout_sec": 5400}) == 5400


# --- 3. the schema rejects a ceiling that is not a positive integer ---------

@pytest.mark.parametrize("bad", [0, -1, -600, 1.5, "600", None, True])
def test_schema_rejects_a_non_positive_integer_ceiling(tmp_path: Path, bad):
    """0 and negatives would make every run fail instantly; a float or a string
    would be a type error inside ``subprocess.run`` at row 1 of the epoch, i.e.
    after the pre-registration was already hashed.
    """
    schema = yaml.safe_load(SCHEMA_PATH.read_text())
    campaign = _campaign(tmp_path, run_cmd="./bench", run_timeout_sec=bad)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(campaign, schema)


def test_schema_accepts_a_positive_integer_ceiling(tmp_path: Path):
    schema = yaml.safe_load(SCHEMA_PATH.read_text())
    campaign = _campaign(tmp_path, run_cmd="./bench", run_timeout_sec=7200)
    jsonschema.validate(campaign, schema)


# --- 4. the resolved ceiling is readable out of the pre-registration --------

def test_the_effective_ceiling_is_recorded_in_the_design_matrix(tmp_path: Path):
    """A post-hoc reader must be able to tell what ceiling a row ran under.

    Same convention as ``workload_seeds``, ``policy_hash`` and ``held_fixed``:
    a resolved run parameter that shaped the measurement is echoed onto the
    design matrix, so the artifact describes the runs it registered rather than
    only the configurations. Without it, a ``failed`` row reading "timed out
    after 900 seconds" cannot be distinguished from a campaign that was
    re-launched at a different ceiling.
    """
    from orchestrator.optimize.harness import run_synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES

    res = run_synthetic_campaign(
        SURFACES["additive"](), seed=7, parent_dir=tmp_path,
        campaign_overrides={
            "run_timeout_sec": 1234,
            "design": {"screen": {"resolution": 5, "center_points": 4},
                       "refine": {"kind": "central_composite",
                                  "center_points": 4},
                       "confirm": {"replicates": 3}},
        },
    )
    dm = json.loads(
        (res.work_dir / "runs" / "iter-2" / "design_matrix.json").read_text(),
    )
    assert dm["run_timeout_sec"] == 1234


def test_the_default_ceiling_is_recorded_too(tmp_path: Path):
    """Recorded even when the campaign said nothing, because "the author did
    not choose" and "the author chose 600" produce the same runs and the
    artifact should not require the reader to know which release they were on.
    """
    from orchestrator.optimize.harness import run_synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES

    res = run_synthetic_campaign(
        SURFACES["additive"](), seed=8, parent_dir=tmp_path,
        campaign_overrides={
            "design": {"screen": {"resolution": 5, "center_points": 4},
                       "refine": {"kind": "central_composite",
                                  "center_points": 4},
                       "confirm": {"replicates": 3}},
        },
    )
    dm = json.loads(
        (res.work_dir / "runs" / "iter-2" / "design_matrix.json").read_text(),
    )
    assert dm["run_timeout_sec"] == 600


def test_an_enriched_design_matrix_still_validates_against_its_schema(
    tmp_path: Path,
):
    """The pre-registration record is schema-governed, so a field added to it
    has to be declared there -- ``additionalProperties: false`` is what makes
    the artifact a record rather than a bag.
    """
    from orchestrator.optimize.harness import run_synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES

    res = run_synthetic_campaign(
        SURFACES["additive"](), seed=9, parent_dir=tmp_path,
        campaign_overrides={
            "run_timeout_sec": 900,
            "workload": {"seed_env": "NOUS_WORKLOAD_SEED"},
            "design": {"screen": {"resolution": 5, "center_points": 4},
                       "refine": {"kind": "central_composite",
                                  "center_points": 4},
                       "confirm": {"replicates": 3}},
        },
    )
    schema = json.loads(
        (REPO_ROOT / "orchestrator" / "schemas"
         / "design_matrix.schema.json").read_text(),
    )
    dm = json.loads(
        (res.work_dir / "runs" / "iter-2" / "design_matrix.json").read_text(),
    )
    jsonschema.validate(dm, schema)


# --- 5. a fired ceiling is still a loud, attributable failure ---------------

def test_a_fired_ceiling_is_recorded_as_a_failed_row_with_its_error(
    tmp_path: Path,
):
    """Only the ceiling became declarable; the failure did not become softer.

    A timed-out row must still be a ``failed`` row carrying the error text, and
    must never resolve to a missing measurement the fit quietly steps over --
    that is the NaN-poisoning class (spec §4 D2), and a configurable ceiling
    would be a new way to reach it if the failure were swallowed.
    """
    from orchestrator.optimize import runner as runner_mod

    factors = _factor()
    row = _Row({"F": "0"}, render_apply(factors, {"F": "0"}))
    log_dir = tmp_path / "failed_runs"
    slow = make_config_runner(
        f"sh {_sleepy_target(tmp_path, 5)}",
        cwd=tmp_path, metric_path="m", timeout=1, log_dir=log_dir,
    )

    outcomes = runner_mod.execute_design(
        [row], runner=slow,
        response_spec={"primary": {"metric": "m", "direction": "maximize"}},
        invariants=None, factors=factors,
    )

    assert len(outcomes) == 1
    assert outcomes[0].status == "failed", (
        "a timed-out row must be a failure, not an absent one"
    )
    assert "timed out" in (outcomes[0].error or "").lower(), outcomes[0].error
    assert log_dir.exists(), (
        "the full output of a timed-out run is the only evidence of how far it "
        "got, so it must still be preserved"
    )


def test_a_high_ceiling_warns_at_validation(tmp_path: Path):
    """A ceiling is a schedule commitment as well as a measurement one.

    90 rows at a two-hour ceiling is a week of wall clock in the worst case, and
    the author who typed the number is the only person positioned to know
    whether that is intended. A WARNING, never an error: a legitimately slow
    compound measurement is exactly the case the field was added for, so
    refusing it would re-close the gap.
    """
    from orchestrator.validate import validate_optimization_campaign

    campaign = _campaign(tmp_path, run_cmd="./bench", run_timeout_sec=7200)
    campaign["optimization"]["design"] = {
        "screen": {"resolution": 3}, "confirm": {"replicates": 1},
        "max_runs": 90,
    }
    issues = validate_optimization_campaign(campaign)
    warns = [i for i in issues if "run_timeout_sec" in i]
    assert warns, issues
    assert all(w.startswith("WARN:") for w in warns), warns
    assert any("90" in w for w in warns), (
        "the warning must quantify the exposure, not just flag the number"
    )

    ok = _campaign(tmp_path, run_cmd="./bench", run_timeout_sec=600)
    assert not [i for i in validate_optimization_campaign(ok)
                if "run_timeout_sec" in i]


# --- 6. --smoke names the ceiling it used ----------------------------------

def test_smoke_reports_the_effective_ceiling(tmp_path: Path, capsys):
    """``--smoke`` is where an author first meets the ceiling, so it says it.

    Smoke executes one real configuration. It is therefore the only place that
    can tell an author "this ran in 4 seconds under a 600-second ceiling" before
    a 90-row screen discovers the same ceiling on row 1 of the epoch --
    including the case where the probe SUCCEEDS but at a duration close enough
    to the ceiling that a slower row will not.
    """
    from orchestrator.cli import _smoke_check_optimization

    repo = tmp_path / "repo"
    repo.mkdir()
    campaign = _campaign(
        repo,
        run_cmd=(
            """python3 -c 'import json;print(json.dumps("""
            """{"applied":{"flag":"0"},"m":1.0}))'"""
        ),
        run_timeout_sec=1800,
    )
    assert _smoke_check_optimization(campaign) == []
    out = capsys.readouterr().out
    assert "1800" in out, (
        f"smoke must name the ceiling the probe ran under; got:\n{out}"
    )
