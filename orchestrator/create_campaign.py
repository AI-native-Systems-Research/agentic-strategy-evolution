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
