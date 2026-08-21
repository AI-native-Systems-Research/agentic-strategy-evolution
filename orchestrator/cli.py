import argparse
import json
import sys
from pathlib import Path

import yaml


def resolve_gate_mode(args, campaign):
    """Resolve the effective ``auto_approve`` bool for a run/resume.

    Gate defaults are scoped to campaign ``kind`` (spec §7.1 of the
    ``kind: optimization`` design): an optimization campaign's stage
    rule is pure Python with no per-stage human decision that changes
    what happens next, so prompting only costs wall-clock. Reflective
    campaigns (or campaigns with no ``kind`` at all) keep the historical
    default of prompting unless the operator opts in.

    Resolution order (highest precedence first):
      1. ``--interactive`` forces prompting (``False``) for either kind.
      2. An explicit ``--auto-approve`` on the command line wins over
         the kind default, in either direction — this is what keeps
         existing invocations and scripts behaving exactly as before.
      3. Otherwise, fall back to the kind default: ``True`` for
         ``kind: optimization``, ``False`` for ``kind: reflective``
         (or absent).

    ``args.auto_approve`` must distinguish "flag omitted" (``None``)
    from "flag explicitly supplied" (``True``) — see the
    ``action="store_const", const=True, default=None`` wiring on the
    ``--auto-approve`` argument. A plain ``store_true`` (default
    ``False``) cannot make that distinction and would let the kind
    default silently override an explicit user choice.
    """
    from orchestrator.validate import campaign_kind

    if getattr(args, "interactive", False):
        return False
    explicit_auto_approve = getattr(args, "auto_approve", None)
    if explicit_auto_approve is not None:
        return explicit_auto_approve
    return campaign_kind(campaign) == "optimization"


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


def _warn_tracked_worktree_extras(repo_path, extras: list[str]) -> None:
    """#251 (F6): emit a soft warning at campaign load time for any
    worktree_extras entry that is tracked in the target repo's main
    branch. Tracked paths are already in every git worktree checkout;
    declaring them in worktree_extras triggers a per-iteration
    collision warning. Catching this at load time saves the operator
    from re-investing in a doomed run.

    Best-effort — git failures fall through silently (the per-iteration
    warning still fires as the second line of defense).
    """
    if not repo_path or not extras:
        return
    import subprocess as _sp

    repo = Path(repo_path)
    if not repo.is_dir():
        return
    for entry in extras:
        if not isinstance(entry, str) or not entry.strip():
            continue
        result = _sp.run(
            ["git", "-C", str(repo), "ls-files", "--error-unmatch", entry],
            capture_output=True, text=True, check=False, timeout=5,
        )
        if result.returncode == 0:
            print(
                f"  ⚠  worktree_extras entry {entry!r} is tracked in the "
                f"target repo's main branch. Tracked paths are already "
                f"in every git worktree checkout; declaring them here "
                f"will trigger per-iteration collision warnings (#251 / F6). "
                f"Remove this entry from campaign.target_system.worktree_extras, "
                f"or move the file out of git tracking if you intend "
                f"to override it."
            )


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

    # #251 (F6): warn at campaign load time about ``worktree_extras``
    # entries that are tracked in the target repo's main branch.
    # Tracked paths are already in every git worktree checkout;
    # declaring them here triggers a per-iteration collision warning
    # that is preventable here.
    _warn_tracked_worktree_extras(
        repo_path, campaign.get("target_system", {}).get("worktree_extras") or [],
    )

    # #239: in-progress detection must check BOTH the legacy and
    # env-var locations — otherwise toggling NOUS_CAMPAIGN_PARENT
    # between runs would silently allow a parallel run that corrupts
    # shared worktrees. find_existing_work_dir consults all candidates
    # plus state.json's recorded work_dir.
    import os as _os

    from orchestrator.work_dir_resolver import (
        ENV_VAR,
        find_existing_work_dir,
    )
    try:
        existing = find_existing_work_dir(run_id, repo_path)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Campaign location resolution failed: {exc}", file=sys.stderr)
        sys.exit(1)
    if existing is not None:
        state = json.loads((existing / "state.json").read_text())
        # #236: read via helper so legacy ``phase`` keys still resolve.
        from orchestrator.engine import read_phase_field
        phase = read_phase_field(state)
        if phase != "INIT":
            print(
                f"Run '{run_id}' already in progress at {existing} "
                f"(phase={phase}). Use 'nous resume' to continue.",
                file=sys.stderr,
            )
            sys.exit(1)
        # Migration hint: if env var is set but the existing campaign
        # lives at the legacy location, point the user at `mv`.
        if _os.environ.get(ENV_VAR) and ".nous" in existing.parts:
            print(
                f"Note: campaign found at legacy location {existing}. "
                f"To migrate to {ENV_VAR}: "
                f"`mv {existing} ${ENV_VAR}/{run_id}` and re-run. "
                f"Continuing at the legacy location for now.",
                file=sys.stderr,
            )

    work_dir = setup_work_dir(
        run_id, repo_path=repo_path,
        campaign_path=campaign_path, campaign=campaign,
    )

    max_iterations = args.max_iterations if args.max_iterations is not None else campaign.get("max_iterations", 10)
    # #188: --bundle / --problem-md / --handoff-md only apply to iter-1.
    # run_campaign passes them through to run_iteration with iter==1.
    pre_authored_bundle = getattr(args, "bundle", None)
    pre_authored_problem_md = getattr(args, "problem_md", None)
    pre_authored_handoff_md = getattr(args, "handoff_md", None)
    if pre_authored_bundle is not None and not pre_authored_bundle.exists():
        print(
            f"Error: --bundle path does not exist: {pre_authored_bundle}",
            file=sys.stderr,
        )
        sys.exit(1)
    # #193: --sandbox CLI flag overrides campaign.sandbox if both present;
    # leaving it unset preserves whatever the campaign.yaml declares (or
    # the SDKDispatcher default of "bypass").
    if getattr(args, "sandbox", None) is not None:
        campaign["sandbox"] = args.sandbox
    run_campaign(
        campaign,
        work_dir,
        max_iterations=max_iterations,
        model=args.model,
        auto_approve=resolve_gate_mode(args, campaign),
        timeout=args.timeout,
        agent=args.agent,
        max_cli_retries=None if args.max_cli_retries == -1 else args.max_cli_retries,
        pre_authored_bundle=pre_authored_bundle,
        pre_authored_problem_md=pre_authored_problem_md,
        pre_authored_handoff_md=pre_authored_handoff_md,
    )


