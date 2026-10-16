"""Campaign-authoring scaffolder (issue #89).

Closes the silent-failure gap where authors put domain context in
``domain_adapter_layer`` (which sounds right but is unimplemented and
silently warned-and-ignored) instead of ``target_system.description``
(which actually reaches the LLM via {{template}} substitution).

Three lines of defense:
  1. ``nous create-campaign`` CLI subcommand (this module's
     ``scaffold_campaign``) — produces a heavily-commented,
     schema-valid campaign.yaml. Inline comments name exactly which
     fields reach the LLM.
  2. Schema description for ``domain_adapter_layer`` flags
     "NOT YET IMPLEMENTED" — schema-as-documentation.
  3. Loud warning in ``llm_dispatch`` when the field is set, pointing
     at this module / the matching skill.

Pure deterministic Python — no LLM, no live calls, no subprocess.
"""
from __future__ import annotations

from pathlib import Path

# Fields that actually reach the LLM agents via {{template}}
# substitution in orchestrator.llm_dispatch._build_context.
# Authors should put domain context HERE, not in domain_adapter_layer
# (which is silently ignored — see #89).
#
# IMPORTANT: keep in sync with llm_dispatch._build_context. If the
# dispatcher gains a new substitution, add it here too. The
# tests/test_create_campaign.py::TestReachableFieldsConstant test
# enforces the floor.
REACHABLE_FIELDS: tuple[str, ...] = (
    "research_question",
    "description",          # target_system.description
    "observable_metrics",   # target_system.observable_metrics
    "controllable_knobs",   # target_system.controllable_knobs
)


