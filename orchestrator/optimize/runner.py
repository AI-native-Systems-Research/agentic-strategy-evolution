"""The tokenless per-config execution loop (spec Sec 6.1).

Per configuration: apply factor levels (already rendered onto ``ConfigRow``
by ``matrix.expand``) -> build (content-hash cached via ``build_cache_key``)
-> run -> parse response metrics -> check manipulation -> check
``design_space`` invariants -> check ``response.constraints`` -> check
``response.ceiling`` -> record. No model call anywhere in this module; that
absence is where the optimization campaign kind's cost advantage comes from.

Both the config runner and the (optional) integrity check arrive as
INJECTED CALLABLES, exactly like ``parallel_arms.run_units``'s ``runner``
parameter -- production wires them to real subprocess invocations, tests
inject fakes, and this module never imports ``subprocess`` itself. That
seam is what makes the loop testable at all.

The failure taxonomy is deliberately asymmetric (spec Sec 6.4):

  * a ``design_space`` invariant violation, or a response above
    ``response.ceiling``, is REJECTED -- the campaign left its declared
    design space, or the instrumentation is lying. Either way the data is
    untrustworthy and is excluded from the fitting inputs entirely.
  * a ``response.constraints`` violation is INFEASIBLE -- the config is
    genuinely inadmissible, but that IS real, trustworthy data about the
    space, so it is retained in the outcomes (just excluded from fitting).
  * a manipulation-predicate failure retries once (the lever may not have
    engaged for a transient reason); if it still fails, the row FAILS.
    Dropping the offending FACTOR (not the whole campaign) and refitting
    with recomputed aliasing is the caller's job, one level up.
  * the runner raising an exception FAILS that one row without aborting
    the rest of the sweep -- partial failure degrades the claim (reported
    resolution drops, dropped factors named); it never silently proceeds
    as if nothing happened.

``response.held_out`` metrics are removed from ``RunOutcome.response``
entirely at this observation boundary and surface only on the distinctly
named ``RunOutcome.held_out`` field -- a structural split, not a filtered
view, so passing ``response`` wholesale to a fitter is safe by default
(belt-and-braces with the schema validator elsewhere) rather than unsafe
by default.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from orchestrator.optimize.factors import Factor
from orchestrator.optimize.matrix import ConfigRow
from orchestrator.optimize.predicates import evaluate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunOutcome:
    """The outcome of running one design-matrix row.

    ``response`` and ``held_out`` are a STRUCTURAL split, not a filtered
    view: any metric named in ``response.held_out`` is removed from
    ``response`` entirely and appears only in ``held_out``. This makes
    ``response`` fitting-safe by construction -- passing it wholesale to a
    fitter is safe by default, rather than safe only if the caller
    remembers to reach for a particular sub-key. Reaching held-out data
    requires the deliberate, distinctly-named ``outcome.held_out`` access
    (e.g. for the confirm-stage generalization check), never an accident of
    passing ``response`` as a whole.

    ``manipulation`` and ``invariants`` are lists of plain-dict verdicts
    (``{"id":..., "ok":..., "detail":...}``) -- one entry per predicate
    checked, in declaration order, across every attempt (so a retry's
    verdicts are visible too).
    """

    row_index: int
    status: str  # "complete" | "failed" | "infeasible" | "rejected"
    response: dict
    manipulation: list
    invariants: list
    duration_ms: int = 0
    error: str = ""
    held_out: dict = field(default_factory=dict)


class ConfigRunner(Protocol):
    """Runs one config and returns its observation dict.

    Production wires this to a real subprocess invocation (build + run +
    parse). Tests inject a deterministic fake -- see ``_RecordingRunner``
    in ``tests/test_optimize_runner.py``. Never called directly by anything
    other than ``execute_design``; this module never shells out itself.
    """

    def __call__(self, row: ConfigRow) -> dict: ...


IntegrityCheck = Callable[[ConfigRow], "tuple[bool, str]"]
"""Optional third guardrail alongside manipulation and the ceiling check.

