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


_LEGACY_FLAGS = ("agent", "auto_approve", "timeout", "max_cli_retries", "sandbox")


def _sdk_client(options):
    """Client factory seam; tests replace this with a fake."""
    from claude_agent_sdk import ClaudeSDKClient
    return ClaudeSDKClient(options)


def _warn_ignored_flags(args) -> None:
    for name in _LEGACY_FLAGS:
        if getattr(args, name, None) not in (None, False):
            flag = "--" + name.replace("_", "-")
            print(f"Warning: {flag} is ignored (Nous v2 always uses one Claude SDK session).",
                  file=sys.stderr)


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

    _warn_ignored_flags(args)
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
    _warn_ignored_flags(args)
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
    """Ask a running campaign to wind down cleanly between phases.

    Writes a ``STOP`` sentinel at the campaign work_dir root. The
    next time the orchestrator passes a checkpoint — at the start of
    each iteration AND at every phase transition within an iteration
    (#198) — it raises ``CampaignStopped``, persists a
    ``stopped_by_user`` ledger row, and exits without orphaning
    worktrees or pending dispatcher calls.

    For mid-iteration interruption, ``Ctrl+C`` still works — the
    engine's atomic checkpoint means the next ``nous resume`` picks
    up at the last completed phase. ``nous stop`` is the agent-friendly
    handle: an enclosing agent can write the sentinel without sending
    SIGINT to the parent process.
    """
    from orchestrator.iteration import STOP_SENTINEL_NAME, check_stop_requested

    work_dir = resolve_work_dir(args.target)
    if not work_dir.exists():
        print(f"Error: work_dir does not exist: {work_dir}", file=sys.stderr)
        sys.exit(1)

    sentinel = work_dir / STOP_SENTINEL_NAME
    immediate = work_dir / "STOP_IMMEDIATE"
    existing = check_stop_requested(work_dir)
    if existing is not None and not getattr(args, "immediate", False):
        print(
            f"STOP sentinel already present at {existing}. "
            f"Campaign will halt at the next checkpoint.",
        )
        sys.exit(0)

    reason = (args.reason or "").strip()
    if not sentinel.exists():
        sentinel.write_text(reason + ("\n" if reason else ""))
        print(f"Wrote STOP sentinel: {sentinel}")
    if getattr(args, "immediate", False):
        # #250 (F5): event-boundary halt. Writes a second sentinel that
        # the SDK turn loop checks at each tool-call return. The
        # phase-boundary STOP is also written so the orchestrator's
        # checkpoint loop terminates cleanly even if the SDK turn
        # didn't notice the immediate sentinel.
        immediate.write_text(reason + ("\n" if reason else ""))
        print(f"Wrote STOP_IMMEDIATE sentinel: {immediate}")
        print(
            "The SDK turn will abort at the next event boundary "
            "(typically within seconds), then the orchestrator's "
            "phase-checkpoint will see the STOP sentinel and shut "
            "down cleanly."
        )
        return
    if reason:
        print(f"Reason: {reason}")
    print(
        "The campaign will halt at the next phase boundary (a phase "
        "transition within the current iteration, or the start of "
        "the next iteration — whichever comes first). To cancel the "
        "stop request, delete the sentinel file. For event-boundary "
        "halt during a long EXECUTE_ANALYZE turn, use ``--immediate`` "
        "(#250 / F5)."
    )


_V2_SCHEMAS = Path(__file__).resolve().parent / "v2" / "schemas"