def _cmd_resume(args):
    import logging

    from orchestrator.campaign import run_campaign, read_persisted_max_iterations

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    # #253 (F8): a frequent user trip-up is passing a work_dir to
    # ``nous resume`` (because ``nous status <work_dir>`` works that
    # way). Detect it and emit a diagnostic error rather than the
    # confusing "Work directory not found" message that doesn't
    # explain the argument-type expectation.
    target_path = Path(args.target)
    if (
        not (args.target.endswith(".yaml") or args.target.endswith(".yml"))
        and target_path.is_dir()
    ):
        # Looks like a directory, not a campaign.yaml. If a
        # campaign.yaml.copy exists at the work_dir, hint to the user
        # to point ``nous resume`` at the original campaign.yaml.
        candidate = target_path / "campaign.yaml.copy"
        hint = ""
        if candidate.exists():
            hint = (
                f"\nNote: a copy of the campaign yaml is at:\n  {candidate}\n"
                f"You can pass that to ``nous resume`` (it will be schema-"
                f"validated like the original)."
            )
        print(
            f"Error: ``nous resume`` expects a campaign.yaml path "
            f"(the same target you passed to ``nous run``). "
            f"Got: {args.target}\n"
            f"This appears to be a work_dir. Use ``nous status "
            f"{args.target}`` to inspect the work_dir; ``nous resume`` "
            f"needs the campaign yaml so it can re-validate the spec "
            f"and re-emit reproducibility metadata (#253 / F8)."
            f"{hint}",
            file=sys.stderr,
        )
        sys.exit(2)

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

    # #197: max_iterations resolution chain on resume:
    #   1. CLI --max-iterations (explicit override wins).
    #   2. state.json (preserves the cap from the original `nous run`).
    #   3. campaign.yaml.max_iterations, or the hardcoded default 10 if
    #      campaign.yaml doesn't pin it. (Both flow through the same
    #      `campaign.get("max_iterations", 10)` call — legacy state files
    #      pre-dating #197 land here.)
    if args.max_iterations is not None:
        max_iterations = args.max_iterations
        print(f"Resuming with max_iterations={max_iterations} (CLI override).")
    else:
        persisted = read_persisted_max_iterations(work_dir)
        if persisted is not None:
            max_iterations = persisted
            print(
                f"Resuming with max_iterations={max_iterations} "
                f"(persisted from original `nous run`)."
            )
        else:
            max_iterations = campaign.get("max_iterations", 10)
            print(
                f"Resuming with max_iterations={max_iterations} "
                f"(from campaign.yaml / default — state.json had no "
                f"persisted value)."
            )
    run_campaign(
        campaign,
        work_dir,
        max_iterations=max_iterations,
        model=args.model,
        auto_approve=resolve_gate_mode(args, campaign),
        timeout=args.timeout,
        agent=args.agent,
        max_cli_retries=None if args.max_cli_retries == -1 else args.max_cli_retries,
    )


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
    SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"
    schema_files = {
        "campaign": SCHEMAS_DIR / "campaign.schema.yaml",
        "bundle": SCHEMAS_DIR / "bundle.schema.yaml",
        "findings": SCHEMAS_DIR / "findings.schema.json",
    }
    target = args.artifact
    schema_path = schema_files[target]
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
        lines.append("- `nous run campaign.yaml` — run a campaign (default `--agent sdk`).")
        lines.append("- `nous run campaign.yaml --bundle ./bundle.yaml` — skip DESIGN with a pre-authored bundle (#188).")
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