Production wires this to a subprocess invocation of
``optimization.integrity_command``; tests inject a fake. Returns
``(ok, detail)`` -- ``detail`` carries the command's stderr (or an
equivalent diagnostic) when ``ok`` is ``False``. ``execute_design`` never
calls ``subprocess`` itself; this callable is the only sanctioned seam.
"""


def build_cache_key(row: ConfigRow, *, patch_hash: str) -> str:
    """A stable cache key over a row's rendered levels plus the patch hash.

    Two rows with identical ``levels`` and the same ``patch_hash`` MUST
    produce the same key (repeated cells share a cached build); any change
    to either input MUST change the key -- a stale binary silently serving
    a different configuration would be a silent-wrong-data defect. Built
    from a canonical (sorted-keys, no-whitespace) JSON encoding of the
    levels so key equality does not depend on dict insertion order, then
    hashed with sha256 for a short, filesystem-safe, collision-resistant
    identifier. ``row_index`` is deliberately excluded: two rows that
    happen to declare the same levels (e.g. a replicate) are the same
    build and should share the cache entry.
    """
    canonical_levels = json.dumps(row.levels, sort_keys=True, separators=(",", ":"))
    digest_input = f"{canonical_levels}|{patch_hash}".encode("utf-8")
    return hashlib.sha256(digest_input).hexdigest()


def _verdict_dict(check_id: Any, verdict, *, kind: str) -> dict:
    return {"id": check_id, "kind": kind, "ok": verdict.ok, "detail": verdict.detail,
            "skipped": verdict.skipped, "missing": verdict.missing}


def _applied_namespace(row: ConfigRow) -> dict:
    """The rendered configuration, addressable as ``applied.<FACTOR_ID>``.

    Every worked example in the authoring guide writes manipulation
    predicates against ``config.*`` or ``telemetry.*`` — which silently
    assumes the target ECHOES ITS CONFIGURATION BACK in its output. Most
    targets do not: BLIS (inference-sim) emits metrics only, with no
    ``config`` block, so a predicate like
    ``{observable: config.routing_policy, op: "==", value: "{level}"}``
    fails on every run with "the target did not emit it" — and since
    ``manipulation`` is REQUIRED and must be non-trivial, that made the
    whole campaign kind unusable against such a target. Confirmed on a live
    run: 115 configurations executed, every one failed its manipulation
    check, zero usable measurements.

    So the rendered configuration is now always addressable. An author whose
    target reports its own state should still prefer that — it is strictly
    stronger evidence, since it confirms the flag was RECEIVED rather than
    merely SENT. But an author whose target reports nothing now has a
    truthful check available instead of an impossible one.

    ``applied_patches`` is the same idea for the ``config_patch`` kind, and it
    reports what was REALIZED rather than what was requested: each entry carries
    the ``materialized_path`` of the patched copy the run actually read. A
    file-configured target that echoes nothing back therefore still has a
    truthful manipulation check available, and a row that failed can say which
    configuration file it failed on.

    IT IS KEYED BY FACTOR ID, NOT A LIST, AND THAT IS LOAD-BEARING.
    ``predicates._resolve`` walks a dotted observable through DICTS only -- there
    is no list-index token in the vocabulary and no ``contains`` operator in
    ``OPS`` -- so a list-shaped ``applied_patches`` would be documented as
    addressable and be addressable by nothing: ``applied_patches.0.value``
    resolves to ``_MISSING`` and fails every row with "the target did not emit
    it". That is precisely the 115-configurations-all-failed shape this whole
    namespace was introduced to end, and it would have been worse here than
    before, because the design-gate pre-flight advisory
    (``stage_runner._preflight_design``) treats an ``applied_patches`` root as
    "this will exist at check time" and stays silent. Keyed by factor,
    ``applied_patches.<FACTOR_ID>.value`` resolves, which is the form the schema
    and the authoring guide document.
    """
    realized = (row.apply or {}).get("applied_patches") or {}
    return {
        "applied": dict(row.levels),
        "applied_args": list((row.apply or {}).get("cli_args") or []),
        "applied_env": dict((row.apply or {}).get("env") or {}),
        "applied_patches": dict(realized) if isinstance(realized, dict) else {},
    }


def _check_manipulation(factors: list[Factor], row: ConfigRow, observed: dict) -> list[dict]:
    """One manipulation verdict per factor whose level appears on this row.

    Predicates resolve against the target's observation merged with the
    rendered configuration (``applied.*``), so a target that does not echo
    its own config back can still be checked. Target-emitted keys win on
    collision: if the target DOES report a field, its value is the one that
    matters, since that is evidence the lever engaged rather than evidence
    it was requested.
    """
    scope = {**_applied_namespace(row), **observed}
    verdicts: list[dict] = []
    for f in factors:
        if f.id not in row.levels:
            continue
        level = row.levels[f.id]
        verdict = evaluate(f.manipulation, scope, level=level)
        verdicts.append(_verdict_dict(f.id, verdict, kind="manipulation"))
    return verdicts


def _manipulation_failed(verdicts: list[dict]) -> bool:
    return any((not v["ok"]) and not v["skipped"] for v in verdicts)


def _check_invariants(invariants: list[dict], observed: dict) -> list[dict]:
    """One invariant verdict per declared ``design_space.invariants`` entry.

    Uses ``predicates.evaluate`` directly (rather than
    ``matrix.check_invariants``, which only returns violation strings) so
    each verdict can be attributed to its own invariant id without
    resorting to substring-matching a rendered message back to an id --
    fragile when one invariant's id happens to be a substring of another's
    statement.
    """
    verdicts: list[dict] = []
    for inv in invariants:
        verdict = evaluate(inv, observed, level=None)
        verdicts.append(_verdict_dict(inv.get("id"), verdict, kind="invariant"))
    return verdicts


def _invariants_failed(verdicts: list[dict]) -> bool:
    return any((not v["ok"]) and not v["skipped"] for v in verdicts)


def _check_constraints(response_spec: dict, observed: dict) -> list[str]:
    """Names of every violated ``response.constraints`` entry."""
    violations: list[str] = []
    for constraint in response_spec.get("constraints") or []:
        verdict = evaluate(constraint, observed)
        if verdict.skipped:
            continue
        if not verdict.ok:
            metric = constraint.get("observable") or constraint.get("metric")
            violations.append(f"constraint {metric!r} violated: {verdict.detail}")
    return violations


def _check_ceiling(response_spec: dict, observed: dict) -> str | None:
    """Error string naming the ceiling if the observed metric exceeds it, else None.

    Physically impossible means the instrumentation is lying, never that a
    new record was set -- so this is a strict ``>`` check against
    ``response.ceiling.value``, not a constraint predicate with an
    author-chosen ``op``.
    """
    ceiling = response_spec.get("ceiling")
    if not ceiling:
        return None
    metric = ceiling.get("observable") or ceiling.get("metric")
    limit = ceiling.get("value")
    if metric is None or limit is None:
        return None
    if metric not in observed:
        return None
    observed_value = observed[metric]
    if observed_value > limit:
        return (
            f"response metric {metric!r} = {observed_value!r} exceeds the declared "
            f"ceiling {limit!r} -- physically impossible means the instrumentation "
            f"is lying, not that a new record was set"
        )
    return None


def _split_held_out(response_spec: dict, observed: dict) -> tuple[dict, dict]:
    """Partition ``observed`` into ``(response, held_out)`` -- a STRUCTURAL split.

    Any metric named in ``response.held_out`` is removed from the
    fitting-safe dict entirely, not merely omitted from a filtered
    sub-view alongside a copy that still contains it. This is the
    belt-and-braces guard against the ``holdout-selection`` leakage
    class: a held-out metric is recorded (in ``held_out``, so callers can
    still see it happened -- e.g. for the confirm-stage generalization
    check) but a caller who passes ``response`` wholesale to a fitter,
    which is the natural first-time idiom, cannot leak it by accident,
    because it is no longer there to leak.
    """
    held_out_keys = set(response_spec.get("held_out") or ())
    response = {k: v for k, v in observed.items() if k not in held_out_keys}
    held_out = {k: v for k, v in observed.items() if k in held_out_keys}
    return response, held_out


def _run_once(row: ConfigRow, runner: "ConfigRunner") -> tuple[dict | None, str]:
    """Call ``runner`` once; returns ``(observation, error)`` -- exactly one is truthy."""
    try:
        return runner(row), ""
    except Exception as exc:  # runner exceptions become failed rows, never abort the sweep
        return None, f"{type(exc).__name__}: {exc}"


def execute_design(
    rows: list[ConfigRow],
    *,
    runner: "ConfigRunner",
    response_spec: dict,
    invariants: list[dict],
    factors: list[Factor],
    on_row: Callable[[RunOutcome], None] | None = None,
    integrity_check: "IntegrityCheck | None" = None,
    max_retries: int = 1,
    max_parallel: int = 1,
) -> list[RunOutcome]:
    """Run every row through the tokenless loop; returns outcomes in row order.

    Order of checks per attempt, matching the spec's stated pipeline:
    run -> manipulation -> (on manipulation success) invariants -> ceiling
    -> constraints. A manipulation failure is retried up to ``max_retries``
    times before the row is marked ``failed``; every other check fires
    only on an attempt where manipulation held, since a config where the
    lever never engaged says nothing trustworthy about the design space.

    Never raises out of the loop for a single bad row -- see
    ``_run_once``. ``on_row`` fires exactly once per row, after its final
    status is known, so a caller can append to ``runs.jsonl`` incrementally
    without buffering every row in memory first.

    ``max_parallel`` is a CEILING on simultaneous in-flight ``runner`` calls,
    defaulting to 1, i.e. the strictly sequential loop this function has always
    been. It exists for one caller -- ``confirm`` -- and the reason it is not
    simply "parallelize the sweep" is statistical, so read the next three
    paragraphs before widening it.

    WHY CONCURRENCY IS NOT FREE HERE. Co-scheduled rows contend for machine
    resources, so a row's measured response comes to depend on WHICH OTHER ROWS
    happened to run beside it. At a spending stage that is a first-order
    confound: those stages fit a surface over DISTINCT configurations, and
    contention distributed unevenly across the design is absorbed by the fitted
    coefficients as though it were a factor effect. It is the same confound that
    run-order randomization exists to defuse (drift: a warming cache, a
    thermally throttling machine, a background job), but in a form randomization
    cannot average away -- a permutation spreads a TIME trend across the design;
    it does nothing about a NEIGHBOUR effect. For an objective that measures
    where a system saturates, this is the measurement, not noise around it.

    WHY A CONFIRM REPLICATE BLOCK IS DIFFERENT IN KIND. Within one block every
    finalist is measured exactly once, so whatever contention the block creates
    is symmetric across exactly the things being compared -- it shifts all the
    finalists together and cancels out of the finalist-to-finalist difference,
    which is the only quantity terminal discrimination reads. That is the same
    argument ``stage_runner._confirm_rows`` makes for putting its run-order
    shuffle INSIDE a block rather than across the whole matrix, and this
    function's bound is scoped to be its exact counterpart. Blocks stay a
    barrier (see below): every finalist is measured once before any is measured
    twice.

    Because the bound is per-block rather than global, this function does NOT
    decide which stages may use it -- the stage runner passes 1 at every
    spending stage. What this function guarantees is that a bound above 1 never
    dissolves the block structure and never reorders a result.

    POSITIONAL ORDER IS PART OF THE CONTRACT, not an incidental property of the
    sequential loop it used to be. ``stage_runner._finish_confirm`` appends each
    finalist's measurements in row order and ``certificate.terminal_regret_bound``
    ZIPS them, so position *i* must be replicate *i* for every finalist; a list
    returned in completion order would mispair the paired differences and
    produce a wrong bound rather than an error. Outcomes are therefore written
    into a pre-sized slot per input position, never appended from a completing
    worker.

    ``on_row`` still fires exactly once per row, and still from the CALLING
    thread rather than from a worker, so a callback appending to ``runs.jsonl``
    needs no locking of its own and cannot interleave a write -- the contract is
    unchanged. What a bound above 1 does change is what its ORDER *means*: rows
    within a block are all in flight together, so their order in ``runs.jsonl``
    records the order they were SUBMITTED, not a sequence in which each finished
    before the next began. That is one more reason the effective bound is
    recorded on the design matrix -- at ``max_parallel: 1`` the log is a
    sequence, above 1 it is a schedule, and nothing else in the artifact set
    tells the two apart.
    """
    if max_parallel < 1:
        raise ValueError(
            f"max_parallel must be >= 1, got {max_parallel!r}: a bound below one "
            f"is not a schedule, it is a stall.",
        )

    def _one(row: ConfigRow) -> RunOutcome:
        return _execute_row(
            row, runner=runner, response_spec=response_spec, invariants=invariants,
            factors=factors, integrity_check=integrity_check, max_retries=max_retries,
        )

    if max_parallel == 1 or len(rows) < 2:
        outcomes: list[RunOutcome] = []
        for row in rows:
            outcome = _one(row)
            outcomes.append(outcome)
            if on_row is not None:
                on_row(outcome)
        return outcomes

    from concurrent.futures import ThreadPoolExecutor

    # A THREAD pool, not a process pool: every unit of work here is a
    # subprocess invocation of the target (``make_config_runner`` shells out and
    # waits), so the worker holds the GIL only to start the child and to parse
    # its JSON. Processes would buy nothing and would break the injected-callable
    # seam this module is built on -- a test's in-process fake runner is not
    # picklable, and neither is a closure over the campaign.
    results: list[RunOutcome | None] = [None] * len(rows)

    # BLOCKS ARE A BARRIER. Rows are grouped by ``replicate`` and each group is
    # drained before the next is submitted, so replicate *i* of every finalist
    # completes before replicate *i+1* of any finalist starts. Keeping the pool
    # full across the boundary instead would let a late finalist's replicate 2
    # overlap an early finalist's replicate 3 -- which restores exactly the
    # asymmetric-neighbour confound the per-block scoping exists to exclude, and
    # would do it invisibly, since every row still ran.
    #
    # Grouping preserves first-appearance order and never sorts: at confirm the
    # rows arrive already emitted one complete block at a time, with the shuffle
    # inside each block, and re-sorting them would discard that shuffle.
    blocks: list[list[int]] = []
    seen: dict[Any, int] = {}
    for pos, row in enumerate(rows):
        key = getattr(row, "replicate", 0)
        if key not in seen:
            seen[key] = len(blocks)
            blocks.append([])
        blocks[seen[key]].append(pos)

    for positions in blocks:
        # The pool is sized to the SMALLER of the bound and the block's width:
        # a bound of 8 over a 3-finalist block must not spill into the next
        # block, and spawning threads that can never be fed is noise in a
        # thread dump.
        with ThreadPoolExecutor(
            max_workers=min(max_parallel, len(positions)),
        ) as pool:
            # Every row in the block is submitted BEFORE any result is
            # collected -- that is what makes them concurrent. Results are then
            # collected in SUBMISSION order, which is harmless (a completed
            # future does not block) and keeps `on_row`'s ordering close to the
            # execution sequence it records.
            futures = {
                pool.submit(_one, rows[pos]): pos for pos in positions
            }
            for future, pos in futures.items():
                # ``_execute_row`` converts a raising runner into a ``failed``
                # RunOutcome itself (``_run_once``), so a future raising here is
                # a defect in THIS module rather than a bad target -- let it
                # propagate rather than silently recording a fabricated row.
                outcome = future.result()
                results[pos] = outcome
                # Called from THIS thread, never from a worker, and therefore
                # never concurrently with itself -- so an `on_row` that appends
                # to `runs.jsonl` needs no lock and cannot interleave a write,
                # exactly as at the sequential seam. This is the reason results
                # are collected here rather than via `as_completed`: a callback
                # firing from N workers would make every consumer of this seam
                # responsible for its own locking.
                if on_row is not None:
                    on_row(outcome)

    # Every slot filled: a None here would mean a submitted row produced no
    # outcome, which would silently shorten the confirm pairing.
    missing = [i for i, o in enumerate(results) if o is None]
    if missing:  # pragma: no cover - defensive; the loop above is total
        raise RuntimeError(
            f"execute_design: rows at position(s) {missing} produced no outcome "
            f"under max_parallel={max_parallel}. Positional pairing downstream "
            f"(certificate.terminal_regret_bound zips finalist measurements) "
            f"would be silently wrong, so this aborts instead.",
        )
    return [o for o in results if o is not None]


def _execute_row(
    row: ConfigRow,
    *,
    runner: "ConfigRunner",
    response_spec: dict,
    invariants: list[dict],
    factors: list[Factor],
    integrity_check: "IntegrityCheck | None",
    max_retries: int,
) -> RunOutcome:
    all_manipulation: list[dict] = []
    observed: dict | None = None
    error = ""
    attempts = max(1, max_retries + 1)

    for attempt in range(attempts):
        observed, run_error = _run_once(row, runner)
        if observed is None:
            # Runner raised. Retrying a crashed build/run is not what
            # max_retries is for (that budget is reserved for manipulation
            # transients) -- fail the row immediately without burning the
            # remaining retry attempts on a build that will keep crashing.
            return RunOutcome(
                row_index=row.row_index, status="failed", response={},
                manipulation=all_manipulation, invariants=[], error=run_error,
            )

        manipulation = _check_manipulation(factors, row, observed)
        all_manipulation.extend(manipulation)
        if not _manipulation_failed(manipulation):
            break
        error = "manipulation predicate failed: " + "; ".join(
            v["detail"] for v in manipulation if (not v["ok"]) and not v["skipped"]
        )
        if attempt == attempts - 1:
            return RunOutcome(
                row_index=row.row_index, status="failed", response={},
                manipulation=all_manipulation, invariants=[], error=error,
            )
        # else: retry -- loop again for up to max_retries additional attempts.

    assert observed is not None  # loop only reaches here via `break` above

    # Structural split, computed once and reused on every remaining exit
    # path (including the rejected ones) so a held-out metric never
    # surfaces at the top level of `response` regardless of status.
    response, held_out = _split_held_out(response_spec, observed)

    invariant_verdicts = _check_invariants(invariants, observed)
    if _invariants_failed(invariant_verdicts):
        failed_detail = "; ".join(
            f"invariant {v['id']!r}: {v['detail']}"
            for v in invariant_verdicts if (not v["ok"]) and not v["skipped"]
        )
        return RunOutcome(
            row_index=row.row_index, status="rejected", response=response,
            manipulation=all_manipulation, invariants=invariant_verdicts,
            error=failed_detail, held_out=held_out,
        )

    if integrity_check is not None:
        integrity_ok, integrity_detail = integrity_check(row)
        if not integrity_ok:
            return RunOutcome(
                row_index=row.row_index, status="rejected", response=response,
                manipulation=all_manipulation, invariants=invariant_verdicts,
                error=integrity_detail or "integrity_command exited non-zero",
                held_out=held_out,
            )

    ceiling_error = _check_ceiling(response_spec, observed)
    if ceiling_error is not None:
        return RunOutcome(
            row_index=row.row_index, status="rejected", response=response,
            manipulation=all_manipulation, invariants=invariant_verdicts,
            error=ceiling_error, held_out=held_out,
        )

    constraint_violations = _check_constraints(response_spec, observed)
    if constraint_violations:
        return RunOutcome(
            row_index=row.row_index, status="infeasible", response=response,
            manipulation=all_manipulation, invariants=invariant_verdicts,
            error="; ".join(constraint_violations), held_out=held_out,
        )

    return RunOutcome(
        row_index=row.row_index, status="complete", response=response,
        manipulation=all_manipulation, invariants=invariant_verdicts, error="",
        held_out=held_out,
    )


def parse_test_results(payload: Any) -> dict[str, bool]:
    """Best-effort parse of a ``test_command`` result into ``relations.reconcile``'s input.

    ``relations.reconcile(factors, results)`` declares ``results:
    dict[str, bool]``; handed ``None`` (or anything else it cannot iterate
    as a mapping) it raises a bare ``TypeError`` from deep inside
    ``required_relations``' loop. That signature is correct for
    ``reconcile``'s contract -- but the realistic path into this module's
    territory is exactly the case it does not defend against: the target's
    ``test_command`` subprocess crashes, times out, or emits a truncated
    report before writing anything ``relations.parse_pytest_json_report``
    or ``relations.parse_junit_xml`` can read.

    This function is the guard: it tries the pytest-JSON-report shape,
    then the JUnit-XML shape, and on ``None``, a non-dict/non-str/non-bytes
    payload, or a parse failure in both shapes, returns ``{}`` -- an empty
    results mapping. Handed to ``reconcile``, an empty mapping makes every
    declared relation's ``native_test`` "not found in results", which is
    already ``reconcile``'s own "declared but not executed" failure
    semantics (never a pass). So a crashed test run fails closed through
    the existing, well-tested contract-violation path, and callers never
    see the opaque stdlib ``TypeError`` for what is, in practice, the most
    likely failure mode of the whole verify stage.
    """
    from orchestrator.optimize.relations import parse_junit_xml, parse_pytest_json_report

    if isinstance(payload, dict):
        try:
            return parse_pytest_json_report(payload)
        except ValueError:
            return {}
    if isinstance(payload, (str, bytes)):
        text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
        try:
            return parse_junit_xml(text)
        except ValueError:
            return {}
    return {}


# ── production wiring: the two callables run_stage needs ──────────────────
#
# These close the gap that made `kind: optimization` unusable end to end:
# `test_command` and the per-config benchmark were declared in the schema and
# documented in the guide, but nothing executed them, so `test_results` was
# always None, every relation reconciled as "declared but not executed", and
# every real campaign aborted at its verify stage.
#
# They live here rather than in stage_runner so the injected seam stays the
# contract: tests pass fakes, production passes these.

def run_test_command(
    command: str, *, cwd: Path, timeout: int = 900,
    log_path: Path | None = None,
) -> dict[str, bool]:
    """Execute a campaign's ``test_command`` and map native tests to verdicts.

    The target's own runner produces the verdict — Nous only checks the
    contract, so this needs no knowledge of Go, pytest, or any other
    ecosystem. It records a pass for each declared test the command reports
    as passing.

    Go's ``go test`` has no machine-readable report by default, so this
    prefers ``-json`` output when the command already asks for it and
    otherwise falls back to scanning per-test ``--- PASS/FAIL`` lines, which
    both ``go test -v`` and pytest's default output emit. On any failure to
    run at all, returns ``{}`` — which ``reconcile`` treats as "declared but
    not executed", i.e. fails closed rather than silently passing.

    ``log_path`` preserves the command's full stdout/stderr verbatim. The
    boolean verdicts are what the gate needs, but they are useless for *fixing*
    anything: a failed assertion's expected-vs-actual, a Go panic and its
    stack, a compile error naming a file and line, a timeout's partial output
    all live in the text and were previously discarded the moment the verdicts
    were parsed. Since a verify abort ends the campaign, that output is the
    only record of why — and re-running it by hand may not reproduce a
    timeout or an ordering-dependent failure.
    """
    import re
    import shlex
    import subprocess

    def _persist(stdout: str, stderr: str, note: str = "") -> None:
        if log_path is None:
            return
        try:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            body = (
                f"$ {command}\n"
                f"# cwd: {cwd}\n"
                + (f"# {note}\n" if note else "")
                + "\n--- stdout ---\n" + (stdout or "")
                + "\n--- stderr ---\n" + (stderr or "")
            )
            Path(log_path).write_text(body)
        except OSError as exc:  # never let logging break the gate
            logger.warning("could not write test log to %s: %s", log_path, exc)

    try:
        proc = subprocess.run(
            shlex.split(command), cwd=str(cwd), capture_output=True,
            text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        # A timeout still carries the partial output, and that is often the
        # most informative artifact of all (which test hung).
        _persist(
            exc.stdout if isinstance(exc.stdout, str) else "",
            exc.stderr if isinstance(exc.stderr, str) else "",
            note=f"TIMED OUT after {timeout}s",
        )
        logger.warning(
            "test_command timed out after %ss: every declared relation will "
            "reconcile as 'declared but not executed', which fails closed.%s",
            timeout,
            f" Partial output saved to {log_path}." if log_path else "",
        )
        return {}
    except OSError as exc:
        _persist("", str(exc), note="FAILED TO EXECUTE")
        logger.warning(
            "test_command failed to run (%s): every declared relation will "
            "reconcile as 'declared but not executed', which fails closed.",
            exc,
        )
        return {}

    _persist(proc.stdout or "", proc.stderr or "", note=f"exit={proc.returncode}")
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")

    # go test -json / pytest --json-report: try the structured shapes first.
    if '"Action"' in text or '"outcome"' in text:
        results: dict[str, bool] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = rec.get("Test") or rec.get("nodeid")
            action = rec.get("Action") or rec.get("outcome")
            if name and action in ("pass", "passed"):
                results[str(name)] = True
            elif name and action in ("fail", "failed"):
                results[str(name)] = False
        if results:
            return results

    # Fallback: per-test PASS/FAIL lines. `go test -v` emits
    # "--- PASS: TestName (0.00s)"; pytest -v emits "path::test PASSED".
    results = {}
    for m in re.finditer(r"---\s+(PASS|FAIL|SKIP):\s+(\S+)", text):
        results[m.group(2)] = m.group(1) == "PASS"
    for m in re.finditer(r"^(\S+::\S+)\s+(PASSED|FAILED|ERROR)", text, re.M):
        results[m.group(1)] = m.group(2) == "PASSED"

    if not results and proc.returncode == 0:
        # The command succeeded but emitted nothing per-test (e.g. `go test`
        # without -v prints only a package-level "ok"). A green exit is not
        # per-test evidence, and inventing one would defeat the whole point
        # of the correctness gate — so say so and fail closed.
        logger.warning(
            "test_command exited 0 but reported no per-test results. Add -v "
            "(go test) or --json-report (pytest) so individual native_test "
            "identifiers can be matched; a package-level 'ok' is not evidence "
            "that a specific relation's test ran.",
        )
    return results


def match_declared_tests(
    factors, results: dict[str, bool],
) -> dict[str, bool]:
    """Map each declared ``native_test`` onto a verdict from ``results``.

    A campaign declares ``native_test`` as a locator a human can act on —
    ``sim/scheduler_test.go::TestFCFSScheduler_PreservesOrder`` — while a
    test runner reports the bare function or node name. This bridges the two
    by matching on the trailing identifier after ``::``, so an author writes
    the useful form and the contract check still resolves.

    Only exact trailing-identifier matches count. An unmatched declaration
    is simply absent from the result, which ``reconcile`` treats as
    "declared but not executed" — the fail-closed path.
    """
    by_tail = {}
    # A parametrized test is reported once per case: pytest emits
    # `test_no_rebalancing[0.95-1.05]`, Go subtests emit `TestX/case_name`.
    # A declaration naming the bare function must match ALL of its cases, and
    # passes only when EVERY case passed — otherwise a suite with one failing
    # parametrization would reconcile as a pass on whichever case happened to
    # be seen last. Observed for real: a campaign whose 68 tests all passed
    # matched only 2 of 6 declared identifiers, because the other four were
    # parametrized; the four reconciled as "declared but not executed" and
    # fail-closed aborted a build that had in fact done everything asked.
    params: dict[str, list[bool]] = {}
    for name, passed in results.items():
        by_tail[name] = passed
        tail = name.rsplit("::", 1)[-1]
        by_tail.setdefault(tail, passed)
        # Strip a pytest parametrization suffix and/or a Go subtest path so the
        # bare function name aggregates every case.
        base = tail.split("[", 1)[0].split("/", 1)[0]
        if base != tail:
            params.setdefault(base, []).append(passed)
        by_tail.setdefault(base, passed)

    for base, verdicts in params.items():
        # all() so one failing case fails the relation.
        by_tail[base] = all(verdicts)

    matched: dict[str, bool] = {}
    for f in factors:
        for rel in getattr(f, "relations", ()) or ():
            declared = rel.get("native_test") if isinstance(rel, dict) else None
            if not declared:
                continue
            if declared in by_tail:
                matched[declared] = by_tail[declared]
                continue
            tail = declared.rsplit("::", 1)[-1]
            if tail in by_tail:
                matched[declared] = by_tail[tail]
                continue
            base = tail.split("[", 1)[0].split("/", 1)[0]
            if base in by_tail:
                matched[declared] = by_tail[base]
    return matched


def _dump_failed_run(
    log_dir: Path | None, row, cmd: list[str], cwd: Path,
    *, proc=None, exc: BaseException | None = None,
) -> Path | None:
    """Write a failed configuration's full output to ``log_dir``.

    A failed run is the single most diagnostic-hungry event in a campaign: it
    is what aborts a fit, and the reason is almost always in the text (a usage
    error naming the rejected flag, a panic and its stack, a partial run before
    a timeout). Truncating stderr to a couple of hundred characters loses
    exactly the part that names the cause, and nothing else preserves it.

    Returns the path written, or None when logging is unavailable — this is a
    diagnostics aid and must never be the reason a campaign fails.
    """
    if log_dir is None:
        return None
    try:
        d = Path(log_dir)
        d.mkdir(parents=True, exist_ok=True)
        idx = getattr(row, "row_index", None)
        name = f"failed_run_{idx if idx is not None else 'unknown'}.log"
        path = d / name
        levels = getattr(row, "levels", None)
        body = [
            f"$ {' '.join(cmd)}",
            f"# cwd: {cwd}",
            f"# row_index: {idx}",
            f"# levels: {dict(levels) if levels else '(unknown)'}",
        ]
        if exc is not None:
            body.append(f"# exception: {type(exc).__name__}: {exc}")
            for stream in ("stdout", "stderr"):
                val = getattr(exc, stream, None)
                if isinstance(val, str) and val:
                    body.append(f"\n--- {stream} (partial) ---\n{val}")
        if proc is not None:
            body.append(f"# exit: {proc.returncode}")
            body.append("\n--- stdout ---\n" + (proc.stdout or ""))
            body.append("\n--- stderr ---\n" + (proc.stderr or ""))
        path.write_text("\n".join(body))
        logger.warning("config run failed; full output saved to %s", path)
        return path
    except OSError as e:
        logger.warning("could not write failed-run log: %s", e)
        return None


@contextmanager
def _patch_scope(row, cmd: list[str], *, cwd: Path, log_dir: Path | None):
    """Materialize this row's ``config_patch`` patches; yield the rewritten command.

    Yields ``cmd`` UNCHANGED and does no filesystem work at all when the row
    declares no patches, which is every row of every ``cli_flag``/``env_var``
    campaign -- the common case pays nothing.

    The realized patches are recorded back onto ``row.apply["applied_patches"]``
    BEFORE the command runs, KEYED BY FACTOR ID, for the same reason
    ``applied_args`` and ``applied_env`` exist (``_applied_namespace``): a
    manipulation predicate resolves against them, and a row that failed still has
    to be able to say what configuration it failed on. The factor key is not
    cosmetic -- see ``_applied_namespace`` on why a list-shaped record would be
    addressable by no predicate at all. ``ConfigRow`` is frozen but its ``apply``
    dict is not, which is the same door ``_confirm_rows`` already uses to ride
    ``finalist`` along on ``apply``.

    THE COPIES ARE KEPT ONLY WHEN THE RUN FAILED, AND ARE NAMED BY ROW. A
    campaign's screen is 60-90 runs plus confirm replicates plus manipulation
    retries; keeping every success's copy left ~100 opaque UUID directories in
    the iteration dir that nothing mapped back to a row, which is storage without
    diagnostic value. So every copy is materialized into a scratch directory and
    only PROMOTED into ``log_dir/patched_configs/row-<index>/`` when the run
    raised -- the same rule and the same row-keyed naming ``_dump_failed_run``
    uses for stdout/stderr, and for the same reason: a failed row's exact
    configuration is what a campaign author needs, and a successful row's is
    reproducible from the pre-registered matrix.
    """
    from orchestrator.optimize import config_patch as cp

    patches = list((row.apply or {}).get("patches") or [])
    if not patches:
        yield cmd
        return

    scratch = tempfile.TemporaryDirectory(prefix="nous-config-patch-")
    promoted = False
    try:
        realized = cp.materialize_patches(
            patches, cwd=Path(cwd), temp_dir=Path(scratch.name),
        )
        rewritten = cp.rewrite_command(cmd, realized)
        # `delivered_command` closes the gap between "the copy was written
        # correctly" and "the copy is what ran". Those are two different claims,
        # and the original defect was precisely a campaign where the first was
        # vacuously true (nothing was written) and nothing checked the second.
        # `--smoke` reads it back; recorded once per row rather than once per
        # patch, since every patch of a row shares the one command.
        record = {
            str(entry.get("factor_id") or f"patch_{i}"): {
                k: v for k, v in entry.items() if k != "factor_id"
            }
            for i, entry in enumerate(realized)
        }
        for value in record.values():
            value["delivered_command"] = list(rewritten)
        if isinstance(row.apply, dict):
            row.apply["applied_patches"] = record
        try:
            yield rewritten
        except BaseException:
            promoted = _promote_patched_configs(log_dir, row, Path(scratch.name))
            raise
    finally:
        # Promotion MOVES the tree out of the scratch dir, so cleanup then has
        # nothing left to remove and the kept copies survive.
        if not promoted:
            scratch.cleanup()


def _promote_patched_configs(log_dir: Path | None, row, scratch: Path) -> bool:
    """Move a failed row's patched config copies under ``log_dir``, row-keyed.

    Returns whether the move happened, so the caller knows whether the scratch
    directory still needs cleaning. Never raises: like ``_dump_failed_run``, this
    is a diagnostics aid and must never be the reason a campaign fails -- the
    row has already failed for a real reason and that reason must be what
    propagates.
    """
    if log_dir is None:
        return False
    try:
        idx = getattr(row, "row_index", None)
        rep = getattr(row, "replicate", None)
        name = f"row-{idx if idx is not None else 'unknown'}"
        if rep:
            name += f"-rep{rep}"
        dest = Path(log_dir).parent / "patched_configs" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            # A retried row (manipulation transient) materializes a second time;
            # the latest attempt is the one whose configuration matters.
            shutil.rmtree(dest, ignore_errors=True)
        shutil.move(str(scratch), str(dest))
        logger.warning(
            "config run failed; the patched configuration it ran on is at %s",
            dest,
        )
        return True
    except OSError as e:
        logger.warning("could not preserve patched configs: %s", e)
        return False


DEFAULT_RUN_TIMEOUT_SEC = 600
"""Wall-clock ceiling on ONE ``run_command`` invocation when the campaign
declares no ``optimization.run_timeout_sec``.

