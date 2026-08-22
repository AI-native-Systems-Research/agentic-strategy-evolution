"""Three guards over the TARGET ADAPTER -- the author-written ``run_command``.

``policy.json`` is content-hashed and ``_load_or_compile_policy`` hard-aborts on
a mismatch, because a pre-registered policy that changed inside an epoch is not
a pre-registration. That discipline covered exactly one half of the apparatus.
A pre-registered design assumes the MEASUREMENT INSTRUMENT is fixed for the
epoch's duration too, and until this module there was no equivalent guard on
the adapter at all -- a campaign author could (and did) edit the adapter's
output schema three times mid-epoch, and every artifact stayed schema-valid.

Everything here is pure Python reading one response dict at a time. No model
call, no measurement interpretation, no next-state decision: a drifted contract
raises ``AdapterContractDrift`` (which ``stage_runner`` converts into the same
campaign-level abort a policy-hash mismatch produces), and the other two guards
produce a ROW failure through ``execute_design``'s existing taxonomy. None of
the three is a new branch in the compiled epoch.

The three guards, and the real defect each closes (field test, two campaigns
against one simulator, seven adapter defects between them):

GUARD 1 -- the contract fingerprint (``adapter_contract.json`` +
``adapter_contract.sha256`` at the work-dir root). The adapter's output CONTRACT
-- key names and value TYPES, never values -- is captured from the first
successful row of the epoch and re-checked on every later row. Defect 7: the
adapter's output schema was edited three times mid-epoch; rows measured before
each edit carried ``null`` for the new keys, and ``_fitting_responses``' coerce
put a ``None`` up against a float, killing an entire iteration at fit time after
~2 hours of measurement. The keys had drifted on the very first row after each
edit; nothing looked.

GUARD 2 -- output freshness (``check_freshness``). Nous cannot police an
adapter's internals, but it can assert what it observes: two rows at DIFFERENT
factor levels whose entire response object is byte-identical is a strong signal
of a cached or stale result. Defect 1: the adapter reused a stale metrics file
whenever the target exited non-zero, so a factor level that PANICKED was
recorded as "no effect, identical to baseline", and three factors were briefly
believed live on that basis.

GUARD 3 -- the declared self-check (``check_self_checks``). Nous cannot know an
objective's semantics, so it cannot detect a self-contradictory row itself; it
CAN require the author to state the invariant that defines the objective and
then enforce it per row. The general case is an objective that is the EXTREMUM OF
A FEASIBLE SET -- the coarsest mesh that still converged, the largest rate that
was sustained, the smallest replica count that held a bound. There the adapter had
to decide set membership, so a bug in that decision yields a flattering number
with no outward sign of being wrong; the self-check is the membership test
restated where Nous can apply it. Defect 2 was one instance: two growth criteria
combined with ``and`` instead of ``or``, so 8 of 12 rows reported a sustained rate
while their own recorded backlog slope said that rate was growing. One declared
self-check would have failed each of those 8 rows at the moment it was measured
rather than after the epoch.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from orchestrator.optimize.predicates import evaluate

logger = logging.getLogger(__name__)

CONTRACT_FILE = "adapter_contract.json"
CONTRACT_HASH_FILE = "adapter_contract.sha256"
#: How deep the fingerprint records nested key TYPES before falling back to key
#: names only. Two covers the shapes real adapters emit (a top-level metric, and
#: one telemetry/cfg block beneath it) while keeping the fingerprint far smaller
#: than the payload it describes.
_MAX_NEST_DEPTH = 2

CONTRACT_VERSION = 2


class AdapterContractDrift(RuntimeError):
    """The adapter's output contract changed inside an epoch.

    Raised by ``check_contract``; ``stage_runner`` re-raises it as
    ``OptimizationAborted`` so it lands on exactly the path a ``policy.sha256``
    mismatch does. It is deliberately NOT a row failure: a row failure says
    "re-run this configuration", and re-running a row against a changed
    instrument produces a number that still cannot be compared to the rows
    measured before the change.
    """


# ── the fingerprint ────────────────────────────────────────────────────────

def _type_name(value: Any, *, _depth: int = 0) -> str:
    """The fingerprinted type of one response value.

    WHAT IS FINGERPRINTED, AND WHY IT IS TYPES AND NOT VALUES. The sorted set of
    top-level keys is the minimum, and it is not enough on its own: defect 7's
    signature was a key PRESENT with a ``null`` value on the rows measured
    before the adapter learned to compute it, which a key-set fingerprint reads
    as no drift at all. So each key carries its value's type as well. Values
    themselves are excluded because they legitimately change on every row --
    that variation IS the measurement.

    ``null`` is its own type name rather than being folded into whatever type
    the key usually holds. That is the whole point: ``{"slope": 0.4}`` and
    ``{"slope": null}`` must not fingerprint alike.

    ``int`` and ``float`` are deliberately NOT unified into one "number" type.
    An adapter that starts emitting ``"3"`` where it emitted ``3`` is caught by
    any type-aware fingerprint, but one that moves a count from ``3`` to ``3.0``
    is a real change in what the instrument reports and is cheap to look at
    once; conflating them buys nothing and hides a class of rounding change.
    ``bool`` is separated from ``int`` for the same reason (and because Python
    would otherwise call ``True`` an ``int``, which is how a bool/int level
    mismatch failed 67 of 67 runs on a real campaign).

    Nesting carries key names AND their types, to a bounded depth
    (``_MAX_NEST_DEPTH``), rather than key names alone. Names alone reproduced
    defect 7 exactly one level down: ``{"telemetry": {"rate": 2.0}}`` and
    ``{"telemetry": {"rate": null}}`` both fingerprinted as
    ``object{rate}`` and ``diff_contract`` reported no drift -- the same
    real-value-becomes-null signature the top level was hardened against, in a
    place a campaign genuinely reads, since ``predicates._resolve`` walks dotted
    paths through dicts so ``telemetry.rate`` can be an objective or a
    ``self_check`` observable.
    The depth is bounded rather than unbounded because an adapter's arbitrarily
    deep telemetry would otherwise make the fingerprint a second copy of the
    payload and drift on per-row content; below the cap the summary falls back to
    key names, and a campaign whose declared observables sit that deep is outside
    what this guard can see -- stated rather than implied.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        if _depth < _MAX_NEST_DEPTH:
            inner = ",".join(
                f"{k}:{_type_name(value[k], _depth=_depth + 1)}"
                for k in sorted(value, key=str)
            )
        else:
            inner = ",".join(sorted(str(k) for k in value))
        return f"object{{{inner}}}"
    if isinstance(value, (list, tuple)):
        kinds = sorted({_scalar_kind(v) for v in value})
        return f"array[{','.join(kinds)}]"
    return type(value).__name__