_TEMPLATE = """\
# ─────────────────────────────────────────────────────────────────────────
# Nous campaign — authored {generated_at_marker}
#
# WHICH FIELDS REACH THE AGENT?
#
# Only these four fields are substituted into the LLM's prompts via
# {{{{template}}}} placeholders today:
#
#   * research_question
#   * target_system.description
#   * target_system.observable_metrics
#   * target_system.controllable_knobs
#
# Everything domain-specific you want the LLM to know — data schema
# gotchas, statistical guardrails, baselines to compare against,
# exact file paths and run commands — must live in
# `target_system.description`. That field is free-form Markdown.
#
# DO NOT put context in `prompts.domain_adapter_layer` — it sounds
# like the right place but is NOT YET IMPLEMENTED. The orchestrator
# warns and ignores it. Issue #89 tracks this trap.
#
# AUTHORING CHECKLIST (before you run):
#   [ ] target_system.description includes critical data schema gotchas
#       (file formats, expected columns, edge cases that have caused
#       silent failures in prior runs).
#   [ ] target_system.description states the statistical guardrails
#       you want the agent to respect (minimum seeds per arm, walk-
#       forward / time-cut split rules, multiple-comparisons handling).
#   [ ] target_system.description includes the EXACT file paths,
#       virtualenv paths, and run commands the agent should use.
#   [ ] target_system.description specifies the BASELINE to compare
#       against, pre-specified, so the agent can't cherry-pick an
#       easy comparator.
#   [ ] research_question is one falsifiable sentence with a clear
#       directional claim.
#   [ ] observable_metrics + controllable_knobs are concrete (no
#       placeholders) — the agent uses these as the experimental
#       vocabulary.
#
# Optional power-analysis (issue #163): per-arm `seeds_rationale` on
# each bundle arm right-sizes the seed count from an effect size.
# Optional ground-truth independence (issue #85): `ground_truth` block
# on each bundle to defend against tautological experiment designs.
# Optional warm-start (issue #83): `warm_start.prior_run_id` to
# inherit principles + handoff from a completed prior campaign.
# Optional theory anchors (issue #88): `theory_references` to declare
# external grounding for ground truths.
# ─────────────────────────────────────────────────────────────────────────

research_question: >
  {research_question}

run_id: {run_id}

# Optional iteration cap. CLI --max-iterations overrides. Default 10.
# max_iterations: 10

target_system:
  name: {target_name}

  # Free-form Markdown. THIS is the channel for domain context the
  # agent needs to do its job. Include data schema gotchas, exact
  # paths, baselines, statistical guardrails. The longer the better
  # — it's cached as part of the system block, paid once per session.
  description: |
    {target_description}

  # Concrete, measurable outputs the agent can cite as evidence.
  # Latency, throughput, error rate, cost-per-request, etc.
  observable_metrics:
    - "TODO: replace with a real metric name"
    - "TODO: replace with a real metric name"

  # Concrete things the agent can change. Algorithms, configurations,
  # resource limits. Not abstract concepts.
  controllable_knobs:
    - "TODO: replace with a real knob name"
    - "TODO: replace with a real knob name"

  # Path to the target system's git repo. Used for two distinct things
  # (#239 keeps them cleanly separated):
  #
  #   1. Code worktrees per arm (#133) live at
  #      <repo_path>/.nous-experiments/<run_id>/<arm>/. Always —
  #      they ARE code FOR the target repo.
  #
  #   2. Campaign artifacts (state, ledger, principles, findings, JSON
  #      results) live at $NOUS_CAMPAIGN_PARENT/<run_id>/ if you've
  #      set that env var (recommended — see below); otherwise at the
  #      legacy <repo_path>/.nous/<run_id>/, which pollutes the
  #      target's git status (#239).
  #
  # Recommended setup: export NOUS_CAMPAIGN_PARENT=~/Documents/Projects/nous-campaigns
  # in your shell rc. Campaign artifacts then live outside the target,
  # cleanly separated from regular development. The target's git status
  # stays clean; `git stash -u` won't capture campaign output.
  #
  # Set repo_path to null only if you plan to override on the CLI;
  # running `nous run` from a different CWD will silently land artifacts
  # in the wrong place (#184).
  repo_path: {repo_path}

prompts:
  # Path to the generic Nous methodology prompts. Usually leave as-is.
  methodology_layer: "prompts/methodology/"

  # ⚠️  NOT YET IMPLEMENTED. Setting this triggers a warning and the
  # field is ignored. Put domain-specific context in
  # target_system.description above. Issue #89.
  domain_adapter_layer: null

# ─── Spec-fidelity locks (issues #246/F1, #258/F13, #265/F20) ────────────
# Hard-pinned campaign parameters. Each key here MUST appear identically
# in the design agent's bundle.experiment_spec.verified_parameters;
# nous's validator hard-fails any deviation, regardless of --auto-approve.
#
# WHAT TO LOCK: any parameter whose deviation would invalidate THIS
# experiment. Common categories:
#
#   * Workload identity:    model, concurrency_per_tenant, duration_seconds, warmup_seconds
#   * KV / batching:        total_kv_blocks, MaxModelLen, MaxOutputLen,
#                           max_num_seqs, max_batched_tokens, gpu_memory_utilization,
#                           BlockSize
#   * Latency model:        MfuPrefill, MfuDecode, TP factor (when these
#                           appear in the target's per-model latency config)
#   * Scheduler tunables:   beta_seconds, omega, H, kv_quota, etc.
#   * Network / streaming:  rtt_ms, bandwidth, FlowControlEnabled
#
# The discipline (#258 / F13): enumerate every parameter that COULD
# affect the experimental physics and decide for EACH whether deviation
# is acceptable. Locking reactively (waiting for a bug to surface)
# accumulates rather than addresses risk. See
# docs/campaign-authoring-guide.md for the inventory checklist.
# locked_parameters:
#   model: meta-llama/llama-3.1-8b-instruct
#   concurrency_per_tenant: 32
#   duration_seconds: 600
#   warmup_seconds: 30
#   total_kv_blocks: 24576
#   gpu_memory_utilization: 0.9

# Workload yaml lock (#265 / F20). Parallel to locked_parameters, for
# per-tenant distributions that live in inputs/<workload>.yaml.
# Mismatches against bundle.inputs/*.yaml hard-fail; deliberate
# deviations require bundle.workload_changes_from_canonical.
# locked_workload:
#   tenants:
#     tenant-A:
#       input_distribution: {{type: constant, value: 1024}}
#       output_distribution: {{type: constant, value: 1}}
#       concurrency: 32
#     tenant-B:
#       input_distribution:
#         type: empirical_pmf
#         values: [100, 4720]
#         probs: [0.8, 0.2]

# Cross-campaign code reuse (#266 / F21). Inherits the cumulative
# patch from a prior campaign's specified iteration. nous applies it
# as a preflight at every experiment-worktree creation.
# derived_from:
#   campaign: paper-memorytime-mirage
#   iteration: 2          # or "final"

# Per-phase silence threshold (#264 / F19). Different phases have
# different rhythms — DESIGN's heavy reasoning between tool calls
# vs EXECUTE_ANALYZE's frequent simulator calls. Defaults are
# design=600, execute_analyze=120, report=240. Scalar form (legacy)
# applies one threshold to all phases.
# sdk_timeouts:
#   silence_threshold_seconds: 600
#   turn_silence_threshold_seconds:
#     design: 600
#     execute_analyze: 120
#     report: 240

# Per-phase SDK effort (#282). design benefits from deep reasoning (high);
# execute_analyze (coding, simulations, JSON parsing) is often adequate at
# medium and much cheaper. Omit to use the SDK default (high) everywhere.
# Valid: low | medium | high | xhigh | max
# sdk_options:
#   design:
#     effort: high
#   execute_analyze:
#     effort: medium

# Declarative figure pipeline (#263 / F18). REPORT phase invokes
# each script with NOUS_RESULTS_DIR + NOUS_FIGURES_DIR env vars.
# plot_specs:
#   - id: figure-1-mirage-ratio
#     script: plots/figure_1_mirage.py
#     consumes: [h-main]
#     metrics: [memorytime_share_ratio]
#     outputs: [figures/figure-1.pdf]
#     caption: "Mirage manifests under WFQ; KV-time corrects."

# ─── Optional cross-campaign + epistemic-rigor blocks ─────────────────────
# Uncomment + fill in as needed. See linked issues for details.

# Warm-start from a completed prior campaign (issue #83):
# warm_start:
#   prior_run_id: "previous-campaign-run-id"

# Pre-work hook (issue #167) — cheap deterministic exploration before iter-1:
# pre_work_script: "scripts/explore.py"

# Composite scoring objective (issue #168). Mutually exclusive with objective_preset.
# objective:
#   weights:
#     compound_return: 0.5
#     walk_forward_consistency: 0.3
#     interpretability: 0.1
#     operational_simplicity: 0.1
#   deploy_threshold: 0.05
# objective_preset: compound-return-style   # OR latency-style

# External theory anchors (issue #88) — declare independent ground-truth sources:
# theory_references:
#   - name: "Little's Law"
#     statement: "L = λ × W (mean queue length = arrival rate × mean wait time)"
#     independent_of_detector: true
#     use_as: ground_truth
#     how: "Compute predicted W from observed λ and L; compare against detector estimate."
"""