def _cmd_schema(args):
    """Print the JSON Schema for a Nous artifact in a friendly form.

    Surface the canonical campaign / bundle / findings shape directly
    from the CLI so agents and humans don't need to grep the source to
    learn what fields are required, optional, or rejected. The Markdown
    rendering walks the schema deterministically; JSON / YAML modes
    print the schema verbatim for tooling.

    **Pure deterministic Python — no LLM, no SDK, no network.** The
    schema YAML/JSON file is the single source of truth; this command
    is just a renderer. Safe to invoke from CI, hooks, or any
    zero-cost context.
    """
    import json as _json
    target = args.artifact
    if target == "campaign":
        schema_path = Path(__file__).resolve().parent / "schemas" / "campaign.schema.yaml"
    else:
        schema_path = _V2_SCHEMAS / f"{target}.schema.json"
    if schema_path.suffix in (".yaml", ".yml"):
        schema = yaml.safe_load(schema_path.read_text())
    else:
        schema = _json.loads(schema_path.read_text())

    fmt = args.format
    if fmt == "json":
        print(_json.dumps(schema, indent=2))
        return
    if fmt == "yaml":
        print(yaml.safe_dump(schema, sort_keys=False))
        return

    # Markdown mode (default).
    print(_render_schema_markdown(schema, artifact=target))


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

    if artifact == "campaign":
        lines.append("## See also")
        lines.append("")
        lines.append("- `nous create-campaign --to ./campaign.yaml` — scaffold a heavily-commented starting point.")
        lines.append("- `nous run campaign.yaml` — run a campaign in one Claude session (v2).")
        lines.append("- `nous resume <work_dir> [--note TEXT]` — continue a campaign.")
        lines.append("- `nous stop <target>` — ask a running campaign to halt at the next phase boundary (#198).")
        lines.append("- `nous status --watch <target>` — live progress, including a STUCK marker after 5 min of silence.")
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


_V2_PHASE_ARTIFACTS = {
    "baseline": ["baseline"],
    "design": ["problem", "bundle", "plan"],
    "execute": ["findings", "principle_updates"],
    "report": ["answer"],
}


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
    errors = validate_phase_artifacts(work_dir, d, _V2_PHASE_ARTIFACTS[args.phase], **limits)
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


def _deprecated(name: str, func=None):
    """Wrap a v1 command: warn on stderr, then run it (or exit 1 if func is None)."""
    def handler(args):
        if func is None:
            print(f"Error: `nous {name}` was removed in Nous v2 (it only read v1 artifacts).",
                  file=sys.stderr)
            sys.exit(1)
        print(f"Warning: `nous {name}` is deprecated; it reads v1 artifacts, not Nous v2 runs.",
              file=sys.stderr)
        func(args)
    return handler


def _cmd_reports(args):
    """On-demand re-emission of meta_findings.json (#242).

    Runs the pure-Python emitter against any work_dir, regardless of
    whether the campaign reached a clean terminal transition. Useful for
    legacy campaigns that pre-date the in-line emission wired into
    campaign.py, and for campaigns that aborted mid-phase and so never
    reached the four call sites that invoke the emitter automatically.

    Target may be a campaign.yaml (preferred — gives full target_system
    context for the heuristics) or a work_dir / run_id (emitted with an
    empty target_system stub).
    """
    import json as _json
    import yaml as _yaml
    from orchestrator.meta_findings import (
        emit_meta_findings,
        write_meta_findings,
    )
    from orchestrator.validate import validate_meta_findings

    work_dir = resolve_work_dir(args.target)

    campaign: dict = {"target_system": {}}
    if args.target.endswith((".yaml", ".yml")):
        try:
            data = _yaml.safe_load(Path(args.target).read_text())
            if isinstance(data, dict):
                campaign = data
        except (_yaml.YAMLError, OSError) as exc:
            print(
                f"Warning: could not parse {args.target} ({exc}); "
                f"emitting against empty target_system context.",
                file=sys.stderr,
            )

    payload = emit_meta_findings(work_dir, campaign)

    state_path = work_dir / "state.json"
    is_terminal = False
    if state_path.exists():
        try:
            state = _json.loads(state_path.read_text())
            phase = state.get("last_entered_phase") or state.get("phase")
            is_terminal = phase in ("DONE", "STOPPED")
        except (_json.JSONDecodeError, OSError):
            pass

    if not is_terminal:
        prior = payload.get("notes") or ""
        suffix = (
            f"Emitted on-demand via `nous reports` against a non-terminal "
            f"work_dir (state.json: phase is not DONE/STOPPED). The "
            f"three streams reflect partial state — re-emit after "
            f"campaign termination for the canonical record."
        )
        payload["notes"] = (prior + " " + suffix).strip() if prior else suffix

    target = write_meta_findings(work_dir, payload)
    result = validate_meta_findings(work_dir)
    if result["status"] == "fail":
        print(
            f"Warning: emitted meta_findings.json failed self-validation: "
            f"{result['errors']}",
            file=sys.stderr,
        )

    n_lessons = len(payload.get("campaign_design_lessons") or [])
    n_repo = len(payload.get("target_system_asks") or [])
    n_nous = len(payload.get("nous_asks") or [])
    print(
        f"{target}  "
        f"({n_lessons} design lesson(s), {n_repo} repo ask(s), "
        f"{n_nous} nous ask(s))"
    )
    if not is_terminal:
        print(
            "Note: emitted against a non-terminal work_dir; see "
            "meta_findings.json `notes` field.",
            file=sys.stderr,
        )


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
    # #184: --target-repo-path overrides; otherwise scaffold_campaign
    # defaults to CWD at scaffold time.
    if args.target_repo_path is not None:
        kwargs["target_repo_path"] = args.target_repo_path

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