def _scalar_kind(value: Any) -> str:
    """A list element's type, summarized without recursing into it."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return type(value).__name__


def fingerprint(response: dict) -> dict[str, str]:
    """The adapter's output contract for one response: ``{key: type_name}``."""
    return {str(k): _type_name(v) for k, v in (response or {}).items()}


def contract_hash(contract: dict) -> str:
    """sha256 over a canonical encoding of the contract document.

    Canonical (sorted keys, no whitespace) for the same reason
    ``build_cache_key`` is: hash equality must not depend on dict insertion
    order, or a re-serialization would read as drift.
    """
    payload = json.dumps(contract, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── persistence: the same sidecar convention policy.sha256 uses ────────────

def write_contract(work_dir: Path, contract: dict) -> Path:
    """Persist the contract document and its hash sidecar, together.

    Two files written in one call, exactly as ``policy.write_policy`` writes
    ``policy.json`` and ``policy.sha256`` together -- a pair that can disagree
    is a pair that means nothing. Lives at the WORK-DIR ROOT, not under
    ``runs/iter-N/``, because the contract is epoch-scoped: an epoch spans
    several iterations and the whole claim is that the instrument did not move
    between them.
    """
    from orchestrator.util import atomic_write

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    target = work_dir / CONTRACT_FILE
    atomic_write(target, json.dumps(contract, indent=2, sort_keys=True) + "\n")
    atomic_write(work_dir / CONTRACT_HASH_FILE, contract_hash(contract) + "\n")
    return target


def read_contract(work_dir: Path) -> dict | None:
    """The recorded contract, or ``None`` when this epoch has not captured one.

    A hash sidecar that disagrees with the document raises: the sidecar exists
    so that an edit to ``adapter_contract.json`` cannot pass itself off as the
    contract the epoch registered, which is the same reasoning
    ``_load_or_compile_policy`` applies to ``policy.json``.
    """
    path = Path(work_dir) / CONTRACT_FILE
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterContractDrift(
            f"{CONTRACT_FILE} could not be read ({exc}). It is the record of "
            f"what the target adapter emitted on this epoch's first successful "
            f"row; without it no later row can be shown comparable to it.",
        ) from exc
    # FAILS CLOSED WHEN THE SIDECAR IS ABSENT, not just when it disagrees. The
    # condition used to be `sidecar.exists() and <mismatch>`, so DELETING the
    # sidecar skipped the check instead of failing it -- the same hole that let a
    # tampered `policy.json` run to completion once `policy.sha256` was removed.
    # `write_contract` writes the document and its sidecar in one call, so a
    # document present without its sidecar means the sidecar was removed after
    # capture, which is exactly the edit the pair exists to detect.
    sidecar = Path(work_dir) / CONTRACT_HASH_FILE
    if not sidecar.exists():
        raise AdapterContractDrift(
            f"{CONTRACT_FILE} exists but its hash sidecar {CONTRACT_HASH_FILE} "
            f"does not. `write_contract` writes the pair together, so the sidecar "
            f"was removed after capture, and without it the recorded contract "
            f"cannot be shown to be the one this epoch captured -- every later "
            f"row's comparability rests on a record nothing vouches for. Restore "
            f"{CONTRACT_HASH_FILE}, or start a NEW epoch so the adapter's contract "
            f"is captured and hashed afresh. AN APPARATUS CHANGE IS AN EPOCH "
            f"BOUNDARY, NOT AN EDIT.",
        )
    if sidecar.read_text().strip() != contract_hash(doc):
        raise AdapterContractDrift(
            f"{CONTRACT_FILE} was edited after capture (hash mismatch with "
            f"{CONTRACT_HASH_FILE}). The adapter's registered output contract "
            f"cannot change inside an epoch -- editing the record instead of "
            f"the adapter would certify comparability that was never checked.",
        )
    return doc


def capture_contract(
    work_dir: Path, response: dict, *, epoch: int, row_index: int,
    stage: str = "",
) -> dict:
    """Record the epoch's adapter contract from its first successful row."""
    contract = {
        "contract_version": CONTRACT_VERSION,
        "epoch": int(epoch),
        "captured_at": {"stage": str(stage or ""), "row_index": int(row_index)},
        "keys": fingerprint(response),
    }
    write_contract(work_dir, contract)
    logger.info(
        "adapter contract captured from the epoch's first successful row "
        "(stage=%s row_index=%s): %d key(s). Every later row is checked "
        "against it.", stage, row_index, len(contract["keys"]),
    )
    return contract


# ── GUARD 1: drift detection ──────────────────────────────────────────────

def diff_contract(recorded: dict, response: dict) -> tuple[list[str], list[str], list[str]]:
    """``(added, removed, changed)`` key names between a contract and a response.

    ``changed`` entries are rendered ``key: was -> now`` so the abort message
    can name what moved without the caller re-deriving it.
    """
    expected: dict = dict((recorded or {}).get("keys") or {})
    observed = fingerprint(response)
    added = sorted(set(observed) - set(expected))
    removed = sorted(set(expected) - set(observed))
    changed = sorted(
        f"{k}: {expected[k]} -> {observed[k]}"
        for k in (set(expected) & set(observed))
        if expected[k] != observed[k]
    )
    return added, removed, changed


def check_contract(recorded: dict, response: dict, *, row_index: int) -> None:
    """Raise ``AdapterContractDrift`` when this row's contract differs. Else return.

    WHAT COUNTS AS DRIFT, AND WHY AN ADDED KEY ABORTS TOO. A key disappearing
    or a type changing is unarguable: a campaign's predicates, its objective,
    and its constraints all address keys by name, and a key that changed type
    changed what the number means (defect 7's ``null`` is exactly this case, and
    is why the fingerprint records ``null`` as its own type).

    An ADDED key is an abort as well, and this is the decision worth defending,
    because the tempting answer is a warning: an extra key is additive, nothing
    downstream reads it, and no existing number changes. That reasoning is
    right about the ROW and wrong about the EPOCH. The only way an adapter grows
    a key between two rows of one pre-registered design is that the adapter was
    edited mid-epoch -- which is defect 7 exactly, and in defect 7 the added key
    was the *carrier* of the damage: the rows measured BEFORE the edit are the
    ones that end up ``null``, and they are already on disk and unfixable by the
    time the new key appears. Warning on the addition would put the loud signal
    at the one moment the damage is still cheap to act on and then let the
    campaign run on to fail at fit time two hours later, which is the behaviour
    this guard exists to replace. A warning would also make the guard
    order-dependent in a way no author could reason about: whether an edit
    aborts or merely warns would depend on which side of the edit the first
    successful row happened to land.

    The one situation an author legitimately wants is "I improved the adapter,
    keep going" -- and the correct expression of that is not a softer check. An
    apparatus change is an EPOCH BOUNDARY: finish or end this epoch and let the
    next one capture the new contract. The message says so.
    """
    added, removed, changed = diff_contract(recorded, response)
    if not (added or removed or changed):
        return
    parts: list[str] = []
    if removed:
        parts.append(f"key(s) that disappeared: {', '.join(removed)}")
    if added:
        parts.append(f"key(s) that appeared: {', '.join(added)}")
    if changed:
        parts.append(f"key(s) whose type changed: {'; '.join(changed)}")
    where = (recorded or {}).get("captured_at") or {}
    raise AdapterContractDrift(
        f"the target adapter's output contract CHANGED MID-EPOCH at row "
        f"{row_index}: " + "; ".join(parts) + ". "
        f"The contract was captured from this epoch's first successful row "
        f"(stage={where.get('stage') or '?'}, row_index="
        f"{where.get('row_index', '?')}) and recorded in {CONTRACT_FILE}. "
        f"A pre-registered design assumes the MEASUREMENT INSTRUMENT is fixed "
        f"for the epoch's duration, so this invalidates comparability across "
        f"rows: the rows already on disk were measured by a different "
        f"instrument from this one, and no re-run repairs them (a key that is "
        f"absent or null on an earlier row stays that way). A value becoming "
        f"null is the same defect as a key vanishing -- an unknown is not a "
        f"measurement. AN APPARATUS CHANGE IS AN EPOCH BOUNDARY, NOT AN EDIT: "
        f"revise the adapter and start a NEW epoch so the next compilation "
        f"registers the instrument it will actually measure with. Do not edit "
        f"{CONTRACT_FILE} -- its hash sidecar is checked.",
    )


# ── GUARD 2: output freshness ─────────────────────────────────────────────

def canonical_response(response: dict, *, ignore: set[str] | None = None) -> str:
    """A canonical encoding of a response, for byte-identity comparison."""
    ignore = ignore or set()
    trimmed = {k: v for k, v in (response or {}).items() if str(k) not in ignore}
    return json.dumps(trimmed, sort_keys=True, separators=(",", ":"), default=str)


def check_freshness(
    response: dict, previous: dict | None, *, levels: dict,
    previous_levels: dict | None, row_index: int, previous_row_index: int | None,
    constant_fields: set[str] | None = None,
) -> str | None:
    """Error text when this response looks stale, else ``None``.

    THE CLAIM, precisely. Nous invokes ``run_command`` and reads the objective
    from its stdout; it cannot see whether the adapter recomputed anything.
    What it CAN assert is that an invocation produced output on THIS call -- and
    a response whose ENTIRE object is byte-identical to the immediately
    preceding row's, while the factor levels differ, is a strong signal that a
    cached or stale result was served (defect 1: a stale metrics file re-read
    whenever the target exited non-zero, reported as a clean null result).

    HOW THE FALSE-POSITIVE RISK IS BOUNDED. Two different level combinations CAN
    legitimately produce the identical OBJECTIVE value -- observed for real, two
    cache policies both measuring exactly 1.3125 -- so comparing objectives
    alone would fire on correct data. Three things bound it instead:

      1. THE FULL RESPONSE OBJECT, never just the objective. A real adapter
         emits the objective alongside diagnostics, counters, and timings; for
         every one of those to coincide to the last bit across two different
         configurations is a different order of coincidence from two objectives
         tying. In the real 1.3125 case the two rows' full objects differed.
      2. ONLY THE IMMEDIATELY PRECEDING ROW, never the whole history. A stale
         file is served on the invocation that follows the one that wrote it,
         which is the adjacent pair; widening the comparison to all prior rows
         would multiply the coincidence budget by the row count for no extra
         detection.
      3. A CALLER-DECLARED ALLOWLIST (``response.constant_fields``) for fields
         that legitimately never move -- a schema version, a host name, a
         workload identifier. Those are excluded from the comparison, so
         declaring them makes the check STRICTER on what remains rather than
         weaker: the surviving fields are exactly the ones that should have
         varied.

    The residual risk is a genuinely degenerate adapter: one that emits nothing
    but the objective, at a coarse quantization, with no diagnostics at all. For
    such a target two adjacent rows can tie legitimately and this fires
    wrongly. That is a ROW failure, not a campaign abort -- one row is lost,
    the fit proceeds on the complete-row subset (spec §4 D2), and the recorded
    reason names both rows so an author can see immediately whether the tie was
    real. Bounding it further would mean either weakening the check on adapters
    that DO emit diagnostics (most of them) or asking Nous to judge which ties
    are plausible, which it cannot do. An author whose adapter is genuinely
    this thin should widen what it reports -- which §7.7 of the authoring guide
    asks for on independent grounds.
    """
    if previous is None:
        return None
    if dict(levels or {}) == dict(previous_levels or {}):
        # Same configuration: an identical response is the EXPECTED outcome of a
        # deterministic target, and a replicate block is built out of exactly
        # this. Nothing to say.
        return None
    ignore = {str(f) for f in (constant_fields or set())}
    if canonical_response(response, ignore=ignore) != canonical_response(
        previous, ignore=ignore,
    ):
        return None
    shown = canonical_response(response, ignore=ignore)
    return (
        f"row {row_index} returned a response object BYTE-IDENTICAL to row "
        f"{previous_row_index}'s while the factor levels differ "
        f"({dict(previous_levels or {})} -> {dict(levels or {})}): "
        f"{shown[:400]}. The invocation must produce output on THIS call; an "
        f"identical object across different configurations is the signature of "
        f"an adapter serving a CACHED OR STALE result -- for instance re-reading "
        f"a metrics file it failed to overwrite when the target exited non-zero, "
        f"which records a configuration that ABORTED as one with no effect. "
        f"This row is failed rather than fitted. If the two configurations "
        f"genuinely measure identically in every reported field, declare the "
        f"fields that legitimately never vary under "
        f"response.constant_fields, or report a diagnostic alongside the "
        f"objective so equal objectives are distinguishable from a stale read."
    )


# ── GUARD 3: declared self-checks ─────────────────────────────────────────

def check_self_checks(self_check: list, response: dict) -> list[dict]:
    """One verdict per declared ``response.self_check`` predicate.

    Evaluated against the row's OWN response, with no level guard: a self-check
    states an invariant the reported objective must satisfy in order to BE the
    objective ("the largest rate that was sustained" must have a non-growing
    backlog), and such an invariant does not hold only at some levels.

    Deliberately the same ``{observable|metric, op, value}`` shape and the same
    ``predicates.evaluate`` the ``manipulation``, ``constraints``, and
    ``design_space.invariants`` checks use. A second predicate language for the
    same job would be a second thing to learn, a second thing to validate, and
    a second place for the two to disagree.
    """
    verdicts: list[dict] = []
    for pred in self_check or []:
        verdict = evaluate(pred, response, level=None)
        verdicts.append({
            "id": pred.get("id") or pred.get("observable") or pred.get("metric"),
            "kind": "self_check",
            "ok": verdict.ok,
            "detail": verdict.detail,
            "skipped": verdict.skipped,
            "missing": verdict.missing,
        })
    return verdicts


def self_check_error(verdicts: list[dict]) -> str | None:
    """Row-failure text naming every violated self-check, or ``None``.

    A VIOLATION IS A ROW FAILURE, NOT A CAMPAIGN ABORT, and the asymmetry is
    the point. A self-check failing says this ROW's reported objective
    contradicts its own recorded diagnostic -- the row is not a measurement of
    anything and must not reach the fit -- but it says nothing about the other
    rows, and in the real defect 4 of 12 rows were fine. Failing the row
    excludes it and records why; aborting the campaign would throw away the
    rows that were sound.
    """
    bad = [v for v in verdicts if (not v["ok"]) and not v["skipped"]]
    if not bad:
        return None
    return (
        "response.self_check violated: "
        + "; ".join(f"{v['id']!r}: {v['detail']}" for v in bad)
        + ". The row reported an objective value that its OWN recorded "
        "diagnostic contradicts, so it is not a measurement of the declared "
        "response and is excluded from the fit. A self-check is the assertion "
        "that the reported answer satisfies the predicate that DEFINES it; a "
        "search returning a point that violates its own acceptance test has a "
        "bug in the search, not a number worth fitting."
    )