def scaffold_campaign(
    target_path: Path,
    *,
    target_name: str = "TODO-SET-SYSTEM-NAME",
    target_description: str = (
        "TODO: Describe the system in 1-3 paragraphs. Include data\n"
        "    schema gotchas, exact file paths, statistical guardrails,\n"
        "    and the pre-specified baseline to compare against."
    ),
    research_question: str = (
        "TODO: One falsifiable sentence stating what you're "
        "investigating, with a clear directional claim."
    ),
    run_id: str = "TODO-SET-RUN-ID",
    target_repo_path: Path | str | None = None,
    force: bool = False,
) -> Path:
    """Write a heavily-commented campaign.yaml at ``target_path``.

    Args:
        target_path: Where to write the campaign.yaml. Parent dirs
            are created if missing.
        target_name: ``target_system.name``. Defaults to a TODO marker.
        target_description: ``target_system.description``. Defaults
            to a TODO block listing the four authoring-checklist items.
        research_question: Top-level research_question. Defaults to a
            TODO marker.
        run_id: Working directory name for campaign output.
        target_repo_path: ``target_system.repo_path``. When omitted,
            defaults to the current working directory at scaffold time
            (which is almost always the right answer — authors run
            ``nous create-campaign`` from inside the target repo). Pass
            ``None`` explicitly via the CLI ``--no-repo-path`` flag if
            you intend to fill it in later. (#184)
        force: Overwrite if the target file already exists.

    Returns:
        The path written.

    Raises:
        FileExistsError: target exists and ``force=False``.
    """
    target_path = Path(target_path)
    if target_path.exists() and not force:
        raise FileExistsError(
            f"campaign.yaml already exists at {target_path}; pass force=True "
            f"to overwrite",
        )
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_repo_path is None:
        # #184: CWD at scaffold time is almost always the right answer.
        # The author is typically inside the target repo when they run
        # `nous create-campaign --to ...`; defaulting to CWD avoids the
        # silent "wrong work_dir" trap when `nous run` is invoked from
        # elsewhere later.
        repo_path_value = str(Path.cwd().resolve())
    else:
        repo_path_value = str(Path(target_repo_path).resolve())

    content = _TEMPLATE.format(
        generated_at_marker="(by `nous create-campaign`)",
        research_question=research_question.replace("\n", "\n  "),
        run_id=run_id,
        target_name=target_name,
        target_description=target_description.replace("\n", "\n    "),
        repo_path=repo_path_value,
    )
    target_path.write_text(content)
    return target_path