def _cmd_lineage(args):
    """#266 (F21): print derivation chain + cumulative-patch availability."""
    from orchestrator.lineage import summarize_lineage

    work_dir = resolve_work_dir(args.target)
    summary = summarize_lineage(work_dir)
    if getattr(args, "json", False):
        print(json.dumps(summary, indent=2))
        return
    print(f"Campaign:    {summary.get('run_id', '?')}")
    print(f"Work dir:    {summary.get('work_dir')}")
    if summary.get("repo_commit"):
        print(f"Repo commit: {summary['repo_commit'][:12]}")
    derived = summary.get("derived_from")
    if derived:
        print(
            f"derived_from: campaign={derived.get('campaign')}, "
            f"iteration={derived.get('iteration', 'final')}"
        )
    else:
        print("derived_from: (none — this campaign is a fresh root)")
    print()
    print("Iterations:")
    for it in summary.get("iterations", []):
        marker = "✓ cumulative" if it.get("cumulative_patch") else "✗ no cumulative"
        print(f"  {it['iteration']}  [{marker}]")
    if not summary.get("iterations"):
        print("  (no iterations completed yet)")


def _cmd_clean(args):
    """#254 (F9): remove orphaned nous-exp-* worktrees + branches."""
    import subprocess as _sp

    target_repo = args.target_repo or Path.cwd()
    target_repo = Path(target_repo).resolve()
    experiments_dir = target_repo / ".nous-experiments"
    if not experiments_dir.is_dir():
        print(f"No .nous-experiments/ under {target_repo}; nothing to clean.")
        return

    candidates: list[Path] = []
    for entry in sorted(experiments_dir.iterdir()):
        if not entry.is_dir():
            continue
        if args.campaign and args.campaign not in entry.name:
            continue
        candidates.append(entry)

    if args.dry_run:
        print(f"Would remove {len(candidates)} worktree(s) under {experiments_dir}:")
        for p in candidates:
            print(f"  - {p}")
        return

    removed = 0
    for entry in candidates:
        # Best-effort liveness check via .nous-pid (matches gc_orphan_worktrees).
        pid_file = entry / ".nous-pid"
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                import os as _os
                _os.kill(pid, 0)
                # Process is alive — skip.
                print(f"  skip {entry.name} (active pid {pid})")
                continue
            except (ValueError, ProcessLookupError, OSError):
                pass
        # Remove worktree + branch.
        _sp.run(
            ["git", "worktree", "remove", str(entry), "--force"],
            cwd=target_repo, capture_output=True, text=True, check=False,
        )
        branch = f"nous-exp-{entry.name}"
        _sp.run(
            ["git", "branch", "-D", branch],
            cwd=target_repo, capture_output=True, text=True, check=False,
        )
        if entry.exists():
            import shutil as _shutil
            _shutil.rmtree(entry, ignore_errors=True)
        print(f"  removed {entry.name} (+ branch {branch})")
        removed += 1
    print(f"Removed {removed} orphaned worktree(s).")


