"""Reuse already-measured rows when a failed iteration is retried.

WHY THIS MODULE EXISTS
----------------------
A real 14-hour campaign produced zero usable output. Iterations 2, 3 and 4
each failed for a different reason; iteration 5 was re-running the identical
18-row screen when it was killed. Fifteen valid rows sat on disk and were
re-measured four times, and that re-measurement was most of the 14 hours.

Nothing was wrong with the retry mechanism itself. ``_resolve_state`` reads
the last recorded transition, a failed iteration records none, so iteration
*i+1* correctly resolves to the same state and legitimately re-registers the
same design. What was missing is that the re-registration threw away the
measurements the previous attempt had already paid for.

THE REUSE-VALIDITY ARGUMENT — read this before widening anything
---------------------------------------------------------------
Reuse is only sound when the reused row is a measurement of *exactly* the
configuration the new attempt pre-registers. Naive "same levels, same
row_index" reuse is NOT sound in this codebase, and the reason is specific:

``_assign_workload_seeds`` derives each row's workload seed from
``run_order_seed``, and ``matrix_payload`` is called with
``run_order_seed=iteration``. So iteration 4's row 0 and iteration 5's row 0
carry DIFFERENT seeds (31676 vs 39595 on the real formula). Under
``optimization.workload.seed_env`` — which nearly every real campaign
declares — those are measurements of two different workload draws. Carrying
iteration 4's number forward as though it answered iteration 5's registered
draw would silently substitute one experiment's randomness for another's,
which is precisely the "stale measurement resurrected" failure mode that is
worse than re-measuring.

So this module does NOT match rows across two independently-derived designs.
It carries the PRIOR ATTEMPT'S REGISTERED DESIGN FORWARD WHOLESALE — seeds
included — and reuses a row only when the row it is reused *as* is the
identical registered configuration, seed and all. Reuse becomes a statement
about one pre-registration continued, not about two designs that happen to
look alike. ``plan_reuse`` therefore takes the prior design matrix and the
candidate design matrix and refuses the whole reuse if they are not the same
registration (``carry_forward_payload`` is what produces a candidate that
can pass).

Six guards, each of which independently refuses reuse:

1. **policy_hash** — the pre-registration itself. A row measured under a
   different compiled policy was scheduled by a different experiment.
2. **The adapter contract** — ``adapter_contract.json``'s hash. This is the
   same "an apparatus change is an epoch boundary, not an edit" rule the
   contract guard already enforces per row; a row measured by a different
   instrument is not comparable to one measured by this one, so it cannot be
   carried across the change either.
3. **Coded levels AND applied config** — ``levels`` must match the planned
   row, and ``apply`` (cli_args / env / patches) must match too. Levels alone
   are insufficient: a ``config_patch`` factor's realized patch or a changed
   env is the difference between two runs whose ``levels`` are identical.
4. **The workload seed** — per the argument above, and it rides inside
   ``apply["env"]``, so guard 3 enforces it rather than a separate branch.
   Note WHERE it is read from: ``stage_runner._run_row`` does not record
   ``apply`` in ``runs.jsonl``, so the configuration a row actually ran under
   is not recoverable from the run log. The comparison therefore reads the
   prior iteration's ``design_matrix.json`` at the same row index — which is
   sound because that matrix IS the pre-registration, and ``check_fidelity``
   already refuses any run whose levels drifted from it. A row whose applied
   configuration cannot be established from either source is re-measured
   rather than assumed to match.
5. **Status** — only ``complete`` / ``infeasible`` / ``rejected`` are reused.
   ``failed`` is re-run: a ``failed`` row is a MEASUREMENT failure a re-run
   can repair (the runner crashed, the lever never engaged, the clock ran
   out), and ``_fitting_responses``' own docstring says so. The other three
   are real information — ``complete`` is usable for fitting, and
   ``infeasible`` / ``rejected`` are trustworthy measurements of an
   inadmissible configuration (spec §6.4).
6. **Epoch** — a row from an earlier epoch is a different pre-registration
   even when every other field agrees.

PROVENANCE
----------
A reused row is written into the new iteration's ``runs.jsonl`` carrying a
``reused_from`` object (``{iteration, epoch}``). A reader can never mistake it
for a fresh measurement, and can find the attempt that paid for it. The row's
own ``duration_ms`` is preserved rather than zeroed, because it really did
cost that much wall clock once; ``reuse_manifest.json`` records the saving
separately.

WHAT THIS MODULE DOES NOT DO
----------------------------
It decides nothing about which STATE runs next — that belongs to the compiled
policy, and nothing here is consulted by ``policy.step``. It is a pure
planner: ``plan_reuse`` reads artifacts and returns a decision, and the
caller does the writing.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: Statuses whose measurement is real information and may be carried forward.
#: ``failed`` is deliberately absent: it is a measurement failure a re-run
#: repairs, so reusing it would make a transient crash permanent.
REUSABLE_STATUSES = frozenset({"complete", "infeasible", "rejected"})

#: Design families that may NEVER supply a reused row, whatever else matches.
#:
#: ``shortlist_replicate`` is the ``confirm`` round's matrix — the paper's
#: TERMINAL DISCRIMINATION stage. Its whole purpose is that the final comparison
#: between finalists rests on FRESH measurements rather than on the fitted
#: surface, so a carried-forward replicate would defeat the one guarantee the
#: stage exists to provide. Two further reasons make this a hard exclusion
#: rather than a judgement call:
#:
#:   * A SECOND confirm round exists precisely BECAUSE round 1 did not
#:     discriminate. Spec §3.8 is explicit that the round keys its seed on the
#:     iteration "so a second confirm round measures fresh draws instead of
#:     re-measuring round 1's — the round exists because round 1 did not
#:     discriminate, and repeating its exact workload could not fix that."
#:     Reuse would repeat exactly that workload.
#:   * Confirm's bound is PAIRED under common random numbers, and
#:     ``certificate.terminal_regret_bound`` ZIPS each finalist's measurements
#:     positionally. Carrying some finalists' replicates forward while measuring
#:     others fresh would pair a reused draw against a fresh one, so the paired
#:     differences would no longer share a workload draw and the recorded
#:     ``bonferroni_one_sided_t_paired`` method would describe a premise that
#:     did not hold.
#:
#: Reuse is a wall-clock optimization for the SPENDING stages (screen /
#: foldover / refine), which fit a surface and where a re-measured row is
#: genuinely redundant. It is not a general-purpose cache.
NEVER_REUSABLE_KINDS = frozenset({"shortlist_replicate"})

#: The one status that must always be re-measured.
RERUN_STATUSES = frozenset({"failed"})

MANIFEST_FILE = "reuse_manifest.json"


@dataclass(frozen=True)
class RowVerdict:
    """Why one candidate row was, or was not, reused."""

    row_index: int
    reused: bool
    reason: str
    source_iteration: int | None = None
    duration_ms: int = 0

    def as_dict(self) -> dict:
        out = {
            "row_index": self.row_index,
            "reused": self.reused,
            "reason": self.reason,
        }
        if self.source_iteration is not None:
            out["source_iteration"] = self.source_iteration
        if self.duration_ms:
            out["duration_ms"] = self.duration_ms
        return out


@dataclass(frozen=True)
class ReusePlan:
    """The rows to carry forward, and the rows still to measure.

    ``rows`` are complete ``runs.jsonl`` row dicts, already carrying their
    ``reused_from`` provenance, ready to be appended to the new iteration's
    log. ``pending_indices`` are the row indices the caller must still
    execute.

    ``refused`` is non-empty when reuse was refused WHOLESALE — a differing
    policy hash, a changed adapter contract, a design that is not the same
    registration. It carries the human-readable reason, and an empty plan is
    the correct, safe outcome: the campaign re-measures exactly as it does
    today.
    """

    rows: list[dict] = field(default_factory=list)
    pending_indices: list[int] = field(default_factory=list)
    verdicts: list[RowVerdict] = field(default_factory=list)
    refused: str = ""
    source_iteration: int | None = None

    @property
    def reused_count(self) -> int:
        return len(self.rows)

    @property
    def saved_ms(self) -> int:
        """Wall clock the reused rows cost when they were first measured."""
        return sum(int(r.get("duration_ms") or 0) for r in self.rows)

    def manifest(self, *, iteration: int, epoch: int, policy_hash: str) -> dict:
        return {
            "iteration": int(iteration),
            "epoch": int(epoch),
            "policy_hash": str(policy_hash),
            "source_iteration": self.source_iteration,
            "reused_rows": sorted(int(r["row_index"]) for r in self.rows),
            "pending_rows": sorted(int(i) for i in self.pending_indices),
            "reused_count": self.reused_count,
            "pending_count": len(self.pending_indices),
            "saved_ms": self.saved_ms,
            "refused": self.refused,
            "verdicts": [v.as_dict() for v in self.verdicts],
        }


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _levels_match(planned: dict, observed: dict) -> bool:
    """Levels agree, comparing numerics with the tolerance ``check_fidelity`` uses.

    Levels round-trip through JSON, so a float can come back a representation
    step away from the planned value; exact ``!=`` would refuse reuse for a
    legitimately identical configuration. Non-numerics compare exactly, since
    a ``choice`` level must match its declared string. Deliberately the same
    rule ``matrix.check_fidelity`` applies, so a row this module carries
    forward cannot then fail the fidelity check it has to pass.
    """
    import math

    if set(planned) != set(observed):
        return False
    for key, expected in planned.items():
        got = observed.get(key)
        numeric = (
            isinstance(expected, (int, float)) and isinstance(got, (int, float))
            and not isinstance(expected, bool) and not isinstance(got, bool)
        )
        if numeric:
            if math.isclose(float(got), float(expected), rel_tol=1e-9, abs_tol=1e-12):
                continue
            return False
        if got != expected:
            return False
    return True


def _seed_of(payload: dict, row_index: int) -> object:
    """The registered workload seed for one row, or ``None`` when unseeded.

    Read from the matrix's recorded ``workload_seeds`` rather than re-derived:
    the recorded value is what the row actually carried, and re-deriving it
    would reproduce whatever bug put a wrong seed there.
    """
    seeds = payload.get("workload_seeds")
    if not isinstance(seeds, dict):
        return None
    return seeds.get(str(row_index))


def _apply_of(payload: dict, row_index: int) -> dict:
    for row in payload.get("rows") or ():
        if row.get("row_index") == row_index:
            return row.get("apply") or {}
    return {}


def _planned(payload: dict) -> dict[int, dict]:
    return {
        row["row_index"]: row
        for row in (payload.get("rows") or ())
        if isinstance(row.get("row_index"), int)
    }


def carry_forward_payload(prior: dict, candidate: dict) -> dict | None:
    """The candidate design re-registered with the PRIOR attempt's draws.

    This is what makes reuse legitimate rather than merely fast. The new
    attempt's own ``workload_seeds`` (and the per-row ``apply.env`` the seeds
    are injected into) are replaced by the previous attempt's, so a reused row
    is a measurement of exactly the configuration this attempt registers.

    Returns ``None`` when the two designs are not the same registration —
    different factors, a different design family, a different row set, or a
    different run order. Continuing one pre-registration is only meaningful
    while it IS the same design; anything else is a new experiment and must
    pay for its own measurements.

    Note what is deliberately NOT carried: ``policy_hash`` is not copied from
    the prior payload. The caller stamps the live policy's hash, and
    ``plan_reuse`` then refuses if the prior rows were measured under a
    different one. Copying it would forge agreement instead of checking it.
    """
    if not isinstance(prior, dict) or not isinstance(candidate, dict):
        return None

    # TERMINAL DISCRIMINATION IS NEVER REUSED. Checked first, and on EITHER
    # side, so a confirm matrix can neither donate nor receive a row. See
    # ``NEVER_REUSABLE_KINDS``: confirm's claim is that the finalist comparison
    # rests on fresh measurements, a second round exists because the first did
    # not discriminate, and its paired bound zips replicates that must share a
    # workload draw. Two confirm rounds also share this ``kind``, so without
    # this the structural comparison below could match round 1 against round 2
    # whenever the shortlist was unchanged — which is exactly when a second
    # round is spent.
    if (str(prior.get("kind") or "") in NEVER_REUSABLE_KINDS
            or str(candidate.get("kind") or "") in NEVER_REUSABLE_KINDS):
        return None

    # Same design, structurally: the same factors, the same design family, the
    # same alias structure, the same held-fixed levels, the same shortlist.
    #
    # `run_order` / `run_order_seed` are deliberately NOT in this list, and the
    # distinction is the crux of what reuse means. Those two describe the
    # SCHEDULE — the order rows are executed in, which exists to keep a
    # time-ordered trend (a warming cache, a thermally throttling machine) from
    # being absorbed into a factor's coefficient. They are not part of any
    # individual row's identity. `run_order_seed` is the ITERATION number, so a
    # retry necessarily draws a different permutation; gating on it would mean
    # reuse could never engage on the one path it exists for. Verified: iter-2
    # registered order [9,11,3,...] and iter-3 [1,7,10,...] for the identical
    # 12-row design.
    #
    # A re-shuffle is also harmless in exactly the way an identity change is
    # not: re-ordering the rows that REMAIN to be measured changes nothing about
    # a row that was already measured. What must not change is the
    # MEASUREMENT's identity, and that is `workload_seeds` plus the applied
    # config — which this function pins by carrying the prior attempt's draws
    # forward below, and which `plan_reuse` then checks per row.
    #
    # The honest cost, stated rather than hidden: the retry's recorded
    # `run_order` describes the order its PENDING rows ran, while its reused
    # rows ran in the previous attempt's order. `reuse_manifest.json` names
    # which rows came from where, so the log remains readable, but a reader
    # reconstructing a single execution sequence for a partially-reused
    # iteration must consult both. Drift protection is unharmed: each row was
    # still measured in a randomized order within its own attempt.
    for key in ("factor_ids", "kind", "resolution", "generators", "aliases",
                "held_fixed", "finalists", "folded_on"):
        if _canonical(prior.get(key)) != _canonical(candidate.get(key)):
            return None

    prior_rows, cand_rows = _planned(prior), _planned(candidate)
    if set(prior_rows) != set(cand_rows):
        return None
    for idx, cand_row in cand_rows.items():
        p = prior_rows[idx]
        if not _levels_match(p.get("levels") or {}, cand_row.get("levels") or {}):
            return None
        if p.get("role") != cand_row.get("role"):
            return None
        if p.get("replicate") != cand_row.get("replicate"):
            return None

    out = dict(candidate)
    seeds = prior.get("workload_seeds")
    if isinstance(seeds, dict):
        out["workload_seeds"] = dict(seeds)
        # And the per-row env the seed was injected into, so the row that
        # EXECUTES carries the same draw the matrix records. A payload whose
        # `workload_seeds` and `apply.env` disagreed would register one seed
        # and run another.
        out["rows"] = [
            {**row, "apply": dict(_apply_of(prior, row["row_index"]))}
            for row in (candidate.get("rows") or ())
        ]
    elif "workload_seeds" in out:
        # The prior attempt recorded no seeds, so neither may this one:
        # otherwise a reused row would be compared against a seed it never
        # carried.
        del out["workload_seeds"]
    if "paired" in prior:
        out["paired"] = prior["paired"]
    return out


def _iteration_of(iter_dir: Path) -> int | None:
    try:
        return int(Path(iter_dir).name.split("-")[1])
    except (IndexError, ValueError):
        return None


def _contract_hash(work_dir: Path) -> str:
    """The epoch's recorded adapter-contract hash, or ``""`` when none.

    Read via ``adapter_contract.read_contract`` so the document/sidecar
    agreement check runs here too — a work_dir whose contract and sidecar
    disagree is not a work_dir whose rows may be carried forward.
    """
    from orchestrator.optimize import adapter_contract as ac

    try:
        doc = ac.read_contract(Path(work_dir))
    except ac.AdapterContractDrift:
        # Deliberately not re-raised: an unreadable contract is a reason to
        # REFUSE reuse, not a reason to end the campaign from inside a
        # planner. The row-level guard raises on real drift; this is the
        # planner declining to reason about a contract it cannot read.
        return "\x00unreadable"
    if not doc:
        return ""
    return ac.contract_hash(doc)


def plan_reuse(
    work_dir: Path,
    *,
    iter_dir: Path,
    payload: dict,
    policy_hash: str,
    epoch: int = 1,
    enabled: bool = True,
) -> ReusePlan:
    """Which of ``payload``'s rows a previous attempt already measured.

    Pure with respect to the campaign: reads artifacts, writes nothing,
    decides no state transition. ``payload`` must already be the
    carry-forward payload (see ``carry_forward_payload``) — that is, the
    design this attempt registers, with the prior attempt's draws.

    Reuse is refused WHOLESALE, with a reason, rather than partially, whenever
    the apparatus or the pre-registration differs. A partial reuse across a
    changed instrument would put rows measured two ways into one fit, which is
    the defect the adapter-contract guard exists to prevent.
    """
    planned = _planned(payload)
    all_indices = sorted(planned)
    if not enabled:
        return ReusePlan(pending_indices=all_indices,
                         refused="reuse disabled for this campaign")

    # TERMINAL DISCRIMINATION IS NEVER REUSED — enforced here as well as in
    # ``carry_forward_payload``, deliberately. The two are separate entry points:
    # a caller can reach this function with a payload it assembled itself, and
    # confirm's guarantee (fresh finalist measurements, a paired bound over
    # replicates that share a draw) is too important to rest on the caller
    # having gone through the other function first.
    if str(payload.get("kind") or "") in NEVER_REUSABLE_KINDS:
        return ReusePlan(
            pending_indices=all_indices,
            refused=(
                "terminal discrimination measures its finalists FRESHLY: a "
                "shortlist_replicate round rests its comparison on new "
                "measurements rather than the fitted surface, and a second "
                "round is spent because the first did not discriminate — so "
                "repeating its workload could not help. Its paired bound also "
                "zips replicates that must share a workload draw."
            ),
        )

    work_dir, iter_dir = Path(work_dir), Path(iter_dir)
    this_iter = _iteration_of(iter_dir)
    runs_root = work_dir / "runs"
    if not runs_root.exists():
        return ReusePlan(pending_indices=all_indices)

    live_contract = _contract_hash(work_dir)
    if live_contract == "\x00unreadable":
        return ReusePlan(
            pending_indices=all_indices,
            refused=("the epoch's adapter_contract.json could not be read "
                     "(document/sidecar hash disagreement); re-measuring "
                     "rather than reusing rows whose instrument cannot be "
                     "identified"),
        )

    # Candidate source iterations: every EARLIER iteration dir, newest first.
    # Newest first because a later attempt's rows were measured under an
    # apparatus closer to the current one.
    candidates: list[Path] = []
    for d in sorted(runs_root.glob("iter-*"), key=lambda p: _iteration_of(p) or 0,
                    reverse=True):
        n = _iteration_of(d)
        if n is None or (this_iter is not None and n >= this_iter):
            continue
        candidates.append(d)

    # The FIRST refusal is remembered even when a later candidate yields
    # nothing either. Dropping it was a real defect this module exists to
    # avoid: "everything was re-measured and nothing said why" is precisely
    # the missing-progress-signal failure, and a refusal reason that never
    # reaches `reuse_manifest.json` is invisible to the human reading it.
    refusal = ""
    refusal_src: int | None = None
    for src in candidates:
        plan = _plan_from(
            src, payload=payload, policy_hash=policy_hash, epoch=epoch,
            live_contract=live_contract, planned=planned,
        )
        if plan is None:
            continue
        if plan.rows:
            return plan
        if plan.refused and not refusal:
            refusal, refusal_src = plan.refused, plan.source_iteration
    return ReusePlan(pending_indices=all_indices, refused=refusal,
                     source_iteration=refusal_src)


def _plan_from(src: Path, *, payload: dict, policy_hash: str, epoch: int,
               live_contract: str, planned: dict[int, dict]) -> ReusePlan | None:
    """A plan built from one source iteration, or ``None`` if unusable."""
    from orchestrator.optimize import artifacts

    src_matrix_path = src / "design_matrix.json"
    if not src_matrix_path.exists():
        return None
    try:
        src_payload = json.loads(src_matrix_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    src_iter = _iteration_of(src)

    # ── guard 1: the pre-registration ────────────────────────────────────
    src_hash = str(src_payload.get("policy_hash") or "")
    if src_hash != str(policy_hash or ""):
        return ReusePlan(
            pending_indices=sorted(planned),
            refused=(
                f"iter-{src_iter} was registered under policy_hash "
                f"{src_hash[:12] or '(absent)'} but this epoch's policy hashes "
                f"to {str(policy_hash)[:12]}; a row scheduled by a different "
                f"pre-registration is not a measurement of this experiment"
            ),
            source_iteration=src_iter,
        )

    # ── guard 6: the epoch ───────────────────────────────────────────────
    src_epoch = src_payload.get("epoch")
    if src_epoch is not None and int(src_epoch) != int(epoch):
        return ReusePlan(
            pending_indices=sorted(planned),
            refused=(f"iter-{src_iter} belongs to epoch {src_epoch}, not "
                     f"epoch {epoch}"),
            source_iteration=src_iter,
        )

    # ── guard 2: the instrument ──────────────────────────────────────────
    src_contract = str(src_payload.get("adapter_contract_hash") or "")
    if src_contract and live_contract and src_contract != live_contract:
        return ReusePlan(
            pending_indices=sorted(planned),
            refused=(
                f"iter-{src_iter} was measured under adapter contract "
                f"{src_contract[:12]} but this epoch records "
                f"{live_contract[:12]}; an apparatus change is an epoch "
                f"boundary, not an edit, so its rows cannot be carried across it"
            ),
            source_iteration=src_iter,
        )

    rows_out: list[dict] = []
    verdicts: list[RowVerdict] = []
    pending: list[int] = []
    by_index: dict[int, dict] = {}
    for row in artifacts.read_runs(src):
        idx = row.get("row_index")
        if isinstance(idx, int) and idx not in by_index:
            # First write wins. `runs.jsonl` is append-only and a duplicate
            # index is already a fidelity violation upstream; taking the first
            # keeps this deterministic rather than order-dependent.
            by_index[idx] = row

    for idx in sorted(planned):
        prior = by_index.get(idx)
        if prior is None:
            pending.append(idx)
            verdicts.append(RowVerdict(idx, False, "not measured by the prior attempt"))
            continue

        status = str(prior.get("status") or "")
        if status not in REUSABLE_STATUSES:
            pending.append(idx)
            verdicts.append(RowVerdict(
                idx, False,
                f"status {status!r} is re-measured, not reused: a failed row is "
                f"a measurement failure a re-run repairs",
                source_iteration=src_iter,
            ))
            continue

        # ── guard 3a: coded levels ───────────────────────────────────────
        if not _levels_match(planned[idx].get("levels") or {},
                             prior.get("levels") or {}):
            pending.append(idx)
            verdicts.append(RowVerdict(
                idx, False, "recorded levels differ from the registered row",
                source_iteration=src_iter))
            continue

        # ── guard 3b + guard 4: the applied config, INCLUDING the seed ───
        #
        # Levels alone are not the configuration: a config_patch factor's
        # realized patch, a CLI flag, or an env entry (which is where the
        # workload seed lives) is the difference between two runs whose
        # `levels` are identical.
        #
        # WHERE THE COMPARISON READS FROM, and why it is the matrix rather than
        # the run row: `stage_runner._run_row` does not record `apply` in
        # `runs.jsonl` (verified — a row carries levels/role/replicate/status/
        # response/held_out/verdicts/instrumentation and no `apply`). So the
        # config a row actually ran under is NOT recoverable from the run log;
        # the only durable record is the `design_matrix.json` that registered
        # it. That is sound, because the matrix IS the pre-registration and
        # `check_fidelity` already refuses any run whose levels drifted from it
        # — but it does mean the seed check has to compare the two MATRICES at
        # the same row index, which is what happens here.
        #
        # A row row-logged without `apply` therefore falls back to the source
        # matrix's entry. If the source matrix has no entry for this row index,
        # the row's configuration cannot be established and it is re-measured
        # rather than assumed to match.
        want_apply = planned[idx].get("apply") or {}
        got_apply = prior.get("apply")
        if not isinstance(got_apply, dict) or not got_apply:
            got_apply = _apply_of(src_payload, idx)
        if not got_apply and want_apply:
            pending.append(idx)
            verdicts.append(RowVerdict(
                idx, False,
                "the prior attempt recorded no applied configuration for this "
                "row, so the configuration it measured cannot be established",
                source_iteration=src_iter))
            continue
        if _canonical(_comparable_apply(want_apply)) != _canonical(
                _comparable_apply(got_apply)):
            pending.append(idx)
            verdicts.append(RowVerdict(
                idx, False, "the applied configuration (levels, flags, patches "
                            "or workload seed) differs from the registered row",
                source_iteration=src_iter))
            continue

        reused = dict(prior)
        reused["reused_from"] = {"iteration": src_iter, "epoch": int(epoch)}
        rows_out.append(reused)
        verdicts.append(RowVerdict(
            idx, True, f"carried forward from iter-{src_iter} (status {status})",
            source_iteration=src_iter,
            duration_ms=int(prior.get("duration_ms") or 0),
        ))

    return ReusePlan(rows=rows_out, pending_indices=pending, verdicts=verdicts,
                     source_iteration=src_iter)


def _comparable_apply(apply: dict) -> dict:
    """``apply`` reduced to the fields that identify the configuration.

    ``cli_args`` / ``env`` / ``patches`` / ``finalist`` are the configuration.
    The workload seed lives INSIDE ``env`` and is therefore compared here —
    that is guard 4, and it needs no separate branch: ``carry_forward_payload``
    puts the prior attempt's seed into the registered row, so agreement here
    means the row about to be reused is registered at the very draw it was
    measured at, and disagreement means the carry-forward did not happen and
    the row must be re-measured.

    Nothing else from ``apply`` is compared. ``env`` is taken wholesale rather
    than reduced to the seed key, so an author-declared environment variable
    that changed between attempts also blocks reuse — the conservative
    direction, and the right one: an env entry a factor renders IS part of the
    configuration.
    """
    return {
        "cli_args": list(apply.get("cli_args") or ()),
        "env": {str(k): v for k, v in (apply.get("env") or {}).items()},
        "patches": apply.get("patches") or [],
        "finalist": apply.get("finalist"),
    }


def write_manifest(iter_dir: Path, manifest: dict) -> Path:
    """Persist the reuse decision beside the iteration's other artifacts.

    Written whether or not anything was reused, and in particular written when
    reuse was REFUSED: "this attempt re-measured everything, and here is why"
    is the fact a reader chasing a 14-hour campaign needs, and it is invisible
    if only successful reuse leaves a trace.
    """
    from orchestrator.util import atomic_write

    iter_dir = Path(iter_dir)
    iter_dir.mkdir(parents=True, exist_ok=True)
    target = iter_dir / MANIFEST_FILE
    atomic_write(target, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return target
