"""Three linked instrumentation defects that cost a real 14-hour campaign.

A ``kind: optimization`` field test ran for ~14 hours and produced nothing
usable, and the diagnosis was crippled by the artifacts rather than helped by
them. This file is the oracle for the three fixes, and for one thing that turned
out not to be broken.

  * **D1 — ``duration_ms`` was structurally always 0.** The field was declared
    on ``RunOutcome`` with a default of 0 and assigned at NONE of the nine
    construction sites, so ``stage_runner._run_row`` faithfully wrote 0 for
    every row of every campaign while staying schema-valid. All 18 rows of the
    field test recorded ``duration_ms: 0``, so sizing ``run_timeout_sec`` from
    the campaign's own data was impossible — and a mis-sized ceiling is what
    killed the epoch. A field that exists, validates, and is always zero is
    WORSE than an absent one: it reads as "measured, instantaneous".

    The defect's nature — *assigned nowhere*, not *assigned wrongly* — dictates
    the test shape. A test exercising one representative path would have passed
    the day a later refactor dropped the assignment from the other eight, so
    ``test_every_outcome_path_records_a_positive_duration`` drives EVERY status
    the taxonomy can produce and asserts on all of them, and
    ``test_no_run_outcome_construction_site_omits_the_instrumentation`` reads the
    source to assert the count of construction sites that carry it.

  * **D2 — a failed row's cause was not machine-readable.** ``error`` itself was
    populated and written (see
    ``test_the_error_text_was_already_reaching_the_row``, which documents that
    the brief's stronger claim was wrong) — but a timeout and a crashed adapter
    BOTH arrived as ``RuntimeError: config run ...``, so telling apart "the
    apparatus ran out of time" (a budget question about the design) from "the
    adapter crashed" (a defect that recurs on every row reaching that branch)
    meant substring-matching prose the raise site is free to reword. The fix is
    ``failure_kind``, a closed vocabulary set AT the raise site.

  * **D3 — ``--smoke`` / ``--liveness`` could not size the ceiling.** Guide §7.1
    already told authors to size ``run_timeout_sec`` from the design's SLOWEST
    corner; the author of that section then sized it from the cheap corner three
    campaigns running. Prose advice demonstrably does not hold. ``--liveness``
    already runs every declared level once, so the per-level wall clock was
    being observed by the OS and discarded; now it is reported and checked.

NO LIVE LLM CALLS, and no mocks of the seam under test: the "target" is a real
Python or shell script in ``tmp_path`` that sleeps, crashes, or echoes its own
configuration back. That choice is load-bearing for D1 in particular — a
duration assertion against an in-process fake proves only that arithmetic
happened, while a script that sleeps 1.2s proves a real clock was read.

Determinism: every duration assertion is a ONE-SIDED bound against a generous
margin (a row that slept 1.2s is asserted ``>= 900ms``, never ``== 1200``), and
every property test iterates a FIXED table rather than sampling. ``hypothesis``
is not installed in this environment; the property tests below are exhaustive
over their (small, closed) domains instead, which for a closed vocabulary and a
monotone predicate is a strictly stronger check than sampling would be.
"""
from __future__ import annotations

import json
import re
import stat
from pathlib import Path

import jsonschema
import pytest

from orchestrator.optimize import runner as runner_mod
from orchestrator.optimize.matrix import ConfigRow
from orchestrator.optimize.stage_runner import _run_row

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROW_SCHEMA = json.loads(
    (REPO_ROOT / "orchestrator" / "schemas" / "runs_row.schema.json").read_text(),
)
RUNNER_SRC = (
    REPO_ROOT / "orchestrator" / "optimize" / "runner.py"
).read_text()


# ────────────────────────────── fixtures ──────────────────────────────────────
#
# Real executables, not fakes. Proving a duration was MEASURED means proving a
# clock was read across a process that really took time.


def _sleepy(tmp_path: Path, seconds: float, name: str = "sleepy") -> Path:
    """A target that takes a known, real amount of wall clock then succeeds."""
    p = tmp_path / f"{name}.sh"
    p.write_text(
        "#!/bin/sh\n"
        f"sleep {seconds}\n"
        "printf '{\"applied\": {}, \"m\": 1.0}\\n'\n",
    )
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


def _crasher(tmp_path: Path, seconds: float = 0.2) -> Path:
    """A target that burns real time and THEN exits non-zero.

    The delay is the point: an ``exit_nonzero`` row must record the time it
    consumed, because a design full of them still spends a schedule.
    """
    p = tmp_path / "crasher.sh"
    p.write_text(
        "#!/bin/sh\n"
        f"sleep {seconds}\n"
        "printf 'panic: runtime error: index out of range\\n' >&2\n"
        "exit 2\n",
    )
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


