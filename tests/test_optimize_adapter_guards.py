"""Three guards over the TARGET ADAPTER -- the author-written ``run_command``.

Nous content-hashes ``policy.json`` and hard-aborts on a mismatch, because a
pre-registered policy that changed inside an epoch is not a pre-registration. A
pre-registered design makes the same assumption about the MEASUREMENT
INSTRUMENT, and nothing enforced it. A field test's author-written adapter had
seven defects; these three guards close the ones Nous can observe:

  1. CONTRACT DRIFT. The adapter's output schema was edited three times
     mid-epoch. Rows measured before each edit carried ``null`` for the new
     keys, and the response-reading path coerces with ``float(raw)``, so a
     ``None`` met a ``>=`` against a float and killed an entire iteration at fit
     time -- after ~2 hours of measurement. The drift was visible on the very
     first row after each edit; nothing looked.
  2. STALE OUTPUT. The adapter reused a stale metrics file whenever the target
     exited non-zero, so a factor level that PANICKED was recorded as "no
     effect, identical to baseline". Three factors were briefly believed live.
  3. A SELF-CONTRADICTORY ROW. Two growth criteria were combined with ``and``
     instead of ``or``, so 8 of 12 rows reported ``max_sustained_rate`` while
     their own recorded ``backlog_slope`` said that rate was growing.

The oracle for guard 1 is a REAL shell-script target whose output keys change
between invocations, driven through ``runner.make_config_runner`` -- the same
seam the epoch runs through. A fake runner could script the same responses, but
it could not demonstrate that the guard sits where a real adapter's output
actually arrives. Guards 2 and 3 use the injected-runner seam where the
behaviour under test is about response CONTENT rather than about the subprocess
boundary.

No test here makes a live LLM call; every "target" is a shell script or a
Python callable constructed in-process.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.optimize import adapter_contract as ac
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.matrix import ConfigRow
from orchestrator.optimize.runner import (
    AdapterGuard,
    execute_design,
    make_config_runner,
)


# ── fixtures ───────────────────────────────────────────────────────────────

def _row(row_index: int, levels: dict, *, replicate: int = 0) -> ConfigRow:
    return ConfigRow(
        row_index=row_index, levels=levels, role="corner", replicate=replicate,
        apply={"cli_args": [], "env": {}, "patches": []},
    )


def _factor(fid: str = "L1") -> dict:
    return {
        "id": fid, "name": fid, "type": "choice", "levels": ["off", "on"],
        "apply": f"--{fid}={{level}}",
        # Against `applied.*` so the fake target need not echo its config back.
        "manipulation": {"observable": f"applied.{fid}", "op": "==",
                         "value": "{level}"},
        "relations": [{"id": f"{fid}-R1", "kind": "correctness",
                       "statement": "s", "native_test": f"t.py::test_{fid}"}],
    }


def _spec(**kw) -> dict:
    base = {"primary": {"metric": "throughput", "direction": "maximize"}}
    base.update(kw)
    return base


class _Scripted:
    """Returns the next scripted observation on each call, in order."""

    def __init__(self, observations: list):
        self._obs = list(observations)
        self.calls = 0

    def __call__(self, row) -> dict:
        outcome = self._obs[min(self.calls, len(self._obs) - 1)]
        self.calls += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return dict(outcome)


# A REAL adapter whose output contract is read from a file it re-reads on every
# invocation. Editing that file between rows is precisely "the author edited the
# adapter mid-epoch" -- the defect-7 shape -- expressed as something a test can
# do without patching any Nous internals.
_MUTABLE_TARGET = """#!/bin/sh
# The emitted JSON object is whatever `shape.json` currently says. An author
# editing their adapter's output schema mid-epoch is this file changing.
cat "$(dirname "$0")/shape.json"
"""


def _mutable_target(tmp_path: Path, shape: dict) -> Path:
    script = tmp_path / "adapter.sh"
    script.write_text(_MUTABLE_TARGET)
    script.chmod(0o755)
    (tmp_path / "shape.json").write_text(json.dumps(shape))
    return script


def _reshape(tmp_path: Path, shape: dict) -> None:
    """Edit the adapter's output contract, exactly as its author would."""
    (tmp_path / "shape.json").write_text(json.dumps(shape))


def _real_runner(tmp_path: Path, script: Path):
    return make_config_runner(
        str(script), cwd=tmp_path, metric_path="throughput",
    )


# ═══ GUARD 1: the adapter contract hash ═══════════════════════════════════

