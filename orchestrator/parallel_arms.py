"""Parallel-arm execution orchestration (issue #123, Phase A).

After DESIGN produces ``experiment_plan.yaml``, EXECUTE_ANALYZE today
runs every (arm × seed × condition) tuple sequentially in one Sonnet
session. That mega-session is what produced the 5/18 connection-drop
incidents and is the proximate cause of the "race two executors" bug
that #71/#111 partly fixed at the symptom level.

The fix: partition the plan into independent units, fan them out to
per-unit subagents (each in its own worktree via #133), wait for all,
and run the existing deterministic merge into findings.json +
principle_updates.json.

Phase A scope:

  * partition_plan(plan) — turn experiment_plan.yaml into a flat list
    of ArmUnit descriptors.
  * run_units(units, *, runner, max_parallel) — fan out via an injected
    runner callable, collect ArmUnitResult records (one per unit).
  * merge_unit_results(results, plan) — deterministic merge into a
    findings-shaped dict (the schema validation step is reused from
    the existing executor pipeline).

Phase B, as it actually landed:

  * SDKDispatcher integration: ``worktree.make_isolated_arm_runner`` builds
    an ``ArmRunner`` that dispatches ``isolation="worktree"`` per unit.
  * ``run_units``'s ``max_parallel`` is a REAL bound -- a bounded
    ``ThreadPoolExecutor`` with positional result slots, not the
    ``anyio.gather`` this docstring used to promise. Threads because the
    module is synchronous throughout and a unit blocks on a subprocess or an
    SDK call; see ``run_units`` for why concurrency is safe over arm units
    but is NOT safe over an optimization campaign's design rows.

Still outstanding:

  * Wire-up into iteration.py so EXECUTE_ANALYZE picks parallel mode
    when ``max_parallel_arms > 1``. Until that lands, ``run_units`` has no
    production caller -- every caller today is a test.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from orchestrator.arm_sweep import SweepSpec


@dataclass(frozen=True)
class ArmUnit:
    """A single (arm, seed, condition) work item."""

    arm_id: str
    seed: str
    condition_name: str
    command: str

    @property
    def relative_results_dir(self) -> str:
        """Where this unit's results land — never overlaps with another unit."""
        return f"results/{self.arm_id}/{self.seed}"


@dataclass
class ArmUnitResult:
    unit: ArmUnit
    status: str  # "complete" | "failed"
    duration_ms: int = 0
    output_files: list[str] = field(default_factory=list)
    error: str = ""


def partition_plan(plan: dict) -> list[ArmUnit]:
    """Turn an experiment_plan.yaml-shaped dict into a list of ArmUnits.

    Each (arm × condition) becomes one unit. Seed defaults to ``"seed-1"``
    when the condition doesn't carry an explicit seed list; multi-seed
    conditions fan out to one unit per seed.

    Arms with a ``sweep`` block are excluded — they're partitioned via
    ``extract_sweep_specs`` and run by ``orchestrator.arm_sweep.run_sweep``
    instead of the fixed-condition runner. Issue #165.
    """
    units: list[ArmUnit] = []
    for arm in plan.get("arms", []) or []:
        if not isinstance(arm, dict):
            continue
        if arm.get("sweep") is not None:
            continue  # handled by extract_sweep_specs
        arm_id = str(arm.get("arm_id") or arm.get("type") or "?")
        for cond in arm.get("conditions", []) or []:
            if not isinstance(cond, dict):
                continue
            command = str(cond.get("command") or cond.get("cmd") or "")
            if not command:
                continue
            cond_name = str(cond.get("name") or cond.get("id") or "default")
            seeds = cond.get("seeds") or [cond.get("seed") or "seed-1"]
            if not isinstance(seeds, list):
                seeds = [str(seeds)]
            for s in seeds:
                units.append(ArmUnit(
                    arm_id=arm_id,
                    seed=str(s),
                    condition_name=cond_name,
                    command=command,
                ))
    return units


ArmRunner = Callable[[ArmUnit], ArmUnitResult]
"""Callable that executes one ArmUnit and returns its result.

The default real-world implementation spawns an SDK subagent with
``isolation="worktree"`` and the planned command. Tests inject a
deterministic fake.
"""