# ─────────────────────────────────────────────────────────────────────────
# kind: optimization scaffold
# ─────────────────────────────────────────────────────────────────────────
#
# Design choice: the scaffold is STRUCTURALLY complete and schema-valid, but
# every value only the author can know is a ``TODO-...`` token. ``nous validate
# campaign`` reports each one by field path (``find_placeholders`` below), and
# ``nous run`` refuses an optimization campaign that still carries one — so an
# agent cannot launch the scaffold unedited, and the validator's list IS the
# fill-in checklist. Making it schema-INVALID instead would hide every other
# problem behind schema noise; making it fully valid would mean inventing a
# target. Neither helps an author converge.

#: The token every placeholder starts with. One spelling, so the scanner and
#: the template cannot drift.
PLACEHOLDER_TOKEN = "TODO-"

#: How an author reaches the quickstart from ANY install. The repo path is not
#: enough: a pip-installed `nous` ships no `docs/` tree, so pointing a user (or a
#: Claude session) outside the checkout at a relative path was a dead end.
QUICKSTART_DOC = "`nous docs quickstart`"

_OPT_TEMPLATE = """\
# ─────────────────────────────────────────────────────────────────────────
# Nous kind: optimization campaign — scaffolded by
# `nous create-campaign --kind optimization`.
#
# Read first: {quickstart}
#
# Every value starting with TODO- is a placeholder only you can fill.
# `nous validate campaign THIS_FILE` lists every one still present, by
# field path, and `nous run` refuses this file until none remain.
#
# THE LOOP (iterate until each step is clean, then move on):
#   1. fill every TODO-                 (this file + your adapter script)
#   2. nous validate campaign FILE              # static, 0 runs
#   3. nous validate campaign FILE --smoke      # tests + 1 config
#   4. nous validate campaign FILE --liveness   # every level once + noise
#                                               # floor + DESIGN PREVIEW
#   5. NOUS_CAMPAIGN_PARENT=~/nous-campaigns nous run FILE
#   6. monitor from any shell: nous progress FILE   (--json for tools,
#      --line for one line); results: report.md / report.json in the
#      work_dir, halt.json if a gate stopped it
#
# Model calls: ZERO unless you enable the opt-in `plan`/`build` stages
# (bottom of file). Factors are declared HERE by you; no model proposes them.
# report.md and gate summaries are rendered from artifacts, zero tokens.
# ─────────────────────────────────────────────────────────────────────────

kind: optimization

run_id: {run_id}

research_question: >
  {research_question}

prompts:
  methodology_layer: "prompts/methodology/"
  domain_adapter_layer: null

target_system:
  name: {target_name}
  # Read by NO stage unless plan/build are enabled. Describe the target and
  # what the adapter measures, for human readers and for build.
  description: >
    {target_description}
  # Absolute path. run_command/test_command run with cwd = this directory.
  # Keep campaign artifacts OUT of it: export NOUS_CAMPAIGN_PARENT.
  repo_path: {repo_path}

# Knobs that must NOT change across rows (workload size, model, dataset...).
# A lock is only ENFORCED when optimization.locked_observables says where the
# adapter reports the value it actually used (validate warns otherwise).
locked_parameters:
  TODO-locked-knob: TODO-locked-value

optimization:
  # argv, NOT a shell line: split with shlex, run with cwd=repo_path. No `cd`,
  # `&&`, pipes, redirects, globs, or leading VAR=value (use `env VAR=v ...`).
  # The interpreter you name must have your dependencies installed — use the
  # target's own venv path, e.g. ".venv/bin/python".
  # Each factor's rendered `apply` argument is APPENDED to this command.
  # Contract (`nous docs targets`): print ONE JSON object last on stdout, echo the
  # EFFECTIVE value of every factor under cfg.* on EVERY row (never omit a
  # field at some corners), read NOUS_WORKLOAD_SEED, write files only under
  # NOUS_RUN_DIR, exit non-zero on any failed measurement.
  # `nous create-campaign --kind optimization --adapter-stub PATH` writes one.
  run_command: "TODO-python TODO-path/to/adapter.py"

  # Runs every declared native_test once at verify. Must print PER-TEST
  # results (pytest -v / go test -v). Paths RELATIVE to repo_path. The target's
  # own pytest config (addopts like `-n auto --cov --cov-fail-under=...`)
  # applies here too: install its test deps in this interpreter, or override
  # (`-p no:cacheprovider --no-cov -n 0`), and watch --smoke for
  # "unrecognized arguments". Prefer the target's own FAST relation tests.
  test_command: "TODO-python -m pytest -v TODO-tests/test_relations.py"

  # Ceilings, seconds. Size run_timeout_sec from the SLOWEST corner (>= 2x
  # its measured wall clock; --liveness measures per-level times for you).
  test_timeout_sec: 900
  run_timeout_sec: 600

  # Optional cap on total wall clock; --liveness compares its preview to it.
  # max_wall_clock_hours: 8

  # Where the adapter reports each locked value (dotted path into its JSON).
  locked_observables:
    TODO-locked-knob: TODO-cfg.locked_knob

  # A configuration you KNOW runs. Every factor, each at one of its DECLARED
  # levels. --liveness varies one factor at a time around it.
  known_valid_baseline: {{A: 4, B: "off"}}

  # Declare when the target is stochastic: replicate i of every finalist then
  # shares one seed, so confirm's comparison is PAIRED (much tighter). The
  # adapter must actually read this variable (`nous docs targets` §3).
  workload:
    seed_env: NOUS_WORKLOAD_SEED

  policy:
    # Indifference width: "we would not reship for less than this". Must be
    # ABOVE the screen's minimum detectable effect (--liveness prints it), or
    # certification rests on confirm's paired replicates alone.
    epsilon: {{pct: 2.0}}         # or {{abs: 0.5}} in the metric's units
    delta_screen: 0.05
    delta_terminal: 0.05

  response:
    primary: {{metric: TODO-primary-metric, direction: maximize}}
    # SLA / budget limits: a row violating one is INFEASIBLE (kept as data,
    # never the winner). Delete the list if you have none.
    constraints:
      - {{metric: TODO-constraint-metric, op: "<=", value: 0}}
    # Invariants of the MEASUREMENT ITSELF (the run completed, nothing was
    # censored) — a violation means the row measured something else.
    self_check:
      - {{metric: TODO-completed-flag, op: "==", value: true}}
    # Recorded on every row and summarised in report.json; NEVER optimized,
    # fitted or ranked on -- the generalization check. Delete if none.
    held_out: [TODO-held-out-metric]
    # Run-to-run noise of the primary metric, percent (measure it:
    # --liveness prints the CV of repeated baseline runs).
    noise_estimate_pct: 2.0

  factors:
    # Numeric factor. Integer-valued levels NEED `grid: 1`, or refine/centre
    # points may ask for 2.5. Levels must bracket the baseline (4 here).
    # `scale: log` for a GEOMETRIC knob (a size, batch, interval spanning
    # orders of magnitude): the centre point is then the geometric mean.
    # Delete it for an additive knob (a ratio, a threshold).
    # A knob that runs ONLY at listed values (powers of two, a menu of sizes)
    # takes `levels_only: true` INSTEAD of `grid`: every point refine runs and
    # every recommendation is then one of the declared levels.
    - id: A
      name: TODO-numeric-knob-name
      type: numeric
      levels: [1, 2, 4, 8]
      grid: 1
      scale: log
      apply: "--TODO-numeric-flag={{level}}"
      # What the adapter ECHOES (a number, not "4"). Never trivially true.
      manipulation: {{observable: TODO-cfg.numeric_knob, op: "==", value: "{{level}}"}}
      relations:
        - id: R_A
          kind: correctness
          statement: "TODO: what must stay correct at every level of this knob"
          # The id EXACTLY as the test runner prints it, relative to repo_path.
          native_test: "TODO-tests/test_relations.py::test_numeric_knob"
    # Choice factor: levels are exact strings the adapter echoes back.
    - id: B
      name: TODO-choice-knob-name
      type: choice
      levels: ["off", "on"]
      apply: "--TODO-choice-flag={{level}}"
      manipulation: {{observable: TODO-cfg.choice_knob, op: "==", value: "{{level}}"}}
      relations:
        - id: R_B
          kind: correctness
          statement: "TODO: what must stay correct with this choice on and off"
          native_test: "TODO-tests/test_relations.py::test_choice_knob"

  design:
    # Resolution 5: no main effect or 2-factor interaction is aliased with
    # another. Centre points buy the pure-error df the screen's tests use:
    # df = center_points - 1 (3 centres -> df=2 -> t=4.30, a coarse screen).
    screen: {{resolution: 5, center_points: 3}}
    # refine fits curvature and NEEDS >= 2 numeric factors with > 2 levels;
    # this scaffold has one, so it is off. Enable by adding a second such
    # factor, uncommenting this, and adding `refine` to stages.
    # refine: {{center_points: 4}}
    # Terminal discrimination: shortlist finalists, each re-measured.
    confirm: {{replicates: 3, shortlist_size: 3}}
    max_runs: 60

  stages: [verify, screen, confirm]
  # OPT-IN MODEL STAGES — only when the mechanism under study does NOT exist
  # in the target yet: `plan` designs it, `build` authors it plus the native
  # tests your relations declare. Each is one agent call. Enable with:
  # stages: [plan, build, verify, screen, confirm]
  # guidance:
  #   factor_nomination: >
  #     Read ONLY by plan/build: what the authoring agent must know.

  # Literal repo-relative paths of the mechanism's code (not globs); the drift
  # oracle watches them.
  # build_checks:
  #   mechanism_paths: ["src/TODO-mechanism.py"]
"""


