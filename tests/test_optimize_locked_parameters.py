"""``locked_parameters`` on the ``kind: optimization`` path (#246 / F1).

The reflective kind hard-fails a bundle whose ``verified_parameters`` deviate
from ``campaign.locked_parameters``. The optimization kind has no bundle, so the
matrix-path equivalent compares each locked value against what the TARGET
reports it actually used, on every measured row, via
``optimization.locked_observables``.

Behavioural throughout: assertions are on validator output, on the
``OptimizationAborted`` a campaign ends with, on artifacts on disk, and on what
``--smoke`` reports. Zero LLM: the end-to-end tests drive the synthetic harness.
"""
from __future__ import annotations

import dataclasses
import json
import stat
from pathlib import Path

import pytest

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES
from orchestrator.validate import validate_optimization_campaign


# ───────────────────────────── validation time ──────────────────────────────


def _campaign(*, locked=None, observables=None, factor_name="alpha") -> dict:
    opt = {
        "response": {"primary": {"metric": "m", "direction": "maximize"}},
        "factors": [{
            "id": "A", "name": factor_name, "type": "numeric",
            "levels": [1, 2], "apply": "--a={level}",
            "manipulation": {"observable": "cfg.a", "op": "==", "value": "{level}"},
            "relations": [{"id": "RA", "kind": "correctness", "statement": "s",
                           "native_test": "t.py::test_a"}],
        }],
        "design": {"screen": {"resolution": 3}},
        "stages": ["verify", "screen"],
    }
    if observables is not None:
        opt["locked_observables"] = observables
    c = {"kind": "optimization", "run_id": "lk", "research_question": "q",
         "prompts": {"methodology_layer": "prompts/methodology",
                     "domain_adapter_layer": None},
         "target_system": {"name": "T", "description": "d"}, "optimization": opt}
    if locked is not None:
        c["locked_parameters"] = locked
    return c


def _errors(c):
    return [m for m in validate_optimization_campaign(c) if not m.startswith("WARN:")]


def _warns(c):
    return [m for m in validate_optimization_campaign(c) if m.startswith("WARN:")]


@pytest.mark.parametrize("key", ["A", "alpha"])
def test_a_locked_parameter_that_is_also_a_factor_is_an_error(key):
    """Pinned and varied at once is not a design; both the id and the name count."""
    errs = _errors(_campaign(locked={key: 1}))
    assert any("locked_parameters" in e and repr(key) in e and "factor" in e
               for e in errs), errs


def test_a_locked_parameter_disjoint_from_the_factors_is_not_an_error():
    assert _errors(_campaign(locked={"max_seq_len": 2048},
                             observables={"max_seq_len": "engine.max_seq_len"})) == []


def test_an_unenforceable_lock_is_an_error_not_a_warning():
    """No observable means no enforcement, so the lock must not pass as one."""
    c = _campaign(locked={"max_seq_len": 2048, "model": "m-7b"},
                  observables={"max_seq_len": "engine.max_seq_len"})
    errs = [e for e in _errors(c) if "cannot be enforced" in e]
    assert len(errs) == 1, _errors(c)
    assert "'model'" in errs[0] and "'max_seq_len'" not in errs[0]


def test_an_acknowledged_unverified_lock_is_a_warning_and_is_reported(tmp_path):
    c = _campaign(locked={"max_seq_len": 2048, "model": "m-7b"},
                  observables={"max_seq_len": "engine.max_seq_len"})
    c["optimization"]["unverified_locks"] = {"model": "harness does not echo it"}
    assert _errors(c) == []
    warns = [w for w in _warns(c) if "UNVERIFIED" in w]
    assert len(warns) == 1 and "'model'" in warns[0], _warns(c)
    from orchestrator.optimize.provenance import waivers

    got = waivers(tmp_path, c)
    assert {"gate": "locked_parameters.model", "reason": "harness does not echo it",
            "note": "lock declared but NOT verified at run time"} in got


def test_unverified_locks_must_name_a_real_unobserved_lock():
    c = _campaign(locked={"max_seq_len": 2048},
                  observables={"max_seq_len": "engine.max_seq_len"})
    c["optimization"]["unverified_locks"] = {"max_seq_len": "x", "typo": "y"}
    errs = _errors(c)
    assert any("'typo'" in e for e in errs) and any(
        "'max_seq_len'" in e and "IS verified" in e for e in errs), errs


def test_every_locked_parameter_enforced_means_no_warning():
    warns = _warns(_campaign(locked={"max_seq_len": 2048},
                             observables={"max_seq_len": "engine.max_seq_len"}))
    assert not [w for w in warns if "locked_observables" in w], warns


def test_an_observable_for_a_parameter_that_is_not_locked_is_an_error():
    """A typo'd key would leave the intended parameter silently unenforced."""
    errs = _errors(_campaign(locked={"max_seq_len": 2048},
                             observables={"max_seqlen": "engine.max_seq_len"}))
    assert any("'max_seqlen'" in e and "locked_parameters" in e for e in errs), errs


def test_the_schema_accepts_locked_observables():
    import jsonschema
    import yaml

    schema = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "orchestrator" / "schemas"
         / "campaign.schema.yaml").read_text())
    c = _campaign(locked={"max_seq_len": 2048},
                  observables={"max_seq_len": "engine.max_seq_len"})
    errs = list(jsonschema.Draft202012Validator(schema).iter_errors(c))
    assert errs == [], [e.message for e in errs]