def _garbler(tmp_path: Path) -> Path:
    """A target that exits 0 and emits nothing parseable."""
    p = tmp_path / "garbler.sh"
    p.write_text("#!/bin/sh\nprintf 'Usage: bench [opts]\\n'\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


def _row(index: int = 0, levels: dict | None = None) -> ConfigRow:
    return ConfigRow(
        row_index=index, levels=dict(levels or {"A": 1}), role="corner",
        replicate=0, apply={},
    )


def _execute(runner, *, response_spec=None, invariants=None, factors=None,
             integrity_check=None, max_retries=0, row=None):
    """One row through the real ``_execute_row``, no scheduling in the way."""
    return runner_mod._execute_row(
        row if row is not None else _row(),
        runner=runner,
        response_spec=response_spec or {"primary": {"metric": "m"}},
        invariants=list(invariants or []), factors=factors or [],
        integrity_check=integrity_check, max_retries=max_retries,
    )


def _subprocess_runner(tmp_path: Path, script: Path, *, timeout: int):
    return runner_mod.make_config_runner(
        f"sh {script}", cwd=tmp_path, metric_path="m", timeout=timeout,
        log_dir=tmp_path / "failed_runs",
    )


# ══════════════════════ D1: duration_ms is really measured ════════════════════


def test_a_timed_out_row_records_the_time_it_consumed_and_names_the_timeout(
    tmp_path: Path,
):
    """THE REGRESSION TEST FOR THE FIELD-TEST FAILURE, readable from the row alone.

    The real campaign lost rows 9, 13 and 17 to ``TimeoutExpired`` after 1800s
    each. ``runs.jsonl`` recorded ``duration_ms: 0`` and a cause a reader had to
    substring-match; the two ``TimeoutExpired``s and one ``ValueError`` traceback
    lived only in ``runs/iter-N/failed_runs/failed_run_{9,13,17}.log`` — sibling
    files the primary artifact never points at.

    So the assertion is deliberately made against the ROW DICT, the thing
    ``runs.jsonl`` holds, and nothing else: no log file is opened, and no
    ``RunOutcome`` attribute is consulted that the row does not carry. Both
    halves of the answer must be there — how long it took, and that the ceiling
    is what stopped it — because either alone is unactionable. A cause with no
    duration cannot size the next ceiling; a duration with no cause cannot
    distinguish a slow target from a small budget.
    """
    script = _sleepy(tmp_path, 3, name="too_slow")
    outcome = _execute(_subprocess_runner(tmp_path, script, timeout=1))
    row = _run_row(_row(), outcome)

    assert row["status"] == "failed"
    # (a) The elapsed time, which is the number that sizes the next ceiling.
    assert row["duration_ms"] >= 900, (
        f"a row that spent ~1s hitting a 1s ceiling recorded "
        f"{row['duration_ms']}ms; the whole defect was this reading 0"
    )
    # (b) A machine-readable cause, with no prose parsing and no log file.
    assert row["failure_kind"] == "timeout", row
    # (c) The human-readable cause survives alongside it.
    assert "timed out" in row["error"].lower(), row["error"]
    # And the row is a legal runs.jsonl line while carrying all of it.
    jsonschema.validate(row, RUNS_ROW_SCHEMA)


def test_a_timed_out_rows_duration_is_at_least_the_ceiling_it_hit(
    tmp_path: Path,
):
    """The property that makes the field usable for sizing a ceiling.

    A row killed by an N-second ceiling must record at least ~N seconds. If it
    recorded less, the number would UNDER-report how much schedule the row
    consumed, and an author reading it would size the next ceiling too low —
    reproducing the original failure with instrumentation in place, which is the
    worst outcome of the three.

    ``>= 0.9 * ceiling`` rather than ``>= ceiling`` because ``subprocess``'s own
    timeout accounting and process teardown are not required to be exact, and a
    test that demands exactness here would be flaky rather than strict.
    """
    for ceiling in (1, 2):
        script = _sleepy(tmp_path, ceiling + 3, name=f"slow_{ceiling}")
        outcome = _execute(_subprocess_runner(tmp_path, script, timeout=ceiling))
        assert outcome.status == "failed"
        assert outcome.duration_ms >= int(ceiling * 900), (
            f"ceiling={ceiling}s produced duration_ms={outcome.duration_ms}"
        )


def test_a_successful_rows_duration_tracks_the_real_wall_clock(tmp_path: Path):
    """A one-sided sanity bound in the other direction: it is not a constant.

    Two targets differing by a real second must produce durations differing by
    about a second. Without this, an implementation that hardcoded ``1`` at
    every site would satisfy every "> 0" assertion in this file.
    """
    fast = _execute(_subprocess_runner(tmp_path, _sleepy(tmp_path, 0.1, "fast"),
                                       timeout=30))
    slow = _execute(_subprocess_runner(tmp_path, _sleepy(tmp_path, 1.3, "slow"),
                                       timeout=30))
    assert fast.status == slow.status == "complete"
    assert slow.duration_ms - fast.duration_ms >= 700, (
        f"fast={fast.duration_ms}ms slow={slow.duration_ms}ms — a duration that "
        f"does not move with real elapsed time is not a measurement"
    )


def _all_status_paths(tmp_path: Path):
    """One scenario per distinct exit path of ``_execute_row``.

    Nine ``RunOutcome`` construction sites, and this table is what makes a
    mutation at ANY of them fail a test rather than only a mutation at the one a
    single happy-path test happened to visit. Each entry is
    ``(name, kwargs-for-_execute, expected_status, expected_failure_kind)``.
    """
    ok = {"applied": {"A": "1"}, "m": 5.0}

    def _factor(fid="A", value="1"):
        from orchestrator.optimize.factors import parse_factors
        return parse_factors([{
            "id": fid, "name": fid.lower(), "type": "choice",
            "levels": ["1", "2"], "apply": f"--{fid}={{level}}",
            "manipulation": {"observable": f"applied.{fid}", "op": "==",
                             "value": value},
            "relations": [{"id": "R", "kind": "correctness", "statement": "s",
                           "native_test": "t.py::test_x"}],
        }])

    return [
        # 1. complete, no adapter guard armed.
        ("complete", {"runner": lambda r: dict(ok)}, "complete", ""),
        # 2. complete, adapter guard armed (a separate construction site).
        ("complete_guarded", {
            "runner": lambda r: dict(ok),
            "_guard": runner_mod.AdapterGuard(tmp_path / "gd", epoch=1,
                                              stage="screen", capture=False),
        }, "complete", ""),
        # 3. runner raised: a real subprocess that exits non-zero.
        ("exit_nonzero", {
            "runner": _subprocess_runner(tmp_path, _crasher(tmp_path), timeout=30),
        }, "failed", "exit_nonzero"),
        # 4. runner raised: a real subprocess that emits garbage.
        ("unparseable", {
            "runner": _subprocess_runner(tmp_path, _garbler(tmp_path), timeout=30),
        }, "failed", "unparseable_output"),
        # 5. runner raised: an in-process adapter exception (the field test's
        #    third lost row was `ValueError: 0.0 is not in list`).
        ("adapter_exception", {
            "runner": lambda r: (_ for _ in ()).throw(
                ValueError("0.0 is not in list"),
            ),
        }, "failed", "adapter_exception"),
        # 6. manipulation predicate never engaged, retries exhausted.
        ("manipulation_failed", {
            "runner": lambda r: {"applied": {"A": "9"}, "m": 1.0},
            "factors": _factor("A", "1"), "max_retries": 1,
        }, "failed", "manipulation_failed"),
        # 7. design_space invariant violated.
        ("invariant_violated", {
            "runner": lambda r: dict(ok),
            "invariants": [{"id": "I1", "metric": "m", "op": "<", "value": 1.0}],
        }, "rejected", "invariant_violated"),
        # 8. integrity_command said no.
        ("integrity_failed", {
            "runner": lambda r: dict(ok),
            "integrity_check": lambda r: (False, "integrity said no"),
        }, "rejected", "integrity_failed"),
        # 9. response.ceiling exceeded.
        ("ceiling_exceeded", {
            "runner": lambda r: dict(ok),
            "response_spec": {"primary": {"metric": "m"},
                              "ceiling": {"metric": "m", "op": "<",
                                          "value": 1.0}},
        }, "rejected", "ceiling_exceeded"),
        # 10. response.constraints violated -> infeasible.
        ("constraint_violated", {
            "runner": lambda r: dict(ok),
            "response_spec": {"primary": {"metric": "m"},
                              "constraints": [{"metric": "m", "op": "<",
                                               "value": 1.0}]},
        }, "infeasible", "constraint_violated"),
    ]


def _drive(kwargs: dict):
    """Run one ``_all_status_paths`` entry, honouring its ``_guard`` if present.

    Factored out so every consumer of the table exercises the SAME set of exit
    paths. An earlier draft popped ``_guard`` and discarded it in two of the
    three, which silently collapsed the ``complete_guarded`` scenario onto the
    unguarded one — so the guarded ``RunOutcome`` construction site (a distinct
    site, one of the nine) was covered by only one test. Mutation testing found
    that gap; this helper closes it.
    """
    kwargs = dict(kwargs)
    guard = kwargs.pop("_guard", None)
    if guard is None:
        return _execute(**kwargs)
    return runner_mod._execute_row(
        _row(), runner=kwargs["runner"],
        response_spec=kwargs.get("response_spec") or {"primary": {"metric": "m"}},
        invariants=list(kwargs.get("invariants") or []),
        factors=kwargs.get("factors") or [],
        integrity_check=kwargs.get("integrity_check"),
        max_retries=kwargs.get("max_retries", 0),
        adapter_guard=guard,
    )


def test_every_outcome_path_records_a_positive_duration(tmp_path: Path):
    """PROPERTY: no path that RAN can produce ``duration_ms == 0``.

    This is the test the original defect needed and did not have. Its shape is
    dictated by the defect's nature: ``duration_ms`` was never assigned at ANY
    of nine construction sites, so a test that exercised one path would have
    stayed green through a mutation at the other eight. Every status the failure
    taxonomy can produce is driven here, and every one is asserted.

    ``> 0`` rather than ``>= 0``: 0 is RESERVED for "did not run" (see
    ``runner._elapsed_ms``). That reservation is what keeps the original defect
    detectable forever — a 0 meaning "measured, instantaneous" is
    indistinguishable from a 0 meaning "never assigned", which is exactly how 18
    schema-valid rows hid a total instrumentation failure.
    """
    for name, kwargs, want_status, _kind in _all_status_paths(tmp_path):
        outcome = _drive(kwargs)
        assert outcome.status == want_status, (name, outcome.status)
        assert outcome.duration_ms > 0, (
            f"path {name!r} produced duration_ms={outcome.duration_ms}; every "
            f"path that invoked the runner must record real elapsed time, and 0 "
            f"is reserved for a row that never ran"
        )
        assert outcome.last_attempt_ms > 0, (name, outcome.last_attempt_ms)
        assert outcome.attempts >= 1, (name, outcome.attempts)


def test_every_outcome_path_lands_a_positive_duration_in_the_row(
    tmp_path: Path,
):
    """The same property one layer out, at the artifact ``runs.jsonl`` holds.

    ``_run_row`` is a separate function in a separate module from
    ``_execute_row``, and the original defect spanned both: the runner never
    assigned the field and the writer faithfully wrote ``int(outcome.duration_ms
    or 0)``. A property asserted only on the dataclass would not have noticed a
    writer that dropped the key, so it is asserted on the dict too — and the dict
    is validated against the schema, so a row cannot carry these fields by being
    illegal.
    """
    for name, kwargs, _status, want_kind in _all_status_paths(tmp_path):
        outcome = _drive(kwargs)
        row = _run_row(_row(), outcome)
        jsonschema.validate(row, RUNS_ROW_SCHEMA)
        assert row["duration_ms"] > 0, (name, row)
        assert row["failure_kind"] == want_kind, (name, row["failure_kind"])


def test_no_run_outcome_construction_site_omits_the_instrumentation():
    """A SOURCE-LEVEL guard, and the one place this file reads code not behaviour.

    Justified by the defect's exact nature. ``duration_ms`` was not computed
    wrongly — it was never passed, at nine similar-looking call sites, and it
    stayed that way through review because a missing keyword argument among nine
    long argument lists is invisible. A behavioural test catches a site that is
    both reachable and covered; this catches a site that is neither.

    The invariant asserted is narrow on purpose: every ``RunOutcome(`` in
    ``_execute_row`` spreads ``**_instr(...)``, the single helper that assembles
    all four instrumentation fields. Adding a tenth exit path that forgets it
    fails here immediately, at the moment the path is written, rather than after
    a campaign records zeros.
    """
    body = RUNNER_SRC.split("def _execute_row(", 1)[1]
    body = body.split("\ndef ", 1)[0]
    sites = body.count("RunOutcome(")
    instrumented = len(re.findall(r"\*\*_instr\(", body))
    assert sites == 9, (
        f"_execute_row has {sites} RunOutcome construction sites, not the 9 this "
        f"guard was written against — re-check that each new one is instrumented, "
        f"then update this count deliberately"
    )
    assert instrumented == sites, (
        f"{sites} construction sites but only {instrumented} carry **_instr(...); "
        f"a RunOutcome built without it records duration_ms=0, which is the "
        f"original defect"
    )


def test_duration_is_derived_from_a_monotonic_clock_so_it_cannot_be_negative():
    """PROPERTY: a duration is never negative, whatever the wall clock does.

    ``time.time()`` can step backwards (NTP correction, a DST transition) and a
    long benchmark run is exactly long enough to be crossed by one. A negative
    duration would be silently absurd rather than loudly wrong. The guarantee
    comes from reading ``time.monotonic``, which the source is asserted to use;
    the floor in ``_elapsed_ms`` is asserted behaviourally right below.
    """
    seam = RUNNER_SRC.split("def _run_once(", 1)[1].split("\ndef _elapsed_ms", 1)[0]
    assert "time.monotonic()" in seam, (
        "the timing seam must read a monotonic clock; time.time() can step "
        "backwards mid-run and produce a negative duration"
    )
    assert "time.time()" not in seam, seam


@pytest.mark.parametrize("fake_delta", [-5.0, -0.001, 0.0, 0.0004, 1.5])
def test_elapsed_ms_never_returns_a_negative_or_zero_for_a_run(
    monkeypatch, fake_delta,
):
    """Exhaustive over the interesting sign/magnitude cases, fixed table.

    Includes the impossible negatives deliberately: if the clock source is ever
    changed to one that can go backwards, ``_elapsed_ms`` still refuses to emit a
    number that would read as "finished before it started" — the floor is
    belt-and-braces with the monotonic clock, not a substitute for it.

    (``hypothesis`` is unavailable in this environment; this table is exhaustive
    over the equivalence classes that matter — below zero, at zero, sub-
    millisecond, and ordinary — rather than a sample.)
    """
    times = iter([100.0, 100.0 + fake_delta])
    monkeypatch.setattr(runner_mod.time, "monotonic", lambda: next(times))
    started = runner_mod.time.monotonic()
    assert runner_mod._elapsed_ms(started) >= 1


def test_a_retried_rows_duration_is_the_total_across_attempts(tmp_path: Path):
    """RETRY SEMANTICS, asserted rather than left to a reader's assumption.

    A manipulation-predicate failure retries the row, so a row can invoke the
    target more than once. ``duration_ms`` is the TOTAL across attempts because
    the question it answers is "how much schedule did this row consume", and a
    retried row really did occupy both slots — that total is what a timeout
    budget must cover. But the per-invocation ceiling applies per ATTEMPT, so the
    two readings differ and both are recorded: ``last_attempt_ms`` is the figure
    to compare against ``run_timeout_sec``, and ``attempts`` is what tells a
    reader which reading is which.

    Recording only the total would make a 2-attempt row indistinguishable from a
    target that got twice as slow — and an author would then raise a ceiling that
    was never the constraint.
    """
    from orchestrator.optimize.factors import parse_factors

    factors = parse_factors([{
        "id": "A", "name": "a", "type": "choice", "levels": ["1", "2"],
        "apply": "--A={level}",
        # Demands applied.A == "1"; the target below always reports "9".
        "manipulation": {"observable": "applied.A", "op": "==", "value": "1"},
        "relations": [{"id": "R", "kind": "correctness", "statement": "s",
                       "native_test": "t.py::test_x"}],
    }])
    calls: list[float] = []

    def never_engages(row):
        import time as _t
        calls.append(_t.monotonic())
        _t.sleep(0.4)
        return {"applied": {"A": "9"}, "m": 1.0}

    outcome = _execute(never_engages, factors=factors, max_retries=1)

    assert outcome.status == "failed"
    assert outcome.failure_kind == "manipulation_failed"
    assert len(calls) == 2, f"expected 2 attempts, the runner saw {len(calls)}"
    assert outcome.attempts == 2, outcome.attempts
    # Total covers both ~0.4s attempts; the last attempt covers only one.
    assert outcome.duration_ms >= 700, outcome.duration_ms
    assert 300 <= outcome.last_attempt_ms < outcome.duration_ms, (
        outcome.last_attempt_ms, outcome.duration_ms,
    )
    row = _run_row(_row(), outcome)
    assert row["attempts"] == 2 and row["last_attempt_ms"] > 0, row
    jsonschema.validate(row, RUNS_ROW_SCHEMA)


def test_the_row_carries_attempts_and_last_attempt_on_every_path(
    tmp_path: Path,
):
    """A SECOND, independent catcher for the retry-provenance pair.

    Mutation testing found that blanking ``attempts`` / ``last_attempt_ms`` in
    ``_run_row`` was caught by exactly ONE test — the retry test, the only one
    that produces ``attempts > 1``. One catcher for an invariant is thin: delete
    or skip that test and the pair silently reverts to constants, which is the
    same failure shape as the original ``duration_ms`` defect (a field present,
    valid, and meaningless).

    This asserts the weaker but path-COMPLETE claim instead: on every exit path,
    both fields reach the row, are positive, and are internally consistent with
    ``duration_ms``. It cannot see a mutation that hardcodes ``attempts = 1``
    where 1 is correct — that is what the retry test is for — but it does see the
    pair being dropped, zeroed, or omitted from the writer.
    """
    for name, kwargs, _status, _kind in _all_status_paths(tmp_path):
        row = _run_row(_row(), _drive(kwargs))
        assert row["attempts"] >= 1, (name, row)
        assert row["last_attempt_ms"] > 0, (
            f"path {name!r} wrote last_attempt_ms={row['last_attempt_ms']}; the "
            f"per-invocation figure is what a run_timeout_sec ceiling applies to"
        )
        assert row["last_attempt_ms"] <= row["duration_ms"], (name, row)
        if row["attempts"] == 1:
            assert row["last_attempt_ms"] == row["duration_ms"], (name, row)


def test_an_unretried_rows_total_equals_its_last_attempt(tmp_path: Path):
    """The degenerate case of the same semantics, so the contract is complete."""
    outcome = _execute(_subprocess_runner(
        tmp_path, _sleepy(tmp_path, 0.2, "one_shot"), timeout=30,
    ))
    assert outcome.attempts == 1
    assert outcome.duration_ms == outcome.last_attempt_ms > 0


def test_a_real_sweep_writes_no_zero_duration_row(tmp_path: Path):
    """End-to-end through ``execute_design``, the seam a stage actually calls.

    ``_execute_row`` is private; ``execute_design`` is what ``stage_runner``
    invokes, and it is where ``on_row`` fires and rows reach ``runs.jsonl``. A mix
    of fast, slow and crashing rows goes through it, and the assertion is that
    the FILE contains no zero — which is the exact statement that was false of
    all 18 rows of the field test.
    """
    good = _subprocess_runner(tmp_path, _sleepy(tmp_path, 0.15, "g"), timeout=30)
    bad = _subprocess_runner(tmp_path, _crasher(tmp_path), timeout=30)
    rows = [_row(i, {"A": i}) for i in range(4)]

    def mixed(row):
        return (bad if row.row_index % 2 else good)(row)

    written: list[dict] = []
    outcomes = runner_mod.execute_design(
        rows, runner=mixed,
        response_spec={"primary": {"metric": "m", "direction": "maximize"}},
        invariants=[], factors=[],
        on_row=lambda o: written.append(_run_row(rows[o.row_index], o)),
    )

    assert len(outcomes) == len(written) == 4
    jsonl = tmp_path / "runs.jsonl"
    jsonl.write_text("".join(json.dumps(r, sort_keys=True) + "\n"
                             for r in written))
    on_disk = [json.loads(x) for x in jsonl.read_text().splitlines()]
    for r in on_disk:
        jsonschema.validate(r, RUNS_ROW_SCHEMA)
    assert all(r["duration_ms"] > 0 for r in on_disk), on_disk
    # And the two kinds of row remain distinguishable from the file alone.
    kinds = {r["row_index"]: r["failure_kind"] for r in on_disk}
    assert kinds == {0: "", 1: "exit_nonzero", 2: "", 3: "exit_nonzero"}, kinds


# ══════════════ D2: the cause is machine-readable, not prose ══════════════════


def test_the_error_text_was_already_reaching_the_row(tmp_path: Path):
    """DOCUMENTS A CLAIM IN THE BRIEF THAT WAS WRONG, so it stays wrong-proof.

    The brief asserted that ``reason``/``error`` was null on failed rows and that
    the cause existed only in ``failed_runs/*.log``. It is not: ``_run_once``
    formats ``f"{type(exc).__name__}: {exc}"``, ``_execute_row`` passes it as
    ``error=``, and ``_run_row`` writes ``outcome.error or ""`` — all three since
    the original feature commits (``c343ccc``, ``5972283``), verified by
    ``git log -S``. There is also no ``reason`` key in a runs row at all.

    The real residual gap was narrower and is what ``failure_kind`` closes: the
    text was there but not switchable-on. This test pins the part that already
    worked so a future refactor of the new field cannot quietly regress it.
    """
    outcome = _execute(_subprocess_runner(tmp_path, _crasher(tmp_path),
                                          timeout=30))
    row = _run_row(_row(), outcome)
    assert row["error"], "the human-readable cause must not be empty"
    assert "exited 2" in row["error"], row["error"]
    assert "reason" not in row, "a runs row has no `reason` key; `error` is it"


def test_every_non_complete_path_carries_a_non_empty_cause(tmp_path: Path):
    """PROPERTY: a row that is not ``complete`` always says why, twice over.

    Once in prose (``error``, for a human) and once as a label (``failure_kind``,
    for a tool). Neither substitutes for the other: prose cannot be switched on
    without parsing, and a label cannot carry the ceiling that was exceeded or
    the stderr tail.
    """
    for name, kwargs, status, want_kind in _all_status_paths(tmp_path):
        outcome = _drive(kwargs)
        if status == "complete":
            assert outcome.failure_kind == "" and outcome.error == "", name
            continue
        assert outcome.error.strip(), f"{name}: no human-readable cause"
        assert outcome.failure_kind == want_kind, (name, outcome.failure_kind)
        assert outcome.failure_kind in runner_mod.FAILURE_KINDS, name


def test_a_timeout_and_a_crash_are_distinguishable_without_opening_a_log(
    tmp_path: Path,
):
    """The exact discrimination the field test could not make.

    Two rows, both ``status: failed``, both with a ``RuntimeError``-shaped
    ``error`` string. One says the apparatus ran out of time — a BUDGET question,
    answered together with ``duration_ms``, whose repair is one integer in the
    campaign file. The other says the adapter crashed — a DEFECT that will recur
    on every row reaching that branch, whose repair is code. Choosing the wrong
    repair costs another campaign.

    Asserted on the row dicts, and asserted to be different, so an implementation
    that labelled both ``failed`` uniformly cannot pass.
    """
    timed_out = _run_row(_row(0), _execute(_subprocess_runner(
        tmp_path, _sleepy(tmp_path, 3, "slowpoke"), timeout=1,
    )))
    crashed = _run_row(_row(1), _execute(_subprocess_runner(
        tmp_path, _crasher(tmp_path), timeout=30,
    )))

    assert timed_out["status"] == crashed["status"] == "failed"
    assert timed_out["failure_kind"] == "timeout"
    assert crashed["failure_kind"] == "exit_nonzero"
    assert timed_out["failure_kind"] != crashed["failure_kind"]


def test_failure_kind_is_a_closed_vocabulary_the_schema_agrees_with():
    """PROPERTY, exhaustive: code and schema enumerate the SAME labels.

    A closed vocabulary is only worth switching on if it is actually closed, and
    a schema enum that drifts from the code is a second copy of the truth rather
    than a check on it — the failure mode ``check_policy`` exists to close for
    ``policy.json``. Both directions are asserted: a label the code can emit and
    the schema rejects would make a legitimate row unwritable, and a label the
    schema allows and the code never emits is dead vocabulary.
    """
    enum = set(RUNS_ROW_SCHEMA["properties"]["failure_kind"]["enum"])
    assert enum == runner_mod.FAILURE_KINDS | {""}, {
        "in schema only": sorted(enum - runner_mod.FAILURE_KINDS - {""}),
        "in code only": sorted(runner_mod.FAILURE_KINDS - enum),
    }


def test_an_unknown_exception_kind_falls_back_rather_than_escaping():
    """A ``kind`` outside the vocabulary must not reach the artifact.

    ``_run_once`` reads ``exc.kind`` off whatever the injected runner raised, and
    an injected runner is author-supplied code. A row carrying an unvetted label
    would break the enum contract the test above pins — so an unrecognised kind
    degrades to ``adapter_exception``, which is the honest label for "something
    outside this module went wrong".
    """
    class Weird(RuntimeError):
        kind = "not_a_real_kind"

    outcome = _execute(lambda r: (_ for _ in ()).throw(Weird("odd")))
    assert outcome.failure_kind == "adapter_exception", outcome.failure_kind
    jsonschema.validate(_run_row(_row(), outcome), RUNS_ROW_SCHEMA)


def test_a_real_runs_row_validates_against_its_own_schema(tmp_path: Path):
    """A gap in the EXISTING schema test, found while extending the schema.

    ``test_each_appended_row_validates_against_runs_row_schema`` validates
    HAND-WRITTEN dicts, so it never noticed that the schema — which is
    ``additionalProperties: false`` — had no entry for ``held_out``,
    ``manipulation`` or ``invariants``, all three of which ``_run_row`` has
    always written. Every real row on disk was therefore schema-INVALID, and
    nothing checked. This test closes that by validating a row produced by the
    real code path, which is the only version of the check that can catch the
    next omission.
    """
    outcome = _execute(_subprocess_runner(
        tmp_path, _sleepy(tmp_path, 0.1, "plain"), timeout=30,
    ))
    row = _run_row(_row(), outcome)
    jsonschema.validate(row, RUNS_ROW_SCHEMA)
    for key in ("held_out", "manipulation", "invariants", "self_check",
                "duration_ms", "attempts", "last_attempt_ms", "failure_kind"):
        assert key in row, f"_run_row stopped writing {key!r}"
        assert key in RUNS_ROW_SCHEMA["properties"], (
            f"{key!r} is written but absent from the schema, which is "
            f"additionalProperties: false — the row would be invalid"
        )


# ═══════════ D3: --smoke/--liveness can size the timeout ══════════════════════


def _timeout_campaign(tmp_path: Path, *, run_seconds: float,
                      timeout_sec: int | None, levels=("1", "2")) -> dict:
    """A campaign whose target takes a KNOWN amount of real wall clock.

    A real script, because the whole claim under test is "the sweep observes wall
    clock". The objective varies with the level so the liveness sweep's own
    dead-axis check does not fire and confuse the assertion.
    """
    target = tmp_path / "timed_target.py"
    target.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys, time\n"
        f"time.sleep({run_seconds!r})\n"
        "levels = {}\n"
        "for a in sys.argv[1:]:\n"
        "    if a.startswith('--') and '=' in a:\n"
        "        k, v = a[2:].split('=', 1)\n"
        "        levels[k] = v\n"
        "score = 100.0 + 50.0 * float(levels.get('A', 0))\n"
        "print(json.dumps({'applied': levels, 'm': score}))\n",
    )
    target.chmod(target.stat().st_mode | stat.S_IXUSR)
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    opt = {
        "response": {"primary": {"metric": "m", "direction": "maximize"}},
        "factors": [{
            "id": "A", "name": "a", "type": "numeric", "levels": list(levels),
            "apply": "--A={level}",
            "manipulation": {"observable": "applied.A", "op": "==",
                             "value": "{level}"},
            "relations": [{"id": "R_A", "kind": "correctness", "statement": "s",
                           "native_test": "t.py::test_present"}],
        }],
        "stages": ["verify", "screen", "confirm"],
        "design": {"screen": {"resolution": 3}, "confirm": {"replicates": 1}},
        "run_command": f"python3 {target}",
        "known_valid_baseline": {"A": levels[0]},
        "workload": {"seed_env": "NOUS_WORKLOAD_SEED"},
    }
    if timeout_sec is not None:
        opt["run_timeout_sec"] = timeout_sec
    return {
        "kind": "optimization", "run_id": "timing",
        "research_question": "q",
        "target_system": {"name": "T", "repo_path": str(repo)},
        "optimization": opt,
    }