def run_units(
    units: list[ArmUnit],
    *,
    runner: ArmRunner,
    max_parallel: int | None = None,
) -> list[ArmUnitResult]:
    """Fan out units to the runner; returns results in ``units`` order.

    ``max_parallel`` is a CEILING on simultaneous in-flight ``runner`` calls.
    ``None`` (the default) and ``1`` both mean the strictly sequential loop
    this function has always been -- concurrency is opt-in, never a silent
    default -- and a value above 1 genuinely runs that many units at once.

    IT USED TO BE A FALSE PROMISE, which is why this docstring is explicit.
    The parameter was validated (``< 1`` raised) and then ignored: the body was
    a plain ``for`` loop, so a caller asking for 8 got serial execution with no
    signal that it had. That is worse than an unimplemented feature -- an
    unimplemented feature announces itself, whereas a bound silently downgraded
    to 1 looks exactly like a slow machine. The bound is now enforced rather
    than documented.

    WHY CONCURRENCY IS SAFE HERE, unlike at an optimization campaign's spending
    stages. ``orchestrator.optimize.runner.execute_design`` keeps its own bound
    at 1 for every fitting state because co-scheduled rows contend, and
    contention distributed unevenly across a design matrix is absorbed by the
    fitted coefficients as though it were a factor effect. An ``ArmUnit`` is not
    a design point: units are ISOLATED BY CONSTRUCTION -- each gets its own git
    worktree (``worktree.make_isolated_arm_runner`` dispatches with
    ``isolation="worktree"``) and its own non-overlapping results directory
    (``ArmUnit.relative_results_dir``) -- and nothing downstream fits a response
    surface over them. ``merge_unit_results`` reduces per-unit statuses; it
    estimates no coefficient that a neighbour effect could contaminate.

    A THREAD pool, not ``anyio``: this module is synchronous throughout and its
    unit of work blocks on a subprocess or an SDK subagent call, so a worker
    holds the GIL only to start the child and to shape the result. Processes
    would buy nothing and would break the injected-callable seam the module is
    built on -- a test's in-process fake runner is not picklable.

    POSITIONAL ORDER IS PART OF THE CONTRACT, not an incidental property of the
    sequential loop this used to be. ``merge_unit_results`` pairs each result
    with its own ``unit``, so a list appended to by completing workers would
    mis-attribute every seed and condition SILENTLY rather than raising.
    Results are therefore written into a pre-sized slot per input position and
    never appended from a worker -- the same discipline, and for the same
    reason, as ``execute_design``'s positional slots.

    A runner that raises still becomes that unit's ``failed`` result, in its own
    position, without disturbing its neighbours: one bad arm must not take down
    the batch.
    """
    if max_parallel is not None and max_parallel < 1:
        raise ValueError(
            f"max_parallel must be >= 1, got {max_parallel!r}: a bound below "
            f"one is not a schedule, it is a stall.",
        )

    def _one(unit: ArmUnit) -> ArmUnitResult:
        try:
            return runner(unit)
        except Exception as exc:  # runner exceptions become failed units
            return ArmUnitResult(
                unit=unit,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )

    if max_parallel is None or max_parallel == 1 or len(units) < 2:
        return [_one(unit) for unit in units]

    from concurrent.futures import ThreadPoolExecutor

    results: list[ArmUnitResult | None] = [None] * len(units)
    # Sized to the SMALLER of the bound and the batch: spawning threads that
    # can never be fed is noise in a thread dump.
    with ThreadPoolExecutor(max_workers=min(max_parallel, len(units))) as pool:
        # Every unit is submitted BEFORE any result is collected -- that is what
        # makes them concurrent. Results are then collected in SUBMISSION order,
        # which is harmless (a completed future does not block) and is what puts
        # each outcome in its own slot regardless of when it finished.
        futures = {pool.submit(_one, unit): i for i, unit in enumerate(units)}
        for future, i in futures.items():
            # `_one` converts a raising runner into a `failed` result itself, so
            # a future raising HERE is a defect in this module rather than a bad
            # arm -- let it propagate rather than fabricating a result row.
            results[i] = future.result()

    # Every slot filled: a None here would mean a submitted unit produced no
    # result, which `merge_unit_results` would silently under-count.
    missing = [i for i, r in enumerate(results) if r is None]
    if missing:  # pragma: no cover - defensive; the loop above is total
        raise RuntimeError(
            f"run_units: unit(s) at position(s) {missing} produced no result "
            f"under max_parallel={max_parallel}. Positional pairing downstream "
            f"(merge_unit_results reads each result's own unit) would be "
            f"silently wrong, so this aborts instead.",
        )
    return [r for r in results if r is not None]


