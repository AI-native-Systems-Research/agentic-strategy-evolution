"""One comparison vocabulary for every check in an optimization campaign.

``manipulation`` (did the lever engage?), ``response.constraints`` (is this
config admissible?), ``response.regimes`` (does it hold in every regime?)
and ``design_space.invariants`` (did we stay inside the declared design
space?) all share the shape::

    {observable | metric: <dotted path>, op: <comparator>, value: <expected>}

Optional ``when`` / ``when_not`` restrict which levels a check applies to,
because a check is often meaningless at one level (a batch-size assertion
says nothing when batching is off).
"""
from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Any

OPS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}

_MISSING = object()


@dataclass(frozen=True)
class Verdict:
    """Outcome of one predicate evaluation."""

    ok: bool
    detail: str = ""
    skipped: bool = False
    missing: bool = False


def _resolve(path: str, observed: dict) -> Any:
    """Walk a dotted path through nested dicts; ``_MISSING`` when absent."""
    cur: Any = observed
    for part in str(path).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _guard_excludes(pred: dict, level: Any) -> bool:
    """Whether a ``when`` / ``when_not`` guard excludes this level."""
    def _members(raw):
        return raw if isinstance(raw, (list, tuple)) else [raw]

    if "when" in pred:
        return level not in _members(pred["when"])
    if "when_not" in pred:
        return level in _members(pred["when_not"])
    return False


def evaluate(pred: dict, observed: dict, *, level: Any = None) -> Verdict:
    """Evaluate one predicate against an observation dict."""
    op_name = pred.get("op")
    if op_name not in OPS:
        raise ValueError(
            f"predicate op must be one of {sorted(OPS)} (got {op_name!r})",
        )

    if "when" in pred and "when_not" in pred:
        raise ValueError(
            "predicate cannot have both 'when' and 'when_not' — they are complementary "
            "level guards; supply one or neither",
        )

    if _guard_excludes(pred, level):
        return Verdict(ok=True, skipped=True,
                       detail=f"skipped at level {level!r}")

    path = pred.get("observable") or pred.get("metric")
    if not path:
        raise ValueError("predicate needs an 'observable' (or 'metric') path")

    got = _resolve(path, observed)
    if got is _MISSING:
        return Verdict(
            ok=False,
            detail=(f"{path!r} not present in the observation — the target did "
                    f"not emit it, so the check cannot pass"),
            missing=True,
        )

    want = pred.get("value")
    if want == "{level}":
        want = level

    ok = bool(OPS[op_name](got, want))
    return Verdict(
        ok=ok,
        detail=f"{path} = {got!r} {op_name} {want!r} -> {'ok' if ok else 'FAIL'}",
    )


def is_trivial(pred: dict) -> bool:
    """Whether a predicate is so weak it cannot meaningfully fail.

    A lazy check manufactures false confidence and is worse than none: it
    makes a broken lever look verified. Mirrors the floor
    ``validate_evidence`` applies to principles.
    """
    op_name = pred.get("op")
    value = pred.get("value")
    if value == "{level}":
        return False
    if op_name == "!=" and value is None:
        return True
    if op_name == ">" and isinstance(value, (int, float)) and value == 0:
        return True
    if op_name in (">=",) and isinstance(value, (int, float)) and value == 0:
        return True
    return False