def test_liveness_reports_the_observed_wall_clock_of_every_level(
    tmp_path: Path, capsys,
):
    """The number that was already being observed and thrown away.

    ``--liveness`` runs every declared level of every factor once. The wall clock
    of each of those runs is exactly the per-level cost data guide §7.1 tells an
    author to size ``run_timeout_sec`` from — and it was measured by the OS and
    discarded. Reporting it is the cheapest half of the fix, and it is worth
    having even on a campaign that PASSES the headroom check: an author who can
    read "level 2 took 40s" can reason about a corner that combines it with
    another costly level, and one who cannot read anything cannot.
    """
    from orchestrator.cli import _smoke_check_optimization

    # A target that takes a KNOWN, non-trivial amount of real time, so the
    # reported figures can be checked against it rather than merely checked for
    # being present. Mutation testing found the earlier version of this test to
    # be inadequate: it asserted only that some `N.Ns` pattern appeared, which
    # `0.0s` satisfies, so replacing the measured elapsed time with a hardcoded
    # 0.0 SURVIVED. A reported duration that is structurally zero is the D1
    # defect reappearing one layer out — the same "field present, always
    # meaningless" shape, in the output an author reads instead of in the row.
    run_seconds = 0.6
    campaign = _timeout_campaign(tmp_path, run_seconds=run_seconds,
                                 timeout_sec=600)
    issues = _smoke_check_optimization(campaign, liveness=True,
                                       liveness_repeats=2)
    out = capsys.readouterr().out
    assert issues == [], issues
    assert "observed wall clock" in out, out
    assert "run_timeout_sec ceiling: 600s" in out, out
    # Every level, plus the noise-floor repeats, appears with a duration.
    assert "A=" in out, out
    assert "noise floor" in out, out

    # Four runs (2 levels + 2 noise-floor repeats), and EVERY reported duration
    # must be at least the time the target really slept. Asserting on all of them
    # rather than "at least one" is what makes a hardcoded constant unreachable:
    # a lower bound below the real sleep would catch a zero but not a fabricated
    # 1.0, and a per-line bound catches both.
    # The table's lines are `    <label padded to 28>  <duration>s`, and a label
    # can contain spaces ("noise floor 1/2"), so the duration is matched by its
    # position at end of line rather than by counting whitespace-delimited words.
    table = out.split("observed wall clock", 1)[1]
    reported = [float(m) for m in re.findall(r"(\d+\.\d+)s\s*$", table, re.M)]
    assert len(reported) >= 4, (reported, out)
    assert all(v >= run_seconds * 0.8 for v in reported), (
        f"reported durations {reported} include one below the {run_seconds}s the "
        f"target actually slept — the figure is not the observed wall clock"
    )


