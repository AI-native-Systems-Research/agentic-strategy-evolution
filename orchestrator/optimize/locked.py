"""``locked_parameters`` spec fidelity on the matrix path (#246 / F1).

The reflective kind enforces ``campaign.locked_parameters`` by comparing it
against ``bundle.experiment_spec.verified_parameters`` (``validate.
_validate_locked_parameters``). A ``kind: optimization`` campaign has no
bundle: its "experiment spec" is the pre-registered design matrix plus the
target's base configuration, and the only evidence of what the target ACTUALLY
ran with is the observation each row returns. So the matrix-path check compares
each locked value against the value the target REPORTS it used, on every
measured row.

WHERE A LOCKED VALUE IS OBSERVABLE: ``optimization.locked_observables``, a map
``{locked_parameter: <dotted path into the run observation>}``. Why a new map
rather than an existing field:

  * ``design_space.invariants`` can already express ``cfg.max_seq_len == 2048``,
    but it would restate the locked VALUE (two sources of truth that can drift
    apart), and its consequence is the wrong one -- a violated invariant
    REJECTS the row and the epoch carries on, whereas a locked-value deviation
    means every row measures an experiment other than the pre-registered one.
  * Adding an ``observable`` to each ``locked_parameters`` entry would change
    that field's shape, which the reflective kind's bundle comparison reads as
    ``key: value``.

The map says only WHERE; the value stays in ``locked_parameters``. Paths use
the same dotted-path convention and the same ``==`` comparator as
``manipulation`` predicates (``predicates.py``), so "the target echoed its
config" is read identically by every check.

A locked parameter with no declared observable CANNOT be enforced here -- Nous
has no way to see what the target used. Validation therefore REJECTS it unless
the author acknowledges it in ``optimization.unverified_locks`` with a reason;
an acknowledged lock is a ``WARN:`` and is recorded in report.json
(``provenance.waivers``), so an unenforceable lock never reads as an enforced
one.
"""
from __future__ import annotations

from typing import Any

from orchestrator.optimize import predicates


class LockedParameterDeviation(RuntimeError):
    """A measured row ran with a value other than the locked one.

    Raised out of the sweep (``stage_runner`` converts it to
    ``OptimizationAborted``) rather than recorded as a row status: the lock is
    a property of the whole experiment, so no re-run of this row and no
    exclusion from the fit makes the remaining rows measure the pre-registered
    experiment.
    """


def locked_parameters(campaign: dict) -> dict:
    locked = (campaign or {}).get("locked_parameters")
    return dict(locked) if isinstance(locked, dict) else {}


def locked_observables(campaign: dict) -> dict[str, str]:
    opt = (campaign or {}).get("optimization") or {}
    raw = opt.get("locked_observables") if isinstance(opt, dict) else None
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def enforced(campaign: dict) -> dict[str, tuple[Any, str]]:
    """``{param: (locked_value, observable)}`` for every enforceable lock."""
    locked = locked_parameters(campaign)
    return {k: (locked[k], path) for k, path in locked_observables(campaign).items()
            if k in locked}