# ───────────────────────────── run time (end to end) ─────────────────────────
#
# Metamorphic pair: the SAME target (which runs with max_seq_len = 1024
# whatever the campaign says) under the SAME campaign, differing only in the
# locked value. Equal -> the campaign is unaffected by the lock; unequal ->
# the campaign aborts naming the deviation, and nothing claims certification.

_TARGET_APPLIES = 1024


def _surface():
    return dataclasses.replace(
        SURFACES["bowl"](),
        extra_observables=lambda lv: {"engine": {"max_seq_len": _TARGET_APPLIES}},
    )


def _run(tmp_path, *, locked_value=None, observable=True, seed=3):
    top = {}
    overrides = {}
    if locked_value is not None:
        top["locked_parameters"] = {"max_seq_len": locked_value}
        if observable:
            overrides["locked_observables"] = {"max_seq_len": "engine.max_seq_len"}
    return run_synthetic_campaign(
        _surface(), seed=seed, parent_dir=tmp_path,
        campaign_overrides=overrides, campaign_top_level=top,
    )


def test_a_target_that_ignores_the_locked_value_aborts_the_campaign(tmp_path):
    res = _run(tmp_path, locked_value=2048)

    aborted = [p for p in res.path if p.startswith("aborted:")]
    assert aborted, res.path
    msg = aborted[0]
    assert "max_seq_len" in msg and "2048" in msg and "1024" in msg, msg
    assert "row" in msg, msg
    # Nothing on disk claims an answer.
    assert not (res.work_dir / "report.json").exists()
    assert res.report.get("certified") is not True
    # The offending row is on disk, so the author can see what the target used.
    runs = (res.work_dir / "runs").glob("iter-*/runs.jsonl")
    rows = [json.loads(ln) for p in runs for ln in p.read_text().splitlines() if ln]
    assert rows, "the row that exposed the deviation should be on disk"


def test_a_target_that_honours_the_locked_value_is_unaffected(tmp_path):
    locked = _run(tmp_path / "locked", locked_value=_TARGET_APPLIES)
    plain = _run(tmp_path / "plain")

    assert not [p for p in locked.path if p.startswith("aborted:")], locked.path
    assert locked.path == plain.path
    assert locked.recommendation == plain.recommendation
    assert locked.report.get("certified") == plain.report.get("certified")


def test_an_unobservable_lock_is_not_enforced_at_run_time(tmp_path):
    """Without an observable there is nothing to compare at run time (validation
    rejects such a lock unless it is acknowledged in unverified_locks)."""
    res = _run(tmp_path, locked_value=2048, observable=False)
    assert not [p for p in res.path if p.startswith("aborted:")], res.path


def test_a_declared_observable_the_target_never_emits_aborts(tmp_path):
    """Declared-observable-but-absent cannot pass, exactly like a manipulation path."""
    top = {"locked_parameters": {"max_seq_len": 1024}}
    res = run_synthetic_campaign(
        SURFACES["bowl"](), seed=3, parent_dir=tmp_path,
        campaign_overrides={"locked_observables": {"max_seq_len": "engine.max_seq_len"}},
        campaign_top_level=top,
    )
    aborted = [p for p in res.path if p.startswith("aborted:")]
    assert aborted and "engine.max_seq_len" in aborted[0], res.path


# ────────────────────────────────── --smoke ──────────────────────────────────


def _smoke_campaign(tmp_path: Path, *, locked_value) -> dict:
    target = tmp_path / "lk_target.py"
    target.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "levels = {}\n"
        "for a in sys.argv[1:]:\n"
        "    if a.startswith('--') and '=' in a:\n"
        "        k, v = a[2:].split('=', 1)\n"
        "        levels[k] = v\n"
        "print(json.dumps({'applied': levels, 'm': 1.0,\n"
        f"                  'engine': {{'max_seq_len': {_TARGET_APPLIES}}}}}))\n",
    )
    target.chmod(target.stat().st_mode | stat.S_IXUSR)
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    return {
        "kind": "optimization", "run_id": "lk", "research_question": "q",
        "target_system": {"name": "T", "repo_path": str(repo)},
        "locked_parameters": {"max_seq_len": locked_value},
        "optimization": {
            "response": {"primary": {"metric": "m", "direction": "maximize"}},
            "factors": [{
                "id": "P", "name": "policy", "type": "choice",
                "levels": ["a", "b"], "apply": "--P={level}",
                "manipulation": {"observable": "applied.P", "op": "==",
                                 "value": "{level}"},
                "relations": [{"id": "R_P", "kind": "correctness",
                               "statement": "s",
                               "native_test": "t.py::test_present"}],
            }],
            "locked_observables": {"max_seq_len": "engine.max_seq_len"},
            "stages": ["verify", "screen", "confirm"],
            "design": {"screen": {"resolution": 3},
                       "confirm": {"replicates": 1}},
            "run_command": f"python3 {target}",
            "known_valid_baseline": {"P": "a"},
        },
    }


def test_smoke_fails_when_the_probe_runs_with_a_different_locked_value(tmp_path):
    from orchestrator.cli import _smoke_check_optimization

    issues = _smoke_check_optimization(_smoke_campaign(tmp_path, locked_value=2048))
    hit = [i for i in issues if "max_seq_len" in i]
    assert hit and "2048" in hit[0] and "1024" in hit[0], issues


def test_smoke_passes_and_reports_the_count_when_the_lock_holds(tmp_path, capsys):
    from orchestrator.cli import _smoke_check_optimization

    issues = _smoke_check_optimization(
        _smoke_campaign(tmp_path, locked_value=_TARGET_APPLIES))
    assert issues == []
    assert "1/1 locked parameter(s) hold" in capsys.readouterr().out