def test_liveness_fails_when_the_ceiling_lacks_headroom_over_the_slowest_level(
    tmp_path: Path,
):
    """The machine check that replaces prose advice §7.1's own author violated.

    A FAILURE rather than a flag, unlike the dead-axis check beside it, and the
    asymmetry is deliberate. A small-but-real effect is a judgement only the
    author can make, so that check reports a number. Insufficient headroom is
    not a judgement: rows WILL die at the ceiling, and each one dies only after
    consuming the whole ceiling, which is how ~14 hours bought nothing.
    ``--smoke`` is also the last moment where the repair is free — before a
    policy hash exists, one integer in the campaign file.
    """
    from orchestrator.cli import _smoke_check_optimization

    # ~1.2s per run against a 2s ceiling: under 2x headroom.
    campaign = _timeout_campaign(tmp_path, run_seconds=1.2, timeout_sec=2)
    issues = _smoke_check_optimization(campaign, liveness=True,
                                       liveness_repeats=2)
    joined = " ".join(issues)
    assert issues, "a ceiling within 2x of the slowest observed level must FAIL"
    assert "run_timeout_sec" in joined, joined
    assert "headroom" in joined, joined


def test_the_headroom_finding_says_what_it_cannot_guarantee(tmp_path: Path):
    """The finding must not oversell the bound it rests on.

    A single level's runtime is a LOWER BOUND on the slowest full corner: the
    sweep varies ONE factor with the others at ``known_valid_baseline``, and a
    corner combines several factors' costly levels at once, with costs that can
    be superadditive. The real defect's slow corner was ``arc + sata_ssd +
    40GiB`` — three costly levels together, a configuration no one-factor-at-a-
    time sweep ever visits.

    So the message must say "lower bound" and must say run order is randomized
    (the slow corner can be row 1). A message that read like a certificate would
    invite an author to size the ceiling to exactly the reported maximum, which
    is the same mistake in a new place.
    """
    from orchestrator.cli import _smoke_check_optimization

    campaign = _timeout_campaign(tmp_path, run_seconds=1.2, timeout_sec=2)
    findings = _smoke_check_optimization(
        campaign, liveness=True, liveness_repeats=2,
    )
    joined = " ".join(findings)
    assert "LOWER BOUND" in joined, joined
    assert "superadditive" in joined.lower(), joined
    assert "randomized" in joined, joined

    # And the caveat must be ACCURATE PER CALLER, not one caveat pasted twice.
    # The probe ran a full corner (its first); the sweep ran one factor at a time
    # with the rest at baseline. Those are weak in different ways, and telling an
    # author "each run varies one factor" about the probe teaches them something
    # false about what was measured — worse than saying nothing.
    probe = [f for f in findings if "probe configuration" in f]
    sweep = [f for f in findings if "liveness run" in f]
    assert len(probe) == 1 and len(sweep) == 1, findings
    assert "FIRST corner" in probe[0], probe[0]
    assert "never runs a corner" in sweep[0], sweep[0]
    assert "never runs a corner" not in probe[0], probe[0]


