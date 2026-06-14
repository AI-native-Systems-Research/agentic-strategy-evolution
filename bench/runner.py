"""Sequential runner. Phase 2 swaps to ProcessPoolExecutor."""
from __future__ import annotations

import datetime as dt
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from bench import report
from bench.isolation import clone_target_repo
from bench.variants.base import Experiment, VariantResult
from bench.variants.claude_plain import ClaudePlainVariant
from bench.variants.nous import NousVariant

VARIANT_REGISTRY: dict[str, type] = {
    "nous": NousVariant,
    "claude_plain": ClaudePlainVariant,
}


def find_repo_root(start: Path) -> Path:
    """Walk up from `start` until a dir containing pyproject.toml is found."""
    current = Path(start).resolve()
    if current.is_file():
        current = current.parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    raise FileNotFoundError(f"No pyproject.toml found above {start}")


def validate_variants(names: list[str]) -> list[str]:
    if len(names) != len(set(names)):
        raise ValueError(f"Duplicate variant names: {names}")
    unknown = [n for n in names if n not in VARIANT_REGISTRY]
    if unknown:
        known = sorted(VARIANT_REGISTRY)
        raise ValueError(f"Unknown variants: {unknown}. Known: {known}")
    return names


def result_to_jsonable(result: VariantResult) -> dict[str, Any]:
    d = asdict(result)
    for k, v in list(d.items()):
        if isinstance(v, Path):
            d[k] = str(v)
    return d


def generate_run_id(experiment_id: str) -> str:
    today = dt.date.today().isoformat()
    return f"{today}_{experiment_id}"


def _resolve_campaign_path(experiment_path: Path) -> Path:
    with open(experiment_path) as f:
        data = yaml.safe_load(f)
    campaign_rel = data["campaign"]
    candidates = [
        (experiment_path.parent / campaign_rel).resolve(),
        (experiment_path.parent.parent / campaign_rel).resolve(),
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(f"campaign yaml not found: {campaign_rel}")


def _run_one_variant(
    variant_name: str,
    experiment: Experiment,
    variant_dir: Path,
) -> VariantResult:
    variant_dir.mkdir(parents=True, exist_ok=True)
    workspace = variant_dir / "workspace"

    try:
        clone_target_repo(
            experiment.campaign.target_repo,
            experiment.campaign.target_ref,
            workspace,
        )
    except Exception as e:
        return VariantResult(
            variant=variant_name,
            campaign_id=experiment.campaign.id,
            tokens_in=0,
            tokens_out=0,
            dollars=0.0,
            wall_seconds=0.0,
            final_answer="",
            artifacts_dir=variant_dir,
            raw_log_path=variant_dir / "clone.error",
            crashed=True,
            hit_cap=False,
            error=f"clone failed: {type(e).__name__}: {e}",
        )

    variant = VARIANT_REGISTRY[variant_name]()
    try:
        return variant.run(experiment.campaign, workspace, experiment.budget)
    except Exception as e:
        return VariantResult(
            variant=variant_name,
            campaign_id=experiment.campaign.id,
            tokens_in=0,
            tokens_out=0,
            dollars=0.0,
            wall_seconds=0.0,
            final_answer="",
            artifacts_dir=variant_dir,
            raw_log_path=variant_dir / "run.error",
            crashed=True,
            hit_cap=False,
            error=f"variant.run raised: {type(e).__name__}: {e}",
        )


def run_experiment(
    experiment_path: Path,
    variants_override: list[str] | None = None,
    budget_overrides: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> Path:
    """Run an experiment end-to-end. Returns the run directory path."""
    experiment_path = Path(experiment_path).resolve()
    experiment = Experiment.from_yaml(experiment_path)

    variants = (
        variants_override if variants_override is not None else experiment.variants
    )
    variants = validate_variants(variants)

    if budget_overrides:
        for key, value in budget_overrides.items():
            if value is not None and hasattr(experiment.budget, key):
                setattr(experiment.budget, key, value)

    repo_root = find_repo_root(experiment_path)
    rid = run_id or generate_run_id(experiment.id)
    run_dir = repo_root / "runs" / rid
    run_dir.mkdir(parents=True, exist_ok=True)

    with open(run_dir / "experiment.snapshot.yaml", "w") as f:
        yaml.safe_dump(
            {
                "id": experiment.id,
                "campaign": str(_resolve_campaign_path(experiment_path)),
                "variants": variants,
                "budget": asdict(experiment.budget),
            },
            f,
            sort_keys=False,
        )
    shutil.copy(
        _resolve_campaign_path(experiment_path),
        run_dir / "campaign.snapshot.yaml",
    )

    started_at = dt.datetime.now(dt.timezone.utc).isoformat()

    results: list[VariantResult] = []
    for variant_name in variants:
        variant_dir = run_dir / variant_name
        result = _run_one_variant(variant_name, experiment, variant_dir)
        with open(variant_dir / "result.json", "w") as f:
            json.dump(result_to_jsonable(result), f, indent=2)
        results.append(result)

    ended_at = dt.datetime.now(dt.timezone.utc).isoformat()

    combined = {
        "experiment_id": experiment.id,
        "campaign_id": experiment.campaign.id,
        "research_question": experiment.campaign.research_question,
        "run_id": rid,
        "started_at": started_at,
        "ended_at": ended_at,
        "variants": [result_to_jsonable(r) for r in results],
    }
    with open(run_dir / "results.json", "w") as f:
        json.dump(combined, f, indent=2)

    report.render(run_dir)
    return run_dir