def _cmd_validate(args):
    import json

    from orchestrator.validate import validate_design, validate_execution

    if args.phase == "campaign":
        if args.file is None:
            print(
                "validate campaign: pass the campaign.yaml path, e.g.\n"
                "  nous validate campaign ./campaign.yaml",
                file=sys.stderr,
            )
            sys.exit(2)
        _validate_campaign_file(args.file, smoke=getattr(args, 'smoke', False))
        return
    if args.dir is None:
        print(
            f"validate {args.phase}: --dir is required (the iteration "
            f"directory to check).",
            file=sys.stderr,
        )
        sys.exit(2)
    if args.phase == "design":
        result = validate_design(args.dir)
    else:
        result = validate_execution(args.dir)

    print(json.dumps(result, indent=2))
    if result["status"] != "pass":
        sys.exit(1)


def _validate_campaign_file(path: Path, smoke: bool = False) -> None:
    """Check a campaign.yaml before spending anything on a run.

    Runs BOTH layers an author can trip: the JSON Schema (shape, required
    fields, enums) and the cross-field rules that JSON Schema cannot express
    (``validate_optimization_campaign``). Before this existed the cross-field
    rules had no production caller at all — they ran only in tests — so an
    author authoring a ``kind: optimization`` campaign got raw jsonschema
    messages with no repair path, and a wrong ``native_test`` identifier was
    only discovered by a real campaign aborting at its verify stage.

    Schema errors are translated from jsonschema's default phrasing into the
    field path plus what was expected, because "60 is not of type 'object'"
    without a path is not actionable.
    """
    import jsonschema
    import yaml

    from orchestrator.validate import campaign_kind, validate_optimization_campaign

    target = Path(path)
    if not target.exists():
        print(f"validate: {target} does not exist", file=sys.stderr)
        sys.exit(2)
    try:
        campaign = yaml.safe_load(target.read_text())
    except yaml.YAMLError as exc:
        print(f"validate: {target} is not valid YAML:\n  {exc}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(campaign, dict):
        print(
            f"validate: {target} must be a YAML mapping, got "
            f"{type(campaign).__name__}",
            file=sys.stderr,
        )
        sys.exit(2)

    kind = campaign_kind(campaign)
    print(f"campaign: {target}")
    print(f"kind:     {kind}")

    schemas_dir = Path(__file__).resolve().parent / "schemas"
    schema = yaml.safe_load((schemas_dir / "campaign.schema.yaml").read_text())
    validator = jsonschema.Draft202012Validator(schema)
    schema_errors = sorted(validator.iter_errors(campaign), key=lambda e: e.path)

    errors: list[str] = []
    for err in schema_errors:
        where = ".".join(str(p) for p in err.absolute_path) or "(top level)"
        errors.append(f"[schema] {where}: {err.message}")

    warnings: list[str] = []
    if not schema_errors:
        # Cross-field rules assume a shape-valid document; running them on a
        # malformed one produces confusing secondary errors.
        for item in validate_optimization_campaign(campaign):
            if item.startswith("WARN:"):
                warnings.append(item[len("WARN:"):].strip())
            else:
                errors.append(f"[rules] {item}")

    if warnings:
        print(f"\n{len(warnings)} warning(s) — not fatal, but worth reading:")
        for w in warnings:
            print(f"  ! {w}")

    if errors:
        print(f"\n{len(errors)} error(s):", file=sys.stderr)
        for e in errors:
            print(f"  x {e}", file=sys.stderr)
        guide = (
            "docs/optimization-campaign-guide.md"
            if kind == "optimization"
            else "docs/campaign-authoring-guide.md"
        )
        print(f"\nSee {guide} for the field-by-field walkthrough.", file=sys.stderr)
        sys.exit(1)

    print(f"\nOK — no errors. {len(warnings)} warning(s).")
    if kind == "optimization":
        opt = campaign.get("optimization") or {}
        n_factors = len(opt.get("factors") or [])
        tests = [
            r.get("native_test")
            for f in (opt.get("factors") or [])
            for r in (f.get("relations") or [])
            if r.get("native_test")
        ]
        print(f"  {n_factors} factor(s), {len(tests)} declared native test(s).")
        print(
            "  NOTE: a native_test identifier that does not exist in the target "
            "repo counts as a FAILED correctness relation (reconcile treats "
            "'declared but not executed' as failure), which aborts the campaign "
            "at its verify stage. Confirm each one runs under "
            "optimization.test_command before starting a run."
        )
        if not smoke:
            print(
                "  Static checks only. Re-run with --smoke to execute the test "
                "command and ONE configuration: that is the only way to catch a "
                "manipulation predicate whose type never matches, an unmatched "
                "native_test, or a run_command that cannot exec."
            )
        else:
            print("\n  --smoke: executing the contract against the target...")
            issues = _smoke_check_optimization(campaign)
            if issues:
                print(f"\n{len(issues)} smoke failure(s):", file=sys.stderr)
                for i in issues:
                    print(f"  x {i}", file=sys.stderr)
                print(
                    "\nThese would each have cost a full campaign to discover. "
                    "Fix them before launching.", file=sys.stderr,
                )
                sys.exit(1)
            print("  smoke: OK — the campaign/target contract holds.")


def _smoke_check_optimization(campaign: dict) -> list[str]:
    """Execute the test command and ONE configuration; report what breaks.

    Static validation cannot see the failures that actually kill campaigns,
    because they live in the *contract between the campaign and the target*
    rather than in the campaign's structure. Every one of these was observed on
    a real run that passed static validation cleanly:

      * a ``run_command`` that cannot exec (an inline ``VAR=value`` prefix is
        parsed by ``shlex`` as the binary name);
      * a declared ``native_test`` the test command never reports, so the
        relation reconciles as "declared but not executed" and fails closed;
      * a manipulation predicate comparing a level string to a value the target
        emits as a bool/int, which can never match -- 67 of 67 runs failed this
        way while the CLI itself was correct;
      * an objective metric absent from the emitted JSON, so every run parses
        and scores NaN;
      * a ``config_patch`` factor whose value never reaches the file the target
        reads. This one is the reason "the probe run succeeded" is not the
        criterion: a config-patch campaign whose patches were dropped exits 0
        and emits perfectly parseable JSON on every row -- it just measures the
        BASELINE. So the probe's materialized copy is read BACK through the same
        pointer that wrote it, value and type compared against the requested
        level.

    One probe run costs seconds and catches all five. It also reports the
    probe's real DURATION against the effective ``run_timeout_sec``, and flags a
    probe that consumed more than half of it -- the case that matters is the one
    where the probe SUCCEEDS, because the first design corner is not the design's
    slowest, so a corner finishing just inside the ceiling clears smoke and still
    kills row *k* of the epoch. Also checked, for free (no subprocess): a
    declared ``build_checks.mechanism_paths`` entry that resolves to nothing
    under the target, which silently narrows the drift oracle instead of
    failing.

    Returns a list of problems; empty means the contract holds at the first
    design corner.
    """
    import shutil
    import tempfile

    from orchestrator.optimize import runner
    from orchestrator.optimize.factors import parse_factors

    problems: list[str] = []
    opt = campaign.get("optimization") or {}
    repo = (campaign.get("target_system") or {}).get("repo_path")
    if not repo or not Path(repo).is_dir():
        return [f"target_system.repo_path is not a directory: {repo!r}"]

    factors = parse_factors(opt["factors"])

    # 0. Declared mechanism_paths: does each entry resolve to something real?
    # Placed first because it costs no subprocess, and ahead of the early return
    # for a campaign with no `run_command` so it is reported either way.
    # A typo'd entry is not a loud failure: it contributes nothing to the drift
    # allowlist, so the oracle watches less than the campaign says it does, and
    # if every entry is wrong the mechanism text filters down to nothing and no
    # edit ever reads as drift. Skipped when `build` is declared -- that stage
    # AUTHORS the mechanism, so its files legitimately do not exist yet.
    stage_names = [
        str(getattr(s, "value", s)) for s in (opt.get("stages") or [])
    ]
    mech_paths = (opt.get("build_checks") or {}).get("mechanism_paths") or []
    if mech_paths and "build" not in stage_names:
        missing = [
            str(p) for p in mech_paths
            if not (Path(repo) / str(p).strip().strip("/")).exists()
        ]
        print(f"  smoke: {len(mech_paths) - len(missing)}/{len(mech_paths)} "
              f"mechanism_paths entr(ies) resolve under the target")
        if missing:
            problems.append(
                f"{len(missing)} build_checks.mechanism_paths entr(ies) do not "
                f"exist under {repo}: {', '.join(missing[:4])}"
                + ("" if len(missing) <= 4 else f" (+{len(missing)-4} more)")
                + ". Each contributes nothing to the drift allowlist, so the "
                "oracle silently watches less than declared (and watches "
                "nothing at all if every entry is wrong). Entries are literal "
                "repo-relative paths -- 'src/' for a directory, 'src/mech.py' "
                "for a file -- not globs."
            )

    # 1. Test command: do the declared identifiers actually resolve?
    if opt.get("test_command"):
        raw = runner.run_test_command(opt["test_command"], cwd=Path(repo))
        matched = runner.match_declared_tests(factors, raw)
        declared = {
            r.get("native_test")
            for f in factors for r in (getattr(f, "relations", ()) or [])
            if isinstance(r, dict) and r.get("native_test")
        }
        missing = sorted(str(x) for x in (declared - set(matched)) if x)
        print(f"  smoke: test command reported {len(raw)} test(s); "
              f"{len(matched)}/{len(declared)} declared identifier(s) matched")
        if missing:
            problems.append(
                f"{len(missing)} declared native_test(s) did not appear in the "
                f"test command's output, so they would fail closed at verify: "
                f"{', '.join(str(m) for m in missing[:4])}"
                + ("" if len(missing) <= 4 else f" (+{len(missing)-4} more)")
                + ". Check the identifier spelling, that the command selects "
                "them, and that it prints per-test results (-v / --json-report)."
            )
        failed = sorted(k for k, v in matched.items() if not v)
        if failed:
            problems.append(
                f"{len(failed)} declared native_test(s) ran and FAILED: "
                f"{', '.join(failed[:4])}",
            )

    # 2. One configuration at every factor's first level.
    if not opt.get("run_command"):
        return problems
    probe_dir = tempfile.mkdtemp(prefix="nous-smoke-")
    try:
        problems.extend(_smoke_probe_one_config(
            opt, factors, repo=Path(repo), probe_dir=Path(probe_dir),
        ))
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)
    return problems


