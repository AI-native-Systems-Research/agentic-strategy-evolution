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
    from orchestrator.v2.config import parse_campaign_config

    try:
        return parse_campaign_config(raw)
    except (ValueError, TypeError, AttributeError) as exc:
        print(f"Campaign validation error: {exc}", file=sys.stderr)
        sys.exit(1)


def _drive_campaign(raw: dict, work_dir: Path, args, *, resume: bool = False) -> None:
    import asyncio
    import logging

    from orchestrator.v2.loop import Campaign

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


def _cmd_stop(args):
    """Write a ``STOP`` sentinel at the work_dir root.

    The v2 loop checks it after each iteration's EXECUTE phase and then
    runs REPORT and exits (stop_reason ``stop_sentinel``). Ctrl+C still
    works for a mid-phase halt; ``nous resume`` continues from state.json.
    """
    work_dir = resolve_work_dir(args.target)
    if not work_dir.exists():
        print(f"Error: work_dir does not exist: {work_dir}", file=sys.stderr)
        sys.exit(1)

    sentinel = work_dir / "STOP"
    if sentinel.exists():
        print(
            f"STOP sentinel already present at {sentinel}. "
            f"Campaign will halt at the next checkpoint.",
        )
        sys.exit(0)

    reason = (args.reason or "").strip()
    sentinel.write_text(reason + ("\n" if reason else ""))
    print(f"Wrote STOP sentinel: {sentinel}")
    if reason:
        print(f"Reason: {reason}")
    print(
        "The campaign will halt at the next phase boundary it checks "
        "(the end of the current iteration's EXECUTE phase), then write "
        "its REPORT. To cancel the stop request, delete the sentinel file."
    )


_V2_SCHEMAS = Path(__file__).resolve().parent / "v2" / "schemas"


def _cmd_schema(args):
    """Print a v2 artifact JSON Schema (md, json or yaml). Pure Python, no LLM."""
    schema = json.loads((_V2_SCHEMAS / f"{args.artifact}.schema.json").read_text())
    if args.format == "json":
        print(json.dumps(schema, indent=2))
    elif args.format == "yaml":
        print(yaml.safe_dump(schema, sort_keys=False))
    else:
        print(_render_schema_markdown(schema, artifact=args.artifact))


def _render_schema_markdown(schema: dict, *, artifact: str) -> str:
    """Render a schema as a human-friendly Markdown reference.

    Walks ``properties`` once and groups required vs optional fields.
    Captures field descriptions verbatim so the schema stays the single
    source of truth — no risk of doc/schema drift.
    """
    title = schema.get("title", artifact)
    description = schema.get("description", "").strip()
    required = set(schema.get("required", []))
    properties = schema.get("properties", {}) or {}

    lines: list[str] = []
    lines.append(f"# {title}")
    if description:
        lines.append("")
        lines.append(description)
    lines.append("")
    extra = (
        "Allows additional properties." if schema.get("additionalProperties")
        else "Rejects unknown top-level properties."
    )
    lines.append(f"_{extra}_")
    lines.append("")

    if required:
        lines.append("## Required fields")
        lines.append("")
        for name in sorted(required):
            spec = properties.get(name, {})
            lines.extend(_render_property_md(name, spec))
        lines.append("")

    optional = [n for n in properties if n not in required]
    if optional:
        lines.append("## Optional fields")
        lines.append("")
        for name in sorted(optional):
            spec = properties.get(name, {})
            lines.extend(_render_property_md(name, spec))
        lines.append("")

    return "\n".join(lines)


def _render_property_md(name: str, spec: dict) -> list[str]:
    """Render one schema property as Markdown bullets."""
    if not isinstance(spec, dict):
        return [f"- **{name}**"]
    type_str = spec.get("type", "")
    if isinstance(type_str, list):
        type_str = " | ".join(type_str)
    enum = spec.get("enum")
    desc = (spec.get("description") or "").strip()
    out = [f"- **{name}** _{type_str}_"]
    if enum:
        out.append(f"  - Allowed values: {', '.join(repr(e) for e in enum)}")
    if desc:
        # Indent each line so the bullet renders cleanly.
        for line in desc.splitlines():
            out.append(f"  {line}")
    sub_props = spec.get("properties")
    if isinstance(sub_props, dict) and sub_props:
        sub_required = set(spec.get("required", []))
        for sub_name in sorted(sub_props):
            sub_spec = sub_props[sub_name]
            sub_type = ""
            if isinstance(sub_spec, dict):
                t = sub_spec.get("type", "")
                if isinstance(t, list):
                    t = " | ".join(t)
                sub_type = t
            req_marker = " (required)" if sub_name in sub_required else ""
            out.append(f"  - `{sub_name}` _{sub_type}_{req_marker}")
            sub_desc = (
                sub_spec.get("description", "").strip()
                if isinstance(sub_spec, dict) else ""
            )
            if sub_desc:
                first_line = sub_desc.splitlines()[0]
                out.append(f"    - {first_line}")
    return out


def _phase_artifacts() -> dict[str, list[str]]:
    from orchestrator.v2.hooks import PHASE_ARTIFACTS
    return {phase.lower(): names for phase, names in PHASE_ARTIFACTS.items()}