_SINGLE_RQ = (
    "TODO-which configuration of the declared knobs maximizes the "
    "primary metric, subject to the constraints?"
)
_MULTI_RQ = (
    "TODO-what is the trade-off frontier between the objectives over the "
    "declared knobs, subject to the constraints?"
)

_PRIMARY_LINE = "    primary: {metric: TODO-primary-metric, direction: maximize}\n"
_NOISE_COMMENT = (
    "    # Run-to-run noise of the primary metric, percent (measure it:\n"
    "    # --liveness prints the CV of repeated baseline runs).\n"
)
_EPSILON_COMMENT = (
    "    # Indifference width: \"we would not reship for less than this\". Must be\n"
    "    # ABOVE the screen's minimum detectable effect (--liveness prints it), or\n"
    "    # certification rests on confirm's paired replicates alone.\n"
    "    epsilon: {pct: 2.0}         # or {abs: 0.5} in the metric's units\n"
)


def _multi_objective_response(content: str, n: int) -> str:
    """Rewrite the single-objective template's response for ``n`` objectives.

    Applied to the RENDERED template rather than kept as a second template, so
    the two scaffolds cannot drift anywhere except the lines this replaces --
    and each replaced line must be present exactly once, or the template has
    moved under this function and that is a bug to surface, not to paper over.
    """
    lines = [
        "    # Two or more objectives: the campaign reports the TRADE-OFF FRONT\n",
        "    # (configurations no other one beats on every objective at once) and\n",
        "    # recommends one point of it by `preference`. Directions: maximize |\n",
        "    # minimize -- CHECK each. An objective may not also be a constraint,\n",
        "    # held_out or self_check metric: if you already know the acceptable\n",
        "    # bound, make it a constraint instead (`nous docs guide`,\n",
        "    # \"Multi-objective: finding the trade-off frontier\").\n",
        "    objectives:\n",
    ]
    for i in range(1, n + 1):
        direction = "maximize" if i == 1 else "minimize"
        lines.append(f"      - {{metric: TODO-objective-{i}-metric, "
                     f"direction: {direction}}}\n")
    lines += [
        "    # How ONE recommended configuration is chosen from the front. Default\n",
        "    # knee (best bang for the buck; needs no weights). Or:\n",
        "    # preference:\n",
        "    #   method: weights          # knee | weights | lexicographic\n",
        "    #   weights: {"
        + ", ".join(f"TODO-objective-{i}-metric: 1.0" for i in range(1, n + 1))
        + "}\n",
        "    #   # method: lexicographic -> order: ["
        + ", ".join(f"TODO-objective-{i}-metric" for i in range(1, n + 1))
        + "]\n",
    ]
    replacements = [
        (_PRIMARY_LINE, "".join(lines)),
        (_NOISE_COMMENT,
         "    # Run-to-run noise of EACH objective, percent (one number for all,\n"
         "    # or a map objective metric -> pct; --liveness prints each CV).\n"),
        (_EPSILON_COMMENT,
         "    # Indifference width PER OBJECTIVE: a difference smaller than it is\n"
         "    # not dominance. One spec for every objective, or a map objective\n"
         "    # metric -> spec when units differ, e.g.\n"
         "    # {TODO-objective-1-metric: {pct: 2.0}, TODO-objective-2-metric: {abs: 5}}.\n"
         "    # --liveness prints each objective's screen MDE against it.\n"
         "    epsilon: {pct: 2.0}\n"),
    ]
    for old, new in replacements:
        if content.count(old) != 1:
            raise RuntimeError(
                f"optimization template changed: expected exactly one "
                f"{old.strip()[:40]!r}")
        content = content.replace(old, new)
    return content