def validation_findings(campaign: dict) -> list[str]:
    """Cross-field rules; plain strings are errors, ``WARN:`` strings advisory."""
    locked = locked_parameters(campaign)
    observables = locked_observables(campaign)
    opt = (campaign or {}).get("optimization") or {}
    out: list[str] = []

    factor_keys: dict[str, str] = {}
    for f in (opt.get("factors") or []) if isinstance(opt, dict) else []:
        if not isinstance(f, dict):
            continue
        for k in ("id", "name"):
            if f.get(k):
                factor_keys[str(f[k])] = str(f.get("id") or f[k])
    for key in locked:
        if key in factor_keys:
            out.append(
                f"locked_parameters pins {key!r}, which is also declared as "
                f"factor {factor_keys[key]!r} in optimization.factors. A knob "
                f"cannot be both held fixed and varied: the design matrix would "
                f"vary it and every row would then deviate from the lock. Remove "
                f"it from locked_parameters (to optimize it) or from "
                f"optimization.factors (to hold it fixed)."
            )

    for key in observables:
        if key not in locked:
            out.append(
                f"optimization.locked_observables names {key!r}, which is not a "
                f"key of locked_parameters, so there is no locked value to "
                f"compare it against. If it is a typo, the parameter you meant "
                f"is silently unenforced; fix the key, or add {key!r} to "
                f"locked_parameters."
            )

    unverified = unverified_locks(campaign)
    for key in unverified:
        if key not in locked:
            out.append(
                f"optimization.unverified_locks names {key!r}, which is not a key "
                f"of locked_parameters. Fix the key or remove the entry."
            )
        elif key in observables:
            out.append(
                f"optimization.unverified_locks names {key!r}, which also has a "
                f"locked_observables entry and IS verified on every row. Remove "
                f"it from unverified_locks."
            )

    unenforced = [k for k in locked if k not in observables and k not in factor_keys]
    undeclared = [k for k in unenforced if k not in unverified]
    acknowledged = [k for k in unenforced if k in unverified]
    if undeclared:
        # AN ERROR, NOT A WARNING. A lock with no observable is unenforceable:
        # nothing Nous measures can show the target ran with it, so letting it
        # pass validation would let the campaign READ as locked when it is not.
        # The author either says where the target reports the value, or
        # acknowledges in writing that the lock is declarative only.
        out.append(
            "locked_parameter(s) "
            + ", ".join(repr(k) for k in undeclared)
            + " cannot be enforced: no entry in optimization.locked_observables "
            "says where the target reports the value it ran with, so a target "
            "that ignores the lock would measure a different experiment on every "
            "row and nothing would notice. Either declare the path "
            "(e.g. locked_observables: {max_seq_len: engine.max_seq_len}) to make "
            "a deviation a hard abort, or acknowledge the lock as unverified "
            "with a reason (optimization.unverified_locks: {<param>: <why>}); "
            "the acknowledgement is recorded in report.json."
        )
    if acknowledged:
        out.append(
            "WARN: locked_parameter(s) "
            + ", ".join(repr(k) for k in acknowledged)
            + " are declared UNVERIFIED (optimization.unverified_locks): Nous "
            "does not check the target honoured them, and report.json records "
            "that under provenance.waivers."
        )
    return out


def unverified_locks(campaign: dict) -> dict[str, str]:
    opt = (campaign or {}).get("optimization") or {}
    raw = opt.get("unverified_locks") if isinstance(opt, dict) else None
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def deviations(campaign: dict, observed: dict) -> list[str]:
    """One line per enforceable lock this observation contradicts.

    An observable that is declared but absent from a non-empty observation is
    a deviation too: like a manipulation path, a check whose input the target
    did not emit cannot pass.
    """
    out: list[str] = []
    for key, (want, path) in enforced(campaign).items():
        got = predicates._resolve(path, observed or {})
        if got is predicates._MISSING:
            out.append(
                f"{key}: locked={want!r}, but {path!r} is not present in the "
                f"run's observation (the target did not report the value it used)"
            )
        elif not predicates.OPS["=="](got, want):
            out.append(f"{key}: locked={want!r}, observed {path} = {got!r}")
    return out


def check_row(campaign: dict, observed: dict, *, row_index: int, stage: str = "") -> None:
    """Raise ``LockedParameterDeviation`` when a measured row breaks a lock.

    A row with an EMPTY observation (the run crashed, or manipulation failed
    and the row was discarded) carries no evidence either way and is skipped.
    """
    if not observed:
        return
    bad = deviations(campaign, observed)
    if not bad:
        return
    where = f"{stage} row {row_index}" if stage else f"row {row_index}"
    raise LockedParameterDeviation(
        f"locked_parameters deviation at {where} (#246/F1): the target ran "
        f"with a value other than the one this campaign pinned:\n  "
        + "\n  ".join(bad)
        + "\nEvery row would otherwise measure a different experiment than the "
        "one pre-registered, so the campaign is aborted regardless of "
        "--auto-approve. Make the target honour the locked value (or report "
        "it at the declared optimization.locked_observables path), then re-run."
    )