def test_contract_captured_from_first_successful_row(tmp_path):
    """The epoch's contract is fingerprinted at the work-dir root, hash and all."""
    script = _mutable_target(tmp_path, {"throughput": 10.0, "slope": 0.01})
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen")

    outcomes = execute_design(
        [_row(0, {"L1": "off"})], runner=_real_runner(tmp_path, script),
        response_spec=_spec(), invariants=[], factors=parse_factors([_factor()]),
        adapter_guard=guard,
    )

    assert outcomes[0].status == "complete"
    doc = json.loads((work_dir / "adapter_contract.json").read_text())
    assert doc["keys"] == {"throughput": "float", "slope": "float"}
    assert doc["epoch"] == 1
    assert doc["captured_at"] == {"stage": "screen", "row_index": 0}
    # The sidecar is the record that the document itself was not edited later --
    # the same convention policy.sha256 uses.
    recorded = (work_dir / "adapter_contract.sha256").read_text().strip()
    assert recorded == ac.contract_hash(doc)


def test_failed_row_does_not_establish_the_contract(tmp_path):
    """A crashed first row must not register a contract every healthy row breaks."""
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen")
    runner = _Scripted([
        RuntimeError("config run exited 2: panic: index out of range"),
        {"throughput": 10.0, "slope": 0.01},
    ])

    outcomes = execute_design(
        [_row(0, {"L1": "off"}), _row(1, {"L1": "on"})], runner=runner,
        response_spec=_spec(), invariants=[], factors=parse_factors([_factor()]),
        adapter_guard=guard,
    )

    assert [o.status for o in outcomes] == ["failed", "complete"]
    doc = json.loads((work_dir / "adapter_contract.json").read_text())
    # Captured from row 1 -- the first row that SUCCEEDED -- not from row 0.
    assert doc["captured_at"]["row_index"] == 1
    assert doc["keys"] == {"throughput": "float", "slope": "float"}


def test_rejected_row_does_not_establish_the_contract(tmp_path):
    """Nor does a row whose instrumentation already failed a declared invariant."""
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen")
    invariants = [{"id": "INV1", "observable": "healthy", "op": "==",
                   "value": True}]
    runner = _Scripted([
        {"throughput": 1.0, "healthy": False},
        {"throughput": 10.0, "healthy": True, "slope": 0.01},
    ])

    outcomes = execute_design(
        [_row(0, {"L1": "off"}), _row(1, {"L1": "on"})], runner=runner,
        response_spec=_spec(), invariants=invariants,
        factors=parse_factors([_factor()]), adapter_guard=guard,
    )

    assert [o.status for o in outcomes] == ["rejected", "complete"]
    doc = json.loads((work_dir / "adapter_contract.json").read_text())
    assert doc["captured_at"]["row_index"] == 1


def test_added_key_mid_epoch_aborts(tmp_path):
    """An added key is an abort, not a warning -- it is defect 7's carrier."""
    script = _mutable_target(tmp_path, {"throughput": 10.0})
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen")
    runner = _real_runner(tmp_path, script)
    rows = [_row(0, {"L1": "off"}), _row(1, {"L1": "on"})]
    factors = parse_factors([_factor()])

    execute_design(rows[:1], runner=runner, response_spec=_spec(),
                   invariants=[], factors=factors, adapter_guard=guard)
    _reshape(tmp_path, {"throughput": 12.0, "backlog_slope": 0.4})

    with pytest.raises(ac.AdapterContractDrift) as exc:
        execute_design(rows[1:], runner=runner, response_spec=_spec(),
                       invariants=[], factors=factors, adapter_guard=guard)

    msg = str(exc.value)
    assert "backlog_slope" in msg
    assert "CHANGED MID-EPOCH" in msg
    assert "invalidates comparability across rows" in msg
    assert "EPOCH BOUNDARY, NOT AN EDIT" in msg


def test_removed_key_mid_epoch_aborts(tmp_path):
    script = _mutable_target(tmp_path, {"throughput": 10.0, "slope": 0.01})
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen")
    runner = _real_runner(tmp_path, script)
    factors = parse_factors([_factor()])

    execute_design([_row(0, {"L1": "off"})], runner=runner,
                   response_spec=_spec(), invariants=[], factors=factors,
                   adapter_guard=guard)
    _reshape(tmp_path, {"throughput": 12.0})

    with pytest.raises(ac.AdapterContractDrift) as exc:
        execute_design([_row(1, {"L1": "on"})], runner=runner,
                       response_spec=_spec(), invariants=[], factors=factors,
                       adapter_guard=guard)

    assert "disappeared: slope" in str(exc.value)


