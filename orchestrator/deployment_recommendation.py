"""Deployment recommendation (issue #170).

Closes the search-oriented loop (#166): pre-work seeds (#167),
composite score ranks (#168), engine continues past REFUTE (#169),
and now every campaign emits a shippable verdict — ``deploy |
deploy_with_caveats | fall_back_to_baseline`` — with concrete
citations the operator can act on.

Decision rule (deterministic Python, no LLM):

  best_score    = best_found.json top_k[0].score (None if empty)
  baseline      = pre_work.json baseline_metrics scored under the same
                  objective (or 0 if pre_work absent / objective None)
  threshold     = campaign.objective.deploy_threshold (default 0.1)
  consistency   = top_k[0].components.get("walk_forward_consistency")
                  (None if not in objective)

  If best_score is None or best_score <= baseline:
    ⇒ fall_back_to_baseline
  Elif best_score > baseline + threshold AND
       (consistency is None OR consistency > 0.7):
    ⇒ deploy
  Else:
    ⇒ deploy_with_caveats

Caveats are auto-generated for the middle case with concrete
citations to iteration / arm / numeric component values, so the
validator floor accepts them.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestrator.composite_score import (
    ObjectiveSpec,
    compute_score,
    get_preset,
)

logger = logging.getLogger(__name__)


_DEFAULT_DEPLOY_THRESHOLD = 0.1
_WALK_FORWARD_KEY = "walk_forward_consistency"
_WALK_FORWARD_MIN = 0.7


@dataclass
class DeploymentRecommendation:
    """Verdict + supporting citations for a campaign's terminal state."""
    verdict: str
    top_candidate_id: str | None = None
    score: float | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "top_candidate_id": self.top_candidate_id,
            "score": self.score,
            "citations": list(self.citations),
            "caveats": list(self.caveats),
        }