def default_max_parallel() -> int:
    """Issue default: ``min(CPU, 4)``."""
    cpus = os.cpu_count() or 1
    return max(1, min(cpus, 4))


def merge_unit_results(
    results: list[ArmUnitResult],
    *,
    plan: dict | None = None,
) -> dict:
    """Deterministic merge of unit results into a findings-shaped dict.

    Output keys (sorted):
      - ``arms``: list of ``{arm_id, status, units}`` rows
      - ``failed_unit_count``: int
      - ``total_unit_count``: int

    No timestamps, no random ordering. Calling twice on the same input
    must produce byte-equal output.
    """
    by_arm: dict[str, list[ArmUnitResult]] = {}
    for r in results:
        by_arm.setdefault(r.unit.arm_id, []).append(r)

    arms_out: list[dict] = []
    for arm_id in sorted(by_arm):
        arm_results = by_arm[arm_id]
        # Arm status: complete only when every unit completed; otherwise
        # failed. Granular per-unit status is preserved in `units`.
        any_failed = any(r.status == "failed" for r in arm_results)
        arms_out.append({
            "arm_id": arm_id,
            "status": "failed" if any_failed else "complete",
            "units": [
                {
                    "seed": r.unit.seed,
                    "condition": r.unit.condition_name,
                    "status": r.status,
                    "duration_ms": r.duration_ms,
                    "output_files": sorted(r.output_files),
                    "error": r.error,
                }
                for r in sorted(
                    arm_results,
                    key=lambda x: (x.unit.seed, x.unit.condition_name),
                )
            ],
        })

    failed_count = sum(1 for r in results if r.status == "failed")
    return {
        "arms": arms_out,
        "failed_unit_count": failed_count,
        "total_unit_count": len(results),
    }


def failed_units(results: list[ArmUnitResult]) -> list[ArmUnit]:
    """Helper for the partial-retry path: which units need re-running?"""
    return [r.unit for r in results if r.status == "failed"]


def extract_sweep_specs(plan: dict) -> list[tuple[str, SweepSpec]]:
    """Pull adaptive-sweep specs out of an experiment_plan.yaml-shaped dict.

    Returns a list of ``(arm_id, SweepSpec)`` pairs — one per arm that
    declares a ``sweep`` block. Arms without ``sweep`` are skipped here
    and instead become ``ArmUnit`` rows via ``partition_plan``. The two
    functions cooperate: their union covers every arm in the plan, and
    they never emit the same arm twice.

    SweepSpec validation runs at construction time (see arm_sweep.py).
    A ``sweep`` block with malformed numeric fields raises ValueError
    here at extraction time — that's the cross-field check JSON Schema
    can't express.
    """
    specs: list[tuple[str, SweepSpec]] = []
    for arm in plan.get("arms", []) or []:
        if not isinstance(arm, dict):
            continue
        sweep = arm.get("sweep")
        if not isinstance(sweep, dict):
            continue
        arm_id = str(arm.get("arm_id") or arm.get("type") or "?")
        spec = SweepSpec(
            param=str(sweep["param"]),
            low=float(sweep["low"]),
            high=float(sweep["high"]),
            budget=int(sweep["budget"]),
            direction=str(sweep.get("direction", "minimize")),
            sampler_name=str(sweep.get("sampler_name", "tpe")),
        )
        specs.append((arm_id, spec))
    return specs