def test_value_becoming_null_aborts(tmp_path):
    """DEFECT 7, VERBATIM: the key is present, its value is null.

    A key-set fingerprint reads this as no drift at all, which is why the
    fingerprint carries each value's TYPE and why ``null`` is its own type name.
    The real consequence was a ``None`` reaching ``float(raw)`` and a ``>=``
    against a float two hours of measurement later.
    """
    script = _mutable_target(tmp_path, {"throughput": 10.0, "slope": 0.01})
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen")
    runner = _real_runner(tmp_path, script)
    factors = parse_factors([_factor()])

    execute_design([_row(0, {"L1": "off"})], runner=runner,
                   response_spec=_spec(), invariants=[], factors=factors,
                   adapter_guard=guard)
    _reshape(tmp_path, {"throughput": 12.0, "slope": None})

    with pytest.raises(ac.AdapterContractDrift) as exc:
        execute_design([_row(1, {"L1": "on"})], runner=runner,
                       response_spec=_spec(), invariants=[], factors=factors,
                       adapter_guard=guard)

    msg = str(exc.value)
    assert "slope: float -> null" in msg
    assert "an unknown is not a measurement" in msg


def test_type_change_aborts(tmp_path):
    """An int silently becoming a string is drift, though every key is present."""
    script = _mutable_target(tmp_path, {"throughput": 10.0, "queue_depth": 4})
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen")
    runner = _real_runner(tmp_path, script)
    factors = parse_factors([_factor()])

    execute_design([_row(0, {"L1": "off"})], runner=runner,
                   response_spec=_spec(), invariants=[], factors=factors,
                   adapter_guard=guard)
    _reshape(tmp_path, {"throughput": 12.0, "queue_depth": "4"})

    with pytest.raises(ac.AdapterContractDrift) as exc:
        execute_design([_row(1, {"L1": "on"})], runner=runner,
                       response_spec=_spec(), invariants=[], factors=factors,
                       adapter_guard=guard)

    assert "queue_depth: int -> str" in str(exc.value)


def test_unchanged_contract_across_many_rows_never_aborts(tmp_path):
    """Values move every row; the contract does not. No drift, no complaint."""
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen")
    runner = _Scripted([
        {"throughput": 10.0, "slope": 0.01},
        {"throughput": 22.5, "slope": 0.09},
        {"throughput": 3.25, "slope": 0.00},
    ])

    outcomes = execute_design(
        [_row(0, {"L1": "off"}), _row(1, {"L1": "on"}), _row(2, {"L1": "off"})],
        runner=runner, response_spec=_spec(), invariants=[],
        factors=parse_factors([_factor()]), adapter_guard=guard,
    )

    assert [o.status for o in outcomes] == ["complete"] * 3


def test_contract_survives_across_iterations_of_one_epoch(tmp_path):
    """The contract is EPOCH-scoped: a later stage reads back the earlier one's.

    An iteration-scoped fingerprint would see nothing at all when an adapter is
    edited between two iterations of the same epoch, which is the interval the
    real defect occupied.
    """
    work_dir = tmp_path / "wd"
    screen = AdapterGuard(work_dir, epoch=1, stage="screen")
    execute_design([_row(0, {"L1": "off"})],
                   runner=_Scripted([{"throughput": 10.0, "slope": 0.01}]),
                   response_spec=_spec(), invariants=[],
                   factors=parse_factors([_factor()]), adapter_guard=screen)

    # A fresh guard for a later stage, as stage_runner constructs one per stage.
    confirm = AdapterGuard(work_dir, epoch=1, stage="confirm")
    with pytest.raises(ac.AdapterContractDrift) as exc:
        execute_design([_row(0, {"L1": "on"})],
                       runner=_Scripted([{"throughput": 11.0}]),
                       response_spec=_spec(), invariants=[],
                       factors=parse_factors([_factor()]),
                       adapter_guard=confirm)

    assert "disappeared: slope" in str(exc.value)


