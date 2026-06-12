"""Composite scoring + best_found.json (issue #168).

Replaces single-metric campaign success (``prediction_accuracy`` —
the only cross-arm metric in ledger.json today) with a weighted
composite over multiple deployability dimensions. Each campaign
declares weights via an optional ``objective:`` block (or a named
preset); ``best_found.json`` tracks the top-K candidates ranked by
composite score across all iterations completed so far.

Design notes
------------
* ``compute_score`` is pure deterministic math — `Σ w_m * value_m`.
  Missing observations contribute zero (campaigns evolve their metric
  vocabulary across iterations and a missing column should not crash
  ranking).

* ``ObjectiveSpec`` validates weight sum at construction time, with
  float tolerance (so ten 0.1-weights still validate). Negative
  weights are rejected; zero weights are allowed (lets a preset
  reserve a slot for a metric that some campaigns won't measure).

* Named presets are immutable; ``get_preset`` returns a fresh
  ``ObjectiveSpec`` each call so callers cannot mutate the template.

* ``update_best_found`` walks ``runs/iter-*/findings.json``, computes
  a score per arm result, and writes the top-K to ``best_found.json``
  via atomic_write. With no objective declared (legacy campaigns),
  it falls back to a status-based ranking: CONFIRMED=1.0,
  PARTIALLY_CONFIRMED=0.5, REFUTED=0.0. This guarantees that issue
  #169's engine-continues-past-REFUTE flow always has a populated
  best_found.json to point at.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from orchestrator.util import atomic_write


_WEIGHT_SUM_TOLERANCE = 1e-6


@dataclass
class ObjectiveSpec:
    """Weighted composite objective.

    Attributes:
        weights: Map of metric name → weight. Must be non-empty,
            all weights ≥ 0, and sum to 1.0 (with float tolerance).
        metric_extractors: Optional map of metric name → dotted path
            into arms[].metadata. When unset, the metric name is used
            as a flat key.
        deploy_threshold: How much best_found composite score must
            exceed baseline_score to trigger a 'deploy' verdict in the
            deployment recommendation (issue #170). Default 0.1.
    """
    weights: dict[str, float]
    metric_extractors: dict[str, str] = field(default_factory=dict)
    deploy_threshold: float = 0.1

    def __post_init__(self) -> None:
        if not self.weights:
            raise ValueError("objective weights must be non-empty")
        for name, w in self.weights.items():
            if w < 0:
                raise ValueError(
                    f"weight for {name!r} must be ≥ 0 (got {w})",
                )
        total = sum(self.weights.values())
        if not math.isclose(total, 1.0, abs_tol=_WEIGHT_SUM_TOLERANCE):
            raise ValueError(
                f"weights must sum to 1.0 (got {total}); "
                f"tolerance ±{_WEIGHT_SUM_TOLERANCE}",
            )


# ─── Named presets ────────────────────────────────────────────────────────
#
# Stored as factories so each call returns a fresh instance — protects
# callers who mutate ObjectiveSpec.weights in place.

PRESETS: dict[str, dict[str, Any]] = {
    "compound-return-style": {
        "weights": {
            "compound_return": 0.5,
            "walk_forward_consistency": 0.3,
            "interpretability": 0.1,
            "operational_simplicity": 0.1,
        },
        "deploy_threshold": 0.05,
    },
    "latency-style": {
        "weights": {
            "throughput": 0.4,
            "latency_p99_inv": 0.3,
            "stability": 0.2,
            "operational_simplicity": 0.1,
        },
        "deploy_threshold": 0.10,
    },
}


def get_preset(name: str) -> ObjectiveSpec:
    """Resolve a named preset to a fresh ObjectiveSpec.

    Returns a new instance each call so callers' mutations cannot leak.
    """
    if name not in PRESETS:
        raise ValueError(
            f"unknown preset {name!r}; available: {sorted(PRESETS)}",
        )
    template = PRESETS[name]
    return ObjectiveSpec(
        weights=dict(template["weights"]),
        deploy_threshold=template.get("deploy_threshold", 0.1),
    )


# ─── compute_score ────────────────────────────────────────────────────────


def compute_score(
    observed_metrics: dict[str, Any], objective: ObjectiveSpec,
) -> float:
    """Weighted sum of observed metric values.

    Missing metrics contribute zero — see module docstring rationale.
    """
    score = 0.0
    for metric, weight in objective.weights.items():
        value = observed_metrics.get(metric, 0.0)
        try:
            score += weight * float(value)
        except (TypeError, ValueError):
            # Non-numeric metric value: treat as zero contribution.
            continue
    return score


def compute_score_components(
    observed_metrics: dict[str, Any], objective: ObjectiveSpec,
) -> dict[str, float]:
    """Per-metric contribution to the score (weight × observed value)."""
    components: dict[str, float] = {}
    for metric, weight in objective.weights.items():
        value = observed_metrics.get(metric, 0.0)
        try:
            components[metric] = weight * float(value)
        except (TypeError, ValueError):
            components[metric] = 0.0
    return components


# ─── update_best_found ────────────────────────────────────────────────────


_LEGACY_STATUS_SCORES = {
    "CONFIRMED": 1.0,
    "PARTIALLY_CONFIRMED": 0.5,
    "REFUTED": 0.0,
}


def _iter_findings(work_dir: Path) -> Iterable[tuple[int, dict]]:
    runs_dir = work_dir / "runs"
    if not runs_dir.is_dir():
        return
    for child in sorted(runs_dir.iterdir()):
        if not child.is_dir() or not child.name.startswith("iter-"):
            continue
        try:
            iteration = int(child.name.split("-", 1)[1])
        except (IndexError, ValueError):
            continue
        path = child / "findings.json"
        if not path.exists():
            continue
        try:
            yield iteration, json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue


def _candidate_id(iteration: int, arm: dict, idx: int) -> str:
    """Stable identifier: prefer arms[].metadata.candidate_id, fall back to position."""
    metadata = arm.get("metadata") or {}
    explicit = metadata.get("candidate_id") if isinstance(metadata, dict) else None
    if isinstance(explicit, str) and explicit:
        return f"iter-{iteration}/{arm.get('arm_type', '?')}/{explicit}"
    return f"iter-{iteration}/{arm.get('arm_type', '?')}/{idx}"


def update_best_found(
    work_dir: Path,
    *,
    objective: ObjectiveSpec | None,
    top_k: int = 5,
    now: datetime | None = None,
) -> dict:
    """Re-rank all candidates seen so far and write best_found.json.

    Pure deterministic Python. Reads runs/iter-N/findings.json across
    iterations, computes a score per arm, sorts descending, truncates
    to ``top_k``, and atomically writes ``best_found.json`` at the
    campaign root.

    Args:
        work_dir: Campaign work directory (containing ``runs/``).
        objective: Composite-scoring objective. ``None`` falls back to
            the legacy status-based ranking (CONFIRMED=1.0, etc.).
        top_k: Cap on the returned list. Best candidates first.
        now: Optional timestamp for ``updated_at``.

    Returns:
        The payload that was written. Empty ``top_k`` is valid.
    """
    work_dir = Path(work_dir)

    candidates: list[dict] = []
    for iteration, findings in _iter_findings(work_dir):
        for idx, arm in enumerate(findings.get("arms", []) or []):
            if not isinstance(arm, dict):
                continue
            metadata = arm.get("metadata") if isinstance(arm.get("metadata"), dict) else {}
            assert isinstance(metadata, dict)

            if objective is None:
                score = _LEGACY_STATUS_SCORES.get(arm.get("status", ""), 0.0)
                components = {"status": score}
            else:
                score = compute_score(metadata, objective)
                components = compute_score_components(metadata, objective)

            candidates.append({
                "candidate_id": _candidate_id(iteration, arm, idx),
                "score": float(score),
                "components": components,
                "iteration": iteration,
                "arm_id": arm.get("arm_type", "?"),
            })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    payload = {
        "top_k": candidates[:top_k],
        "k": top_k,
        "updated_at": (now or datetime.now(timezone.utc)).isoformat(),
    }

    atomic_write(
        work_dir / "best_found.json",
        json.dumps(payload, indent=2) + "\n",
    )
    return payload
