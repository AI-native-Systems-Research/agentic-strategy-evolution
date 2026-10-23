"""Nous v2 stop rule (spec 3.6).

Checked after each iteration to decide whether the campaign should
continue, enter REPORT, or halt.
"""

from __future__ import annotations

import json
from pathlib import Path


def _key(v) -> str:
    """Hashable form of any agent-written JSON value (lists, dicts: e.g. a Pareto front)."""
    return json.dumps(v, sort_keys=True, default=str)


def _collect_claims(findings: dict) -> set[tuple]:
    """Extract (claim_id, metric, condition, value) tuples from findings."""
    claims: set[tuple] = set()
    for hyp in findings.get("hypotheses", []):
        for c in hyp.get("claims", []):
            claims.add(tuple(_key(c.get(k)) for k in ("claim_id", "metric", "condition", "value")))
    return claims


def claims_changed(prev: dict | None, curr: dict) -> bool:
    """True if the current claims differ from the previous iteration's."""
    if prev is None:
        return bool(_collect_claims(curr))
    return _collect_claims(prev) != _collect_claims(curr)


def best_changed(
    prev: dict | None,
    curr: dict,
    *,
    direction: str = "increase",
    min_improvement: float = 0,
) -> bool:
    """True if curr's best beats prev's best by more than min_improvement."""
    curr_best = curr.get("best")
    if curr_best is None:
        return False
    curr_val = curr_best.get("value")
    if curr_val is None:
        return False
    if prev is None or prev.get("best") is None:
        return True
    prev_val = prev.get("best", {}).get("value")
    if prev_val is None:
        return True
    num = (int, float)
    if not isinstance(curr_val, num) or not isinstance(prev_val, num):
        return False

    delta = curr_val - prev_val if direction == "increase" else prev_val - curr_val
    return delta > min_improvement


def principles_changed(principle_updates: dict | None) -> bool:
    """True if principle_updates has at least one add or revise action."""
    if principle_updates is None:
        return False
    updates = principle_updates.get("updates", [])
    return any(u.get("action") in ("add", "revise") for u in updates)


def _is_quiet(entry: dict) -> bool:
    """True if a ledger entry represents a quiet iteration."""
    return not (
        entry.get("claims_changed")
        or entry.get("best_changed")
        or entry.get("principles_changed")
    )


def check_stop(
    *,
    iteration: int,
    findings: dict,
    principle_updates: dict | None,
    ledger: list[dict],
    max_iterations: int,
    stall_iterations: int,
    halt_path: Path,
    stop_sentinel_path: Path,
    current_claims_changed: bool = False,
    current_best_changed: bool = False,
    claims_needed: list[dict] | None = None,
    status: str = "ok",
) -> str | None:
    """Return stop reason string or None to continue.

    Priority: halt > stop_sentinel > answered > max_iterations > stall > None.
    """
    if halt_path.exists():
        return "halt"

    if stop_sentinel_path.exists():
        return "stop_sentinel"

    hypotheses = findings.get("hypotheses", [])
    question_answered = bool(findings.get("question_answered"))
    has_non_inconclusive = any(
        h.get("status") is not None and h["status"] != "INCONCLUSIVE"
        for h in hypotheses
    )
    if (status == "ok" and question_answered and has_non_inconclusive
            and _claims_needed_met(findings, claims_needed)):
        return "answered"

    if iteration >= max_iterations:
        return "max_iterations"

    current_quiet = not (
        current_claims_changed
        or current_best_changed
        or principles_changed(principle_updates)
    )
    if current_quiet:
        trailing = 0
        for entry in reversed(ledger):
            if _is_quiet(entry):
                trailing += 1
            else:
                break
        total_quiet = trailing + 1
        if total_quiet >= stall_iterations:
            return "stall"

    return None


def _claims_needed_met(
    findings: dict, claims_needed: list[dict] | None
) -> bool:
    """True if every claims_needed entry is produced and meets its declared
    min_seeds / needs_ci / conditions (spec 3.6). Undeclared ones are not checked."""
    by_id: dict = {}
    for hyp in findings.get("hypotheses", []):
        for c in hyp.get("claims", []):
            by_id.setdefault(_key(c.get("claim_id")), []).append(c)
    for need in claims_needed or []:
        got = by_id.get(_key(need.get("id")))
        if not got:
            return False
        seeds = {_key(s) for c in got if isinstance(c.get("seeds"), list) for s in c["seeds"]}
        if len(seeds) < need.get("min_seeds", 0):
            return False
        if need.get("needs_ci") and not any(c.get("ci") is not None for c in got):
            return False
        if not {_key(x) for x in need.get("conditions") or []} <= {_key(c.get("condition")) for c in got}:
            return False
    return True