def test_editing_the_recorded_contract_is_refused(tmp_path):
    """The hash sidecar is what makes the record itself unforgeable."""
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen")
    execute_design([_row(0, {"L1": "off"})],
                   runner=_Scripted([{"throughput": 10.0, "slope": 0.01}]),
                   response_spec=_spec(), invariants=[],
                   factors=parse_factors([_factor()]), adapter_guard=guard)

    doc = json.loads((work_dir / "adapter_contract.json").read_text())
    doc["keys"]["slope"] = "null"  # "make the drift go away"
    (work_dir / "adapter_contract.json").write_text(json.dumps(doc))

    with pytest.raises(ac.AdapterContractDrift) as exc:
        ac.read_contract(work_dir)
    assert "hash mismatch" in str(exc.value)


def test_no_guard_means_no_contract_file_and_todays_behaviour(tmp_path):
    """A caller that arms nothing gets exactly the pre-guard behaviour."""
    outcomes = execute_design(
        [_row(0, {"L1": "off"}), _row(1, {"L1": "on"})],
        runner=_Scripted([{"throughput": 10.0}, {"throughput": 11.0, "extra": 1}]),
        response_spec=_spec(), invariants=[], factors=parse_factors([_factor()]),
    )

    assert [o.status for o in outcomes] == ["complete", "complete"]
    assert not (tmp_path / "adapter_contract.json").exists()
    assert all(o.self_check == [] for o in outcomes)


# ═══ GUARD 2: output freshness ════════════════════════════════════════════

def test_stale_byte_identical_response_fails_the_row(tmp_path):
    """A cached read across different levels is a loud row failure."""
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen")
    stale = {"throughput": 10.0, "slope": 0.01, "runs": 7}
    runner = _Scripted([dict(stale), dict(stale)])

    outcomes = execute_design(
        [_row(0, {"L1": "off"}), _row(1, {"L1": "on"})], runner=runner,
        response_spec=_spec(), invariants=[], factors=parse_factors([_factor()]),
        adapter_guard=guard,
    )

    assert [o.status for o in outcomes] == ["complete", "failed"]
    err = outcomes[1].error
    assert "BYTE-IDENTICAL" in err
    assert "row 1" in err and "row 0" in err          # names BOTH rows
    assert "{'L1': 'off'}" in err and "{'L1': 'on'}" in err
    assert "CACHED OR STALE" in err


def test_identical_objective_at_different_levels_is_not_a_false_positive(tmp_path):
    """The real 1.3125 case: two policies, one hit rate, different diagnostics.

    This is why the check compares the FULL response object rather than the
    objective. `arc` and `lru` both measured exactly 1.3125 on a live campaign;
    a check on the objective alone would have failed a correct row.
    """
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen")
    runner = _Scripted([
        {"throughput": 1.3125, "evictions": 402},
        {"throughput": 1.3125, "evictions": 517},
    ])

    outcomes = execute_design(
        [_row(0, {"L1": "off"}), _row(1, {"L1": "on"})], runner=runner,
        response_spec=_spec(), invariants=[], factors=parse_factors([_factor()]),
        adapter_guard=guard,
    )

    assert [o.status for o in outcomes] == ["complete", "complete"]


def test_identical_response_at_the_SAME_levels_is_not_stale(tmp_path):
    """A replicate of one configuration on a deterministic target must pass.

    Replicate blocks are built out of exactly this, so treating it as staleness
    would fail every confirm round on a deterministic target.
    """
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="confirm")
    same = {"throughput": 10.0, "slope": 0.01}
    runner = _Scripted([dict(same), dict(same)])

    outcomes = execute_design(
        [_row(0, {"L1": "on"}, replicate=0), _row(1, {"L1": "on"}, replicate=1)],
        runner=runner, response_spec=_spec(), invariants=[],
        factors=parse_factors([_factor()]), adapter_guard=guard,
    )

    assert [o.status for o in outcomes] == ["complete", "complete"]


def test_constant_fields_allowlist_excludes_declared_invariants(tmp_path):
    """Declaring never-varying fields makes the check STRICTER on what remains.

    With `schema_version` and `host` excluded, two rows that differ ONLY in
    those fields are byte-identical on everything that should have varied -- so
    the row fails, where a naive whole-object comparison would have passed it.
    """
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen",
                         constant_fields={"schema_version", "host"})
    runner = _Scripted([
        {"throughput": 10.0, "schema_version": 3, "host": "a"},
        {"throughput": 10.0, "schema_version": 3, "host": "a"},
    ])

    outcomes = execute_design(
        [_row(0, {"L1": "off"}), _row(1, {"L1": "on"})], runner=runner,
        response_spec=_spec(), invariants=[], factors=parse_factors([_factor()]),
        adapter_guard=guard,
    )

    assert outcomes[1].status == "failed"
    assert "constant_fields" in outcomes[1].error


