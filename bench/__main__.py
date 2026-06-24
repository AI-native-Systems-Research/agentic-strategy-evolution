"""CLI entry point for nous-bench. `python3 -m bench run <experiment.yaml>`."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

from bench import import_nous as import_nous_mod
from bench import judge as judge_mod
from bench import runner

VARIANT_DESCRIPTIONS = {
    "nous": "full orchestrator (multi-iter, schema-validated, isolated)",
    "claude_plain": "single Claude Code session, no methodology",
    "claude_loop": "N sequential plain sessions, summary carry-forward",
    "claude_methodology": "single session w/ methodology.md as system prompt",
    "claude_methodology_loop": "N methodology sessions w/ principle carry-forward",
}


def _parse_metrics_csv(s: str | None) -> list[str] | None:
    if s is None:
        return None
    return [m.strip() for m in s.split(",") if m.strip()]


def _cmd_run(args: argparse.Namespace) -> int:
    variants_override = (
        [s.strip() for s in args.variants.split(",")] if args.variants else None
    )
    budget_overrides: dict = {}
    if args.max_tokens is not None:
        budget_overrides["max_tokens"] = args.max_tokens
    if args.max_iterations is not None:
        budget_overrides["max_iterations"] = args.max_iterations
    if args.max_wall_seconds is not None:
        budget_overrides["max_wall_seconds"] = args.max_wall_seconds

    # --variant-model overrides the model used by claude_plain /
    # claude_methodology / claude_methodology_loop / claude_loop variants.
    # Plumbed via env var read inside _claude_common.invoke_claude.
    if args.variant_model:
        os.environ["BENCH_VARIANT_MODEL"] = args.variant_model

    run_dir = runner.run_experiment(
        Path(args.experiment),
        variants_override=variants_override,
        budget_overrides=budget_overrides or None,
        run_id=args.run_id,
        max_parallel_variants=args.max_parallel_variants,
        skip_judge=args.skip_judge,
        judge_metrics=_parse_metrics_csv(args.judge_metrics),
        judge_preset=args.judge_preset,
        judge_model=args.judge_model,
    )
    print(f"Run complete: {run_dir}")
    print(f"Report:       {run_dir / 'report.md'}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    try:
        repo_root = runner.find_repo_root(Path.cwd())
    except FileNotFoundError:
        repo_root = None

    print("Campaigns:")
    if repo_root is not None:
        campaigns_dir = repo_root / "bench" / "campaigns"
        if campaigns_dir.exists():
            for yml in sorted(campaigns_dir.glob("*.yaml")):
                with open(yml) as f:
                    data = yaml.safe_load(f) or {}
                cid = data.get("id", yml.stem)
                q = (data.get("research_question") or "").strip()
                q_short = q[:80] + ("..." if len(q) > 80 else "")
                print(f"  {cid:24s} {q_short}")
        else:
            print("  (no bench/campaigns/ dir found)")
    else:
        print("  (run from inside the repo to list campaigns)")

    print()
    print("Variants:")
    for name in sorted(runner.VARIANT_REGISTRY):
        desc = VARIANT_DESCRIPTIONS.get(name, "")
        print(f"  {name:24s} {desc}")

    print()
    print("Judge metrics:")
    for name in judge_mod.ALL_METRICS:
        marker = (
            " (multi-iter only)"
            if name in judge_mod.MULTI_ITER_ONLY_METRICS
            else ""
        )
        print(f"  {name}{marker}")
    print()
    print("Judge presets:")
    for name, mlist in judge_mod.PRESETS.items():
        print(f"  {name:22s} {', '.join(mlist)}")
    return 0


def _cmd_rejudge(args: argparse.Namespace) -> int:
    """Re-run the judge over an existing results.json without re-running variants."""
    results_path = Path(args.results_path).resolve()
    if not results_path.exists():
        print(f"error: results file not found: {results_path}", file=sys.stderr)
        return 2

    with open(results_path) as f:
        results = json.load(f)

    # Reconstruct VariantResult-shaped objects for run_judge. We only need
    # the fields run_judge reads: variant, final_answer, crashed.
    from bench.variants.base import VariantResult

    rebuilt: list[VariantResult] = []
    for v in results.get("variants", []):
        rebuilt.append(
            VariantResult(
                variant=v["variant"],
                campaign_id=v.get("campaign_id", ""),
                tokens_in=v.get("tokens_in", 0),
                tokens_out=v.get("tokens_out", 0),
                dollars=v.get("dollars", 0.0),
                wall_seconds=v.get("wall_seconds", 0.0),
                final_answer=v.get("final_answer", ""),
                artifacts_dir=Path(v.get("artifacts_dir", "/tmp")),
                raw_log_path=Path(v.get("raw_log_path", "/tmp/log")),
                crashed=v.get("crashed", False),
                hit_cap=v.get("hit_cap", False),
                error=v.get("error"),
            )
        )

    research_question = results.get("research_question", "")

    # Detect multi-iter from the snapshot if present, else from existing
    # judge_usage.metrics, else fall back to False.
    is_multi_iter = bool(args.multi_iter)
    if not args.multi_iter:
        snapshot_path = results_path.parent / "experiment.snapshot.yaml"
        if snapshot_path.exists():
            try:
                snap = yaml.safe_load(snapshot_path.read_text()) or {}
                budget = snap.get("budget") or {}
                is_multi_iter = (budget.get("max_iterations") or 0) > 1
            except Exception:
                pass

    outcome = judge_mod.run_judge(
        research_question,
        rebuilt,
        model=args.judge_model or judge_mod.DEFAULT_JUDGE_MODEL,
        metrics=_parse_metrics_csv(args.judge_metrics),
        preset=args.judge_preset,
        is_multi_iter=is_multi_iter,
    )

    # Write the new results.json with updated judge_scores per variant +
    # judge_usage with the new metric set.
    scores_by_variant = {s.variant: s for s in outcome.scores}
    for v in results.get("variants", []):
        score = scores_by_variant.get(v["variant"])
        if score is None:
            v["judge_scores"] = {m: None for m in outcome.metrics}
            v["judge_rationale"] = ""
        else:
            v["judge_scores"] = dict(score.scores)
            v["judge_rationale"] = score.rationale

    results["judge_usage"] = {
        "tokens_in": outcome.tokens_in,
        "tokens_out": outcome.tokens_out,
        "dollars": outcome.dollars,
        "crashed": outcome.crashed,
        "error": outcome.error,
        "metrics": outcome.metrics,
    }

    out_path = (
        Path(args.out).resolve()
        if args.out
        else results_path.with_name("results.rejudged.json")
    )
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Re-judged: {out_path}")
    print(f"  metrics: {', '.join(outcome.metrics)}")
    print(f"  cost:    ${outcome.dollars:.2f}")
    if outcome.crashed:
        print(f"  ERROR:   {outcome.error}")
        return 1
    return 0


def _cmd_import_nous(args: argparse.Namespace) -> int:
    """Convert a nous campaign dir into a bench-compatible results.json."""
    input_dir = Path(args.input_dir).expanduser().resolve()
    if not input_dir.exists():
        print(f"error: input dir not found: {input_dir}", file=sys.stderr)
        return 2

    try:
        snap = import_nous_mod.import_nous_campaign(
            input_dir,
            campaign_id=args.campaign_id,
            research_question=args.research_question,
        )
    except import_nous_mod.ArtifactsDirNotFound as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    run_id = args.run_id or f"imported_{snap.campaign_id}"
    combined = import_nous_mod.snapshot_to_bench_results(snap, run_id=run_id)

    # Optional merge with an existing baselines results.json
    if args.merge_baselines:
        baselines_path = Path(args.merge_baselines).expanduser().resolve()
        if not baselines_path.exists():
            print(
                f"error: --merge-baselines path not found: {baselines_path}",
                file=sys.stderr,
            )
            return 2
        with open(baselines_path) as f:
            baselines = json.load(f)
        combined = import_nous_mod.merge_baselines(combined, baselines)

    out_path = (
        Path(args.out).expanduser().resolve()
        if args.out
        else Path.cwd() / "runs" / run_id / "results.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(combined, f, indent=2)

    print(f"Imported: {out_path}")
    print(f"  campaign_id:           {snap.campaign_id}")
    print(f"  artifacts_dir:         {snap.artifacts_dir}")
    print(f"  iterations_completed:  {snap.iterations_completed}")
    print(f"  final_answer:          {len(snap.final_answer):,} chars")
    print(f"  tokens_in:             {snap.tokens_in:,}")
    print(f"  tokens_out:            {snap.tokens_out:,}")
    print(f"  dollars:               ${snap.dollars:.2f}")
    if args.merge_baselines:
        print(
            f"  merged with baselines: "
            f"{len(combined['variants'])} variants total"
        )
    return 0


def _add_judge_flags(p: argparse.ArgumentParser) -> None:
    """Shared judge-metric/preset/model flags for `run` and `rejudge`."""
    p.add_argument(
        "--judge-metrics",
        help=(
            "comma-separated judge metric names (e.g. "
            "'correctness,novelty,coverage'). Combined with --judge-preset "
            "if both given. Defaults to the 'default' preset."
        ),
    )
    p.add_argument(
        "--judge-preset",
        choices=sorted(judge_mod.PRESETS),
        help=f"named preset (one of: {', '.join(sorted(judge_mod.PRESETS))})",
    )
    p.add_argument(
        "--judge-model",
        help=f"override judge model (default: {judge_mod.DEFAULT_JUDGE_MODEL})",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bench",
        description="nous-bench: compare nous against baselines on a research question",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="run an experiment")
    p_run.add_argument("experiment", help="path to experiment yaml")
    p_run.add_argument(
        "--variants",
        help="comma-separated variants to run (overrides yaml's list)",
    )
    p_run.add_argument("--max-tokens", type=int, help="override budget.max_tokens")
    p_run.add_argument(
        "--max-iterations", type=int, help="override budget.max_iterations"
    )
    p_run.add_argument(
        "--max-wall-seconds", type=int, help="override budget.max_wall_seconds"
    )
    p_run.add_argument("--run-id", help="override generated run id")
    p_run.add_argument(
        "--max-parallel-variants",
        type=int,
        help="cap concurrent variants (default min(num_variants, cpu_count))",
    )
    p_run.add_argument(
        "--skip-judge",
        action="store_true",
        help="skip the Claude-as-judge accuracy scoring step",
    )
    p_run.add_argument(
        "--variant-model",
        help=(
            "model id used by all claude_* variants (overrides "
            "DEFAULT_MODEL='claude-sonnet-4-6'). Use to match the model "
            "tier nous had access to for fair ablation; e.g. "
            "'claude-opus-4-7'. Does not affect the judge model — see "
            "--judge-model for that."
        ),
    )
    _add_judge_flags(p_run)
    p_run.set_defaults(func=_cmd_run)

    p_list = sub.add_parser("list", help="list campaigns, variants, judge metrics + presets")
    p_list.set_defaults(func=_cmd_list)

    p_rejudge = sub.add_parser(
        "rejudge",
        help="re-run the judge over an existing results.json without re-running variants",
    )
    p_rejudge.add_argument(
        "results_path", help="path to an existing runs/<run_id>/results.json"
    )
    p_rejudge.add_argument(
        "--out",
        help="output path (default: results.rejudged.json next to input)",
    )
    p_rejudge.add_argument(
        "--multi-iter",
        action="store_true",
        help="treat run as multi-iter for metric resolution (auto-detected from "
        "experiment.snapshot.yaml budget.max_iterations if not set)",
    )
    _add_judge_flags(p_rejudge)
    p_rejudge.set_defaults(func=_cmd_rejudge)

    p_import = sub.add_parser(
        "import-nous",
        help="convert an existing nous campaign dir into a bench-compatible "
        "results.json (so it can be re-judged under the new rubric)",
    )
    p_import.add_argument(
        "input_dir",
        help="path to a nous campaign directory (e.g. "
        "~/Downloads/succesful_campaigns/flow-control-reflective-v2). "
        "Auto-detects whether artifacts live at the root or one subdirectory deep.",
    )
    p_import.add_argument(
        "--out",
        help="output path for the generated results.json "
        "(default: ./runs/imported_<campaign_id>/results.json)",
    )
    p_import.add_argument(
        "--campaign-id",
        help="override the campaign id (default: read from campaign yaml's run_id, "
        "fallback to input dir name)",
    )
    p_import.add_argument(
        "--research-question",
        help="override the research question (default: read from campaign yaml)",
    )
    p_import.add_argument(
        "--run-id",
        help="bench run id used in the output (default: imported_<campaign_id>)",
    )
    p_import.add_argument(
        "--merge-baselines",
        help="path to an existing baselines results.json (from `bench run`) to "
        "merge with the imported nous variant. After merge, the output contains "
        "all 5 variants and can be re-judged together.",
    )
    p_import.set_defaults(func=_cmd_import_nous)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
