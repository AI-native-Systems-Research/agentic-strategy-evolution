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

``response.held_out`` metrics are stripped from the fitting-inputs view at
this observation boundary (belt-and-braces with the schema validator
elsewhere) so a careless caller cannot leak held-out data into the fitter
even by accident.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from orchestrator.optimize.factors import Factor
from orchestrator.optimize.matrix import ConfigRow
from orchestrator.optimize.predicates import evaluate


@dataclass(frozen=True)
class RunOutcome:
    """The outcome of running one design-matrix row.

    ``response`` carries every metric the runner observed, PLUS a
    ``fitting_inputs`` sub-dict holding exactly the metrics safe to hand a
    fitter: the primary response, minus any ``response.held_out`` metric.
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


def _check_manipulation(factors: list[Factor], row: ConfigRow, observed: dict) -> list[dict]:
    """One manipulation verdict per factor whose level appears on this row."""
    verdicts: list[dict] = []
    for f in factors:
        if f.id not in row.levels:
            continue
        level = row.levels[f.id]
        verdict = evaluate(f.manipulation, observed, level=level)
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


def _fitting_inputs(response_spec: dict, observed: dict) -> dict:
    """Every observed metric EXCEPT any named in ``response.held_out``.

    Belt-and-braces with the schema validator elsewhere: a held-out metric
    is recorded (callers can still see it happened, e.g. for the confirm-
    stage generalization check) but never appears here, so a careless
    caller cannot leak it into ``fit_effects`` even by accident.
    """
    held_out = set(response_spec.get("held_out") or ())
    return {k: v for k, v in observed.items() if k not in held_out}


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
    """
    outcomes: list[RunOutcome] = []
    for row in rows:
        outcome = _execute_row(
            row, runner=runner, response_spec=response_spec, invariants=invariants,
            factors=factors, integrity_check=integrity_check, max_retries=max_retries,
        )
        outcomes.append(outcome)
        if on_row is not None:
            on_row(outcome)
    return outcomes


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

    invariant_verdicts = _check_invariants(invariants, observed)
    if _invariants_failed(invariant_verdicts):
        failed_detail = "; ".join(
            f"invariant {v['id']!r}: {v['detail']}"
            for v in invariant_verdicts if (not v["ok"]) and not v["skipped"]
        )
        return RunOutcome(
            row_index=row.row_index, status="rejected", response=dict(observed),
            manipulation=all_manipulation, invariants=invariant_verdicts,
            error=failed_detail,
        )

    if integrity_check is not None:
        integrity_ok, integrity_detail = integrity_check(row)
        if not integrity_ok:
            return RunOutcome(
                row_index=row.row_index, status="rejected", response=dict(observed),
                manipulation=all_manipulation, invariants=invariant_verdicts,
                error=integrity_detail or "integrity_command exited non-zero",
            )

    ceiling_error = _check_ceiling(response_spec, observed)
    if ceiling_error is not None:
        return RunOutcome(
            row_index=row.row_index, status="rejected", response=dict(observed),
            manipulation=all_manipulation, invariants=invariant_verdicts,
            error=ceiling_error,
        )

    response = dict(observed)
    response["fitting_inputs"] = _fitting_inputs(response_spec, observed)

    constraint_violations = _check_constraints(response_spec, observed)
    if constraint_violations:
        return RunOutcome(
            row_index=row.row_index, status="infeasible", response=response,
            manipulation=all_manipulation, invariants=invariant_verdicts,
            error="; ".join(constraint_violations),
        )

    return RunOutcome(
        row_index=row.row_index, status="complete", response=response,
        manipulation=all_manipulation, invariants=invariant_verdicts, error="",
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