def test_liveness_passes_when_the_ceiling_has_generous_headroom(tmp_path: Path):
    """No false positive: a well-sized ceiling draws no finding at all."""
    from orchestrator.cli import _smoke_check_optimization

    campaign = _timeout_campaign(tmp_path, run_seconds=0.2, timeout_sec=600)
    assert _smoke_check_optimization(
        campaign, liveness=True, liveness_repeats=2,
    ) == [], "a 600s ceiling over a 0.2s level must not be a finding"


@pytest.mark.parametrize("slowest,timeout,expected_problem", [
    # Exhaustive over the boundary and its neighbourhood, fixed table.
    (1.0, 1, True),     # no headroom at all
    (1.0, 2, False),    # exactly 2x -- the boundary is inclusive of passing
    (1.0, 3, False),
    (1.0, 600, False),
    (10.0, 19, True),   # just under 2x
    (10.0, 20, False),  # exactly 2x
    (10.0, 21, False),
    (0.0, 600, False),  # nothing observed -> nothing to say
    (5.0, 0, False),    # no ceiling resolved -> not this check's business
])
def test_the_headroom_verdict_at_and_around_the_boundary(
    slowest, timeout, expected_problem,
):
    """The verdict's exact boundary, pinned so a refactor cannot slide it."""
    from orchestrator.cli import _timeout_headroom_problem

    out = _timeout_headroom_problem(slowest, timeout, what="x")
    assert (out is not None) is expected_problem, (slowest, timeout, out)


