import argparse
import json
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
    print(
        f"Could not find .nous/ directory in any parent of {Path.cwd()}. "
        f"Either run from inside the target repo, pass an explicit "
        f"work_dir path, or set NOUS_CAMPAIGN_PARENT (#239).",
        file=sys.stderr,
    )
    sys.exit(1)


def resolve_work_dir(target):
    """Resolve a CLI ``target`` (yaml path | dir | run_id) to a work_dir.

    Honors NOUS_CAMPAIGN_PARENT (#239) and finds existing campaigns
    that may live at the legacy ``<repo>/.nous/<run_id>/`` path even
    when the env var is set (so users with pre-#239 campaigns can still
    run ``nous status`` / ``nous resume`` without first migrating).

    For an explicit dir target with state.json, the dir is taken at
    face value.
    """
    import os

    from orchestrator.work_dir_resolver import (
        ENV_VAR,
        find_existing_work_dir,
    )

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
            # Wrap in Path() for type-robustness: surfaces a clear error
            # immediately if repo_path is the wrong type (e.g. an int
            # from a hand-edited yaml) rather than failing later in the
            # resolver with a less helpful message.
            repo_path = (
                Path(data["target_system"]["repo_path"])
                if data["target_system"].get("repo_path") is not None
                else None
            )
            run_id = data["run_id"]
        except (KeyError, TypeError) as exc:
            print(f"Campaign file {target} missing required field: {exc}", file=sys.stderr)
            sys.exit(1)
        try:
            work_dir = find_existing_work_dir(run_id, repo_path)
        except (ValueError, FileNotFoundError) as exc:
            print(f"Campaign location resolution failed: {exc}", file=sys.stderr)
            sys.exit(1)
        if work_dir is None:
            print(
                f"Work directory not found for run_id={run_id!r} "
                f"(checked {ENV_VAR} location and "
                f"{repo_path!s}/.nous/{run_id}/ if applicable).",
                file=sys.stderr,
            )
            sys.exit(1)
        return work_dir

    p = Path(target)
    if p.is_dir() and (p / "state.json").exists():
        return p

    if p.is_absolute() or "/" in target:
        print(f"Work directory not found: {p}", file=sys.stderr)
        sys.exit(1)

    run_id = target
    # Bare run_id: prefer find_existing_work_dir (env-var path), then
    # fall back to CWD-walk for the legacy invocation pattern.
    work_dir = None
    try:
        work_dir = find_existing_work_dir(run_id, repo_path=None)
    except ValueError as exc:
        print(f"Campaign location resolution failed: {exc}", file=sys.stderr)
        sys.exit(1)
    if work_dir is None and not os.environ.get(ENV_VAR):
        # No env var set: fall through to legacy CWD-walk for
        # backward-compat with `nous status <run_id>` invoked from
        # inside the target repo.
        root = _find_repo_root()
        candidate = root / ".nous" / run_id
        if candidate.is_dir():
            work_dir = candidate
    if work_dir is None:
        print(
            f"Work directory not found for run_id={run_id!r}. "
            f"Either run from inside the target repo, pass an explicit "
            f"work_dir path, or set {ENV_VAR}.",
            file=sys.stderr,
        )
        sys.exit(1)
    return work_dir


def _sdk_client(options):
    """Client factory seam; tests replace this with a fake."""
    from claude_agent_sdk import ClaudeSDKClient
    return ClaudeSDKClient(options)


def _parse_or_exit(raw):
    from orchestrator.lightweight.config import parse_campaign_config

    try:
        return parse_campaign_config(raw)
    except (ValueError, TypeError, AttributeError) as exc:
        print(f"Campaign validation error: {exc}", file=sys.stderr)
        sys.exit(1)


def _drive_campaign(raw: dict, work_dir: Path, args, *, resume: bool = False) -> None:
    import asyncio
    import logging

    from orchestrator.lightweight.loop import Campaign

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    if args.max_iterations is not None:
        raw["max_iterations"] = args.max_iterations
    if args.model:
        raw["models"] = {**(raw.get("models") or {}), "session": args.model}
    cfg = _parse_or_exit(raw)
    # Save overrides so a later resume without flags keeps them.
    (work_dir / "campaign.yaml").write_text(yaml.safe_dump(raw, sort_keys=False))
    campaign = Campaign(cfg, work_dir, client_factory=_sdk_client)
    if resume:
        summary = asyncio.run(campaign.resume(note=args.note))
    else:
        summary = asyncio.run(campaign.run())
    print(json.dumps(summary, indent=2))