600 is not a considered number -- it is the value this seam was hardcoded to
before the ceiling had an authoring surface at all. It stays the default
precisely because of that history: every campaign already on disk measured its
epoch under a 600-second ceiling, and a pre-registration whose measurement
ceiling silently moved underneath it would no longer describe the runs it
registered. A campaign whose single legitimate measurement is a COMPOUND one --
an objective evaluation that is itself a bisection or a sweep to saturation --
says so by declaring ``run_timeout_sec``, and ``stage_runner.resolve_run_timeout``
is the one place that resolution happens.
"""


def make_config_runner(
    command_template: str, *, cwd: Path, metric_path: str,
    timeout: int = DEFAULT_RUN_TIMEOUT_SEC, log_dir: Path | None = None,
) -> Callable:
    """Build the per-config benchmark callable ``run_stage`` requires.

    ``command_template`` is the target's run command; each factor's rendered
    ``apply`` arguments are appended. ``metric_path`` is a dotted path into
    the emitted JSON naming the response metric, so this stays agnostic to
    what the target measures.

    ``log_dir`` preserves the full stdout/stderr of any configuration that
    fails, keyed by row index. Without it, the only surviving trace of a
    failed run is a truncated stderr tail in an exception message.

    ``timeout`` is the wall-clock ceiling on ONE invocation, resolved from the
    campaign's ``optimization.run_timeout_sec`` by
    ``stage_runner.resolve_run_timeout`` and defaulting to
    ``DEFAULT_RUN_TIMEOUT_SEC``. It is a hard failure, never a budget: exceeding
    it raises out of the closure, so ``execute_design`` records a ``failed`` row
    carrying the timeout text and the fit proceeds on the complete-row subset
    (spec §4 D2). Nothing here ever returns a partial measurement, because a
    partial measurement of a compound objective is indistinguishable from a
    complete measurement of a different one.

    ``apply["patches"]`` (the rendered form of an ``apply.kind: config_patch``
    factor) is MATERIALIZED here, per run, into a patched copy of the author's
    config file, and every reference to the original path in the assembled
    command is rewritten to point at that copy. Before this existed the field
    was rendered onto every row and read by nothing, so a design whose factors
    were config-file knobs measured the target's BASELINE on every row while
    the pre-registered matrix and the fitted surface looked real -- the
    silent-wrong-result class. See ``orchestrator.optimize.config_patch`` for
    why the copy is per-run rather than an in-place edit-and-restore, and why a
    path the command never names is fatal rather than a no-op.
    """
    import shlex
    import subprocess

    def run(row) -> dict:
        cmd = shlex.split(command_template)
        for args in (row.apply or {}).get("cli_args", []) or []:
            cmd.append(args)
        env_extra = (row.apply or {}).get("env") or {}
        # The patched copies land next to the iteration's other run artifacts
        # when there is a log dir (so a campaign author debugging a row can read
        # the exact configuration it ran on), and in a scratch directory
        # otherwise. `_patch_scope` removes the scratch case afterwards; the
        # log-dir case is kept deliberately -- it is evidence.
        with _patch_scope(row, cmd, cwd=cwd, log_dir=log_dir) as cmd:
            return _run_command(row, cmd, cwd=cwd, env_extra=env_extra,
                                timeout=timeout, log_dir=log_dir)

    def _run_command(row, cmd, *, cwd, env_extra, timeout, log_dir):
        try:
            proc = subprocess.run(
                cmd, cwd=str(cwd), capture_output=True, text=True,
                timeout=timeout,
                env={**os.environ, **{k: str(v) for k, v in env_extra.items()}},
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            _dump_failed_run(log_dir, row, cmd, cwd, exc=exc)
            raise RuntimeError(f"config run failed: {exc}") from exc
        if proc.returncode != 0:
            path = _dump_failed_run(log_dir, row, cmd, cwd, proc=proc)
            raise RuntimeError(
                f"config run exited {proc.returncode}: "
                f"{(proc.stderr or '')[-400:]}"
                + (f" [full output: {path}]" if path else ""),
            )
        obs = _last_json_object(proc.stdout)
        if obs is None:
            # The command "succeeded" but produced nothing parseable. Without
            # the raw stdout there is no way to tell a silent usage error from
            # a changed output format, and this is the failure that NaN-poisons
            # a fit, so keep the text.
            path = _dump_failed_run(log_dir, row, cmd, cwd, proc=proc)
            raise RuntimeError(
                "config run emitted no parseable JSON object"
                + (f" [full output: {path}]" if path else ""),
            )
        return obs

    return run


def _last_json_object(text: str) -> dict | None:
    """The last complete JSON object in ``text``, decoded incrementally."""
    dec = json.JSONDecoder()
    blocks, idx = [], 0
    while True:
        nxt = text.find("{", idx)
        if nxt < 0:
            break
        try:
            obj, end = dec.raw_decode(text, nxt)
        except json.JSONDecodeError:
            idx = nxt + 1
            continue
        blocks.append(obj)
        idx = end
    return blocks[-1] if blocks else None