def test_the_headroom_verdict_is_monotone_in_the_declared_timeout():
    """PROPERTY: raising the ceiling can never turn a PASS into a FAIL.

    Exhaustive over a fixed grid rather than sampled (``hypothesis`` is not
    installed), which for a monotone predicate over an ordered domain is the
    stronger check: every adjacent pair in the grid is verified, so a
    non-monotonicity anywhere between the endpoints is caught.

    Monotonicity is what makes the finding ACTIONABLE. The remedy the message
    prints is "raise ``run_timeout_sec``", and a check whose verdict could
    worsen under its own remedy would send an author in circles. It also rules
    out a whole class of implementation error at once — an inverted comparison,
    or a ratio computed the wrong way round, is non-monotone and fails here even
    if it happens to agree with the boundary table above at some point.
    """
    from orchestrator.cli import _timeout_headroom_problem

    for slowest in (0.5, 1.0, 3.7, 10.0, 100.0):
        verdicts = [
            _timeout_headroom_problem(slowest, t, what="x") is not None
            for t in range(1, 401)
        ]
        # Once it stops failing it must never fail again as the ceiling rises.
        for i in range(1, len(verdicts)):
            assert not (verdicts[i] and not verdicts[i - 1]), (
                f"slowest={slowest}: raising the ceiling from {i}s to {i + 1}s "
                f"turned a PASS into a FAIL — the check's own remedy would make "
                f"it worse"
            )


