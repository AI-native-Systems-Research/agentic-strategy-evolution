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
    #: On a failure, what the SHAPE of the failure says to fix -- empty on a pass.
    hint: str = ""


#: An observable the target never emitted. Distinct from an EMPTY one: here the
#: key itself is missing, so the namespace or the dotted path is the suspect.
_HINT_ABSENT = (
    "The target did not emit this observable at all: check the dotted path and "
    "that the target reports it on every run."
)

#: Present, but '' or None, against a non-empty level (issue #318). Not a type
#: problem -- both sides are usually strings -- so the TYPE hint pointed at the
#: wrong cause. The cause seen in practice is an adapter that reports a field
#: only when some other knob enables it, reasoning that it is inert otherwise.
_HINT_EMPTY = (
    "The observable is PRESENT but EMPTY, and the level is non-empty, so this "
    "is not a type mismatch: the target emitted no value for this field at this "
    "corner. An adapter that reports a field conditionally -- only when some "
    "other knob is enabled -- records '' at the corners where the condition is "
    "false, and every such row is rejected. Record the level the design matrix "
    "asked for, unconditionally; what the knob DOES at that level is a finding, "
    "not a reason to omit it from the row."
)

_HINT_VALUE = (
    "The observable is the same type as the level but a different value: the "
    "target ran a configuration other than the one requested. Check that the "
    "level actually reaches the target (its apply template, env, or "
    "config_patch)."
)


def _empty(value: Any) -> bool:
    return value is None or value == ""


def _incomparable(got: Any, want: Any) -> bool:
    """Types an ordering comparison cannot meaningfully relate.

    ``6.0 >= 8`` is a comparison that ran and was false; ``"6" >= 8`` and a
    bool against a number are not comparisons of quantities at all.
    """
    num = (int, float)
    if isinstance(got, bool) or isinstance(want, bool):
        return type(got) is not type(want)
    return isinstance(got, num) != isinstance(want, num)


def _failure_hint(got: Any, want: Any, op: str = "==") -> str:
    """Name the one shape a failed ``got <op> want`` comparison has.

    Shape depends on the OPERATOR. The equality shapes (empty / type / value)
    only make sense for ``==``; reading a failed ``!=`` as "a different value"
    or a failed ``6.0 >= 8`` as a type mismatch points the author at a cause
    that is not there -- the misdirection these hints exist to remove.
    """
    if op == "!=":
        return (
            f"The observable EQUALS {want!r}, the one value this predicate "
            f"excludes: the target ran the configuration the check rules out."
        )
    if _empty(got) and not _empty(want):
        return _HINT_EMPTY
    if op != "==":
        if _incomparable(got, want):
            return (
                f"Check the observable's TYPE -- the target emitted "
                f"{type(got).__name__} {got!r}, which cannot be ordered against "
                f"the {type(want).__name__} {want!r} this predicate compares to."
            )
        return (
            f"The comparison ran and was false: {got!r} is not {op} {want!r}. "
            f"The observable is the right kind of value; the target's reading "
            f"is on the wrong side of the declared bound at this level."
        )
    if type(got) is not type(want):
        return (
            f"Check the observable's TYPE -- the target emitted "
            f"{type(got).__name__} {got!r} where the level is "
            f"{type(want).__name__} {want!r}, and values of different types "
            f"can never compare equal."
        )
    return _HINT_VALUE


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
            hint=_HINT_ABSENT,
        )

    want = pred.get("value")
    if want == "{level}":
        want = level

    ok = bool(OPS[op_name](got, want))
    return Verdict(
        ok=ok,
        detail=f"{path} = {got!r} {op_name} {want!r} -> {'ok' if ok else 'FAIL'}",
        hint="" if ok else _failure_hint(got, want, op_name),
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
