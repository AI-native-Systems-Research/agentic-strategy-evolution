import argparse
import sys
from pathlib import Path

import yaml


def _find_repo_root(start=None):
    current = Path(start) if start else Path.cwd()
    while True:
        if (current / ".nous").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    print("Could not find .nous/ directory in any parent", file=sys.stderr)
    sys.exit(1)


def resolve_work_dir(target):
    if target.endswith(".yaml") or target.endswith(".yml"):
        p = Path(target)
        if not p.exists():
            print(f"Campaign file not found: {target}", file=sys.stderr)
            sys.exit(1)
        try:
            data = yaml.safe_load(p.read_text())
        except yaml.YAMLError as exc:
            print(f"Failed to parse {target}: {exc}", file=sys.stderr)
            sys.exit(1)
        if not isinstance(data, dict):
            print(f"Campaign file {target} is empty or not a YAML mapping", file=sys.stderr)
            sys.exit(1)
        try:
            repo_path = Path(data["target_system"]["repo_path"])
            run_id = data["run_id"]
        except (KeyError, TypeError) as exc:
            print(f"Campaign file {target} missing required field: {exc}", file=sys.stderr)
            sys.exit(1)
        work_dir = repo_path / ".nous" / run_id
        return work_dir

    p = Path(target)
    if p.is_dir() and (p / "state.json").exists():
        return p

    run_id = target
    root = _find_repo_root()
    work_dir = root / ".nous" / run_id
    if not work_dir.is_dir():
        print(f"Work directory not found: {work_dir}", file=sys.stderr)
        sys.exit(1)
    return work_dir


def _cmd_run(args):
    import json
    import logging

    import jsonschema

    from orchestrator.campaign import run_campaign
    from orchestrator.iteration import setup_work_dir

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    campaign_path = Path(args.campaign)
    if not campaign_path.exists():
        print(f"Campaign file not found: {campaign_path}", file=sys.stderr)
        sys.exit(1)

    with open(campaign_path) as f:
        campaign = yaml.safe_load(f)

    schemas_dir = Path(__file__).resolve().parent / "schemas"
    schema = yaml.safe_load((schemas_dir / "campaign.schema.yaml").read_text())
    try:
        jsonschema.validate(campaign, schema)
    except jsonschema.ValidationError as exc:
        print(f"Campaign validation error: {exc.message}", file=sys.stderr)
        sys.exit(1)

    run_id = args.run_id or campaign.get("run_id") or (campaign_path.parent.name + "-run")
    repo_path = campaign["target_system"].get("repo_path")

    if repo_path:
        state_path = Path(repo_path) / ".nous" / run_id / "state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text())
            if state.get("phase") != "INIT":
                print(
                    f"Run '{run_id}' already in progress (phase={state['phase']}). "
                    f"Use 'nous resume' to continue.",
                    file=sys.stderr,
                )
                sys.exit(1)

    work_dir = setup_work_dir(run_id, repo_path=repo_path)

    max_iterations = args.max_iterations if args.max_iterations is not None else campaign.get("max_iterations", 10)
    run_campaign(
        campaign,
        work_dir,
        max_iterations=max_iterations,
        model=args.model,
        auto_approve=args.auto_approve,
        timeout=args.timeout,
        agent=args.agent,
        max_cli_retries=None if args.max_cli_retries == -1 else args.max_cli_retries,
    )


def _cmd_resume(args):
    import logging

    from orchestrator.campaign import run_campaign

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    work_dir = resolve_work_dir(args.target)

    state_path = work_dir / "state.json"
    if not state_path.exists():
        print(f"No state.json found in {work_dir}. Nothing to resume.", file=sys.stderr)
        sys.exit(1)

    if args.target.endswith(".yaml") or args.target.endswith(".yml"):
        with open(args.target) as f:
            campaign = yaml.safe_load(f)
    else:
        print("resume requires campaign.yaml", file=sys.stderr)
        sys.exit(1)

    max_iterations = args.max_iterations if args.max_iterations is not None else campaign.get("max_iterations", 10)
    run_campaign(
        campaign,
        work_dir,
        max_iterations=max_iterations,
        model=args.model,
        auto_approve=args.auto_approve,
        timeout=args.timeout,
        agent=args.agent,
        max_cli_retries=None if args.max_cli_retries == -1 else args.max_cli_retries,
    )