def _resolve_objective(campaign: dict) -> ObjectiveSpec | None:
    """Pull an ObjectiveSpec from campaign config, or None if neither set."""
    if not isinstance(campaign, dict):
        return None
    if (preset_name := campaign.get("objective_preset")):
        try:
            return get_preset(str(preset_name))
        except ValueError:
            return None
    obj = campaign.get("objective")
    if isinstance(obj, dict) and obj.get("weights"):
        try:
            return ObjectiveSpec(
                weights={str(k): float(v) for k, v in obj["weights"].items()},
                metric_extractors=dict(obj.get("metric_extractors") or {}),
                deploy_threshold=float(
                    obj.get("deploy_threshold", _DEFAULT_DEPLOY_THRESHOLD),
                ),
            )
        except (TypeError, ValueError):
            return None
    return None


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text())
        return loaded if isinstance(loaded, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _baseline_score(work_dir: Path, objective: ObjectiveSpec | None) -> float:
    """Score pre_work.json baseline_metrics under the same objective.

    Returns 0.0 when:
      * pre_work.json is missing or has no baseline_metrics
      * no objective is declared (legacy fallback in best_found.json
        already used status-as-score, which has 0..1 range — comparing
        to baseline=0 means "anything CONFIRMED beats nothing")
    """
    if objective is None:
        return 0.0
    pre_work = _read_json(work_dir / "pre_work.json")
    if not pre_work:
        return 0.0
    baseline = pre_work.get("baseline_metrics")
    if not isinstance(baseline, dict):
        return 0.0
    return compute_score(baseline, objective)


def _format_evidence(iteration: int, arm_id: str, components: dict) -> str:
    """Concrete citation: iter-N + arm + numeric components.

    Must pass meta_findings.evidence_is_concrete (regex floor — needs
    an iter-N marker, an arm marker, and a numeric measurement).
    """
    parts = [f"iter-{iteration}", f"arm_id={arm_id}"]
    for k, v in sorted(components.items()):
        try:
            parts.append(f"{k}={float(v):.3f}")
        except (TypeError, ValueError):
            continue
    return " ".join(parts)


def _make_caveats(
    *,
    iteration: int,
    arm_id: str,
    best_score: float,
    baseline: float,
    threshold: float,
    consistency: float | None,
) -> list[str]:
    """Caveats are auto-generated with concrete citations."""
    out: list[str] = []
    margin = best_score - baseline
    if margin <= threshold:
        out.append(
            f"iter-{iteration} arm {arm_id}: best_score margin over baseline "
            f"= {margin:.3f}, below deploy_threshold of {threshold:.3f}",
        )
    if consistency is not None and consistency <= _WALK_FORWARD_MIN:
        out.append(
            f"iter-{iteration} arm {arm_id}: walk_forward_consistency "
            f"= {consistency:.3f}, below threshold of {_WALK_FORWARD_MIN:.2f}",
        )
    return out


def make_deployment_recommendation(
    work_dir: Path,
    *,
    campaign: dict,
) -> DeploymentRecommendation:
    """Read best_found.json + pre_work.json, decide verdict.

    Returns a fall_back_to_baseline verdict (with empty citations and
    caveats) when there's nothing to recommend — never raises.
    """
    work_dir = Path(work_dir)
    best_found_path = work_dir / "best_found.json"
    best_found = _read_json(best_found_path)

    # Issue #178: distinguish "no candidate beat baseline" (genuine
    # fall-back) from "best_found.json is missing" (upstream wiring
    # gap — see #177). Both keep the conservative fall_back_to_baseline
    # verdict, but the caveats now tell the operator what actually
    # happened. Each caveat passes meta_findings.validate_caveat
    # (cites a concrete artifact name + numeric / issue reference).
    if best_found is None:
        return DeploymentRecommendation(
            verdict="fall_back_to_baseline",
            caveats=[
                f"best_found.json not present at {best_found_path}; "
                f"cannot rank candidates. The iteration finalize step "
                f"either did not run or did not call update_best_found. "
                f"See issue #177 in orchestrator/iteration.py."
            ],
        )

    if not best_found.get("top_k"):
        return DeploymentRecommendation(
            verdict="fall_back_to_baseline",
            caveats=[
                f"best_found.json present at {best_found_path} but "
                f"top_k is empty (k={best_found.get('k', 0)}); no "
                f"candidate scored above baseline across the iterations "
                f"recorded in runs/iter-N/findings.json."
            ],
        )

    top = best_found["top_k"][0]
    if not isinstance(top, dict):
        return DeploymentRecommendation(
            verdict="fall_back_to_baseline",
            caveats=[
                f"best_found.json top_k[0] has unexpected type "
                f"{type(top).__name__!r} at {best_found_path}; "
                f"expected dict. Investigate whether update_best_found "
                f"wrote a corrupt entry — see issue #177."
            ],
        )

    best_score = float(top.get("score", 0.0))
    iteration = int(top.get("iteration", 0))
    arm_id = str(top.get("arm_id", "?"))
    candidate_id = str(top.get("candidate_id", ""))
    components = top.get("components") or {}

    objective = _resolve_objective(campaign)
    threshold = (
        objective.deploy_threshold if objective else _DEFAULT_DEPLOY_THRESHOLD
    )
    baseline = _baseline_score(work_dir, objective)

    consistency: float | None = None
    if isinstance(components, dict) and _WALK_FORWARD_KEY in components:
        # `components` are weight-multiplied contributions; recover the raw
        # metric value as contribution / weight when we have the weight.
        contrib = components.get(_WALK_FORWARD_KEY)
        weight = (
            objective.weights.get(_WALK_FORWARD_KEY)
            if objective else None
        )
        if isinstance(contrib, (int, float)) and weight:
            consistency = float(contrib) / float(weight)

    citations = [{
        "iteration": iteration,
        "arm_id": arm_id,
        "evidence_snippet": _format_evidence(iteration, arm_id, components),
    }]

    if best_score <= baseline:
        return DeploymentRecommendation(
            verdict="fall_back_to_baseline",
            top_candidate_id=candidate_id or None,
            score=best_score,
            citations=citations,
            caveats=[
                f"iter-{iteration} arm {arm_id}: best_score = {best_score:.3f} "
                f"<= baseline = {baseline:.3f}",
            ],
        )

    margin_ok = best_score > baseline + threshold
    consistency_ok = consistency is None or consistency > _WALK_FORWARD_MIN

    if margin_ok and consistency_ok:
        verdict = "deploy"
        caveats: list[str] = []
    else:
        verdict = "deploy_with_caveats"
        caveats = _make_caveats(
            iteration=iteration,
            arm_id=arm_id,
            best_score=best_score,
            baseline=baseline,
            threshold=threshold,
            consistency=consistency,
        )

    return DeploymentRecommendation(
        verdict=verdict,
        top_candidate_id=candidate_id or None,
        score=best_score,
        citations=citations,
        caveats=caveats,
    )