def _smoke_probe_one_config(
    opt: dict, factors, *, repo: Path, probe_dir: Path,
) -> list[str]:
    """Run ONE configuration and check everything that run makes answerable.

    Split out of ``_smoke_check_optimization`` so ``probe_dir`` — where any
    ``config_patch`` copy materialized for the probe lands, and which check 2b
    reads back — has exactly one lifetime with exactly one cleanup, rather than
    a removal duplicated across this function's several early returns.
    """
    import time

    from orchestrator.optimize import predicates, runner
    from orchestrator.optimize.matrix import render_apply
    from orchestrator.optimize.stage_runner import resolve_run_timeout

    problems: list[str] = []
    levels = {f.id: f.levels[0] for f in factors if getattr(f, "levels", None)}
    # A log dir is supplied so that any config_patch copies materialized for the
    # probe SURVIVE the run: check 2b below reads them back to confirm the patch
    # landed, and without a log dir the runner cleans its scratch copies up (as
    # it should — under a real campaign the surviving copies live next to the
    # iteration's artifacts as evidence).
    # The SAME ceiling the epoch will run under, resolved through the same
    # function -- not a probe-specific one. `--smoke` exists to catch mismatches
    # between what the campaign declares and what the target does; a probe that
    # quietly ran at 600 while the epoch runs at 5400 (or the reverse) would turn
    # the one check that catches those into a source of them.
    timeout = resolve_run_timeout(opt)
    cfg_runner = runner.make_config_runner(
        opt["run_command"], cwd=repo,
        metric_path=((opt.get("response") or {}).get("primary") or {}).get(
            "metric", "",
        ),
        timeout=timeout,
        log_dir=probe_dir / "failed_runs",
    )

    class _Row:
        row_index = 0
        replicate = 0
        role = "smoke"
        levels: dict = {}
        apply: dict = {}

    row = _Row()
    row.levels = dict(levels)
    row.apply = render_apply(factors, levels)
    started = time.monotonic()
    try:
        obs = cfg_runner(row)
    except Exception as exc:  # noqa: BLE001 — any failure is a finding
        problems.append(
            f"run_command failed at the first design corner {levels} under a "
            f"{timeout}s run_timeout_sec ceiling: {exc}",
        )
        return problems
    elapsed = time.monotonic() - started

    # The ceiling AND the duration, together. Either alone is uninformative: the
    # ceiling is the number the author typed and can already read, and a bare
    # duration says nothing about the headroom. The pair is what answers the
    # question a 90-row screen would otherwise answer on row 1 -- and it answers
    # it for the SUCCEEDING probe too, which is the case the timeout error can
    # never cover: a corner that finishes at 570s under a 600s ceiling has
    # already passed smoke and will still kill the epoch on the first slower row.
    print(f"  smoke: ran one configuration {levels} in {elapsed:.1f}s "
          f"(run_timeout_sec ceiling: {timeout}s) — "
          f"{len(obs)} observable(s) returned")
    if elapsed > 0.5 * timeout:
        problems.append(
            f"the probe configuration took {elapsed:.1f}s against a "
            f"run_timeout_sec ceiling of {timeout}s, leaving under 2x headroom. "
            f"This corner is the design's FIRST one, not its slowest, and a "
            f"campaign's rows vary by more than 2x routinely -- so the epoch is "
            f"likely to lose rows to the ceiling rather than to the target. "
            f"Raise optimization.run_timeout_sec above the slowest corner's "
            f"expected duration.",
        )

    # 2b. Did every config_patch actually land in the file the target read?
    #
    # This is the check that was missing when `config_patch` was rendered onto
    # every row and consumed by nothing: a broken config-patch campaign ran
    # CLEANLY under --smoke, because the probe run exits 0 and emits parseable
    # JSON whether or not the patch took effect. The run succeeded; it just
    # measured the baseline. So "the run worked" is not the question. Two
    # separate claims have to hold, and confusing them IS the defect:
    #
    #   (i) the patched document holds the requested value, at the requested
    #       pointer, with the requested TYPE -- checked by materializing into
    #       the probe's own directory and reading it back through `read_pointer`;
    #  (ii) that document is the one the command was pointed at -- checked
    #       against `delivered_command`, the argv the runner actually executed.
    #
    # (i) without (ii) is exactly the state the original defect was in.
    realized = (getattr(row, "apply", None) or {}).get("applied_patches") or {}
    if realized:
        from orchestrator.optimize import config_patch as _cp

        print(f"  smoke: verifying {len(realized)} config_patch(es) reached the "
              f"target's config file")
    for fid, entry in sorted(realized.items()):
        where = f"{entry.get('path')}{entry.get('pointer')}"
        want = entry.get("value")
        delivered = entry.get("delivered_command") or []
        materialized = str(entry.get("materialized_path") or "")
        if not any(materialized and materialized in str(tok) for tok in delivered):
            problems.append(
                f"factor {fid}: config_patch {where} was written to "
                f"{materialized} but that path does not appear in the command the "
                f"run actually executed ({' '.join(str(t) for t in delivered)}). "
                f"The run therefore read the target's UNPATCHED configuration: "
                f"it exits 0, emits parseable JSON, and reports a number for the "
                f"baseline while the design matrix records the requested level.",
            )
            continue
        # Re-materialized rather than read from `materialized_path`, because the
        # runner keeps a copy only for a FAILED row (a 90-run screen would
        # otherwise leave ~90 unattributed copies in the iteration dir). The
        # rendering is pure and deterministic, so a fresh materialization of the
        # same patch is the same document the run read.
        try:
            fresh = _cp.materialize_patches(
                [{"path": entry["path"], "pointer": entry["pointer"],
                  "value": want}],
                cwd=repo, temp_dir=probe_dir / "verify",
            )
            got = _cp.read_pointer(
                _cp.load_config(Path(fresh[0]["materialized_path"])),
                entry["pointer"],
            )
        except Exception as exc:  # noqa: BLE001 — any failure is a finding
            problems.append(
                f"factor {fid}: config_patch {where} could not be read back "
                f"after patching: {exc}",
            )
            continue
        if got != want or type(got) is not type(want):
            problems.append(
                f"factor {fid}: config_patch {where} did not land as declared: "
                f"requested {want!r} ({type(want).__name__}), the patched file "
                f"holds {got!r} ({type(got).__name__}). A level that arrives as "
                f"the wrong TYPE is the same silent-wrong-config failure as one "
                f"that never arrived -- the target parses it, rejects or coerces "
                f"it, and reports a number for a configuration the design matrix "
                f"never described.",
            )

    # 3. Is the objective metric present?
    metric = ((opt.get("response") or {}).get("primary") or {}).get("metric")
    if metric and metric not in obs:
        problems.append(
            f"response.primary.metric {metric!r} is absent from the run's "
            f"output, so every configuration would score NaN. Emitted keys: "
            f"{', '.join(sorted(str(k) for k in obs)[:8])}",
        )

    # 4. Do the manipulation predicates hold at this corner?
    # Build the scope the way run_stage does: the target's OWN echo of its
    # configuration wins over the requested levels. Using the requested levels
    # for `applied` would make `applied.X == "{level}"` trivially true and hide
    # exactly the type mismatch this check exists to find -- a target echoing a
    # bool where the level is the string "0" can never compare equal, and that
    # failed 67 of 67 runs on a real campaign.
    #
    # The BASE is `runner._applied_namespace(row)` rather than a hand-built
    # `{"applied": levels}`, so every namespace the schema tells authors to use
    # is present here exactly as it is at run time. Built by hand, smoke supplied
    # only `applied` -- so a predicate against `applied_env.X` or
    # `applied_patches.<FACTOR_ID>.value`, both of which the schema explicitly
    # recommends, reported a spurious smoke failure and then passed in
    # production. A pre-flight check that disagrees with the run is worse than
    # no pre-flight check: it trains the author to ignore it.
    scope = dict(runner._applied_namespace(row))
    scope["applied"] = dict(levels)
    scope.update({k: v for k, v in obs.items()})
    if isinstance(obs.get("applied"), dict):
        merged = dict(levels)
        merged.update(obs["applied"])
        scope["applied"] = merged
    for f in factors:
        man = getattr(f, "manipulation", None)
        if not man:
            continue
        try:
            v = predicates.evaluate(man, scope, level=levels.get(f.id))
            ok, detail = v.ok, v.detail
        except Exception as exc:  # noqa: BLE001
            problems.append(f"factor {f.id}: manipulation check raised: {exc}")
            continue
        if not ok:
            problems.append(
                f"factor {f.id}: manipulation predicate fails at its first "
                f"level ({detail}). Every run would be rejected. Check the "
                f"observable's TYPE -- a level is a string, and a target that "
                f"emits a bool or int for it can never compare equal.",
            )
    return problems


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