def _cmd_validate(args):
    """Validate v2 phase artifacts in --dir (an iter dir, or the work dir for baseline/report)."""
    from orchestrator.v2.validators import validate_phase_artifacts

    from orchestrator.v2.config import validator_limits

    d = args.dir.resolve()
    work_dir = d.parent.parent if d.parent.name == "runs" else d
    limits = {}
    if (work_dir / "campaign.yaml").exists():  # same locks the loop checks
        cfg = _parse_or_exit(yaml.safe_load((work_dir / "campaign.yaml").read_text()))
        limits = validator_limits(cfg, work_dir)
    errors = validate_phase_artifacts(work_dir, d, _phase_artifacts()[args.phase], **limits)
    print(json.dumps({"status": "fail" if errors else "pass", "errors": errors}, indent=2))
    if errors:
        sys.exit(1)


def _read_v2_run(target) -> tuple[Path, dict, list]:
    work_dir = resolve_work_dir(target)
    if not (work_dir / "state.json").exists():
        print(f"Error: no state.json at {work_dir}", file=sys.stderr)
        sys.exit(1)
    state = json.loads((work_dir / "state.json").read_text())
    ledger_path = work_dir / "ledger.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else []
    return work_dir, state, ledger if isinstance(ledger, list) else []


def _cmd_status(args):
    work_dir, state, ledger = _read_v2_run(args.target)
    print(f"Work dir:   {work_dir}")
    print(f"Phase:      {state.get('phase')}  iteration {state.get('iteration')}")
    print(f"Session id: {state.get('session_id')}")
    for row in ledger:
        print(f"  iter-{row.get('iteration')}: status={row.get('status')} "
              f"stop_reason={row.get('stop_reason')}")


def _cmd_cost(args):
    _, _, ledger = _read_v2_run(args.target)
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
            "Nous v2: hypothesis-driven experimentation in one Claude "
            "session. Phases: BASELINE once, then DESIGN and EXECUTE per "
            "iteration, then REPORT. Start with `nous run campaign.yaml`; "
            "continue with `nous resume <work_dir>`."
        ),
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable DEBUG-level logging.",
    )
    subparsers = parser.add_subparsers(dest="command")

    p_run = subparsers.add_parser("run", help="Run a Nous v2 campaign in one Claude session.")
    p_run.add_argument("campaign", help="Path to a campaign.yaml.")
    p_run.add_argument("--max-iterations", type=int,
                       help="Iteration cap. Overrides campaign.max_iterations.")
    p_run.add_argument("--model", help="Session model. Overrides campaign.models.")
    p_run.add_argument("--run-id", help="Work dir name. Defaults to campaign.run_id "
                       "or a value derived from the file path.")
    p_run.set_defaults(func=_cmd_run)

    p_resume = subparsers.add_parser("resume", help="Resume a v2 campaign from its work dir.")
    p_resume.add_argument("target", help="Work dir, run_id, or campaign.yaml.")
    p_resume.add_argument("--note", default=None,
                          help="Human note added to the next phase message and the ledger.")
    p_resume.add_argument("--max-iterations", type=int,
                          help="Iteration cap. Saved to the work dir's campaign.yaml.")
    p_resume.add_argument("--model", help="Session model. Saved to the work dir's campaign.yaml.")
    p_resume.set_defaults(func=_cmd_resume)

    p_schema = subparsers.add_parser(
        "schema", help="Print the JSON Schema for a v2 artifact.",
    )
    p_schema.add_argument(
        "artifact",
        choices=sorted(p.name.split(".")[0] for p in _V2_SCHEMAS.glob("*.schema.json")),
        help="Which artifact schema to print.",
    )
    p_schema.add_argument(
        "--format", choices=["md", "json", "yaml"], default="md",
        help="Output format. 'md' (default) is human-readable. "
             "'json' and 'yaml' print the raw schema for tooling.",
    )
    p_schema.set_defaults(func=_cmd_schema)

    p_validate = subparsers.add_parser("validate", help="Validate v2 phase artifacts.")
    p_validate.add_argument("phase", choices=list(_phase_artifacts()))
    p_validate.add_argument("--dir", required=True, type=Path,
                            help="runs/iter-N for design/execute; the work dir for baseline/report.")
    p_validate.set_defaults(func=_cmd_validate)

    p_stop = subparsers.add_parser(
        "stop",
        help="Ask a running campaign to halt cleanly at the next phase "
             "boundary by writing a STOP sentinel.",
        description=(
            "Write a STOP sentinel in the work dir. The v2 loop checks it "
            "at the phase boundary after each iteration's EXECUTE phase, "
            "then runs REPORT and exits. For a mid-phase halt use Ctrl+C; "
            "`nous resume` continues from state.json."
        ),
    )
    p_stop.add_argument(
        "target",
        help="Work dir, campaign.yaml, or run_id.",
    )
    p_stop.add_argument(
        "--reason", default=None,
        help="Optional human-readable reason written into the sentinel.",
    )
    p_stop.set_defaults(func=_cmd_stop)

    p_status = subparsers.add_parser("status", help="Show v2 campaign state and ledger.")
    p_status.add_argument("target", help="Work dir, campaign.yaml, or run_id.")
    p_status.set_defaults(func=_cmd_status)

    p_cost = subparsers.add_parser("cost", help="Sum the v2 cost meter from ledger.json.")
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
