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
            # Launched with `NOUS_CAMPAIGN_PARENT=... nous run FILE` from another
            # shell: the variable is gone here, but the work_dir was recorded.
            from orchestrator.work_dir_resolver import recorded_work_dir

            work_dir = recorded_work_dir(run_id, repo_path)
        if work_dir is None:
            print(
                f"Work directory not found for run_id={run_id!r} "
                f"(checked {ENV_VAR} location, "
                f"{repo_path!s}/.nous/{run_id}/ if applicable, and the work_dirs "
                f"Nous has recorded). If the campaign was launched with "
                f"{ENV_VAR}=... set inline, pass the same value here, or pass "
                f"the work_dir itself.",
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
    if work_dir is None:
        from orchestrator.work_dir_resolver import recorded_work_dir

        work_dir = recorded_work_dir(run_id)
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

    # A `nous create-campaign --kind optimization` scaffold is schema-valid by
    # design; its TODO- placeholders are what stop it from launching unedited.
    from orchestrator.validate import campaign_kind as _campaign_kind
    if _campaign_kind(campaign) == "optimization":
        from orchestrator.create_campaign import find_placeholders

        _holes = find_placeholders(campaign)
        if _holes:
            print(f"Refusing to run: {campaign_path} still has "
                  f"{len(_holes)} scaffold placeholder(s):", file=sys.stderr)
            for where, value in _holes:
                print(f"  x {where}: {value!r}", file=sys.stderr)
            print(f"next: fill them, then `nous validate campaign "
                  f"{campaign_path} --liveness`", file=sys.stderr)
            sys.exit(1)

    run_id = args.run_id or campaign.get("run_id") or (campaign_path.parent.name + "-run")
    repo_path = campaign["target_system"].get("repo_path")

    # A build campaign's preconditions, checked BEFORE plan/build spends a
    # token (round 3, D3): a committed git repo and a work_dir outside it.
    if _campaign_kind(campaign) == "optimization":
        from orchestrator.optimize.clean_tree import build_preconditions

        _pre = build_preconditions(campaign, run_id)
        if _pre:
            print(f"Refusing to run {campaign_path}: its build stage cannot start.",
                  file=sys.stderr)
            for p_ in _pre:
                print(f"  x {p_}", file=sys.stderr)
            sys.exit(1)

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


#: `nous docs <topic>` -> the packaged copy under orchestrator/docs/. The repo's
#: docs/ files are canonical; tests/test_docs_command.py fails if a packaged copy
#: drifts from its source, so the two can never disagree.
DOC_TOPICS = {
    "quickstart": ("quickstart.md", "docs/optimization-authoring-quickstart.md"),
    "guide": ("guide.md", "docs/optimization-campaign-guide.md"),
    "targets": ("targets.md", "docs/targets.md"),
    "invariants": ("invariants.md", "docs/optimization-invariants.md"),
}


def _cmd_docs(args):
    from importlib.resources import files

    res = files("orchestrator") / "docs" / DOC_TOPICS[args.topic][0]
    if args.path:
        print(res)
    else:
        sys.stdout.write(res.read_text(encoding="utf-8"))
    return 0


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
        _validate_campaign_file(
            args.file,
            # --liveness runs inside the smoke pass; asking for it implies it.
            smoke=getattr(args, 'smoke', False) or getattr(args, 'liveness', False),
            liveness=getattr(args, 'liveness', False),
            liveness_repeats=getattr(args, 'liveness_repeats', 3),
        )
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


def _validate_campaign_file(
    path: Path, smoke: bool = False, *, liveness: bool = False,
    liveness_repeats: int = 3,
) -> None:
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

    # Placeholders left by `nous create-campaign --kind optimization`. Checked
    # regardless of schema validity, so the author gets the whole fill-in list
    # in one pass.
    if kind == "optimization":
        from orchestrator.create_campaign import find_placeholders

        for where, value in find_placeholders(campaign):
            errors.append(f"[placeholder] {where} = {value!r} — fill in")

    warnings: list[str] = []
    # Cross-field rules run on EVERY pass, so one run reports every static
    # problem. On a schema-invalid file they may report consequences of the
    # schema errors (hence the label), and a crash on a malformed shape is
    # reported rather than hiding the schema errors above it.
    rule_tag = "[rules]" if not schema_errors else "[rules, provisional]"
    try:
        rule_items = validate_optimization_campaign(campaign)
    except Exception as exc:  # noqa: BLE001 -- a malformed shape
        rule_items = []
        errors.append(
            f"{rule_tag} cross-field rules could not run on this shape "
            f"({type(exc).__name__}: {exc}); fix the schema errors and re-run",
        )
    for item in rule_items:
        if item.startswith("WARN:"):
            warnings.append(item[len("WARN:"):].strip())
        else:
            errors.append(f"{rule_tag} {item}")
    if kind == "optimization":
        from orchestrator.optimize.clean_tree import build_preconditions

        try:
            for item in build_preconditions(campaign):
                errors.append(f"[build] {item}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"[build] preconditions could not be checked ({exc})")

    if warnings:
        print(f"\n{len(warnings)} warning(s) — not fatal, but worth reading:")
        for w in warnings:
            print(f"  ! {w}")

    if errors:
        print(f"\n{len(errors)} error(s):", file=sys.stderr)
        for e in errors:
            print(f"  x {e}", file=sys.stderr)
        if kind == "optimization":
            from orchestrator.create_campaign import QUICKSTART_DOC

            print(
                f"\nSee {QUICKSTART_DOC} (the authoring loop and the traps "
                f"checklist), then `nous docs guide` for the "
                f"field-by-field walkthrough.", file=sys.stderr,
            )
        else:
            print("\nSee docs/campaign-authoring-guide.md for the field-by-field "
                  "walkthrough.", file=sys.stderr)
        print(f"\nnext: fix the {len(errors)} error(s) above, then re-run "
              f"`nous validate campaign {target}`", file=sys.stderr)
        sys.exit(1)

    print(f"\nOK — no errors. {len(warnings)} warning(s).")
    if kind != "optimization":
        print(f"\nnext: {_run_hint(target)}")
        return
    opt = campaign.get("optimization") or {}
    n_factors = len(opt.get("factors") or [])
    tests = [
        r.get("native_test")
        for f in (opt.get("factors") or [])
        for r in (f.get("relations") or [])
        if r.get("native_test")
    ]
    print(f"  {n_factors} factor(s), {len(tests)} declared native test(s).")
    if not smoke:
        print(
            "  Static checks only. --smoke executes the test command and ONE "
            "configuration: the only way to catch a manipulation predicate "
            "whose type never matches, an unmatched native_test, or a "
            "run_command that cannot exec. --liveness (implies --smoke) also "
            "runs EVERY declared level once, measures the noise floor, and "
            "prints a design preview (run counts, wall clock, screen MDE)."
        )
        print(f"\nnext: `nous validate campaign {target} --smoke`")
        return
    print("\n  --smoke: executing the contract against the target...")
    issues = _smoke_check_optimization(
        campaign, liveness=liveness, liveness_repeats=liveness_repeats,
    )
    if issues:
        print(f"\n{len(issues)} smoke failure(s):", file=sys.stderr)
        for i in issues:
            print(f"  x {i}", file=sys.stderr)
        print(
            "\nThese would each have cost a full campaign to discover. "
            "Fix them before launching.", file=sys.stderr,
        )
        flag = "--liveness" if liveness else "--smoke"
        print(f"\nnext: fix the {len(issues)} failure(s) above, then re-run "
              f"`nous validate campaign {target} {flag}`", file=sys.stderr)
        sys.exit(1)
    print("  smoke: OK — the campaign/target contract holds.")
    if not liveness:
        print(f"\nnext: `nous validate campaign {target} --liveness`")
    else:
        print(f"\nnext: {_run_hint(target)}")


def _run_hint(target: Path) -> str:
    """The launch command, with artifacts kept OUT of the target (#239).

    When this campaign already has a work_dir (the registry knows its run_id
    and repo), the next step is `nous resume`, which recompiles a revised
    campaign into a new epoch over the SAME work_dir. Suggesting `nous run`
    with a fresh parent there would start the campaign over somewhere else
    (found revising a real campaign for its second epoch).
    """
    import os

    try:
        import yaml

        from orchestrator.work_dir_resolver import recorded_work_dir

        doc = yaml.safe_load(Path(target).read_text()) or {}
        existing = recorded_work_dir(
            str(doc.get("run_id") or ""),
            (doc.get("target_system") or {}).get("repo_path"),
        ) if doc.get("run_id") else None
    except (OSError, ValueError, yaml.YAMLError, AttributeError):
        existing = None
    if existing is not None:
        return (f"`nous resume {target} --auto-approve` -- this campaign already "
                f"has a work_dir at {existing}; resume continues it (a revised "
                f"campaign recompiles into a new epoch there)")
    parent = os.environ.get("NOUS_CAMPAIGN_PARENT") or "~/nous-campaigns"
    return f"`NOUS_CAMPAIGN_PARENT={parent} nous run {target}`"


def _smoke_check_optimization(
    campaign: dict, *, liveness: bool = False, liveness_repeats: int = 3,
) -> list[str]:
    """Execute the test command and ONE configuration; report what breaks.

    ``liveness`` opts into the per-level sweep (``_smoke_liveness_sweep``):
    every declared level run once at the baseline, which both catches a level
    that ABORTS the target and measures each factor's effect against the
    workload's own noise floor. Off by default because it is the only part of
    ``--smoke`` whose cost scales with the design (``sum(len(levels)) +
    liveness_repeats`` runs rather than one); without it, the count of levels
    that went unexercised is printed instead so the gap stays visible.

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

    # 0b. With `build` declared, some declared tests do not exist YET: build
    # authors them. Partition with rule 12's locator logic (one source of
    # truth), so smoke neither fails on them nor pushes the author to delete
    # them from test_command -- which would make verify fail closed after build.
    declared_all = sorted({
        str(r.get("native_test"))
        for f in factors for r in (getattr(f, "relations", ()) or [])
        if isinstance(r, dict) and r.get("native_test")
    })
    to_author: set[str] = set()
    if "build" in stage_names and declared_all:
        from orchestrator.validate import locate_native_tests

        _present, not_yet, _unk, _cmd = locate_native_tests(Path(repo), declared_all)
        to_author = set(not_yet)
        if to_author:
            print(f"  smoke: {len(to_author)} declared test(s) are expected to "
                  f"be authored by build: {', '.join(sorted(to_author))}; "
                  f"verify will require them")
    # Tests build must make true: not written yet, or written and failing
    # pre-build (filled in by the test run below). A factor relating to any of
    # them has no mechanism yet, so its liveness is not measurable pre-build.
    prebuild_failing: set[str] = set()

    # 1. Test command: do the declared identifiers actually resolve?
    test_command = opt.get("test_command")
    skip_tests = False
    if test_command and to_author:
        test_command, dropped, skip_tests = _drop_unbuilt_test_paths(
            test_command, Path(repo), to_author,
        )
        if dropped:
            print(f"  smoke: pre-build, dropped {len(dropped)} test path "
                  f"argument(s) build will author ({', '.join(dropped)}) from "
                  f"THIS smoke run only; verify runs test_command unchanged")
        if skip_tests:
            print("  smoke: every test path in test_command is to be authored "
                  "by build, so the test command is not run pre-build")
    if test_command and not skip_tests:
        from orchestrator.optimize.stage_runner import resolve_test_timeout

        # The SAME ceiling the verify gate will use: a smoke that ran the suite
        # under a different one could pass a suite the campaign then kills.
        # Saved, because both failure messages below point at the output: a
        # killed run's partial output names the test that was running, and a
        # crashed one's stderr names why. Outside the target repo, so the probe
        # leaves nothing behind for the mechanism-drift hash to see.
        test_log = Path(tempfile.mkdtemp(prefix="nous-smoke-tests-")) / "test_output.log"
        problems_before = len(problems)
        raw = runner.run_test_command(
            test_command, cwd=Path(repo),
            timeout=resolve_test_timeout(opt), log_path=test_log,
        )
        matched = runner.match_declared_tests(factors, raw)
        # Tests build will author are not expected pre-build (reported above).
        matched = {k: v for k, v in matched.items() if k not in to_author}
        declared = {
            r.get("native_test")
            for f in factors for r in (getattr(f, "relations", ()) or [])
            if isinstance(r, dict) and r.get("native_test")
        } - to_author
        missing = sorted(str(x) for x in (declared - set(matched)) if x)
        if raw.timed_out:
            # Said FIRST and instead of the identifier advice. A killed suite
            # reports "0 test(s); 0/N matched" exactly like a misspelled one,
            # and the old message only described the latter -- one real author
            # chased spelling, selection and output format, a gate cycle each,
            # before finding a hard-coded ceiling in the source.
            print(f"  smoke: test command KILLED at the {raw.timeout_sec}s "
                  f"timeout after reporting {len(raw.partial)} test(s)")
            problems.append(runner.explain_killed(raw, factors))
        else:
            print(f"  smoke: test command reported {len(raw)} test(s); "
                  f"{len(matched)}/{len(declared)} declared identifier(s) "
                  f"matched")
        if missing and not raw.timed_out:
            problems.append(
                f"{len(missing)} declared native_test(s) did not appear in the "
                f"test command's output, so they would fail closed at verify. "
                + runner.explain_unmatched(
                    missing, sorted(raw),
                    returncode=raw.returncode, exec_error=raw.exec_error,
                    log_path=raw.log_path,
                ),
            )
        failed = sorted(k for k, v in matched.items() if not v)
        if failed and "build" in stage_names:
            # Pre-build, a correctness test is SUPPOSED to fail (oracle 2(b)):
            # build exists to make it pass, and verify requires that it does.
            print(f"  smoke: {len(failed)} declared test(s) FAIL pre-build — "
                  f"expected while the mechanism does not exist; verify will "
                  f"require them to pass after build: {', '.join(failed[:4])}"
                  + ("" if len(failed) <= 4 else f" (+{len(failed) - 4} more)"))
            prebuild_failing = set(failed)
            failed = []
        if "build" in stage_names and not (
            (opt.get("build_checks") or {}).get("allow_preexisting_tests")
        ):
            correctness = {
                r.get("native_test")
                for f in factors for r in (getattr(f, "relations", ()) or [])
                if isinstance(r, dict) and r.get("kind") == "correctness"
            }
            # The same factor-scoped rule verify applies: only a BUILT factor's
            # pre-existing passing test is vacuous; an existing knob's is not.
            from orchestrator.optimize.stage_runner import built_factor_ids

            built = built_factor_ids(factors, set(matched) - set(to_author))
            factor_of = {
                r.get("native_test"): f.id
                for f in factors for r in (getattr(f, "relations", ()) or [])
                if isinstance(r, dict)
            }
            already = sorted(
                k for k, v in matched.items()
                if v and k in correctness and (not built or factor_of.get(k) in built)
            )
            if already:
                print(
                    f"  smoke: WARNING — {len(already)} declared correctness "
                    f"test(s) already PASS pre-build: {', '.join(already[:4])}"
                    + ("" if len(already) <= 4 else f" (+{len(already) - 4} more)")
                    + ". verify's oracle 2(b) aborts on a correctness test that "
                    "passed before build ran (it proves nothing about the "
                    "mechanism being built). Strengthen them so they fail "
                    "against the pre-build tree; set "
                    "optimization.build_checks.allow_preexisting_tests: true "
                    "only if one genuinely covers pre-existing behaviour."
                )
        if failed:
            problems.append(
                f"{len(failed)} declared native_test(s) ran and FAILED: "
                f"{', '.join(failed[:4])}",
            )
        # Kept only when a problem above points at it.
        if len(problems) == problems_before:
            shutil.rmtree(test_log.parent, ignore_errors=True)

    build_authored = {
        f.id for f in factors
        if any(isinstance(r, dict)
               and r.get("native_test") in (to_author | prebuild_failing)
               for r in (getattr(f, "relations", ()) or []))
    }

    # 2. One configuration at every factor's first level.
    if not opt.get("run_command"):
        return problems
    probe_dir = tempfile.mkdtemp(prefix="nous-smoke-")
    try:
        problems.extend(_smoke_probe_one_config(
            opt, factors, repo=Path(repo), probe_dir=Path(probe_dir),
            locked=campaign.get("locked_parameters"),
        ))
        # 2b. The GENERATED CENTER POINT, when the design asks for one.
        #
        # Neither of the other probes can reach this configuration. Check 2 runs
        # ONE CORNER (every factor's first level); `--liveness` runs every declared
        # LEVEL. A center point is neither: its numeric coordinates are midpoints
        # that appear in no `levels` list, and its `choice` factors are PINNED to
        # their first level because a choice factor has no midpoint (see
        # `matrix.expand`'s `center_choice_pinned`).
        #
        # That combination is unreachable by declaration and therefore unchecked,
        # and on a CONSTRAINED factor space it can be unrunnable. Observed: a
        # campaign whose numeric factor was only meaningful when a choice factor
        # was ON declared the numeric's OFF sentinel as a level; the generated
        # center paired the numeric's midpoint with the choice's OFF level, the
        # target rejected the combination as nonsense (correctly), and all three
        # center points failed -- taking the design's only replication, hence its
        # pure-error estimate and its lack-of-fit test, with them. Static
        # validation passed, `--smoke` passed, and `--liveness` passed.
        if _screen_center_points(opt) > 0:
            centre = _center_levels(factors)
            if centre:
                problems.extend(_smoke_probe_one_config(
                    opt, factors, repo=Path(repo), probe_dir=Path(probe_dir),
                    levels=centre, label="generated center point",
                    locked=campaign.get("locked_parameters"),
                ))
        # 5. Per-level abort sweep + liveness (opt-in). Gated behind
        # `--liveness` because it costs REAL runs -- one per declared level plus
        # the baseline repeats -- unlike everything above it, which is one run
        # total. Plain `--smoke` reports the size of the gap instead of closing
        # it, so an author can see what was not exercised and decide.
        if liveness:
            measured: dict = {}
            problems.extend(_smoke_liveness_sweep(
                opt, factors, repo=Path(repo), probe_dir=Path(probe_dir),
                repeats=liveness_repeats, build_authored=build_authored,
                measured_out=measured,
            ))
            _print_design_preview(campaign, measured)
        else:
            problems.extend(_report_unexercised_levels(factors))
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)
    return problems


def _drop_unbuilt_test_paths(
    command: str, repo: Path, to_author: set[str],
) -> tuple[str, list[str], bool]:
    """``test_command`` minus path arguments naming files build will author.

    Pre-build, ``pytest a.py b.py`` with ``b.py`` not yet written exits 4 and
    runs NOTHING, so even ``a.py``'s existing relations look unmatched. For the
    smoke run only, drop each argument whose path does not exist and is the
    file of a to-be-authored test. Returns ``(command, dropped, skip)``;
    ``skip`` is True when every path argument was dropped -- running the bare
    runner would execute the whole suite instead, which is not the contract.
    """
    import shlex

    from orchestrator.validate import _TEST_SOURCE_SUFFIXES

    files = {t.split("::", 1)[0].strip() for t in to_author}
    argv = shlex.split(command)
    kept: list[str] = argv[:1]
    dropped: list[str] = []
    path_args = 0
    for tok in argv[1:]:
        head = tok.split("::", 1)[0]
        is_path = not tok.startswith("-") and (
            "/" in head or head.endswith(_TEST_SOURCE_SUFFIXES))
        if is_path:
            path_args += 1
            if head in files and not (repo / head).exists():
                dropped.append(tok)
                continue
        kept.append(tok)
    skip = bool(dropped) and len(dropped) == path_args
    return shlex.join(kept), dropped, skip


def _print_design_preview(campaign: dict, measured: dict) -> None:
    """Print the zero-token DESIGN PREVIEW from what --liveness measured."""
    from orchestrator.optimize.preview import build_preview, format_preview

    if "noise_sd" not in measured:
        return  # the sweep stopped before the noise floor existed
    try:
        pv = build_preview(
            campaign, noise_sd=measured.get("noise_sd"),
            mean=measured.get("mean"), run_secs=measured.get("run_secs"),
            objectives=measured.get("objectives"),
        )
    except Exception as exc:  # noqa: BLE001 -- a preview must never mask results
        print(f"  DESIGN PREVIEW unavailable: {type(exc).__name__}: {exc}")
        return
    for line in format_preview(pv):
        print(line)


def _report_unexercised_levels(factors) -> list[str]:
    """Say how many declared levels plain ``--smoke`` did NOT exercise.

    Never a problem -- always the empty list. The single probe corner covers
    exactly one level per factor, so every other declared level is untested at
    this point, and a level that ABORTS the target (a real one exited 2 on a Go
    panic) is caught only if it happens to sit at the corner. Reporting the
    count is what keeps that gap from being invisible; closing it costs
    ``sum(len(levels))`` runs and is therefore opt-in.
    """
    declared = sum(len(getattr(f, "levels", ()) or ()) for f in factors)
    covered = sum(1 for f in factors if getattr(f, "levels", None))
    unexercised = declared - covered
    if unexercised <= 0:
        return []
    print(
        f"  smoke: {unexercised} of {declared} declared level(s) were NOT "
        f"exercised — the probe ran ONE corner, so a level that aborts the "
        f"target is caught only if it sits at that corner. Re-run with "
        f"--liveness to run every level once ({declared} runs) and to measure "
        f"each factor's effect against the workload's noise floor.",
    )
    return []


def _check_declared_locked(opt: dict, locked: dict | None, obs: dict, *,
                           where: str) -> list[str]:
    """Evaluate the enforceable ``locked_parameters`` against one observation.

    The SAME comparison the epoch makes on every row
    (``optimization.locked.deviations``), so a mismatch -- a target that ignores
    the pinned value -- surfaces before the policy hash is written instead of
    as an abort on the first measured row. A smoke FAILURE, not a warning: the
    epoch would hard-abort on it.
    """
    from orchestrator.optimize import locked as locked_mod

    view = {"locked_parameters": locked or {}, "optimization": opt}
    n = len(locked_mod.enforced(view))
    if not n:
        return []
    bad = locked_mod.deviations(view, obs)
    print(f"  smoke: {n - len(bad)}/{n} locked parameter(s) hold at {where}")
    if not bad:
        return []
    return [
        f"locked_parameters deviate at {where}: " + "; ".join(bad)
        + ". The target ran with a value other than the one this campaign "
        "pinned, so every epoch row would measure an unregistered experiment "
        "and the campaign would abort on its first row. Make the target honour "
        "the locked value, or fix optimization.locked_observables."
    ]


def _check_declared_self_checks(opt: dict, obs: dict, *, where: str) -> list[str]:
    """Evaluate ``response.self_check`` against one observation; problems, if any.

    Shared by the ``--smoke`` probe and every ``--liveness`` run, and it goes
    through the SAME ``adapter_contract.check_self_checks`` the epoch uses -- a
    pre-flight check that disagreed with the run would be worse than none, since
    it trains the author to ignore it (the reason ``_smoke_probe_one_config``
    builds its manipulation scope from ``runner._applied_namespace``).

    A self-check violation here is a SMOKE FAILURE, not a warning, because the
    consequence of ignoring it is the whole epoch: the objective the campaign is
    about to pre-register a design over does not satisfy the predicate that
    defines it, so every row that follows measures something other than the
    declared response.
    """
    from orchestrator.optimize import adapter_contract as ac

    self_check = ((opt.get("response") or {}).get("self_check")) or []
    if not self_check:
        return []
    try:
        verdicts = ac.check_self_checks(self_check, obs)
    except Exception as exc:  # noqa: BLE001 — a malformed predicate is a finding
        return [f"response.self_check could not be evaluated at {where}: {exc}"]
    bad = [v for v in verdicts if (not v["ok"]) and not v["skipped"]]
    print(f"  smoke: {len(verdicts) - len(bad)}/{len(verdicts)} declared "
          f"response.self_check invariant(s) hold at {where}")
    if not bad:
        return []
    return [
        f"response.self_check violated at {where}: "
        + "; ".join(f"{v['id']!r}: {v['detail']}" for v in bad)
        + ". The run reported an objective value its OWN recorded diagnostic "
        "contradicts, so it is not a measurement of the declared response. "
        "Under an epoch this fails the row and excludes it from the fit; here "
        "it means the objective's definition and the adapter's computation of "
        "it disagree, which no amount of replication repairs. Fix the adapter "
        "(assert the returned extremum against its own acceptance test before "
        "reporting it) or correct the declared invariant.",
    ]


HEADROOM_FACTOR = 2.0
"""How much slack ``run_timeout_sec`` must leave over the slowest OBSERVED run.

Not a new number: it is the factor the probe's existing check already applied
(``elapsed > 0.5 * timeout`` is ``timeout < 2 * elapsed``), lifted to a name so
the probe and the liveness sweep cannot drift apart. Two mechanisms disagreeing
about how much headroom is enough would be worse than one being slightly wrong.

2x rather than 1.1x because the quantity being bounded is not measurement noise
around one configuration — it is the gap between the configuration that was
measured and the SLOWEST CORNER OF THE DESIGN, which no single run visits."""


def _timeout_headroom_problem(
    slowest_sec: float, timeout: int, *, what: str,
    why_a_lower_bound: str = (
        "no single measured configuration is the design's costliest one"
    ),
) -> str | None:
    """The headroom finding for the slowest observed run, or None if it is fine.

    ONE function for both callers (the ``--smoke`` probe's single corner and the
    ``--liveness`` sweep's per-level maximum) because they are asking the same
    question of different evidence, and a second copy of the arithmetic would be
    free to disagree with the first. ``what`` names which evidence, so the
    message says how weak the bound it rests on is.

    WHAT THIS CHECK CANNOT GUARANTEE, stated here because the message below
    promises no more than this:

      * A single run's wall clock is a LOWER BOUND on the slowest corner. The
        liveness sweep varies ONE factor at a time with the others held at
        ``known_valid_baseline``; the design's slowest corner combines several
        factors' costly levels at once, and costs can be superadditive. The real
        defect's slow corner was ``arc + sata_ssd + 40GiB`` — three costly levels
        TOGETHER, a configuration a one-factor-at-a-time sweep never visits. So a
        passing verdict here means "the ceiling clears every corner I actually
        measured by 2x", never "the ceiling clears the design".
      * It cannot see the machine the epoch will run on, contention from
        ``max_parallel``, a cold cache on the first row, or a workload that grows
        with a factor the sweep held fixed.
      * A FAILING verdict, by contrast, is sound in the direction that matters:
        a level already measured within 2x of the ceiling will be joined in the
        design by corners at least that slow, so the finding is real evidence
        rather than a heuristic.

    That asymmetry is why this is worth having at all despite the weak bound:
    the check is conservative exactly where an author gets hurt.
    """
    if slowest_sec <= 0 or timeout <= 0:
        return None
    if slowest_sec * HEADROOM_FACTOR <= timeout:
        return None
    # ``why_a_lower_bound`` differs per caller because the two callers' evidence
    # is weak in DIFFERENT ways, and an inaccurate caveat is worse than none: an
    # author who reads "each run varies one factor" about a probe that ran a full
    # corner learns the wrong thing about what was measured.
    return (
        f"{what} took {slowest_sec:.1f}s against a run_timeout_sec ceiling of "
        f"{timeout}s, leaving under {HEADROOM_FACTOR:g}x headroom. That "
        f"measurement is a LOWER BOUND on the design's slowest corner, not an "
        f"estimate of it: {why_a_lower_bound} and costs across factors can be "
        f"superadditive. Run order is randomized, so the slow corner may run "
        f"FIRST. Raise optimization.run_timeout_sec to at least "
        f"{int(slowest_sec * HEADROOM_FACTOR) + 1}s, or higher if the costly "
        f"levels compound."
    )


def _smoke_liveness_sweep(
    opt: dict, factors, *, repo: Path, probe_dir: Path, repeats: int = 3,
    build_authored: set[str] | frozenset = frozenset(),
    measured_out: dict | None = None,
) -> list[str]:
    """Run every declared level once, then report effect size against noise.

    Two gaps, one set of runs — deliberately shared, because a level that
    aborts the target cannot produce an effect size, so measuring liveness and
    detecting an aborting level are the same sweep read two ways:

      * GAP 3, a HARD failure. Each declared level of each factor is run once
        with every other factor at ``known_valid_baseline``. A non-zero exit, a
        crash signature, or unparseable output is a smoke FAILURE naming the
        factor AND the level. The real defect this closes: a level that exited 2
        on a Go panic was reported by the author's own harness as a clean null
        result identical to baseline, because that harness reused a stale
        metrics file on non-zero exit.
      * GAP 2, REPORTED not refused. The baseline is run ``repeats`` times
        varying only the workload seed, giving the objective's coefficient of
        variation — the noise floor. A factor whose objective RANGE across its
        measured levels is under ``2 x`` that floor is flagged "not
        demonstrably live". A
        genuinely-small-but-real effect is the author's call to keep; what was
        missing was the NUMBER. On a real target 3 of 8 candidate factors were
        dead axes, and a pre-registered policy hash over dead axes is a
        pre-registration of nothing.

    Cost is ``sum(len(levels)) + repeats`` runs — LINEAR in the design, never
    ``prod(len(levels))``. That is what makes it affordable enough to be worth
    offering at all.
    """
    from orchestrator.optimize.stage_runner import resolve_run_timeout

    problems: list[str] = []
    baseline = opt.get("known_valid_baseline")
    if not isinstance(baseline, dict) or not baseline:
        return [
            "--liveness needs optimization.known_valid_baseline: every "
            "per-factor run holds the OTHER factors at the baseline, and every "
            "noise-floor run is the baseline itself. Without it there is no "
            "configuration the campaign promises is runnable to vary from, so "
            "an effect measured against an arbitrary corner would not be "
            "attributable to the factor.",
        ]
    from orchestrator.optimize.objectives import (
        declared_objectives,
        is_multi_objective,
    )

    multi = is_multi_objective(opt)
    objectives = declared_objectives(opt)
    metrics = [o["metric"] for o in objectives]
    direction_of = {o["metric"]: o["direction"] for o in objectives}
    if not metrics:
        return [
            "--liveness needs response.objectives metrics to compare levels on."
            if multi else
            "--liveness needs response.primary.metric to compare levels on.",
        ]
    metric = metrics[0]
    # CONSTRAINT metrics are measured too. A knob can be dead for the
    # objective and still decide FEASIBILITY (a compression level that barely
    # moves throughput but moves the ratio a constraint bounds); calling it
    # droppable from the objective alone is wrong advice. Tracked tolerantly:
    # a constraint metric that is not numeric on some run (a boolean flag, an
    # absent field) is simply not tracked, never a run failure.
    constraint_dir: dict[str, str | None] = {}
    for c in ((opt.get("response") or {}).get("constraints") or []):
        if not isinstance(c, dict):
            continue
        cm = c.get("metric") or c.get("observable")
        if not isinstance(cm, str) or not cm or cm in metrics:
            continue
        # Which way is SAFER: away from the bound. `==`/`!=` have no side.
        side = {">": "maximize", ">=": "maximize",
                "<": "minimize", "<=": "minimize"}.get(c.get("op"))
        if cm in constraint_dir and constraint_dir[cm] != side:
            side = None
        constraint_dir[cm] = side
    cmetrics = list(constraint_dir)
    untracked: set[str] = set()
    seed_env = ((opt.get("workload") or {}).get("seed_env")) or None

    # Every run's wall clock, in the order the sweep made them, keyed by the
    # label already used for error messages. Collected for EVERY run including
    # the failing ones and the noise-floor repeats, because "the ceiling is the
    # binding constraint" is a claim about the whole sweep and a level that died
    # AT the ceiling is its strongest evidence.
    observed_sec: list[tuple[str, float, bool]] = []
    # Every objective value every successful run reported, per metric: the
    # input to the "constant objective" warning (multi-objective only).
    all_values: dict[str, list[float]] = {m: [] for m in metrics}
    cvalues_ok: dict[str, bool] = {m: True for m in cmetrics}

    def _run(levels: dict, *, seed: int | None, label: str):
        """One configuration. Returns ``({metric: objective}, error_text)``.

        Any ``response.self_check`` violation is appended to ``problems``
        directly rather than returned as this run's ``error_text``. The two are
        different findings and must not be conflated: an error means the level
        could not be RUN (a hole in the design matrix), while a self-check
        violation means it ran and reported a self-contradictory number. Folding
        the second into the first would report "level could not be run" about a
        configuration that ran fine, and would also suppress its effect-size
        measurement -- which is still worth having, since a violated invariant on
        a live axis and on a dead one call for different repairs.
        """
        obs, err, elapsed = _liveness_run_one(
            opt, factors, levels, repo=repo, probe_dir=probe_dir,
            seed_env=seed_env, seed=seed, label=label,
        )
        observed_sec.append((label, elapsed, err is None))
        if err is not None:
            return None, err
        problems.extend(_check_declared_self_checks(
            opt, obs, where=f"liveness run {label}",
        ))
        values: dict[str, float] = {}
        for m in metrics:
            value = obs.get(m)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return None, (
                    f"the run emitted no numeric {m!r} (got {value!r}), so no "
                    f"effect size is computable"
                )
            values[m] = float(value)
        for m, v in values.items():
            all_values[m].append(v)
        for m in cmetrics:
            value = obs.get(m)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values[m] = float(value)
            else:
                untracked.add(m)
        return values, None

    # 1. Noise floor: the baseline, `repeats` times, varying ONLY the seed.
    samples: list[dict[str, float]] = []
    for i in range(max(1, int(repeats or 1))):
        # A campaign with no `workload.seed_env` gets seed=None: the repeats
        # still measure whatever run-to-run variation the target has (process
        # startup, timing, an internal clock), which is the floor that matters.
        val, err = _run(dict(baseline), seed=(i + 1) if seed_env else None,
                        label=f"noise floor {i + 1}/{repeats}")
        if err is not None:
            problems.append(
                f"the known_valid_baseline configuration {baseline} failed on "
                f"noise-floor run {i + 1}: {err}. The baseline is the bottom "
                f"rung of report.json's fallback ladder — a campaign whose "
                f"baseline does not run has nothing to fall back to.",
            )
            # Reported even on this early return: a baseline that failed AT the
            # ceiling is itself the finding, and it is the one case where the
            # duration is more informative than the effect sizes the sweep now
            # cannot compute.
            _report_liveness_durations(
                observed_sec, resolve_run_timeout(opt), problems,
            )
            return problems
        samples.append(val)

    # Per objective: (mean, sd, noise_abs, threshold). A single-objective
    # campaign is the K = 1 case and prints exactly what it always printed.
    floor: dict[str, tuple[float, float, float, float]] = {}
    cmetrics = [m for m in cmetrics if m not in untracked]
    for m in metrics + cmetrics:
        xs = [s[m] for s in samples]
        mean = sum(xs) / len(xs)
        if len(xs) > 1:
            var = sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)
            sd = var ** 0.5
        else:
            sd = 0.0
        cv = (sd / abs(mean)) if mean else 0.0
        noise_abs = abs(cv * mean) if mean else sd
        floor[m] = (mean, sd, noise_abs, 2.0 * noise_abs)
        tag = " (constraint metric)" if m in constraint_dir else ""
        print(f"  liveness: noise floor from {len(samples)} baseline run(s): "
              f"mean {m}={mean:.6g}, sd={sd:.6g}, CV={cv * 100:.2f}%{tag}")
    if measured_out is not None:
        # Handed to the DESIGN PREVIEW; nothing here re-measures. The
        # top-level keys are the first objective's (the single-objective
        # contract); `objectives` carries every objective's floor.
        mean0, sd0 = floor[metric][0], floor[metric][1]
        measured_out.update(noise_sd=sd0, mean=mean0, n_samples=len(samples))
        if multi:
            measured_out["objectives"] = {
                m: {"noise_sd": floor[m][1], "mean": floor[m][0]}
                for m in metrics
            }
    if len(samples) < 2:
        print("  liveness: NOTE — one baseline sample cannot estimate a noise "
              "floor; the CV is reported as 0 and every non-zero effect will "
              "clear it. Raise --liveness-repeats to at least 3.")

    # 2. Every declared level once, other factors at baseline.
    #    Both bullets above read this ONE sweep: an aborting level is a hard
    #    failure, and the surviving extremes give the effect size.
    # rows[m]: (factor id, effect, ratio) per objective.
    rows: dict[str, list[tuple[str, float | None, float | None]]] = {
        m: [] for m in metrics + cmetrics}
    live_on_constraint: dict[str, set[str]] = {}
    live_for: dict[str, set[str]] = {}       # factor id -> objectives it moves
    per_factor_levels: dict[str, dict] = {}  # factor id -> {level: values}
    dead: list[str] = []
    for f in factors:
        levels = list(getattr(f, "levels", ()) or ())
        if not levels:
            continue
        measured: dict = {}
        for level in levels:
            cfg = dict(baseline)
            cfg[f.id] = level
            val, err = _run(cfg, seed=1 if seed_env else None,
                            label=f"{f.id}={level!r}")
            if err is not None and f.id in build_authored:
                # Its mechanism does not exist yet; a pre-build failure of
                # this level says nothing about the post-build design.
                print(f"  liveness: {f.id}={level!r} failed pre-build (its "
                      f"mechanism is authored by build): {err}")
                continue
            if err is not None:
                problems.append(
                    f"factor {f.id} level {level!r} could not be run: {err}. "
                    f"A declared level the target cannot execute is not a null "
                    f"result — it is a hole in the design matrix that a fitter "
                    f"will read as a failed row, and (if a harness reuses a "
                    f"stale metrics file on non-zero exit) as a measurement "
                    f"identical to baseline.",
                )
                continue
            measured[level] = val
        if len(measured) < 2:
            for m in metrics + cmetrics:
                rows[m].append((f.id, None, None))
            continue
        per_factor_levels[f.id] = measured
        # The objective's full RANGE across the levels actually measured, not
        # just the difference between the two extreme LEVELS. A strict superset
        # of the latter, and the right criterion: a factor whose endpoints
        # happen to coincide but whose middle level moves the objective IS live,
        # and an endpoints-only comparison would call it dead. For a two-level
        # factor the two definitions coincide.
        live_for[f.id] = set()
        live_on_constraint[f.id] = set()
        for m in metrics + cmetrics:
            _mean, _sd, noise_abs, threshold = floor[m]
            vals = [v[m] for v in measured.values() if m in v]
            if len(vals) < 2:
                rows[m].append((f.id, None, None))
                continue
            effect = max(vals) - min(vals)
            rows[m].append(
                (f.id, effect, (effect / noise_abs) if noise_abs else None))
            if m in constraint_dir:
                # Strictly positive too: a constraint metric that never moved
                # (sd 0, effect 0) is not evidence the knob drives it.
                if effect > 0 and effect >= threshold:
                    live_on_constraint[f.id].add(m)
            elif abs(effect) >= threshold:
                live_for[f.id].add(m)
        # Live for ANY objective OR ANY constraint metric is live: a knob that
        # moves only one side of the trade-off, or only feasibility, is still a
        # knob the answer depends on.
        if (not live_for[f.id] and not live_on_constraint[f.id]
                and f.id not in build_authored):
            dead.append(f.id)

    def _constraint_only(fid: str) -> str:
        names = ", ".join(f"`{c}`" for c in sorted(live_on_constraint.get(fid, ())))
        return (f"  <-- drives constraint {names} only — keep (it decides "
                f"feasibility)")

    for m in metrics + cmetrics:
        noise_abs, threshold = floor[m][2], floor[m][3]
        if m in constraint_dir:
            what = f"constraint metric {m} range"
        elif multi:
            what = f"objective {m} ({direction_of[m]}) range"
        else:
            what = "objective range"
        print(f"  liveness: effect ({what} across measured levels) vs "
              f"noise (threshold: |effect| >= 2 x {noise_abs:.6g} = "
              f"{threshold:.6g})")
        for fid, effect, ratio in rows[m]:
            if fid in build_authored:
                print(f"    {fid:<20} authored by build; liveness not "
                      f"applicable pre-build")
                continue
            if effect is None:
                print(f"    {fid:<20} effect: n/a (fewer than 2 levels measured)")
                continue
            if m in constraint_dir:
                flag = ("" if m in live_on_constraint.get(fid, set())
                        else "  <-- does not move this constraint metric")
            elif fid in dead:
                flag = "  <-- not demonstrably live"
            elif not live_for.get(fid) and live_on_constraint.get(fid):
                flag = _constraint_only(fid)
            elif multi and m not in live_for.get(fid, set()):
                flag = "  <-- not demonstrably live on this objective"
            else:
                flag = ""
            shown = "inf" if ratio is None else f"{ratio:.2f}x"
            if ratio is None and effect == 0 and m in constraint_dir:
                shown = "0.00x"
            print(f"    {fid:<20} effect: {effect:.6g}   ({shown} noise){flag}")
    if dead:
        # REPORTED, never refused: a small-but-real effect is the author's
        # call, and the point of the check is to make that call informed.
        moved = ("across all their measured levels, they moved no objective "
                 "and no constraint metric by more than 2x its own run-to-run "
                 "variation. " if multi or cmetrics else
                 "the objective moved less across all their measured levels "
                 "than 2x the workload's own run-to-run variation. ")
        print(
            f"  liveness: {len(dead)} factor(s) NOT demonstrably live "
            f"({', '.join(dead)}): {moved}"
            f"Such a factor consumes its share of the design, contributes only "
            f"variance to the fit, and makes the policy hash a "
            f"pre-registration of a knob nothing reads. Confirm the knob "
            f"reaches a mechanism (not just a config file), widen its levels, "
            f"or drop it before pre-registering.",
        )
        # Printed once, not per factor: the caveat is about where the probe
        # ran, which is the same corner for every factor (issue #318).
        print(
            "  liveness: a factor flagged here moved the objective by less "
            "than 2x the workload's own variation AT THE BASE CONFIGURATION. "
            "That is where every factor's levels are probed, so a knob whose "
            "effect only appears away from the base corner -- a cap that binds "
            "only above some load, a backend that matters only at a wider "
            "parallelism -- reads as dead here. Before dropping it, check "
            "whether its levels bracket a regime the base corner is not in.",
        )
    keep = [fid for fid in live_on_constraint
            if live_on_constraint[fid] and not live_for.get(fid)
            and fid not in build_authored]
    if keep:
        print(
            f"  liveness: {len(keep)} factor(s) move no objective beyond noise "
            f"but DO move a constraint metric ({', '.join(keep)}): keep them. "
            f"A constraint decides which configurations are admissible, so a "
            f"knob that moves it changes where the feasible optimum is even "
            f"when it cannot move the objective directly.",
        )
    if multi or any(d is not None for d in constraint_dir.values()):
        directional = {**direction_of,
                       **{c: d for c, d in constraint_dir.items()
                          if d is not None and c in cmetrics}}
        _report_tradeoff_candidates(
            per_factor_levels, floor, directional,
            objectives=metrics, build_authored=build_authored,
        )
    if multi:
        _report_constant_objectives(all_values, live_for, metrics)

    # 3. GAP 1: the ceiling, against the per-level wall clock this sweep just
    #    measured and used to throw away.
    #
    #    The sweep already ran every declared level of every factor once. Each of
    #    those runs' durations is the per-level cost data guide §7.1 tells an
    #    author to size `run_timeout_sec` from -- and it was observed by the OS
    #    and discarded, so the advice stayed prose. Prose advice demonstrably does
    #    not hold: the author of §7.1 then sized the ceiling from the CHEAP corner
    #    three campaigns in a row, and run order is randomized, so the slow corner
    #    can be row 1.
    #
    #    FAIL rather than merely flag, and deliberately so, unlike the dead-axis
    #    check right above. The two findings differ in who can adjudicate them. A
    #    small-but-real effect is a judgement call only the author can make, so
    #    that check reports a number. Insufficient timeout headroom is not a
    #    judgement call: rows WILL die at the ceiling, and they die after
    #    consuming the full ceiling each, which is how ~14 hours bought nothing.
    #    A `--smoke` failure is also the only actionable moment -- it is
    #    pre-registration, before a policy hash exists, and the repair is one
    #    integer in the campaign file. The probe's existing single-corner check
    #    already fails for exactly this reason; this raises the evidence from one
    #    corner to every declared level rather than changing the verdict's kind.
    _report_liveness_durations(observed_sec, resolve_run_timeout(opt), problems)
    if measured_out is not None:
        measured_out["run_secs"] = [secs for _lbl, secs, ok in observed_sec if ok]
    return problems


def _report_tradeoff_candidates(
    per_factor_levels: dict, floor: dict, directional: dict, *,
    objectives: list[str], build_authored=frozenset(),
) -> None:
    """Print the factors whose levels TRADE one objective against another.

    A factor is a trade-off candidate when some pair of its measured levels
    ``a -> b`` improves an objective by more than 2x that objective's noise
    floor while WORSENING another objective -- or a directional constraint
    metric (``>=``/``<=`` bound: worse means towards the bound) -- by more than
    2x ITS noise floor. Those are the knobs a Pareto front is made of; a knob
    that improves everything at once only moves the front, it does not shape
    it. Measured one factor at a time around ``known_valid_baseline``, so a
    trade-off that exists only through an interaction is invisible here.
    """
    import math

    from orchestrator.optimize.objectives import improves

    multi = len(objectives) > 1
    found: list[str] = []
    for fid, measured in per_factor_levels.items():
        if fid in build_authored:
            continue
        best = None   # (score, line)
        levels = list(measured)
        for a in levels:
            for b in levels:
                if a == b:
                    continue
                va, vb = measured[a], measured[b]
                for i in objectives:
                    thr_i = floor[i][3]
                    gain = improves(directional[i], vb[i] - va[i])
                    if not (gain > 0 and gain >= thr_i):
                        continue
                    for j, dj in directional.items():
                        if j == i or j not in va or j not in vb:
                            continue
                        thr_j = floor[j][3]
                        loss = -improves(dj, vb[j] - va[j])
                        if not (loss > 0 and loss >= thr_j):
                            continue
                        score = min(gain / thr_i if thr_i else math.inf,
                                    loss / thr_j if thr_j else math.inf)
                        kind = ("objective" if j in objectives
                                else "constraint metric")
                        line = (
                            f"    {fid:<20} {fid}={a!r} -> {fid}={b!r} improves "
                            f"{i} by {abs(vb[i] - va[i]):.6g} ({directional[i]}) "
                            f"but worsens {kind} {j} by "
                            f"{abs(vb[j] - va[j]):.6g} ({dj})"
                        )
                        if best is None or score > best[0]:
                            best = (score, line)
        if best is not None:
            found.append(best[1])
    if found:
        what = ("the factors a trade-off front is made of" if multi else
                "the objective is bought at the cost of feasibility margin")
        print(f"  liveness: {len(found)} trade-off candidate(s) — a level "
              f"change that improves an objective beyond 2x its noise while "
              f"worsening another objective or a constraint metric beyond 2x "
              f"its noise ({what}):")
        for line in found:
            print(line)
    elif multi:
        print("  liveness: no trade-off candidate — no single factor moved two "
              "objectives (or an objective and a constraint metric) in "
              "opposite directions beyond noise at the base configuration. The "
              "front may still come from interactions, or collapse to a single "
              "point that is best on every objective.")


def _report_constant_objectives(
    all_values: dict, live_for: dict, metrics: list[str],
) -> None:
    """Warn on an objective with nothing to trade: constant, or moved by nothing."""
    for m in metrics:
        vals = all_values.get(m) or []
        if len(vals) >= 2 and max(vals) == min(vals):
            print(
                f"  liveness: WARNING — objective {m} was constant ({vals[0]:.6g}) "
                f"across all {len(vals)} liveness run(s): no trade-off to "
                f"discover on it. Either the adapter reports a fixed value "
                f"(check it measures this configuration) or no declared factor "
                f"reaches it; then it belongs in constraints or nowhere, not in "
                f"objectives.",
            )
        elif not any(m in s for s in live_for.values()):
            print(
                f"  liveness: NOTE — no factor moved objective {m} beyond 2x "
                f"its noise floor at the base configuration; the front may be "
                f"flat along it.",
            )


def _report_liveness_durations(
    observed_sec: list[tuple[str, float, bool]], timeout: int,
    problems: list[str],
) -> None:
    """Print every run's wall clock and check the slowest against the ceiling.

    Split out so the printing and the verdict have one home and can be tested
    without executing a sweep. ``problems`` is appended to in place, matching how
    the rest of ``_smoke_liveness_sweep`` accumulates findings.

    The slowest run is taken over SUCCESSFUL runs only. A failed run's elapsed
    time is printed (it is evidence, and a level that died at the ceiling is the
    most damning kind) but is not the basis of the headroom verdict, because its
    duration is bounded BY the ceiling: feeding it back in would compare the
    ceiling against itself and report a failure on every campaign that has ever
    lost a row, including one whose level crashed in 0.2s. That level's own
    finding is already raised, by name, as a hard failure.
    """
    if not observed_sec:
        return
    print(f"  liveness: observed wall clock per run "
          f"(run_timeout_sec ceiling: {timeout}s)")
    for label, secs, ok in sorted(observed_sec, key=lambda r: -r[1]):
        mark = "" if ok else "   <-- did not complete"
        print(f"    {label:<28} {secs:8.1f}s{mark}")
    completed = [(lbl, s) for lbl, s, ok in observed_sec if ok]
    if not completed:
        return
    label, slowest = max(completed, key=lambda r: r[1])
    problem = _timeout_headroom_problem(
        slowest, timeout, what=f"the slowest completed liveness run ({label})",
        why_a_lower_bound=(
            "the sweep varies ONE factor with the others at "
            "known_valid_baseline and never runs a corner, while the design's "
            "slowest corner combines several factors' costly levels at once"
        ),
    )
    if problem:
        problems.append(problem)


def _liveness_run_one(
    opt: dict, factors, levels: dict, *, repo: Path, probe_dir: Path,
    seed_env: str | None, seed: int | None, label: str,
):
    """Execute one configuration for the liveness sweep.

    Returns ``(observations, error_text, elapsed_sec)`` — exactly one of the
    first two is None, and ``elapsed_sec`` is populated on BOTH paths. Goes
    through the SAME ``runner.make_config_runner`` / ``matrix.render_apply`` /
    ``resolve_run_timeout`` seams the epoch runs through — a sweep that ran the
    target differently from the way the epoch will could not certify anything
    about the epoch. In particular the runner already raises on a non-zero exit,
    on a timeout, and on unparseable output, which is exactly the abort
    detection GAP 3 needs; nothing here reimplements it.

    THE ELAPSED TIME WAS ALREADY BEING OBSERVED HERE AND THROWN AWAY. ``--liveness``
    runs every declared level of every factor once; the wall clock of each of
    those runs is exactly the per-level cost data an author needs to size
    ``run_timeout_sec``, and it was measured by the OS and discarded. Returning
    it costs one ``time.monotonic()`` pair and turns prose advice (guide §7.1,
    "size the ceiling from the slowest corner") into a machine check — advice
    whose own author then violated it three times running.

    Timed on the FAILING path too, and that is the case that matters most: a
    level that dies AT the ceiling reports an elapsed time approximately equal
    to the ceiling, which is the strongest possible evidence that the ceiling is
    the binding constraint rather than the target.
    """
    import time

    from orchestrator.optimize import runner
    from orchestrator.optimize.matrix import render_apply
    from orchestrator.optimize.stage_runner import resolve_run_timeout

    from orchestrator.optimize.objectives import objective_metrics as _om

    cfg_runner = runner.make_config_runner(
        opt["run_command"], cwd=repo,
        metric_path=(_om(opt) or [""])[0],
        timeout=resolve_run_timeout(opt),
        log_dir=probe_dir / "failed_runs",
    )

    class _Row:
        row_index = 0
        replicate = 0
        role = "liveness"
        levels: dict = {}
        apply: dict = {}

    row = _Row()
    row.levels = dict(levels)
    apply = render_apply(factors, levels)
    if seed_env and seed is not None:
        apply = {**apply, "env": {**(apply.get("env") or {}),
                                  seed_env: str(seed)}}
    row.apply = apply
    started = time.monotonic()
    try:
        obs = cfg_runner(row)
    except Exception as exc:  # noqa: BLE001 — any failure is a finding
        return None, f"{exc}", time.monotonic() - started
    return obs, None, time.monotonic() - started


def _screen_center_points(opt: dict) -> int:
    """How many center points the screen will generate. 0 when none."""
    design = (opt.get("design") or {})
    screen = (design.get("screen") or {})
    try:
        return int(screen.get("center_points") or 0)
    except (TypeError, ValueError):
        return 0


def _center_levels(factors) -> dict:
    """The levels a generated CENTER POINT will take, decoded exactly as the
    design will decode them.

    Delegates to ``matrix._decode_level`` with a synthetic center ``DesignPoint``
    rather than reimplementing the rule, because the rule has two halves that
    must not drift: a numeric factor takes ``decode_coded(f, 0.0)`` (its
    midpoint, grid-snapped), and a ``choice`` factor runs the level of centre
    REPLICATE 0 -- ``screen_levels[0]``, the first configuration of the
    diagonal cyclic assignment -- since it has no midpoint (the other levels'
    centre configurations are the liveness sweep's corners at numeric mid). A probe that guessed either
    half differently would test a configuration the epoch never runs.
    """
    from orchestrator.optimize.design import DesignPoint
    from orchestrator.optimize.matrix import _decode_level

    levels: dict = {}
    for idx, f in enumerate(factors):
        if not getattr(f, "levels", None):
            continue
        point = DesignPoint(
            coded=tuple(0.0 for _ in factors), role="center", replicate=0,
        )
        try:
            levels[f.id] = _decode_level(f, point, idx)
        except Exception:  # noqa: BLE001 -- a factor we cannot decode is skipped
            return {}
    return levels


def _smoke_probe_one_config(
    opt: dict, factors, *, repo: Path, probe_dir: Path,
    levels: dict | None = None, label: str = "", locked: dict | None = None,
) -> list[str]:
    """Run ONE configuration and check everything that run makes answerable.

    ``locked`` is the campaign's top-level ``locked_parameters`` (this function
    otherwise sees only the ``optimization`` block); see
    ``_check_declared_locked``.

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
    # Default: every factor's FIRST level (the corner `--smoke` has always run).
    # An explicit `levels` lets a caller probe a configuration the design will
    # generate but no declared level names -- notably a CENTER POINT, whose
    # numeric midpoints are not levels at all.
    if levels is None:
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
    from orchestrator.optimize.objectives import objective_metrics as _om

    cfg_runner = runner.make_config_runner(
        opt["run_command"], cwd=repo,
        metric_path=(_om(opt) or [""])[0],
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
    # Same arithmetic the liveness sweep applies to its per-level maximum,
    # through the same function -- see `_timeout_headroom_problem` for what the
    # verdict can and cannot guarantee. One corner is the weakest evidence this
    # check ever runs on (it is the design's FIRST corner, not its slowest),
    # which is exactly why `--liveness` upgrading the evidence is worth the runs.
    headroom = _timeout_headroom_problem(
        elapsed, timeout, what=f"the probe configuration {levels}",
        why_a_lower_bound=(
            "this is the design's FIRST corner, not its slowest -- every factor "
            "sits at its first declared level"
        ),
    )
    if headroom:
        problems.append(headroom)

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

    # 2c. Do the declared response.self_check invariants hold at this corner?
    #
    # Placed before the objective-presence check deliberately: a row whose
    # reported objective contradicts its own recorded diagnostic is a WORSE
    # finding than a missing objective, because a missing objective scores NaN
    # loudly on every row while a self-contradictory one scores a plausible
    # number. Checked here rather than only mid-epoch because that is the whole
    # value: the real defect this closes produced 8 bad rows out of 12, all
    # biased in the flattering direction, and was found only after the epoch.
    problems.extend(_check_declared_self_checks(opt, obs, where=f"corner {levels}"))
    problems.extend(_check_declared_locked(opt, locked, obs, where=f"corner {levels}"))

    # 3. Is the objective metric present? With response.objectives, EVERY
    # objective must be present AND numeric: a front fitted with one objective
    # NaN on every row is a front over the others with that axis silently
    # missing.
    from orchestrator.optimize.objectives import (
        is_multi_objective,
        objective_metrics,
    )

    if not is_multi_objective(opt):
        metric = ((opt.get("response") or {}).get("primary") or {}).get("metric")
        if metric and metric not in obs:
            problems.append(
                f"response.primary.metric {metric!r} is absent from the run's "
                f"output, so every configuration would score NaN. Emitted keys: "
                f"{', '.join(sorted(str(k) for k in obs)[:8])}",
            )
    else:
        shown: list[str] = []
        for metric in objective_metrics(opt):
            value = obs.get(metric)
            if metric not in obs:
                problems.append(
                    f"response.objectives metric {metric!r} is absent from the "
                    f"run's output, so every configuration would score NaN on "
                    f"it and the front would silently lose that axis. Emitted "
                    f"keys: {', '.join(sorted(str(k) for k in obs)[:8])}",
                )
            elif not isinstance(value, (int, float)) or isinstance(value, bool):
                problems.append(
                    f"response.objectives metric {metric!r} is {value!r} "
                    f"({type(value).__name__}), not a number: it cannot be "
                    f"fitted or compared for dominance. Emit it as a JSON number.",
                )
            else:
                shown.append(f"{metric}={value:.6g}")
        if shown:
            print(f"  smoke: objectives at this corner: {', '.join(shown)}")

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
        except Exception as exc:  # noqa: BLE001
            problems.append(f"factor {f.id}: manipulation check raised: {exc}")
            continue
        if not v.ok:
            # The hint names the failure's SHAPE -- absent, empty, wrong type,
            # wrong value -- because each calls for a different fix, and a
            # blanket TYPE hint sent an author with '' == 'ag_rs' (two strings)
            # looking for a type problem that was not there (issue #318).
            problems.append(
                f"factor {f.id}: manipulation predicate fails at its first "
                f"level ({v.detail}). Every run would be rejected. {v.hint}",
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


def _cmd_progress(args):
    """Progress surface for a kind: optimization campaign (stage/rows/ETA).

    Separate from ``nous status`` rather than folded into it, because the two
    answer different questions from different artifacts. ``status`` reports the
    engine PHASE from ``state.json`` and the last SDK tool-call event, which is
    the right surface for a reflective campaign. It cannot report which STAGE an
    optimization campaign is on -- the stage lives in ``transitions.jsonl`` and
    the row counts live in each iteration's ``design_matrix.json`` / ``runs.jsonl``,
    none of which ``status`` reads. A supervising human watching a real campaign
    reported "confirm is running, 17 rows to go" for hours while it was actually
    retry-looping, because no surface answered "which stage, how many rows".
    """
    import json
    import time as _time

    from orchestrator.optimize.progress import (
        format_progress,
        format_progress_line,
        read_progress_snapshot,
    )

    work_dir = resolve_work_dir(args.target)
    if not (work_dir / "state.json").exists():
        print(f"Error: no state.json at {work_dir}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json", False):
        print(json.dumps(read_progress_snapshot(work_dir).as_dict(), indent=2,
                         sort_keys=True))
        return

    if getattr(args, "line", False):
        print(format_progress_line(read_progress_snapshot(work_dir)))
        return

    if getattr(args, "watch", False):
        try:
            while True:
                snap = read_progress_snapshot(work_dir)
                if sys.stdout.isatty():
                    sys.stdout.write("\033[2J\033[H")
                else:
                    sys.stdout.write("\n" + "\u2500" * 60 + "\n")
                sys.stdout.write(format_progress(snap) + "\n")
                sys.stdout.flush()
                _time.sleep(args.interval if args.interval > 0 else 2)
        except KeyboardInterrupt:
            print()
            return

    print(format_progress(read_progress_snapshot(work_dir)))


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


def _cmd_reanalyze(args):
    """Re-derive a kind:optimization campaign's analysis from its recorded rows
    and diff it against disk (audit Q7). Zero tokens, zero measurements."""
    import json as _json
    import logging

    from orchestrator.optimize.reanalyze import format_result, reanalyze

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.ERROR)
    work_dir = resolve_work_dir(args.target)
    campaign = None
    if args.target.endswith((".yaml", ".yml")):
        campaign = yaml.safe_load(Path(args.target).read_text())
    try:
        res = reanalyze(Path(work_dir), campaign=campaign, keep=args.keep)
    except (ValueError, OSError) as exc:
        print(f"reanalyze: {exc}", file=sys.stderr)
        sys.exit(2)
    print(_json.dumps(res.to_dict(), indent=2, default=str) if args.json
          else format_result(res))
    sys.exit(0 if res.identical else 1)


def _cmd_create_campaign(args):
    """Scaffold a heavily-commented campaign.yaml (issue #89)."""
    from orchestrator.create_campaign import scaffold_campaign

    if getattr(args, "kind", "reflective") == "optimization":
        _create_optimization_campaign(args)
        return
    if getattr(args, "adapter_stub", None) is not None:
        print("Error: --adapter-stub applies to --kind optimization only.",
              file=sys.stderr)
        sys.exit(2)
    if getattr(args, "objectives", 1) != 1:
        print("Error: --objectives applies to --kind optimization only.",
              file=sys.stderr)
        sys.exit(2)

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


def _create_optimization_campaign(args):
    from orchestrator.create_campaign import (
        QUICKSTART_DOC,
        scaffold_optimization_campaign,
        write_adapter_stub,
    )

    kwargs: dict = {"force": args.force}
    # The reflective defaults ("TODO-SET-...") are not used here: this kind's
    # own TODO- defaults are what the placeholder scan reports.
    if args.target_name and args.target_name != "TODO-SET-SYSTEM-NAME":
        kwargs["target_name"] = args.target_name
    if args.target_description:
        kwargs["target_description"] = args.target_description
    if args.research_question:
        kwargs["research_question"] = args.research_question
    if args.run_id and args.run_id != "TODO-SET-RUN-ID":
        kwargs["run_id"] = args.run_id
    if args.target_repo_path is not None:
        kwargs["target_repo_path"] = args.target_repo_path
    n_obj = getattr(args, "objectives", 1)
    if n_obj < 1:
        print(f"Error: --objectives must be >= 1 (got {n_obj}); 1 writes "
              f"response.primary, 2+ writes response.objectives.",
              file=sys.stderr)
        sys.exit(2)
    if n_obj != 1:
        kwargs["objectives"] = n_obj
    try:
        path = scaffold_optimization_campaign(args.to, **kwargs)
        stub = (write_adapter_stub(args.adapter_stub, force=args.force)
                if args.adapter_stub is not None else None)
    except FileExistsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("Pass --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    print(f"Wrote {path}  (kind: optimization)")
    if stub is not None:
        print(f"Wrote {stub}  (run_command adapter skeleton)")
    print()
    print(f"Read first: {QUICKSTART_DOC}")
    print()
    print("Next steps:")
    print(f"  1. Fill every TODO- value in {path}"
          + (f" and {stub}" if stub else "") + ".")
    print(f"  2. nous validate campaign {path}            "
          f"# lists every TODO- left, by field path")
    print(f"  3. nous validate campaign {path} --smoke")
    print(f"  4. nous validate campaign {path} --liveness "
          f"# + design preview")
    print(f"  5. NOUS_CAMPAIGN_PARENT=~/nous-campaigns nous run {path}")


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
            "software systems. A campaign.yaml declares one of two kinds."
        ),
        epilog=(
            "campaign kinds:\n"
            "  reflective (default)  WHY does the system behave this way? An agent\n"
            "                        runs DESIGN -> EXECUTE_ANALYZE -> REPORT\n"
            "                        iterations to build causal claims.\n"
            "                        Start: nous create-campaign --to campaign.yaml\n"
            "  optimization          WHICH setting of knobs you already know is\n"
            "                        best, and how sure? A pre-registered factorial\n"
            "                        design (screen -> refine -> confirm), zero model\n"
            "                        calls unless plan/build are enabled.\n"
            "                        Start: nous create-campaign --kind optimization\n"
            "                        --to campaign.yaml, then read\n"
            "                        `nous docs quickstart`\n"
            "\n"
            "Then: nous validate campaign FILE [--smoke | --liveness] until clean,\n"
            "and nous run FILE. `nous schema campaign` lists every field."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
    p_validate.add_argument(
        "--liveness", action="store_true",
        help="Implies --smoke. Also run EVERY declared level of every factor once "
             "(other factors at known_valid_baseline) and measure each factor's "
             "effect against the workload's noise floor. Opt-in because it is "
             "the only check whose cost scales with the design: "
             "sum(len(levels)) + --liveness-repeats runs, not one. Catches a "
             "level that ABORTS the target (caught otherwise only if it happens "
             "to sit at the first design corner) and flags a factor whose "
             "levels move the objective by less than 2x run-to-run noise — a "
             "dead axis that consumes its share of the design and makes the "
             "policy hash a pre-registration of a knob nothing reads. Also "
             "reports each run's observed WALL CLOCK and fails when "
             "run_timeout_sec leaves under 2x headroom over the slowest "
             "completed run — a lower bound on the slowest CORNER, since the "
             "sweep varies one factor at a time and never runs a corner. Ends "
             "with a zero-token DESIGN PREVIEW: runs per stage, expected wall "
             "clock, and the screen's minimum detectable effect vs epsilon.",
    )
    p_validate.add_argument(
        "--liveness-repeats", type=int, default=3, metavar="N",
        help="How many times --liveness runs the known_valid_baseline, varying "
             "only the workload seed, to estimate the objective's noise floor "
             "(default: 3). Below 2 no floor is estimable and every non-zero "
             "effect clears it.",
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

    p_progress = subparsers.add_parser(
        "progress",
        help="Stage, row counts, elapsed and ETA for a kind: optimization "
             "campaign (reads progress.json's inputs live).",
    )
    p_progress.add_argument("target")
    p_progress.add_argument(
        "--watch", action="store_true",
        help="Loop and redraw every --interval seconds.",
    )
    p_progress.add_argument(
        "--line", action="store_true",
        help="Print a single-line summary suitable for shell prompts.",
    )
    p_progress.add_argument(
        "--json", action="store_true",
        help="Print the machine-readable snapshot (same shape as "
             "progress.json at the work-dir root).",
    )
    p_progress.add_argument(
        "--interval", type=float, default=2.0,
        help="Watch redraw interval in seconds (default: 2).",
    )
    p_progress.set_defaults(func=_cmd_progress)

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

    p_reanalyze = subparsers.add_parser(
        "reanalyze",
        help="kind:optimization: recompute every fit, recommendation, "
             "confirmation and the report from the recorded runs.jsonl (no "
             "measurement, no LLM) and diff against what is on disk. Exit 0 "
             "when identical, 1 when anything differs.",
    )
    p_reanalyze.add_argument("target", help="campaign.yaml or work_dir")
    p_reanalyze.add_argument("--keep", action="store_true",
                             help="keep the re-derived scratch work_dir")
    p_reanalyze.add_argument("--json", action="store_true")
    p_reanalyze.set_defaults(func=_cmd_reanalyze)

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
        "--kind", choices=["reflective", "optimization"], default="reflective",
        help="Campaign kind to scaffold. 'optimization' writes a structurally "
             "complete factorial campaign whose TODO- placeholders `nous "
             "validate campaign` lists by field path (and `nous run` refuses "
             "until filled). Default: reflective.",
    )
    p_create.add_argument(
        "--adapter-stub", type=Path, default=None, metavar="PATH",
        help="With --kind optimization: also write a minimal run_command "
             "adapter skeleton at PATH honouring docs/targets.md (one JSON "
             "object on stdout, echo effective cfg, NOUS_WORKLOAD_SEED, "
             "NOUS_RUN_DIR).",
    )
    p_create.add_argument(
        "--objectives", type=int, default=1, metavar="N",
        help="With --kind optimization: how many objectives. 1 (default) "
             "writes response.primary; N >= 2 writes a response.objectives "
             "block of N TODO- metrics plus a commented preference block, for "
             "a campaign that reports the trade-off (Pareto) front.",
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
    p_docs = subparsers.add_parser(
        "docs",
        help="Print a bundled kind: optimization doc (quickstart, guide, targets, "
             "invariants) -- available from any install, no checkout needed.",
    )
    p_docs.add_argument("topic", nargs="?", default="quickstart",
                        choices=sorted(DOC_TOPICS))
    p_docs.add_argument("--path", action="store_true",
                        help="Print the installed file's path instead of its text.")
    p_docs.set_defaults(func=_cmd_docs)

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

    # Reap the target adapter's process trees on SIGTERM/SIGINT. Installed HERE,
    # at the entry point, and nowhere in library code: an application embedding
    # `nous` has its own signal handling, and a library that silently replaced
    # it would be a worse bug than the orphan this fixes. `install_signal_handlers`
    # is additionally careful not to clobber a handler that is already set to
    # something other than the default.
    #
    # What it buys: a campaign killed with SIGTERM used to leave the benchmark's
    # children alive — an SDK child was found still running, and billing, 18
    # hours after its campaign was stopped. `atexit` alone cannot cover that,
    # because it does not run on a signal death.
    try:
        from orchestrator.optimize.reaper import install_signal_handlers
        install_signal_handlers()
    except Exception:  # pragma: no cover - never block the command
        import logging as _logging
        _logging.getLogger(__name__).debug(
            "could not install child-reaping signal handlers", exc_info=True,
        )

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