def test_the_smoke_probe_and_the_liveness_sweep_share_one_headroom_rule(
    tmp_path: Path,
):
    """One rule, two bodies of evidence — not two rules.

    The probe's single-corner check and the sweep's per-level check ask the same
    question of different data. Two implementations of the arithmetic would be
    free to disagree about how much headroom is enough, and an author meeting one
    number under ``--smoke`` and a different one under ``--liveness`` would
    reasonably conclude the tool is broken. Asserted by driving the SAME campaign
    both ways and requiring both to fail.
    """
    from orchestrator.cli import _smoke_check_optimization

    campaign = _timeout_campaign(tmp_path, run_seconds=1.2, timeout_sec=2)
    plain = " ".join(_smoke_check_optimization(campaign))
    swept = " ".join(_smoke_check_optimization(
        campaign, liveness=True, liveness_repeats=2,
    ))
    assert "headroom" in plain, plain
    assert "headroom" in swept, swept


def test_a_level_that_dies_at_the_ceiling_is_reported_but_does_not_set_the_bound(
    tmp_path: Path,
):
    """A failed run's duration is evidence, never the basis of the verdict.

    A run killed BY the ceiling has an elapsed time bounded by the ceiling, so
    feeding it into the headroom comparison would compare the ceiling against
    itself and report insufficient headroom on every campaign that has ever lost
    a run — including one whose level crashed in 0.2s, where the ceiling is
    irrelevant. That level already has its own hard failure, named. Its duration
    is still PRINTED, marked as not having completed, because a level that died
    at the ceiling is the strongest available evidence that the ceiling is the
    binding constraint.
    """
    from orchestrator.cli import _report_liveness_durations

    problems: list[str] = []
    _report_liveness_durations(
        [("noise floor 1/2", 0.2, True), ("A=2", 590.0, False)], 600, problems,
    )
    assert problems == [], (
        "a 590s FAILED run must not drive the headroom verdict; the 0.2s "
        "completed run has ample headroom"
    )


def test_a_liveness_sweep_with_no_runs_reports_nothing_and_claims_nothing():
    """Silence must never read as a passing verdict.

    A sweep that made no runs (an early return before any level was reached) has
    no evidence, so it must produce no finding AND no reassuring output.
    """
    from orchestrator.cli import _report_liveness_durations

    problems: list[str] = []
    _report_liveness_durations([], 600, problems)
    assert problems == []
