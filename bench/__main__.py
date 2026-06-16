"""CLI entry point for nous-bench. `python3 -m bench run <experiment.yaml>`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from bench import runner

VARIANT_DESCRIPTIONS = {
    "nous": "full orchestrator (multi-iter, schema-validated, isolated)",
    "claude_plain": "single Claude Code session, no methodology",
    "claude_loop": "N sequential plain sessions, summary carry-forward",
    "claude_methodology": "single session w/ methodology.md as system prompt",
    "claude_methodology_loop": "N methodology sessions w/ principle carry-forward",
}


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

    run_dir = runner.run_experiment(
        Path(args.experiment),
        variants_override=variants_override,
        budget_overrides=budget_overrides or None,
        run_id=args.run_id,
        max_parallel_variants=args.max_parallel_variants,
        skip_judge=args.skip_judge,
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
    return 0


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
    p_run.set_defaults(func=_cmd_run)

    p_list = sub.add_parser("list", help="list campaigns and variants")
    p_list.set_defaults(func=_cmd_list)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