def test_stale_row_failure_does_not_stop_the_sweep(tmp_path):
    """One stale row is lost; the rows around it are measured normally."""
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen")
    runner = _Scripted([
        {"throughput": 10.0, "slope": 0.01},
        {"throughput": 10.0, "slope": 0.01},   # stale
        {"throughput": 30.0, "slope": 0.05},
    ])

    outcomes = execute_design(
        [_row(0, {"L1": "off"}), _row(1, {"L1": "on"}), _row(2, {"L1": "off"})],
        runner=runner, response_spec=_spec(), invariants=[],
        factors=parse_factors([_factor()]), adapter_guard=guard,
    )

    assert [o.status for o in outcomes] == ["complete", "failed", "complete"]


def test_stale_echo_from_a_real_target_fails_the_row(tmp_path):
    """End to end through a real subprocess that echoes a constant.

    The adapter here is the degenerate form of defect 1: a script that prints
    the same metrics object no matter what flags it is handed, which is
    indistinguishable from one re-reading a metrics file it never overwrote.
    """
    script = _mutable_target(tmp_path, {"throughput": 5.0, "slope": 0.02})
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen")

    outcomes = execute_design(
        [_row(0, {"L1": "off"}), _row(1, {"L1": "on"})],
        runner=_real_runner(tmp_path, script), response_spec=_spec(),
        invariants=[], factors=parse_factors([_factor()]), adapter_guard=guard,
    )

    assert [o.status for o in outcomes] == ["complete", "failed"]
    assert "BYTE-IDENTICAL" in outcomes[1].error


# ═══ GUARD 3: the declared self-check ═════════════════════════════════════

_SELF_CHECK = [{"metric": "backlog_slope", "op": "<=", "value": 0.060}]


def test_self_check_violation_fails_only_its_own_row(tmp_path):
    """DEFECT 2: the reported optimum must satisfy the predicate that defines it.

    ``max_sustained_rate = 2.1562`` alongside ``backlog_slope = 0.1234`` against
    a growing threshold of 0.060 is a row asserting a rate was sustained while
    its own diagnostic says it was growing. 8 of 12 real rows had this shape. The
    other rows must be unaffected -- a self-check failure is a ROW failure, not a
    campaign abort.
    """
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen",
                         self_check=_SELF_CHECK)
    runner = _Scripted([
        {"throughput": 1.9000, "backlog_slope": 0.0100},   # honest
        {"throughput": 2.1562, "backlog_slope": 0.1234},   # self-contradictory
        {"throughput": 1.7500, "backlog_slope": 0.0200},   # honest
    ])

    outcomes = execute_design(
        [_row(0, {"L1": "off"}), _row(1, {"L1": "on"}), _row(2, {"L1": "off"})],
        runner=runner, response_spec=_spec(self_check=_SELF_CHECK),
        invariants=[], factors=parse_factors([_factor()]), adapter_guard=guard,
    )

    assert [o.status for o in outcomes] == ["complete", "failed", "complete"]
    err = outcomes[1].error
    assert "response.self_check violated" in err
    assert "backlog_slope" in err and "0.1234" in err
    assert "excluded from the fit" in err


def test_self_check_verdicts_recorded_on_passing_rows_too(tmp_path):
    """"Record enough to adjudicate a flag, not just to raise it" (guide §7.7).

    A reader of a passing row must be able to tell "the invariant held" from "no
    invariant was declared", and a reader of a failed row needs the observed
    value the predicate compared -- not merely that something failed.
    """
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen",
                         self_check=_SELF_CHECK)
    runner = _Scripted([{"throughput": 1.9, "backlog_slope": 0.01}])

    outcomes = execute_design(
        [_row(0, {"L1": "off"})], runner=runner,
        response_spec=_spec(self_check=_SELF_CHECK), invariants=[],
        factors=parse_factors([_factor()]), adapter_guard=guard,
    )

    verdicts = outcomes[0].self_check
    assert len(verdicts) == 1
    assert verdicts[0]["ok"] is True
    assert verdicts[0]["kind"] == "self_check"
    assert verdicts[0]["id"] == "backlog_slope"
    assert "0.01" in verdicts[0]["detail"]


