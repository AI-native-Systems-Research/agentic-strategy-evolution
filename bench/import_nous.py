"""Import an existing nous campaign into a bench-compatible `results.json`.

Lets us re-judge an existing nous run under the new 11-metric rubric without
re-running the campaign. The actual data isn't regenerated — this is a
format translation from nous's per-iter artifact layout to the flat
results.json shape `bench rejudge` expects.

Auto-detects whether the artifacts live at the root of the given dir or
one subdirectory deep (e.g. `Graph-Coloring/graph-coloring-v1/`).

Path-agnostic — designed to work on any contributor's machine. Pass an
absolute or `~`-expanded path; resolve before reading.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from bench.variants.nous import _harvest_metrics, _read_final_answer


@dataclass
class NousCampaignSnapshot:
    """In-memory representation of a nous campaign suitable for handing
    to the bench schema converter."""
    campaign_id: str
    research_question: str
    artifacts_dir: Path        # contains principles.json, ledger.json, runs/, etc.
    iterations_completed: int
    final_answer: str          # rendered by _read_final_answer
    tokens_in: int
    tokens_out: int
    dollars: float
    wall_seconds: float        # 0.0 if not derivable; cost-tracked but wall isn't in nous artifacts


class ArtifactsDirNotFound(FileNotFoundError):
    """Raised when we can't locate principles.json + ledger.json + runs/
    in the given input dir or any 1-level subdirectory."""


def find_artifacts_dir(input_dir: Path) -> Path:
    """Locate the nous artifacts dir within `input_dir`.

    Returns the first dir (input_dir or 1-level subdir) that contains all
    three of: principles.json, ledger.json, runs/. Raises if none found.
    """
    input_dir = input_dir.resolve()

    def _looks_like_artifacts(d: Path) -> bool:
        return (
            (d / "principles.json").exists()
            and (d / "ledger.json").exists()
            and (d / "runs").is_dir()
        )

    if _looks_like_artifacts(input_dir):
        return input_dir
    for sub in sorted(input_dir.iterdir()):
        if sub.is_dir() and _looks_like_artifacts(sub):
            return sub
    raise ArtifactsDirNotFound(
        f"could not find principles.json + ledger.json + runs/ in {input_dir} "
        "or any 1-level subdirectory"
    )


def _load_campaign_yaml(input_dir: Path) -> dict:
    """Find and load any *.yaml at the top level of input_dir. Prefer
    'campaign.yaml'; fall back to the first match."""
    yamls = sorted(input_dir.glob("*.yaml"))
    if not yamls:
        # Try one level deep too
        yamls = sorted(input_dir.glob("*/*.yaml"))
    preferred = [y for y in yamls if y.name == "campaign.yaml"]
    chosen = (preferred or yamls)[0] if yamls else None
    if chosen is None:
        return {}
    try:
        with open(chosen) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _count_iterations(artifacts_dir: Path) -> int:
    """Count completed iters by reading ledger.json. Skips the iter=0
    baseline placeholder. Returns 0 on error."""
    try:
        with open(artifacts_dir / "ledger.json") as f:
            data = json.load(f)
        its = data.get("iterations", [])
        return sum(1 for it in its if it.get("iteration", 0) > 0)
    except Exception:
        return 0


def import_nous_campaign(
    input_dir: Path,
    *,
    campaign_id: str | None = None,
    research_question: str | None = None,
) -> NousCampaignSnapshot:
    """Read a nous campaign directory and produce a NousCampaignSnapshot
    ready to be serialized into a bench-compatible results.json.

    `input_dir` may be the campaign root or a parent dir whose first
    subdirectory contains the artifacts (auto-detected).

    `campaign_id` and `research_question` overrides take precedence over
    values discovered in the campaign.yaml (if any).
    """
    input_dir = input_dir.expanduser().resolve()
    artifacts_dir = find_artifacts_dir(input_dir)
    yaml_data = _load_campaign_yaml(input_dir)

    cid = campaign_id or yaml_data.get("run_id") or input_dir.name
    rq = research_question or yaml_data.get("research_question") or ""
    if not rq.strip():
        raise ValueError(
            f"research_question not found in {input_dir}'s campaign yaml; "
            "pass --research-question explicitly"
        )

    final_answer = _read_final_answer(artifacts_dir)
    iters = _count_iterations(artifacts_dir)

    metrics_path = artifacts_dir / "llm_metrics.jsonl"
    if metrics_path.exists():
        tokens_in, tokens_out, dollars = _harvest_metrics(metrics_path)
    else:
        tokens_in, tokens_out, dollars = 0, 0, 0.0

    return NousCampaignSnapshot(
        campaign_id=cid,
        research_question=rq.strip(),
        artifacts_dir=artifacts_dir,
        iterations_completed=iters,
        final_answer=final_answer,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        dollars=dollars,
        wall_seconds=0.0,
    )


def snapshot_to_bench_results(
    snap: NousCampaignSnapshot,
    *,
    run_id: str,
    started_at: str = "imported",
    ended_at: str = "imported",
) -> dict:
    """Convert a NousCampaignSnapshot into the dict shape that
    `bench rejudge` consumes (one variant entry: 'nous')."""
    return {
        "experiment_id": f"imported_{snap.campaign_id}",
        "campaign_id": snap.campaign_id,
        "research_question": snap.research_question,
        "run_id": run_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "variants": [
            {
                "variant": "nous",
                "campaign_id": snap.campaign_id,
                "tokens_in": snap.tokens_in,
                "tokens_out": snap.tokens_out,
                "dollars": snap.dollars,
                "wall_seconds": snap.wall_seconds,
                "final_answer": snap.final_answer,
                "artifacts_dir": str(snap.artifacts_dir),
                "raw_log_path": str(snap.artifacts_dir / "llm_metrics.jsonl"),
                "crashed": False,
                "hit_cap": False,
                "error": None,
            }
        ],
        "imported": {
            "source": str(snap.artifacts_dir),
            "iterations_completed": snap.iterations_completed,
        },
    }


def merge_baselines(combined: dict, baselines_results: dict) -> dict:
    """Merge a baselines `results.json` into the imported nous result.

    The imported result has one variant ('nous'); the baselines have the
    other 4 (claude_plain, etc.). After merge, the combined dict's
    variants list contains all 5, with nous first.

    Preserves baselines' judge_usage/judge_scores if already present.
    """
    nous_variants = [v for v in combined["variants"] if v["variant"] == "nous"]
    baseline_variants = [
        v for v in baselines_results.get("variants", []) if v["variant"] != "nous"
    ]
    out = dict(combined)
    out["variants"] = nous_variants + baseline_variants
    # Carry forward research_question / campaign_id from the imported nous
    # (they should match anyway, but baselines might use a different id)
    if "judge_usage" in baselines_results:
        out["judge_usage"] = baselines_results["judge_usage"]
    return out