def _cmd_run(args):
    from orchestrator.work_dir_resolver import find_existing_work_dir
    from orchestrator.work_dir_resolver import resolve_work_dir as resolve_new

    campaign_path = Path(args.campaign)
    if not campaign_path.exists():
        print(f"Campaign file not found: {campaign_path}", file=sys.stderr)
        sys.exit(1)
    raw = yaml.safe_load(campaign_path.read_text())
    if not isinstance(raw, dict):
        print(f"Campaign file {campaign_path} is not a YAML mapping", file=sys.stderr)
        sys.exit(1)
    raw["run_id"] = args.run_id or raw.get("run_id") or (campaign_path.parent.name + "-run")
    repo_path = _parse_or_exit(raw).target_system["repo_path"]
    try:
        existing = find_existing_work_dir(raw["run_id"], repo_path)
        work_dir = existing or resolve_new(raw["run_id"], repo_path)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Campaign location resolution failed: {exc}", file=sys.stderr)
        sys.exit(1)
    if (work_dir / "state.json").exists():
        print(f"Campaign already exists at {work_dir}. Use `nous resume {work_dir}` to continue.",
              file=sys.stderr)
        sys.exit(1)
    work_dir.mkdir(parents=True, exist_ok=True)
    print(f"Working directory: {work_dir}")
    _drive_campaign(raw, work_dir, args)


def _cmd_resume(args):
    target = Path(args.target)
    if target.is_dir() and not (target / "state.json").exists():
        print(f"No state.json in {target}. Nothing to resume; use `nous run`.", file=sys.stderr)
        sys.exit(1)
    work_dir = resolve_work_dir(args.target)
    if not (work_dir / "state.json").exists():
        print(f"No state.json in {work_dir}. Nothing to resume; use `nous run`.", file=sys.stderr)
        sys.exit(1)
    campaign_path = work_dir / "campaign.yaml"
    if not campaign_path.exists() and args.target.endswith((".yaml", ".yml")):
        campaign_path = target
    if not campaign_path.exists():
        print(f"No campaign.yaml in {work_dir}.", file=sys.stderr)
        sys.exit(1)
    print(f"Using campaign config {campaign_path}")
    raw = yaml.safe_load(campaign_path.read_text())
    _drive_campaign(raw, work_dir, args, resume=True)


def _read_run(target) -> tuple[Path, dict, list]:
    work_dir = resolve_work_dir(target)
    if not (work_dir / "state.json").exists():
        print(f"Error: no state.json at {work_dir}", file=sys.stderr)
        sys.exit(1)
    state = json.loads((work_dir / "state.json").read_text())
    ledger_path = work_dir / "ledger.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else []
    return work_dir, state, ledger if isinstance(ledger, list) else []


def _cmd_status(args):
    work_dir, state, ledger = _read_run(args.target)
    print(f"Work dir:   {work_dir}")
    print(f"Phase:      {state.get('phase')}  iteration {state.get('iteration')}")
    print(f"Session id: {state.get('session_id')}")
    for row in ledger:
        print(f"  iter-{row.get('iteration')}: status={row.get('status')} "
              f"stop_reason={row.get('stop_reason')}")


def _cmd_cost(args):
    _, _, ledger = _read_run(args.target)
    cost = sum((r.get("cost_meter_usd") or 0) + (r.get("report_cost_usd") or 0) for r in ledger)
    tin = sum((r.get("tokens") or {}).get("input", 0) for r in ledger)
    tout = sum((r.get("tokens") or {}).get("output", 0) for r in ledger)
    print(f"Iterations:   {len(ledger)}")
    print(f"Total cost:   ${cost:.4f} (cost meter)")
    print(f"Total tokens: {tin + tout} (in: {tin}, out: {tout})")


def main():
    parser = argparse.ArgumentParser(
        prog="nous",
        description=(
            "Nous Lightweight: Claude investigates a research question in "
            "one session, keeping a notebook; Nous records every command, "
            "checks the answer against the evidence and runs one independent "
            "challenger. Start with `nous run campaign.yaml`; continue with "
            "`nous resume <work_dir>`."
        ),
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable DEBUG-level logging.",
    )
    subparsers = parser.add_subparsers(dest="command")

    p_run = subparsers.add_parser("run", help="Run a Nous campaign in one Claude session.")
    p_run.add_argument("campaign", help="Path to a campaign.yaml.")
    p_run.add_argument("--max-iterations", type=int,
                       help="Continue messages sent when the agent stops without an answer. "
                       "Overrides campaign.max_iterations.")
    p_run.add_argument("--model", help="Session model. Overrides campaign.models.")
    p_run.add_argument("--run-id", help="Work dir name. Defaults to campaign.run_id "
                       "or a value derived from the file path.")
    p_run.set_defaults(func=_cmd_run)

    p_resume = subparsers.add_parser("resume", help="Resume a campaign from its work dir.")
    p_resume.add_argument("target", help="Work dir, run_id, or campaign.yaml.")
    p_resume.add_argument("--note", default=None,
                          help="Human note added to the first message after the resume.")
    p_resume.add_argument("--max-iterations", type=int,
                          help="Continue-message cap. Saved to the work dir's campaign.yaml.")
    p_resume.add_argument("--model", help="Session model. Saved to the work dir's campaign.yaml.")
    p_resume.set_defaults(func=_cmd_resume)

    p_status = subparsers.add_parser("status", help="Show campaign state and ledger.")
    p_status.add_argument("target", help="Work dir, campaign.yaml, or run_id.")
    p_status.set_defaults(func=_cmd_status)

    p_cost = subparsers.add_parser("cost", help="Sum the cost meter from ledger.json.")
    p_cost.add_argument("target", help="Work dir, campaign.yaml, or run_id.")
    p_cost.set_defaults(func=_cmd_cost)

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