def test_self_check_over_a_missing_diagnostic_fails_the_row(tmp_path):
    """An invariant the adapter does not report cannot pass.

    Same fail-closed rule ``predicates.evaluate`` applies everywhere else: a
    check that "the target did not emit it" is not a check that passed, and an
    objective whose defining diagnostic is unreported cannot be certified.
    """
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen",
                         self_check=_SELF_CHECK)
    runner = _Scripted([{"throughput": 1.9}])

    outcomes = execute_design(
        [_row(0, {"L1": "off"})], runner=runner,
        response_spec=_spec(self_check=_SELF_CHECK), invariants=[],
        factors=parse_factors([_factor()]), adapter_guard=guard,
    )

    assert outcomes[0].status == "failed"
    assert "not present in the observation" in outcomes[0].error


def test_no_self_check_declared_behaves_exactly_as_today(tmp_path):
    """A campaign declaring none is unaffected: every row complete, no verdicts."""
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen")
    runner = _Scripted([
        {"throughput": 2.1562, "backlog_slope": 0.1234},
        {"throughput": 1.9000, "backlog_slope": 0.0100},
    ])

    outcomes = execute_design(
        [_row(0, {"L1": "off"}), _row(1, {"L1": "on"})], runner=runner,
        response_spec=_spec(), invariants=[], factors=parse_factors([_factor()]),
        adapter_guard=guard,
    )

    assert [o.status for o in outcomes] == ["complete", "complete"]
    assert all(o.self_check == [] for o in outcomes)


def test_self_check_is_evaluated_on_a_real_target(tmp_path):
    """End to end: a shell-script adapter emitting a self-contradictory row."""
    script = _mutable_target(
        tmp_path, {"throughput": 2.1562, "backlog_slope": 0.1234},
    )
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen",
                         self_check=_SELF_CHECK)

    outcomes = execute_design(
        [_row(0, {"L1": "off"})], runner=_real_runner(tmp_path, script),
        response_spec=_spec(self_check=_SELF_CHECK), invariants=[],
        factors=parse_factors([_factor()]), adapter_guard=guard,
    )

    assert outcomes[0].status == "failed"
    assert "response.self_check violated" in outcomes[0].error


# ═══ interaction between the guards ══════════════════════════════════════

def test_contract_drift_beats_a_stale_or_self_check_verdict(tmp_path):
    """Drift is checked first: a key that moved may be the key a check reads."""
    work_dir = tmp_path / "wd"
    guard = AdapterGuard(work_dir, epoch=1, stage="screen",
                         self_check=_SELF_CHECK)
    runner = _Scripted([
        {"throughput": 1.9, "backlog_slope": 0.01},
        {"throughput": 1.9, "backlog_slope": None},   # both stale-ish AND drifted
    ])

    execute_design([_row(0, {"L1": "off"})], runner=runner,
                   response_spec=_spec(self_check=_SELF_CHECK), invariants=[],
                   factors=parse_factors([_factor()]), adapter_guard=guard)
    with pytest.raises(ac.AdapterContractDrift):
        execute_design([_row(1, {"L1": "on"})], runner=runner,
                       response_spec=_spec(self_check=_SELF_CHECK),
                       invariants=[], factors=parse_factors([_factor()]),
                       adapter_guard=guard)


# ═══ the fingerprint itself ══════════════════════════════════════════════

@pytest.mark.parametrize("value,expected", [
    (None, "null"), (True, "bool"), (3, "int"), (3.0, "float"),
    ("x", "str"), ({"a": 1, "b": 2}, "object{a:int,b:int}"), ([1, 2], "array[int]"),
])
def test_fingerprint_names_each_type_distinctly(value, expected):
    assert ac.fingerprint({"k": value}) == {"k": expected}


def test_fingerprint_ignores_values_and_key_order():
    """Values change every row; the contract must not depend on them.

    Nor on dict insertion order -- a re-serialization that reordered keys would
    otherwise read as drift.
    """
    a = ac.fingerprint({"x": 1.0, "y": "a", "z": {"p": 1}})
    b = ac.fingerprint({"z": {"p": 99}, "y": "zzz", "x": 12345.678})
    assert a == b
    assert ac.contract_hash({"keys": a}) == ac.contract_hash({"keys": b})


def test_nested_key_set_is_part_of_the_contract():
    """A nested block losing a key is drift: predicates address dotted paths."""
    before = {"keys": ac.fingerprint({"tel": {"a": 1, "b": 2}})}
    added, removed, changed = ac.diff_contract(before, {"tel": {"a": 1}})
    assert not added and not removed
    assert changed == ["tel: object{a:int,b:int} -> object{a:int}"]