def _cmd_validate(args):
    import json

    from orchestrator.validate import validate_design, validate_execution

    if args.phase == "design":
        result = validate_design(args.dir)
    else:
        result = validate_execution(args.dir)

    print(json.dumps(result, indent=2))
    if result["status"] != "pass":
        sys.exit(1)


def _cmd_status(args):
    """Status surface — one-shot, single-line, or live --watch (#127)."""
    import time as _time
    from orchestrator.status import (
        format_one_liner,
        format_watch_panel,
        read_status_snapshot,
    )

    work_dir = resolve_work_dir(args.target)
    if not (work_dir / "state.json").exists():
        print(f"Error: no state.json at {work_dir}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "line", False):
        print(format_one_liner(read_status_snapshot(work_dir)))
        return

    if getattr(args, "watch", False):
        try:
            while True:
                snap = read_status_snapshot(work_dir)
                # Clear screen + home cursor (ANSI). Falls back gracefully
                # in non-tty contexts to a separator line.
                if sys.stdout.isatty():
                    sys.stdout.write("\033[2J\033[H")
                else:
                    sys.stdout.write("\n" + "─" * 60 + "\n")
                sys.stdout.write(format_watch_panel(snap) + "\n")
                sys.stdout.flush()
                _time.sleep(args.interval if args.interval > 0 else 2)
        except KeyboardInterrupt:
            print()
            return

    print(format_watch_panel(read_status_snapshot(work_dir)))


def _cmd_cost(args):
    from orchestrator.metrics import summarize_metrics

    work_dir = resolve_work_dir(args.target)
    metrics_path = work_dir / "llm_metrics.jsonl"
    if not metrics_path.exists():
        print("No metrics recorded yet.")
        return

    s = summarize_metrics(metrics_path)
    total_tokens = s["total_input_tokens"] + s["total_output_tokens"]
    duration_min = s.get("total_duration_ms", 0) / 60000

    print(f"Total calls:   {s['total_calls']}")
    print(f"Total cost:    ${s['total_cost_usd']:.4f}")
    print(f"Total tokens:  {total_tokens} (in: {s['total_input_tokens']}, out: {s['total_output_tokens']})")
    print(f"Total time:    {duration_min:.1f} min")

    if s.get("by_phase"):
        print(f"\nBy phase:")
        for phase, b in s["by_phase"].items():
            print(f"  {phase:20s}  {b['calls']} calls  ${b['cost_usd']:.4f}  {b['input_tokens']+b['output_tokens']} tok")

    if getattr(args, "cache_stats", False):
        from orchestrator.cache_stats import cache_stats, format_cache_stats
        print("\nCache stats:")
        print(format_cache_stats(cache_stats(metrics_path)))


def _cmd_report(args):
    import logging
    import yaml
    from orchestrator.campaign import _generate_report

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if not args.target.endswith((".yaml", ".yml")):
        print(
            "Error: report requires campaign.yaml for LLM configuration.\n"
            "Use: nous report <campaign.yaml>",
            file=sys.stderr,
        )
        sys.exit(1)

    work_dir = resolve_work_dir(args.target)
    campaign = yaml.safe_load(Path(args.target).read_text())
    _generate_report(campaign, work_dir, args.model, agent=args.agent, timeout=args.timeout)


def _cmd_replay(args):
    import subprocess
    import yaml
    from orchestrator.worktree import create_experiment_worktree, remove_experiment_worktree

    if not args.target.endswith((".yaml", ".yml")):
        print("Error: replay requires campaign.yaml.\nUse: nous replay <campaign.yaml> --iter N", file=sys.stderr)
        sys.exit(1)

    work_dir = resolve_work_dir(args.target)
    iteration = args.iter
    iter_dir = work_dir / "runs" / f"iter-{iteration}"

    if not iter_dir.is_dir():
        print(f"Error: {iter_dir} does not exist.", file=sys.stderr)
        sys.exit(1)

    plan_path = iter_dir / "experiment_plan.yaml"
    if not plan_path.exists():
        print(f"Error: no experiment_plan.yaml in {iter_dir}", file=sys.stderr)
        sys.exit(1)

    campaign = yaml.safe_load(Path(args.target).read_text())
    raw_repo = campaign.get("target_system", {}).get("repo_path")
    if not raw_repo:
        print("Error: replay requires target_system.repo_path in campaign.yaml", file=sys.stderr)
        sys.exit(1)
    repo_path = Path(raw_repo)

    plan = yaml.safe_load(plan_path.read_text())
    if not isinstance(plan, dict):
        print(f"Error: experiment_plan.yaml is empty or malformed in {iter_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Replaying iteration {iteration} from {iter_dir}")
    experiment_id = None
    experiment_dir, experiment_id = create_experiment_worktree(repo_path, iteration)
    print(f"  Worktree: {experiment_dir}")

    try:
        for step in plan.get("setup", []):
            print(f"  [setup] {step.get('description', step['cmd'][:60])}")
            result = subprocess.run(step["cmd"], shell=True, cwd=experiment_dir)
            if result.returncode != 0:
                print(f"Error: setup command failed (exit {result.returncode})", file=sys.stderr)
                sys.exit(1)

        total = sum(len(arm.get("conditions", [])) for arm in plan.get("arms", []))
        done = 0
        for arm in plan.get("arms", []):
            arm_id = arm.get("arm_id", "unknown")
            for cond in arm.get("conditions", []):
                done += 1
                name = cond.get("name", "unnamed")
                print(f"  [{done}/{total}] {arm_id}/{name}")
                result = subprocess.run(cond["cmd"], shell=True, cwd=experiment_dir)
                if result.returncode != 0:
                    print(f"Error: {arm_id}/{name} failed (exit {result.returncode})", file=sys.stderr)
                    sys.exit(1)

        print(f"  Replay complete: {done}/{total} conditions passed.")
    finally:
        if experiment_id:
            remove_experiment_worktree(repo_path, experiment_id)
            print("  Worktree cleaned up.")


def _cmd_create_campaign(args):
    """Scaffold a heavily-commented campaign.yaml (issue #89)."""
    from orchestrator.create_campaign import scaffold_campaign

    kwargs: dict = {"force": args.force}
    if args.target_name:
        kwargs["target_name"] = args.target_name
    if args.target_description:
        kwargs["target_description"] = args.target_description
    if args.research_question:
        kwargs["research_question"] = args.research_question
    if args.run_id:
        kwargs["run_id"] = args.run_id

    try:
        path = scaffold_campaign(args.to, **kwargs)
    except FileExistsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("Pass --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    print(f"Wrote {path}")
    print()
    print("Next steps:")
    print(f"  1. Edit {path} — replace TODO markers, especially")
    print(f"     target_system.description (that's the channel the LLM reads).")
    print(f"  2. Skim the AUTHORING CHECKLIST near the top of the file.")
    print(f"  3. Run: nous run {path}")


def main():
    parser = argparse.ArgumentParser(prog="nous")
    parser.add_argument("-v", "--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command")

    p_run = subparsers.add_parser("run")
    p_run.add_argument("campaign")
    p_run.add_argument("--max-iterations", type=int)
    p_run.add_argument("--model")
    p_run.add_argument("--run-id")
    p_run.add_argument("--auto-approve", action="store_true")
    p_run.add_argument("--timeout", type=int, default=1800)
    p_run.add_argument("--max-cli-retries", type=int, default=10)
    p_run.add_argument("--agent", choices=["inline", "api", "sdk"], default="api")
    p_run.set_defaults(func=_cmd_run)

    p_resume = subparsers.add_parser("resume")
    p_resume.add_argument("target")
    p_resume.add_argument("--max-iterations", type=int)
    p_resume.add_argument("--model")
    p_resume.add_argument("--auto-approve", action="store_true")
    p_resume.add_argument("--timeout", type=int, default=1800)
    p_resume.add_argument("--max-cli-retries", type=int, default=10)
    p_resume.add_argument("--agent", choices=["inline", "api", "sdk"], default="api")
    p_resume.set_defaults(func=_cmd_resume)

    p_validate = subparsers.add_parser("validate")
    p_validate.add_argument("phase", choices=["design", "execution"])
    p_validate.add_argument("--dir", required=True, type=Path)
    p_validate.set_defaults(func=_cmd_validate)

    p_status = subparsers.add_parser("status")
    p_status.add_argument("target")
    p_status.add_argument(
        "--watch", action="store_true",
        help="Loop and redraw every --interval seconds (#127).",
    )
    p_status.add_argument(
        "--line", action="store_true",
        help="Print a single-line summary suitable for shell prompts (#127).",
    )
    p_status.add_argument(
        "--interval", type=float, default=2.0,
        help="Watch redraw interval in seconds (default: 2).",
    )
    p_status.set_defaults(func=_cmd_status)

    p_cost = subparsers.add_parser("cost")
    p_cost.add_argument("target")
    p_cost.add_argument(
        "--cache-stats", action="store_true",
        help="Include prompt-cache hit-rate stats (#122).",
    )
    p_cost.set_defaults(func=_cmd_cost)

    p_report = subparsers.add_parser("report")
    p_report.add_argument("target")
    p_report.add_argument("--model")
    p_report.add_argument("--timeout", type=int, default=1800)
    p_report.add_argument("--agent", choices=["inline", "api", "sdk"], default="api")
    p_report.set_defaults(func=_cmd_report)

    p_replay = subparsers.add_parser("replay")
    p_replay.add_argument("target")
    p_replay.add_argument("--iter", required=True, type=int)
    p_replay.set_defaults(func=_cmd_replay)

    # `create-campaign` (issue #89): scaffold a heavily-commented
    # campaign.yaml that names the four agent-reachable fields and
    # warns about the domain_adapter_layer trap.
    p_create = subparsers.add_parser(
        "create-campaign",
        help="Scaffold a new campaign.yaml with inline guidance.",
    )
    p_create.add_argument(
        "--to", required=True, type=Path,
        help="Path to write the new campaign.yaml.",
    )
    p_create.add_argument(
        "--target-name", default="TODO-SET-SYSTEM-NAME",
        help="target_system.name in the scaffolded YAML.",
    )
    p_create.add_argument(
        "--target-description", default=None,
        help="target_system.description (the field the agent actually reads). "
             "Use heredoc / file substitution for multi-line content.",
    )
    p_create.add_argument(
        "--research-question", default=None,
        help="Top-level research_question (one falsifiable sentence).",
    )
    p_create.add_argument(
        "--run-id", default="TODO-SET-RUN-ID",
        help="Working directory name for campaign output.",
    )
    p_create.add_argument(
        "--force", action="store_true",
        help="Overwrite if the target file already exists.",
    )
    p_create.set_defaults(func=_cmd_create_campaign)

    args = parser.parse_args()
    if not args.command:
        parser.print_help(sys.stderr)
        sys.exit(1)

    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        if args.verbose:
            import traceback
            traceback.print_exc()
        else:
            print("  (use -v for full traceback)", file=sys.stderr)
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