def scaffold_optimization_campaign(
    target_path: Path,
    *,
    target_name: str = "TODO-target-name",
    target_description: str = (
        "TODO-describe the target and what one run of the adapter measures."
    ),
    research_question: str = (
        "TODO-which configuration of the declared knobs maximizes the "
        "primary metric, subject to the constraints?"
    ),
    run_id: str = "TODO-run-id",
    target_repo_path: Path | str | None = None,
    force: bool = False,
    objectives: int = 1,
) -> Path:
    """Write a structurally complete ``kind: optimization`` campaign.yaml.

    Schema-valid, but carrying ``TODO-`` placeholders that
    ``find_placeholders`` reports by path, so validation fails naming them and
    ``nous run`` refuses it until they are filled.

    ``objectives`` = 1 (default) writes ``response.primary`` -- byte-identical
    to the template before multi-objective support existed. ``objectives`` >= 2
    writes a ``response.objectives`` block of that many ``TODO-`` metrics plus
    a commented ``preference`` block (see :func:`_multi_objective_response`).
    """
    if not isinstance(objectives, int) or objectives < 1:
        raise ValueError(f"objectives must be an integer >= 1, got {objectives!r}")
    if objectives >= 2 and research_question == _SINGLE_RQ:
        research_question = _MULTI_RQ
    target_path = Path(target_path)
    if target_path.exists() and not force:
        raise FileExistsError(
            f"campaign.yaml already exists at {target_path}; pass force=True "
            f"to overwrite",
        )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    repo = Path.cwd() if target_repo_path is None else Path(target_repo_path)
    content = _OPT_TEMPLATE.format(
        quickstart=QUICKSTART_DOC,
        run_id=run_id,
        research_question=research_question.replace("\n", "\n  "),
        target_name=target_name,
        target_description=target_description.replace("\n", "\n    "),
        repo_path=str(repo.resolve()),
    )
    if objectives >= 2:
        content = _multi_objective_response(content, objectives)
    target_path.write_text(content)
    return target_path