def _cmd_package(args):
    """#263 (F18): tarball work_dir + reproduce.sh + Dockerfile + README."""
    import tarfile
    import textwrap

    work_dir = resolve_work_dir(args.target)
    if not (work_dir / "state.json").exists():
        print(f"Error: {work_dir} has no state.json; not a campaign work dir.",
              file=sys.stderr)
        sys.exit(1)

    output = args.output or work_dir.parent / f"{work_dir.name}.tar.gz"

    state = json.loads((work_dir / "state.json").read_text())
    repro = state.get("reproducibility_metadata") or {}

    repro_section = "\n".join(
        f"#   {k}: {v}" for k, v in repro.items()
    ) if repro else "#   (no reproducibility_metadata recorded — pre-#262 campaign)"

    repo_commit = repro.get("repo_commit", "<UNKNOWN>")
    reproduce_sh = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        # Generated by ``nous package`` (#263 / F18).
        # Reproducibility metadata captured at INIT (#262 / F17):
        {repro_section}
        set -euo pipefail
        echo "Re-running campaign {state.get('run_id', '?')}"
        echo "Target repo commit at INIT: {repo_commit}"
        echo
        echo "1. Clone the target repo at the captured commit:"
        echo "     git clone <repo-url> target/"
        echo "     cd target && git checkout {repo_commit}"
        echo "2. Re-apply the cumulative patch from any iteration of interest:"
        echo "     git apply ../runs/iter-N/patches/cumulative.patch"
        echo "3. Re-run from this campaign yaml:"
        echo "     nous run campaign.yaml.copy --auto-approve"
    """)

    dockerfile = textwrap.dedent(f"""\
        # Generated by ``nous package`` (#263 / F18).
        # Pins language versions captured by ``capture_reproducibility_metadata`` at INIT.
        FROM ubuntu:24.04
        ENV DEBIAN_FRONTEND=noninteractive
        RUN apt-get update && apt-get install -y --no-install-recommends \\
            git ca-certificates curl python3 python3-pip && \\
            rm -rf /var/lib/apt/lists/*
        # Captured language versions (informational):
        {repro_section.replace(chr(10), chr(10) + '# ')}
        WORKDIR /work
        COPY . /work/
        ENTRYPOINT ["/bin/bash", "/work/reproduce.sh"]
    """)

    readme = textwrap.dedent(f"""\
        # Campaign artifact: {state.get('run_id', '?')}

        Generated by ``nous package`` (#263 / F18). Self-contained
        bundle for paper artifact evaluation.

        ## Contents

        * Campaign work directory (state.json, ledger.json, principles.json,
          per-iter runs/, meta_findings.json).
        * ``reproduce.sh`` — operator-runnable reproduction script
          using the captured reproducibility metadata (#262 / F17).
        * ``Dockerfile`` — pins language versions captured at INIT.
        * Cumulative patches per iteration (``runs/iter-N/patches/cumulative.patch``).

        ## Reproducibility metadata

        ```
        {json.dumps(repro, indent=2)}
        ```
    """)

    # Stage these alongside the work_dir for tar inclusion.
    pkg_root = work_dir
    (pkg_root / "reproduce.sh").write_text(reproduce_sh)
    (pkg_root / "reproduce.sh").chmod(0o755)
    (pkg_root / "Dockerfile").write_text(dockerfile)
    (pkg_root / "PACKAGE_README.md").write_text(readme)

    with tarfile.open(output, "w:gz") as tar:
        tar.add(work_dir, arcname=work_dir.name)
    print(f"Wrote {output}")


def main():
    parser = argparse.ArgumentParser(
        prog="nous",
        description=(
            "Nous v2: hypothesis-driven experimentation in one Claude "
            "session (BASELINE, then DESIGN, EXECUTE per iteration, then "
            "REPORT). Start with `nous run campaign.yaml`; continue with "
            "`nous resume <work_dir>`."
        ),
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable DEBUG-level logging.",
    )
    subparsers = parser.add_subparsers(dest="command")

    def add_legacy_flags(sp):
        """v1 flags: accepted, warned about, ignored (spec section 4)."""
        sp.add_argument("--agent", choices=["inline", "sdk"], default=None,
                        help="Ignored (v2 always uses one Claude SDK session).")
        sp.add_argument("--auto-approve", action="store_true", help="Ignored.")
        sp.add_argument("--timeout", type=int, default=None, help="Ignored.")
        sp.add_argument("--max-cli-retries", type=int, default=None, help="Ignored.")
        sp.add_argument("--sandbox", choices=["bypass", "default"], default=None, help="Ignored.")

    p_run = subparsers.add_parser("run", help="Run a Nous v2 campaign in one Claude session.")
    p_run.add_argument("campaign", help="Path to a campaign.yaml.")
    p_run.add_argument("--max-iterations", type=int,
                       help="Iteration cap. Overrides campaign.max_iterations.")
    p_run.add_argument("--model", help="Session model. Overrides campaign.models.")
    p_run.add_argument("--run-id", help="Work dir name. Defaults to campaign.run_id "
                       "or a value derived from the file path.")
    add_legacy_flags(p_run)
    p_run.set_defaults(func=_cmd_run)

    p_resume = subparsers.add_parser("resume", help="Resume a v2 campaign from its work dir.")
    p_resume.add_argument("target", help="Work dir, run_id, or campaign.yaml.")
    p_resume.add_argument("--note", default=None,
                          help="Human note added to the next phase message and the ledger.")
    p_resume.add_argument("--max-iterations", type=int)
    p_resume.add_argument("--model")
    add_legacy_flags(p_resume)
    p_resume.set_defaults(func=_cmd_resume)

    p_schema = subparsers.add_parser(
        "schema", help="Print the schema for campaign.yaml or a v2 artifact.",
    )
    p_schema.add_argument(
        "artifact",
        choices=["campaign"] + sorted(p.name.split(".")[0] for p in _V2_SCHEMAS.glob("*.schema.json")),
        nargs="?", default="campaign",
        help="Which schema to print. Defaults to 'campaign'.",
    )
    p_schema.add_argument(
        "--format", choices=["md", "json", "yaml"], default="md",
        help="Output format. 'md' (default) is human-readable. "
             "'json' and 'yaml' print the raw schema for tooling.",
    )
    p_schema.set_defaults(func=_cmd_schema)

    p_validate = subparsers.add_parser("validate", help="Validate v2 phase artifacts.")
    p_validate.add_argument("phase", choices=list(_V2_PHASE_ARTIFACTS))
    p_validate.add_argument("--dir", required=True, type=Path,
                            help="runs/iter-N for design/execute; the work dir for baseline/report.")
    p_validate.set_defaults(func=_cmd_validate)

    p_stop = subparsers.add_parser(
        "stop",
        help="Ask a running campaign to halt cleanly at the next "
             "phase boundary by writing a STOP sentinel (#198: honoured "
             "at DESIGN / HUMAN_DESIGN_GATE / EXECUTE_ANALYZE / "
             "HUMAN_FINDINGS_GATE transitions, not just between iterations).",
        description=(
            "Write a STOP sentinel that the running campaign honours at "
            "the next phase boundary (#198). Phase boundaries are DESIGN, "
            "HUMAN_DESIGN_GATE, EXECUTE_ANALYZE, and HUMAN_FINDINGS_GATE — "
            "so the operator can halt cleanly without waiting for the "
            "next iteration. Mid-phase interruption (a wedged BLIS "
            "subprocess, a stuck SDK turn) is still SIGINT's job."
        ),
    )
    p_stop.add_argument(
        "target",
        help="Campaign target — either a path to the work_dir, a path "
             "to campaign.yaml, or a run_id whose work_dir is under "
             "the current repo's .nous/.",
    )
    p_stop.add_argument(
        "--reason", default=None,
        help="Optional human-readable reason recorded in the sentinel "
             "and surfaced in the campaign's halt message.",
    )
    p_stop.add_argument(
        "--immediate", action="store_true",
        help="Event-boundary halt (#250 / F5). Writes a STOP_IMMEDIATE "
             "sentinel that the SDK turn loop checks at each tool-call "
             "return — aborts within seconds rather than at the next "
             "phase boundary. Use when EXECUTE_ANALYZE is building "
             "wrong code and you want to halt promptly.",
    )
    p_stop.set_defaults(func=_cmd_stop)

    p_status = subparsers.add_parser("status", help="Show v2 campaign state and ledger.")
    p_status.add_argument("target")
    p_status.set_defaults(func=_cmd_status)

    p_cost = subparsers.add_parser("cost", help="Sum the v2 cost meter from ledger.json.")
    p_cost.add_argument("target")
    p_cost.set_defaults(func=_cmd_cost)

    for name in ("report", "replay"):
        p_old = subparsers.add_parser(name, help="Deprecated (v1 only).")
        p_old.add_argument("target")
        p_old.add_argument("--iter", type=int)
        p_old.add_argument("--model")
        add_legacy_flags(p_old)
        p_old.set_defaults(func=_deprecated(name))

    p_reports = subparsers.add_parser(
        "reports",
        help="Re-emit meta_findings.json on demand for any work_dir (#242). "
             "Pure-Python; zero LLM tokens. Works against legacy or aborted "
             "campaigns that never reached the in-line emitter.",
    )
    p_reports.add_argument(
        "target",
        help="campaign.yaml (preferred — supplies target_system context) "
             "OR a work_dir / run_id resolvable via NOUS_CAMPAIGN_PARENT.",
    )
    p_reports.set_defaults(func=_deprecated("reports", _cmd_reports))

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
        "--target-repo-path", default=None, type=Path,
        help="target_system.repo_path in the scaffold (#184). When "
             "omitted, the current working directory at scaffold time "
             "is written — which is almost always the right answer "
             "since authors typically scaffold from inside the target "
             "repo. Override with this flag for cross-repo authoring.",
    )
    p_create.add_argument(
        "--force", action="store_true",
        help="Overwrite if the target file already exists.",
    )
    p_create.set_defaults(func=_deprecated("create-campaign", _cmd_create_campaign))

    # #266 (F21): cross-campaign lineage inspection.
    p_lineage = subparsers.add_parser(
        "lineage",
        help="Show derivation chain + per-iteration cumulative-patch "
             "availability for a campaign (#266 / F21).",
    )
    p_lineage.add_argument(
        "target",
        help="Campaign run_id, work_dir, or path to campaign.yaml.",
    )
    p_lineage.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of human-readable text.",
    )
    p_lineage.set_defaults(func=_deprecated("lineage", _cmd_lineage))

    # #254 (F9): orphan-worktree cleanup.
    p_clean = subparsers.add_parser(
        "clean",
        help="Remove stale nous-exp-* worktrees and branches (#254 / F9).",
    )
    p_clean.add_argument(
        "--orphaned", action="store_true",
        help="Remove worktrees whose owning campaign run is dead. "
             "Default mode when --campaign and --target-repo are both unset.",
    )
    p_clean.add_argument(
        "--target-repo", type=Path, default=None,
        help="Target repo to scan. Default: current directory.",
    )
    p_clean.add_argument(
        "--campaign", default=None,
        help="Scope cleanup to a single campaign run_id.",
    )
    p_clean.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be removed without acting.",
    )
    p_clean.set_defaults(func=_deprecated("clean", _cmd_clean))

    # #263 (F18): paper-artifact tarball.
    p_package = subparsers.add_parser(
        "package",
        help="Tarball a work_dir + reproduce.sh + Dockerfile + README "
             "for paper artifact evaluation (#263 / F18).",
    )
    p_package.add_argument(
        "target",
        help="Campaign run_id, work_dir, or path to campaign.yaml.",
    )
    p_package.add_argument(
        "--output", type=Path, default=None,
        help="Path to write the tarball. Default: <work_dir>.tar.gz.",
    )
    p_package.set_defaults(func=_deprecated("package", _cmd_package))

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