def build_parser():
    """Build the ``nous`` argparse parser.

    Factored out of ``main()`` so tests can exercise real flag wiring
    (e.g. ``--auto-approve`` / ``--interactive`` resolution, #task-11a)
    via ``build_parser().parse_args([...])`` instead of hand-rolling
    ``argparse.Namespace`` objects that could silently drift from the
    actual CLI surface.
    """
    parser = argparse.ArgumentParser(
        prog="nous",
        description=(
            "Nous — hypothesis-driven experimentation framework for "
            "software systems. Author a campaign.yaml describing your "
            "target system, then run iterative DESIGN → EXECUTE_ANALYZE "
            "→ REPORT cycles with a Claude Agent SDK-driven inner loop. "
            "Use `nous schema` to discover the campaign.yaml shape and "
            "`nous create-campaign --to ./campaign.yaml` to scaffold one."
        ),
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable DEBUG-level logging.",
    )
    subparsers = parser.add_subparsers(dest="command")

    p_run = subparsers.add_parser(
        "run",
        help=(
            "Run a Nous campaign end-to-end. Default `--agent sdk` uses "
            "the Claude Agent SDK; pass `--bundle` to skip DESIGN."
        ),
    )
    p_run.add_argument(
        "campaign",
        help="Path to a campaign.yaml. See `nous schema` for the shape.",
    )
    p_run.add_argument(
        "--max-iterations", type=int,
        help="Total iteration cap. Overrides campaign.max_iterations. "
             "Default: campaign value, or 10.",
    )
    p_run.add_argument(
        "--model",
        help="Fallback model for any phase whose model is not pinned in "
             "the campaign or defaults.yaml.",
    )
    p_run.add_argument(
        "--run-id",
        help="Working directory name under <repo>/.nous/. Defaults to "
             "campaign.run_id or a value derived from the file path.",
    )
    p_run.add_argument(
        "--auto-approve", dest="auto_approve",
        action="store_const", const=True, default=None,
        help="Auto-approve all human gates — required for unattended "
             "runs (CI, agent-driven invocation). See README "
             "'--auto-approve safety preconditions' (#255 / F10) "
             "for when this is safe — at minimum, declare "
             "campaign.locked_parameters (#246 / F1) for every "
             "campaign-spec-critical knob. Default depends on "
             "campaign kind: 'optimization' campaigns auto-approve "
             "by default (no per-stage human decision changes the "
             "pure-Python stage rule); 'reflective' campaigns (or no "
             "kind) still default to prompting. Omitting this flag "
             "lets the kind default apply; pass it explicitly to "
             "force auto-approve for either kind. See --interactive "
             "to force prompting instead.",
    )
    p_run.add_argument(
        "--interactive", action="store_true",
        help="Force human-gate prompting regardless of campaign kind "
             "or --auto-approve. Wins over everything else in gate-"
             "mode resolution.",
    )
    p_run.add_argument(
        "--timeout", type=int, default=1800,
        help="Per-phase wall-clock timeout in seconds (default 1800 = "
             "30 minutes).",
    )
    p_run.add_argument(
        "--max-cli-retries", type=int, default=10,
        help="Max retries per phase on transient SDK failures. -1 means "
             "unbounded (default: 10).",
    )
    p_run.add_argument(
        "--agent", choices=["inline", "sdk"], default="sdk",
        help="Dispatch backend. 'sdk' (default) uses the Claude Agent "
             "SDK for code phases; 'inline' emits prompts to stdout for "
             "an enclosing agent framework. The legacy 'api' backend "
             "was removed in #183.",
    )
    p_run.add_argument(
        "--sandbox", choices=["bypass", "default"], default=None,
        help="SDK filesystem sandbox mode (#193). Default 'bypass' (set "
             "via campaign.sandbox). Pass 'default' to use the SDK's "
             "default permission gating — only sensible when the "
             "campaign's writes all land under the launched cwd.",
    )
    p_run.add_argument(
        "--bundle", type=Path, default=None,
        help="Path to a pre-authored bundle.yaml. Skips DESIGN's agent "
             "turn entirely and uses the supplied bundle as iter-1's "
             "design output (#188). The bundle is schema-validated, "
             "hashed, and recorded in iter-1/bundle_manifest.json for "
             "reviewer-defensible provenance.",
    )
    p_run.add_argument(
        "--problem-md", type=Path, default=None,
        help="Optional path to a pre-authored problem.md. Used with "
             "--bundle. When omitted, a stub is generated from the "
             "campaign's research_question (#188).",
    )
    p_run.add_argument(
        "--handoff-md", type=Path, default=None,
        help="Optional path to a pre-authored handoff_snapshot.md. Used "
             "with --bundle. When omitted, a stub is generated from "
             "the bundle's metadata block (#188).",
    )
    p_run.set_defaults(func=_cmd_run)

    p_resume = subparsers.add_parser("resume")
    p_resume.add_argument("target")
    p_resume.add_argument("--max-iterations", type=int)
    p_resume.add_argument("--model")
    p_resume.add_argument(
        "--auto-approve", dest="auto_approve",
        action="store_const", const=True, default=None,
    )
    p_resume.add_argument("--interactive", action="store_true")
    p_resume.add_argument("--timeout", type=int, default=1800)
    p_resume.add_argument("--max-cli-retries", type=int, default=10)
    p_resume.add_argument("--agent", choices=["inline", "sdk"], default="sdk")
    p_resume.set_defaults(func=_cmd_resume)

    p_schema = subparsers.add_parser(
        "schema",
        help="Print a friendly reference for a Nous artifact schema "
             "(campaign / bundle / findings). The schema YAML is the "
             "single source of truth — this is just a renderer.",
    )
    p_schema.add_argument(
        "artifact",
        choices=["campaign", "bundle", "findings"],
        nargs="?",
        default="campaign",
        help="Which schema to print. Defaults to 'campaign'.",
    )
    p_schema.add_argument(
        "--format", choices=["md", "json", "yaml"], default="md",
        help="Output format. 'md' (default) is human-readable. "
             "'json' and 'yaml' print the raw schema for tooling.",
    )
    p_schema.set_defaults(func=_cmd_schema)

    p_validate = subparsers.add_parser(
        "validate",
        help="Validate a campaign.yaml before running it (`campaign FILE`), "
             "or an iteration's on-disk artifacts (`design|execution --dir`).",
    )
    p_validate.add_argument("phase", choices=["campaign", "design", "execution"])
    p_validate.add_argument(
        "file", nargs="?", type=Path,
        help="campaign.yaml to check (phase=campaign only).",
    )
    p_validate.add_argument(
        "--dir", type=Path,
        help="Iteration directory (phase=design|execution only).",
    )
    p_validate.add_argument(
        "--smoke", action="store_true",
        help="For `validate campaign` on a kind: optimization campaign, also "
             "EXECUTE the test command and one configuration against the "
             "target. Catches the failures static checks cannot see: an "
             "unmatched native_test, a manipulation predicate whose type never "
             "matches, an objective metric the target does not emit, and a "
             "run_command that cannot exec.",
    )
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
    p_report.add_argument("--agent", choices=["inline", "sdk"], default="sdk")
    p_report.set_defaults(func=_cmd_report)

    p_replay = subparsers.add_parser("replay")
    p_replay.add_argument("target")
    p_replay.add_argument("--iter", required=True, type=int)
    p_replay.set_defaults(func=_cmd_replay)

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
    p_reports.set_defaults(func=_cmd_reports)

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
    p_create.set_defaults(func=_cmd_create_campaign)

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
    p_lineage.set_defaults(func=_cmd_lineage)

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
    p_clean.set_defaults(func=_cmd_clean)

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
    p_package.set_defaults(func=_cmd_package)

    return parser


def main():
    parser = build_parser()
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