_ADAPTER_STUB = '''\
#!/usr/bin/env python3
"""Nous run_command adapter skeleton (contract: `nous docs targets`).

Nous invokes:  <run_command argv> + each factor's rendered `apply` argument,
with cwd = target_system.repo_path. This script must:

  * run ONE configuration of the target and print ONE JSON object LAST on
    stdout (progress logs may go to stderr);
  * echo the EFFECTIVE value of EVERY factor under "cfg" on EVERY run — what
    the target actually used, never just what was requested, and never omit
    a key at some configurations (the output contract is frozen at row 1);
  * read the workload seed from NOUS_WORKLOAD_SEED (when declared);
  * write any file only under NOUS_RUN_DIR (private per run);
  * exit NON-ZERO on any failed measurement — never print a 0 or null for a
    number it did not measure.

Edit every TODO. Then: nous validate campaign FILE --smoke
"""
import argparse
import json
import os
import sys
import tempfile


def main() -> int:
    ap = argparse.ArgumentParser()
    # One flag per factor, matching each factor's `apply` template.
    ap.add_argument("--TODO-numeric-flag", dest="numeric_knob", type=int, required=True)
    ap.add_argument("--TODO-choice-flag", dest="choice_knob", choices=["off", "on"], required=True)
    args = ap.parse_args()

    seed = int(os.environ.get("NOUS_WORKLOAD_SEED", "0"))
    run_dir = os.environ.get("NOUS_RUN_DIR") or tempfile.mkdtemp(prefix="nous-run-")

    # TODO: run the target with these settings, under run_dir, seeded by seed.
    # Raise / return non-zero on ANY failure.
    result = {"TODO_primary_metric": None}
    effective = {
        "numeric_knob": args.numeric_knob,   # TODO: read back from the target
        "choice_knob": args.choice_knob,     # TODO: read back from the target
    }

    if any(v is None for v in result.values()):
        print("measurement incomplete; refusing to emit a partial row", file=sys.stderr)
        return 1
    print(json.dumps({**result, "seed": seed, "cfg": effective}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def write_adapter_stub(path: Path, *, force: bool = False) -> Path:
    """Write the minimal adapter skeleton honouring the `nous docs targets` contract."""
    path = Path(path)
    if path.exists() and not force:
        raise FileExistsError(
            f"adapter stub already exists at {path}; pass --force to overwrite",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_ADAPTER_STUB)
    path.chmod(path.stat().st_mode | 0o111)
    return path


def find_placeholders(doc, _path: str = "") -> list[tuple[str, str]]:
    """Every ``(field_path, value)`` whose key or string value carries a
    ``TODO-``/``TODO:`` placeholder. Pure; order is document order."""
    found: list[tuple[str, str]] = []
    if isinstance(doc, dict):
        for k, v in doc.items():
            here = f"{_path}.{k}" if _path else str(k)
            if _is_placeholder(str(k)):
                found.append((here, f"(key) {k}"))
            found.extend(find_placeholders(v, here))
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            found.extend(find_placeholders(v, f"{_path}[{i}]"))
    elif isinstance(doc, str) and _is_placeholder(doc):
        found.append((_path, doc))
    return found


def _is_placeholder(text: str) -> bool:
    return PLACEHOLDER_TOKEN in text or "TODO:" in text
