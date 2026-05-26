"""Deterministic post-extraction classifier for principle empiricism (issue #179).

The sort_bench dry-run on 2026-05-25 surfaced that extracted principles
ship with `empirical_content` and `derivation_type` (issue #86) unset
because the methodology prompt is advisory and the schema treats them
as optional. RP-2 in that run was a clear empirical observation
(*"timsort uses 460 comparisons on nearly-sorted input"*) but was
silently filed without tags.

This module provides a deterministic Python heuristic that runs on
``principle_updates.json`` before merge into ``principles.json``,
filling the fields when the statement is classifiable. Residual
unclassifiable principles are caught by the validator warning in
``orchestrator.validate.validate_principles_have_empirical_content``.

Approach: composable A+B from issue #179.
  * A: This module — deterministic auto-classifier.
  * B: ``validate.py`` — soft validator emitting WARN on residual misses.

Heuristic priority:
  1. Existing explicit tags are preserved (explicit > heuristic).
  2. Algebraic markers (`iff`, `algebraic`, `identity`, `theorem`) → algebraic.
  3. Definitional markers (`is defined as`, `by definition`) → definitional.
  4. Empirical markers (`iter-N`, numeric measurements with units,
     `observed`, `measured`, `experiments`) → empirical.
  5. Otherwise leave None — the validator warning surfaces to the human.

No LLM, no live calls. Tests assert on the heuristic's verdicts for
known statement shapes.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

from orchestrator.util import atomic_write


_ALGEBRAIC_MARKERS = (
    re.compile(r"\biff\b", re.IGNORECASE),
    re.compile(r"\bif\s+and\s+only\s+if\b", re.IGNORECASE),
    re.compile(r"\balgebraic(?:ally)?\b", re.IGNORECASE),
    re.compile(r"\bidentity\b", re.IGNORECASE),
    re.compile(r"\bequivalent(?:ly)?\s+to\b", re.IGNORECASE),
    re.compile(r"\bfollows\s+from\b", re.IGNORECASE),
    re.compile(r"\btheorem\b", re.IGNORECASE),
    re.compile(r"\baxiom\b", re.IGNORECASE),
    re.compile(r"\bproof\b", re.IGNORECASE),
)

_DEFINITIONAL_MARKERS = (
    re.compile(r"\bis\s+defined\s+as\b", re.IGNORECASE),
    re.compile(r"\bby\s+definition\b", re.IGNORECASE),
    re.compile(r"\bdefinitional(?:ly)?\b", re.IGNORECASE),
)

_EMPIRICAL_MARKERS = (
    # Iteration / arm citations
    re.compile(r"\biter[-_ ]?\d+\b", re.IGNORECASE),
    re.compile(r"\barm[-_]?\w+\b", re.IGNORECASE),
    # Empirical-process verbs
    re.compile(r"\bobserved\b", re.IGNORECASE),
    re.compile(r"\bmeasured\b", re.IGNORECASE),
    re.compile(r"\bfound\s+that\b", re.IGNORECASE),
    re.compile(r"\bexperiments?\b", re.IGNORECASE),
    re.compile(r"\bdiscover(?:ed|y)?\b", re.IGNORECASE),
    re.compile(r"\bempirical(?:ly)?\b", re.IGNORECASE),
    # Numeric measurements with units (high signal)
    re.compile(
        r"\b\d+(?:\.\d+)?\s*"
        r"(?:%|ms|us|s|MB|GB|comparisons?|tokens?|seeds?|x)\b",
        re.IGNORECASE,
    ),
    # Concrete equations / values: "= 460", "approximately 0.85"
    re.compile(r"=\s*\d{2,}"),
    re.compile(r"\bratio\s*=?\s*\d", re.IGNORECASE),
)


def classify_principle(p: dict) -> dict:
    """Return a copy of ``p`` with ``empirical_content`` / ``derivation_type``
    filled in if the heuristic fires and the field is currently unset.

    Pure: does not mutate the input. Existing values are preserved
    (explicit > heuristic). When neither side fires strongly, returns
    a copy with the fields still ``None`` — the validator warning
    surfaces the residual to the human.
    """
    if not isinstance(p, dict):
        return p  # malformed; let downstream validators catch it
    out = deepcopy(p)

    # If both fields are already set, no change.
    has_empirical = out.get("empirical_content") is not None
    has_derivation = out.get("derivation_type") is not None
    if has_empirical and has_derivation:
        return out

    statement = str(out.get("statement") or "")
    algebraic_hits = sum(1 for r in _ALGEBRAIC_MARKERS if r.search(statement))
    definitional_hits = sum(1 for r in _DEFINITIONAL_MARKERS if r.search(statement))
    empirical_hits = sum(1 for r in _EMPIRICAL_MARKERS if r.search(statement))

    # Case 1: ``empirical_content`` was explicitly set; derivation_type
    # follows. True ⇒ empirical; False ⇒ algebraic or definitional
    # depending on which marker family dominates.
    if has_empirical and not has_derivation:
        if out.get("empirical_content") is True:
            out["derivation_type"] = "empirical"
        else:
            if definitional_hits >= 1 and definitional_hits >= algebraic_hits:
                out["derivation_type"] = "definitional"
            else:
                out["derivation_type"] = "algebraic"
        return out

    # Case 2: ``derivation_type`` was explicitly set; empirical_content
    # follows by definition (only "empirical" → True; the others → False).
    if has_derivation and not has_empirical:
        out["empirical_content"] = (out.get("derivation_type") == "empirical")
        return out

    # Case 3: neither set. Apply the heuristic with priority:
    # definitional > algebraic > empirical.

    # Definitional markers are most specific — "is defined as" /
    # "by definition" override algebraic markers that may co-occur.
    if definitional_hits >= 1:
        out["empirical_content"] = False
        out["derivation_type"] = "definitional"
        return out

    # Algebraic markers — at least one of {iff, theorem, identity, …}
    # AND no stronger empirical signal.
    if algebraic_hits >= 1 and algebraic_hits >= empirical_hits:
        out["empirical_content"] = False
        out["derivation_type"] = "algebraic"
        return out

    # Empirical markers — require at least 2 (single iter-N alone is too
    # weak; we want corroborating evidence like a numeric measurement
    # or a process verb).
    if empirical_hits >= 2 and empirical_hits > algebraic_hits:
        out["empirical_content"] = True
        out["derivation_type"] = "empirical"
        return out

    # Neither side fired strongly. Leave fields as-is (likely None) —
    # validator will warn for category=domain principles.
    return out


def classify_principles(principles: list[dict]) -> list[dict]:
    """Classify a list of principle dicts; returns a new list."""
    if not isinstance(principles, list):
        return principles
    return [classify_principle(p) for p in principles]


def classify_principle_updates_in_place(iter_dir: Path) -> None:
    """Read ``runs/iter-N/principle_updates.json``, classify, and write back atomically.

    No-op if the file is missing or malformed. Idempotent: re-running on
    an already-classified file produces byte-equal output.

    This is the seam ``finalize_iteration`` calls before
    ``_merge_principles``, so the merged ``principles.json`` reflects
    the tags on its very first write.
    """
    updates_path = Path(iter_dir) / "principle_updates.json"
    if not updates_path.exists():
        return
    try:
        updates = json.loads(updates_path.read_text())
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(updates, list):
        return

    classified = classify_principles(updates)
    atomic_write(updates_path, json.dumps(classified, indent=2) + "\n")
