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
    import json

    work_dir = resolve_work_dir(args.target)
    state_file = work_dir / "state.json"
    if not state_file.exists():
        print(f"Error: no state.json at {work_dir}", file=sys.stderr)
        sys.exit(1)

    state = json.loads(state_file.read_text())
    ledger = json.loads((work_dir / "ledger.json").read_text()) if (work_dir / "ledger.json").exists() else {"iterations": []}
    principles = json.loads((work_dir / "principles.json").read_text()) if (work_dir / "principles.json").exists() else {"principles": []}

    active_principles = [p for p in principles.get("principles", []) if p.get("status") == "active"]
    completed = [it for it in ledger.get("iterations", []) if it.get("iteration", 0) > 0]

    print(f"Campaign:    {state.get('run_id', '?')}")
    print(f"Phase:       {state.get('phase', '?')}")
    print(f"Iteration:   {state.get('iteration', '?')}")
    print(f"Completed:   {len(completed)} iteration(s)")
    print(f"Principles:  {len(active_principles)} active")


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
    import logging
    import yaml
    from orchestrator.worktree import create_experiment_worktree, remove_experiment_worktree
    from orchestrator.cli_dispatch import CLIDispatcher

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

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

    print(f"Replaying iteration {iteration} from {iter_dir}")
    experiment_id = None
    experiment_dir, experiment_id = create_experiment_worktree(repo_path, iteration)
    print(f"  Worktree: {experiment_dir}")

    try:
        model = args.model or campaign.get("models", {}).get("execute_analyze") or "claude-sonnet-4-6"
        dispatcher = CLIDispatcher(
            work_dir=work_dir, campaign=campaign,
            model=model, timeout=args.timeout,
        )
        with dispatcher.override_cwd(experiment_dir):
            dispatcher.dispatch(
                "executor", "execute-analyze",
                output_path=iter_dir / "executor_log.md",
                iteration=iteration,
            )
    finally:
        if experiment_id:
            remove_experiment_worktree(repo_path, experiment_id)
            print("  Worktree cleaned up.")


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
    p_run.add_argument("--agent", choices=["inline", "api"], default="api")
    p_run.set_defaults(func=_cmd_run)

    p_resume = subparsers.add_parser("resume")
    p_resume.add_argument("target")
    p_resume.add_argument("--max-iterations", type=int)
    p_resume.add_argument("--model")
    p_resume.add_argument("--auto-approve", action="store_true")
    p_resume.add_argument("--timeout", type=int, default=1800)
    p_resume.add_argument("--max-cli-retries", type=int, default=10)
    p_resume.add_argument("--agent", choices=["inline", "api"], default="api")
    p_resume.set_defaults(func=_cmd_resume)

    p_validate = subparsers.add_parser("validate")
    p_validate.add_argument("phase", choices=["design", "execution"])
    p_validate.add_argument("--dir", required=True, type=Path)
    p_validate.set_defaults(func=_cmd_validate)

    p_status = subparsers.add_parser("status")
    p_status.add_argument("target")
    p_status.set_defaults(func=_cmd_status)

    p_cost = subparsers.add_parser("cost")
    p_cost.add_argument("target")
    p_cost.set_defaults(func=_cmd_cost)

    p_report = subparsers.add_parser("report")
    p_report.add_argument("target")
    p_report.add_argument("--model")
    p_report.add_argument("--timeout", type=int, default=1800)
    p_report.add_argument("--agent", choices=["inline", "api"], default="api")
    p_report.set_defaults(func=_cmd_report)

    p_replay = subparsers.add_parser("replay")
    p_replay.add_argument("target")
    p_replay.add_argument("--iter", required=True, type=int)
    p_replay.add_argument("--model")
    p_replay.add_argument("--timeout", type=int, default=1800)
    p_replay.set_defaults(func=_cmd_replay)

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
