"""Progress, the repeated-failure circuit breaker, and the wall-clock budget.

Three capabilities, one module, because all three answer the same question at
the same layer: **is this campaign still making progress, and may the campaign
loop continue?** None of them decides which STATE runs next — that belongs to
the compiled policy, and nothing here is consulted by ``policy.step``.

WHICH LAYER, AND WHY IT IS NOT A POLICY DECISION
------------------------------------------------
``CLAUDE.md`` forbids adding an ``if``/``elif`` to ``stage_runner`` that decides
the next STAGE, and it is right to: stage sequencing is the pre-registration,
and a branch in Python is a claim about the source tree rather than about the
run.

The circuit breaker is a different kind of decision, at a different layer, and
the distinction is not a technicality:

* The compiled policy answers "given this iteration's OBSERVATIONS, which
  registered branch fires?" Its inputs are measurements. Every answer it can
  give is a state the pre-registration already enumerated.
* The circuit breaker answers "has the campaign LOOP stopped making progress?"
  Its inputs are not measurements at all — they are iteration *failures*, i.e.
  the absence of measurement. A failed iteration produces no observation for a
  policy to branch on; that is precisely why it repeats (``current_state``
  reads the last recorded transition, a failed iteration records none, so the
  same state is resolved again).

So the breaker cannot be a policy transition even in principle: the policy's
domain is observations, and a repeated crash yields none. It lives in
``run_campaign``'s loop, which is the thing that is looping, and it stops that
loop. It never selects a stage, never writes ``transitions.jsonl``, and never
changes what the policy would do with a real observation.

The wall-clock budget is the same layer for the same reason, with one addition:
on exhaustion it must end the epoch CLEANLY through the existing machinery so
the fallback ladder still names an action. It therefore does not kill anything
— it declines to START another iteration, and lets the normal terminal path
produce the report.

WHY THE VERDICT IS ITS OWN ARTIFACT
-----------------------------------
``epoch_end-<epoch>.json`` already records "why the epoch ended", so it is a
fair question whether the breaker's verdict belongs there. It does not, and
the reason is that ``epoch_end`` means something specific: a **semantic
exception** ended the epoch, and ``next_epoch_requires`` tells the next agent
what to revise about the *interface*. It is written by the ``exception`` state,
inside the policy, from an observation.

A tripped breaker is not that. Nothing semantic was discovered; the apparatus
crashed the same way four times. Writing it into ``epoch_end`` would tell the
next agent to revise a design that is fine, and would put a record the policy
did not produce into an artifact whose whole meaning is "the policy routed
here". ``halt.json`` is therefore its own artifact, at the work-dir root, and
it says which layer stopped the campaign.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

PROGRESS_FILE = "progress.json"
HALT_FILE = "halt.json"

#: Consecutive identical failures before the loop stops. Small on purpose: the
#: real campaign wasted four iterations on one deterministic defect, and the
#: third repeat already carries no new information. Overridable per campaign
#: via ``optimization.max_identical_failures``.
DEFAULT_MAX_IDENTICAL_FAILURES = 3


# ─────────────────────────── failure fingerprints ───────────────────────────

#: Substrings replaced before fingerprinting, so incidental per-iteration text
#: does not make two occurrences of ONE defect look like two different defects.
#: Each pattern here is a value that legitimately changes between attempts of
#: the same failure; anything that identifies the DEFECT must survive.
_NORMALIZERS: tuple[tuple[str, str], ...] = (
    # Timestamps and memory addresses first — they contain digits the later
    # rules would otherwise chew into an unrecognisable shape.
    (r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\s]*", "TS"),
    (r"0x[0-9a-fA-F]+", "ADDR"),
    # Hex digests (policy hashes, contract hashes, sha prefixes).
    (r"\b[0-9a-f]{8,}\b", "HEX"),
    # Iteration/run directories: `runs/iter-4/...` vs `runs/iter-5/...`.
    (r"iter-\d+", "iter-N"),
    # Absolute paths under a tmp/work dir — the run_id and tmp segment vary.
    (r"/[^\s'\"]*/runs/", "/runs/"),
    # Row indices and counts, normalized ONLY where the surrounding words say
    # the number is an incidental index or tally: "row_index 3", "3 of 18
    # rows", "4 rows". Those really are the same defect across attempts.
    #
    # Bare standalone integers are deliberately NOT normalized. An earlier
    # version replaced every `\b\d+\b`, and a property test caught it merging
    # genuinely DISTINCT failures ("distinct failure number 0" and "... 1"
    # collapsed to the same fingerprint) — which would trip the breaker on a
    # campaign that was failing three different ways, i.e. stop a campaign that
    # still had information to gain. Over-merging is the more dangerous
    # direction, so the normalization is anchored to explicit index/count
    # vocabulary instead of applied blindly.
    (r"\b(row_index|row|rows|replicate|iteration|epoch|column|attempt)\b"
     r"(\s*[:=]?\s*)\d+", r"\1\2N"),
    (r"\b\d+\s+of\s+\d+\b", "N of N"),
    (r"\b\d+(?=\s+(rows?|runs?|configurations?|iterations?|attempts?)\b)", "N"),
)


def normalize_error(text: str) -> str:
    """An error message with its per-attempt incidentals removed.

    Lowercased, whitespace-collapsed, and with the ``_NORMALIZERS`` applied, so
    the same defect on two attempts produces the same string while two
    different defects keep different ones.
    """
    out = str(text or "")
    for pattern, repl in _NORMALIZERS:
        out = re.sub(pattern, repl, out)
    return " ".join(out.lower().split())


def failure_fingerprint(*, stage: str, error: str,
                        exc_type: str = "") -> str:
    """A stable identity for one failure mode.

    ``(exception type, failing stage, normalized message)`` hashed to 16 hex
    characters. All three are load-bearing:

    * The **exception type** separates an ``OptimizationAborted`` from a
      ``KeyError`` whose messages happen to normalize alike.
    * The **stage** separates the same exception raised from ``screen`` and
      from ``confirm`` — the same text at two states is two defects, and
      stopping the campaign on the second is wrong.
    * The **normalized message** is what makes a genuinely repeating defect
      recognisable across attempts.

    A DELIBERATE, NARROWLY-SCOPED IMPRECISION: indices and tallies are
    normalized away where the surrounding words identify them as such, so
    "3 of 18 rows unusable" and "4 of 18 rows unusable" share a fingerprint.
    Treating a changed row count as a brand-new failure is exactly what let the
    real campaign loop — each attempt failed with a slightly different count
    and nothing recognised the pattern.

    The normalization is anchored to explicit index/count vocabulary rather
    than applied to every integer, and that boundary was set by a failing
    property test rather than by taste: a blanket ``\\b\\d+\\b`` rule merged
    "distinct failure number 0" with "distinct failure number 1", which would
    trip the breaker on a campaign failing three DIFFERENT ways — stopping a
    campaign that still had information to gain. Over-merging is the more
    dangerous direction, so bare standalone integers keep their identity.

    Whatever merging does still occur stays visible: ``halt.json`` records the
    messages verbatim, so a human sees the grouping rather than having it
    hidden.
    """
    payload = "\x00".join((
        str(exc_type or ""), str(stage or ""), normalize_error(error),
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ───────────────────────────── circuit breaker ──────────────────────────────

@dataclass(frozen=True)
class BreakerVerdict:
    """Whether the campaign loop may continue, and why not if it may not."""

    tripped: bool
    fingerprint: str = ""
    count: int = 0
    threshold: int = DEFAULT_MAX_IDENTICAL_FAILURES
    iterations: tuple[int, ...] = ()
    messages: tuple[str, ...] = ()
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "tripped": self.tripped,
            "fingerprint": self.fingerprint,
            "count": self.count,
            "threshold": self.threshold,
            "iterations": list(self.iterations),
            "messages": list(self.messages),
            "reason": self.reason,
        }


@dataclass
class FailureRecord:
    """One observed iteration failure."""

    iteration: int
    stage: str
    error: str
    exc_type: str = ""

    @property
    def fingerprint(self) -> str:
        return failure_fingerprint(
            stage=self.stage, error=self.error, exc_type=self.exc_type,
        )


def check_breaker(failures: list[FailureRecord], *,
                  threshold: int = DEFAULT_MAX_IDENTICAL_FAILURES,
                  ) -> BreakerVerdict:
    """Has the same failure now happened ``threshold`` times in a row?

    CONSECUTIVE, not cumulative, and counted over the most recent run of
    identical fingerprints. Consecutive is the honest reading of "this campaign
    is failing the same way repeatedly": two crashes of one kind separated by a
    successful iteration are not a stuck loop, they are a flaky apparatus that
    the campaign is nonetheless making progress through. Cumulative counting
    would stop a campaign that is working.

    A genuinely transient failure therefore does not trip it unless it recurs
    ``threshold`` times with nothing succeeding in between — and if it does, it
    is no longer usefully called transient.

    Pure: no disk, no clock. ``failures`` is the caller's list in iteration
    order.
    """
    threshold = max(1, int(threshold))
    if not failures:
        return BreakerVerdict(False, threshold=threshold)

    tail_fp = failures[-1].fingerprint
    run: list[FailureRecord] = []
    for rec in reversed(failures):
        if rec.fingerprint != tail_fp:
            break
        run.append(rec)
    run.reverse()

    if len(run) < threshold:
        return BreakerVerdict(
            False, fingerprint=tail_fp, count=len(run), threshold=threshold,
            iterations=tuple(r.iteration for r in run),
        )

    stage = run[-1].stage
    return BreakerVerdict(
        True, fingerprint=tail_fp, count=len(run), threshold=threshold,
        iterations=tuple(r.iteration for r in run),
        messages=tuple(r.error for r in run),
        reason=(
            f"iteration failed {len(run)} consecutive times with the same "
            f"failure mode (fingerprint {tail_fp}) at stage {stage!r}. Retrying "
            f"has produced no new information, so the campaign loop is stopping "
            f"rather than spending the remaining budget reproducing one defect. "
            f"Failing iterations: "
            f"{', '.join(str(r.iteration) for r in run)}. Fix the cause and "
            f"resume: `nous resume` continues from the last recorded transition, "
            f"and rows already measured under this pre-registration are reused."
        ),
    )


#: ``run_campaign`` records a failure as ``"ExcType: message"``. Recovering the
#: type lets the fingerprint keep two defects apart whose prose normalizes
#: alike. Anchored to a conservative identifier shape so a message that merely
#: contains a colon is not mistaken for a prefixed one.
_EXC_PREFIX = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]{0,63})\s*:\s*(.*)$", re.DOTALL)


def _split_exc_prefix(text: str) -> tuple[str, str]:
    """``("ExcType", "message")`` when the error carries a type prefix, else ``("", text)``.

    Rows written before this prefix existed, and rows whose message merely
    begins with a word and a colon, degrade to ``("", text)`` — the fingerprint
    is then computed on the message alone, exactly as it was. A campaign
    resumed across the change therefore still recognises its own history rather
    than treating every prior failure as a new mode.
    """
    m = _EXC_PREFIX.match(str(text or ""))
    if not m:
        return "", str(text or "")
    candidate, rest = m.group(1), m.group(2)
    # An exception class name, not a sentence's first word: it must look like a
    # type (CamelCase or dotted), which "note" / "error" in prose do not.
    if not (candidate[:1].isupper() and any(c.isupper() for c in candidate[1:])
            or "." in candidate):
        return "", str(text or "")
    return candidate, rest


def failures_from_ledger(work_dir: Path, *, stage_of=None) -> list[FailureRecord]:
    """Every FAILED ledger row, in iteration order, as ``FailureRecord``s.

    ``ledger.json`` is the right source: ``append_failed_row`` already writes
    one row per failed iteration with the error text, atomically, on every
    failure path including ``nous stop``. Reading it means the breaker needs no
    parallel bookkeeping of its own and survives a process restart — a campaign
    resumed after a crash still sees the failures that preceded it.

    ``stage_of`` maps an iteration number to the stage it ran, when the caller
    can supply it (from ``transitions.jsonl`` this is not recoverable for a
    FAILED iteration, precisely because it recorded no transition — so the
    caller passes what it knows and the fingerprint falls back to "" otherwise).
    """
    path = Path(work_dir) / "ledger.json"
    if not path.exists():
        return []
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    out: list[FailureRecord] = []
    for row in doc.get("iterations") or ():
        if not isinstance(row, dict) or row.get("status") != "FAILED":
            continue
        it = row.get("iteration")
        if not isinstance(it, int):
            continue
        raw = str(row.get("error") or "")
        exc_type, error = _split_exc_prefix(raw)
        out.append(FailureRecord(
            iteration=it,
            stage=str(stage_of(it)) if callable(stage_of) else "",
            error=error,
            exc_type=exc_type,
        ))
    out.sort(key=lambda r: r.iteration)
    return out


def write_halt(work_dir: Path, payload: dict) -> Path:
    """Record WHY the campaign loop stopped, at the work-dir root.

    Its own artifact rather than a line in ``epoch_end-<epoch>.json``: see the
    module docstring. ``epoch_end`` means "a semantic exception ended the
    epoch, and here is what a new epoch would need"; a tripped breaker or an
    exhausted wall-clock budget is neither semantic nor a policy decision, and
    filing it there would tell the next agent to revise an interface that is
    fine.
    """
    from orchestrator.util import atomic_write

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    target = work_dir / HALT_FILE
    atomic_write(target, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return target


# ─────────────────────────── wall-clock budget ──────────────────────────────

@dataclass(frozen=True)
class BudgetVerdict:
    """Whether the declared wall-clock budget still allows another iteration."""

    exhausted: bool
    budget_hours: float | None = None
    elapsed_hours: float = 0.0
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "exhausted": self.exhausted,
            "budget_hours": self.budget_hours,
            "elapsed_hours": round(self.elapsed_hours, 4),
            "reason": self.reason,
        }


def check_budget(*, budget_hours: float | None, started_at: float,
                 now: float | None = None) -> BudgetVerdict:
    """Is the declared wall-clock budget spent?

    ``None`` (undeclared) is unbounded — the behaviour every campaign authored
    before the field existed has, and the field is opt-in precisely so that
    adding it cannot shorten an existing campaign.

    Checked BETWEEN iterations, never inside one. A budget that killed a
    running measurement would leave a half-measured row on disk and would
    produce no report; the fallback ladder's guarantee that the report always
    names an action depends on the epoch ending through its normal terminal
    path. So this answers "may another iteration START", and the caller lets
    the current one finish.
    """
    if budget_hours is None:
        return BudgetVerdict(False)
    try:
        budget = float(budget_hours)
    except (TypeError, ValueError):
        return BudgetVerdict(False)
    if budget <= 0:
        return BudgetVerdict(False, budget_hours=budget)

    now = time.time() if now is None else float(now)
    elapsed_h = max(0.0, (now - float(started_at))) / 3600.0
    if elapsed_h < budget:
        return BudgetVerdict(False, budget_hours=budget, elapsed_hours=elapsed_h)
    return BudgetVerdict(
        True, budget_hours=budget, elapsed_hours=elapsed_h,
        reason=(
            f"the campaign's declared wall-clock budget of {budget:g} hour(s) "
            f"is spent ({elapsed_h:.2f}h elapsed), so no further iteration is "
            f"started. The epoch ends through its normal terminal path, so a "
            f"recommendation is still produced from what was measured — read "
            f"report.json's recommendation.basis to see which rung of the "
            f"fallback ladder it rests on."
        ),
    )


# ────────────────────────────── progress surface ─────────────────────────────

@dataclass
class ProgressSnapshot:
    """What a supervising human could not answer for hours.

    Every count is derived from artifacts on disk, and every field that cannot
    be derived is ABSENT rather than guessed. ``eta_seconds`` in particular is
    ``None`` whenever the durations it would need are missing or zero — a
    fabricated ETA is worse than none, and per-row ``duration_ms`` has a
    reserved 0 meaning "never executed", so a mean over zeros would report a
    confident instant completion for a campaign that has measured nothing.
    """

    run_id: str = ""
    epoch: int = 1
    iteration: int = 0
    stage: str = ""
    phase: str = ""
    rows_planned: int = 0
    rows_done: int = 0
    rows_failed: int = 0
    rows_reused: int = 0
    rows_pending: int = 0
    completed_iterations: int = 0
    failed_iterations: int = 0
    elapsed_seconds: float | None = None
    eta_seconds: float | None = None
    eta_basis: str = "unavailable"
    mean_row_seconds: float | None = None
    budget_hours: float | None = None
    halted: dict | None = None
    recent_failures: list[dict] = field(default_factory=list)
    updated_at: str = ""

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "epoch": self.epoch,
            "iteration": self.iteration,
            "stage": self.stage,
            "phase": self.phase,
            "rows": {
                "planned": self.rows_planned,
                "done": self.rows_done,
                "failed": self.rows_failed,
                "reused": self.rows_reused,
                "pending": self.rows_pending,
            },
            "iterations": {
                "completed": self.completed_iterations,
                "failed": self.failed_iterations,
            },
            "elapsed_seconds": self.elapsed_seconds,
            "eta_seconds": self.eta_seconds,
            "eta_basis": self.eta_basis,
            "mean_row_seconds": self.mean_row_seconds,
            "budget_hours": self.budget_hours,
            "halted": self.halted,
            "recent_failures": self.recent_failures,
            "updated_at": self.updated_at,
        }


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _estimate_eta(*, pending: int, durations: list[int],
                  max_parallel: int = 1,
                  planned: int | None = None) -> tuple[float | None, str, float | None]:
    """``(eta_seconds, basis, mean_row_seconds)`` — ``None`` when not derivable.

    THE POINT OF THIS FUNCTION IS THE NEGATIVE CASE. ``duration_ms`` reserves 0
    for "this row never executed", and for most of this project's history the
    field was structurally always 0 — so an ETA computed from a naive mean would
    have reported "0 seconds remaining" for an 18-row screen that had measured
    nothing, which is precisely the plausible-looking-signal failure this whole
    exercise is about. Zero and negative durations are therefore discarded
    rather than averaged, and if nothing survives, there is no ETA.
    """
    usable = [int(d) for d in durations if isinstance(d, (int, float)) and int(d) > 0]
    if planned is not None and planned <= 0:
        # No design registered yet (pre-DESIGN, or a work_dir with nothing in
        # it). "0 seconds remaining" here would be a confident claim about a
        # campaign that has not planned a single row — the same class of lie as
        # an ETA averaged over zero durations.
        return None, "no design matrix registered yet", None
    if pending <= 0:
        return 0.0, "no rows pending", None
    if not usable:
        return None, "no completed row has a usable duration", None
    mean_s = (sum(usable) / len(usable)) / 1000.0
    width = max(1, int(max_parallel or 1))
    eta = (pending * mean_s) / width
    basis = (
        f"mean of {len(usable)} measured row duration(s)"
        + (f" over {width} parallel slot(s)" if width > 1 else "")
    )
    return eta, basis, mean_s


def read_progress_snapshot(work_dir: Path) -> ProgressSnapshot:
    """Assemble the progress snapshot from artifacts on disk.

    Read-only and defensive throughout: a campaign that is RUNNING is writing
    these files concurrently, so every read tolerates absence and malformed
    content rather than raising. A snapshot that says "unknown" is useful; one
    that raises while the campaign is mid-write is not.
    """
    work_dir = Path(work_dir)
    snap = ProgressSnapshot(updated_at=_now_iso())

    state = _read_json(work_dir / "state.json") or {}
    if isinstance(state, dict):
        snap.run_id = str(state.get("run_id") or "")
        try:
            snap.iteration = int(state.get("iteration") or 0)
        except (TypeError, ValueError):
            snap.iteration = 0
        try:
            from orchestrator.engine import read_phase_field
            snap.phase = str(read_phase_field(state, default="") or "")
        except Exception:  # pragma: no cover - defensive
            snap.phase = str(state.get("last_entered_phase")
                             or state.get("phase") or "")

    pol = _read_json(work_dir / "policy.json") or {}
    if isinstance(pol, dict) and pol:
        try:
            snap.epoch = int(pol.get("epoch") or 1)
        except (TypeError, ValueError):
            snap.epoch = 1
        # The STAGE, which `nous status` cannot report for an optimization
        # campaign: it reads state.json only, and the stage lives in the
        # transition log. This is the single field the supervising human most
        # needed and could not get.
        try:
            from orchestrator.optimize import policy as policy_mod
            snap.stage = str(policy_mod.current_state(pol, work_dir))
        except Exception:  # pragma: no cover - defensive
            snap.stage = ""

    ledger = _read_json(work_dir / "ledger.json") or {}
    rows = ledger.get("iterations") if isinstance(ledger, dict) else None
    if isinstance(rows, list):
        real = [r for r in rows
                if isinstance(r, dict) and isinstance(r.get("iteration"), int)
                and r["iteration"] >= 1]
        snap.failed_iterations = sum(1 for r in real if r.get("status") == "FAILED")
        snap.completed_iterations = len(real) - snap.failed_iterations
        snap.recent_failures = [
            {"iteration": r["iteration"], "error": str(r.get("error") or "")[:300]}
            for r in real if r.get("status") == "FAILED"
        ][-5:]

    # Row counts for the CURRENT iteration, from its own artifacts.
    iter_dir = work_dir / "runs" / f"iter-{snap.iteration}"
    matrix = _read_json(iter_dir / "design_matrix.json") or {}
    planned_rows = matrix.get("rows") if isinstance(matrix, dict) else None
    if isinstance(planned_rows, list):
        snap.rows_planned = len(planned_rows)
    max_parallel = 1
    if isinstance(matrix, dict):
        try:
            max_parallel = max(1, int(matrix.get("max_parallel") or 1))
        except (TypeError, ValueError):
            max_parallel = 1

    durations: list[int] = []
    try:
        from orchestrator.optimize import artifacts
        run_rows = artifacts.read_runs(iter_dir)
    except Exception:  # pragma: no cover - defensive
        run_rows = []
    for row in run_rows:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "")
        if status == "failed":
            snap.rows_failed += 1
        else:
            snap.rows_done += 1
        if row.get("reused_from"):
            snap.rows_reused += 1
        else:
            # Only FRESH measurements inform the ETA. A reused row's duration
            # was paid in a previous iteration and predicts nothing about how
            # long the rows still pending will take.
            durations.append(int(row.get("duration_ms") or 0))

    accounted = snap.rows_done + snap.rows_failed
    snap.rows_pending = max(0, snap.rows_planned - accounted)

    snap.eta_seconds, snap.eta_basis, snap.mean_row_seconds = _estimate_eta(
        pending=snap.rows_pending, durations=durations, max_parallel=max_parallel,
        planned=snap.rows_planned,
    )

    started = _campaign_started_at(work_dir)
    if started is not None:
        snap.elapsed_seconds = max(0.0, time.time() - started)

    halt = _read_json(work_dir / HALT_FILE)
    if isinstance(halt, dict):
        snap.halted = halt

    return snap


def _campaign_started_at(work_dir: Path) -> float | None:
    """When the campaign began, or ``None`` when it cannot be established.

    ``state.json``'s mtime is not it — the file is rewritten on every phase
    transition. The earliest mtime among the campaign's durable artifacts is
    the best available answer, and ``None`` is returned rather than a guess
    when there are none.
    """
    candidates: list[float] = []
    for name in ("policy.json", "state.json", "ledger.json"):
        p = Path(work_dir) / name
        if p.exists():
            try:
                candidates.append(p.stat().st_ctime)
            except OSError:
                pass
    runs = Path(work_dir) / "runs"
    if runs.exists():
        for d in runs.glob("iter-*"):
            try:
                candidates.append(d.stat().st_ctime)
            except OSError:
                pass
    return min(candidates) if candidates else None


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def write_progress(work_dir: Path, snap: ProgressSnapshot | None = None) -> Path:
    """Rewrite ``progress.json`` atomically. Safe to call while measuring.

    ``atomic_write`` is temp-file + fsync + rename, so a reader either sees the
    previous complete document or the new one, never a partial write, and a
    process killed mid-write leaves the previous document intact.
    """
    from orchestrator.util import atomic_write

    work_dir = Path(work_dir)
    snap = read_progress_snapshot(work_dir) if snap is None else snap
    work_dir.mkdir(parents=True, exist_ok=True)
    target = work_dir / PROGRESS_FILE
    atomic_write(target, json.dumps(snap.as_dict(), indent=2, sort_keys=True) + "\n")
    return target


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def format_progress(snap: ProgressSnapshot) -> str:
    """A human-readable panel. Says "unknown" where it does not know."""
    lines = [
        f"run        {snap.run_id or '(unknown)'}",
        f"epoch      {snap.epoch}",
        f"iteration  {snap.iteration}"
        + (f"  (stage: {snap.stage})" if snap.stage else "")
        + (f"  [phase {snap.phase}]" if snap.phase else ""),
        f"rows       {snap.rows_done} done"
        + (f" ({snap.rows_reused} reused)" if snap.rows_reused else "")
        + f" / {snap.rows_failed} failed"
        + f" / {snap.rows_pending} pending"
        + f" of {snap.rows_planned} planned",
        f"iters      {snap.completed_iterations} completed"
        f" / {snap.failed_iterations} failed",
        f"elapsed    {_fmt_duration(snap.elapsed_seconds)}",
    ]
    if snap.eta_seconds is None:
        lines.append(f"eta        unavailable ({snap.eta_basis})")
    else:
        lines.append(
            f"eta        ~{_fmt_duration(snap.eta_seconds)} ({snap.eta_basis})",
        )
    if snap.budget_hours:
        lines.append(f"budget     {snap.budget_hours:g}h wall clock")
    if snap.halted:
        lines.append("")
        lines.append(f"HALTED     {snap.halted.get('kind', 'unknown')}")
        reason = str(snap.halted.get("reason") or "").strip()
        if reason:
            lines.append(f"           {reason}")
    if snap.recent_failures:
        lines.append("")
        lines.append("recent failures:")
        for f in snap.recent_failures:
            lines.append(f"  iter-{f['iteration']}: {f['error'][:160]}")
    return "\n".join(lines)


def format_progress_line(snap: ProgressSnapshot) -> str:
    """One line, for a shell prompt or a log."""
    eta = "eta ?" if snap.eta_seconds is None else f"eta ~{_fmt_duration(snap.eta_seconds)}"
    stage = snap.stage or "?"
    return (
        f"[{snap.run_id or '?'}] iter {snap.iteration} {stage} — "
        f"{snap.rows_done}/{snap.rows_planned} rows"
        + (f" ({snap.rows_reused} reused)" if snap.rows_reused else "")
        + (f", {snap.rows_failed} failed" if snap.rows_failed else "")
        + f", {eta}"
        + (", HALTED" if snap.halted else "")
    )
