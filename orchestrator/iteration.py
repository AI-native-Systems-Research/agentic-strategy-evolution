#!/usr/bin/env python3
"""Run a single Nous iteration.

Usage:
    python run_iteration.py examples/campaign.yaml

    # Inline mode — embed inside an agent framework:
    python run_iteration.py examples/campaign.yaml --agent inline

Creates a working directory named after the target system, copies templates,
and runs one full iteration with human gates for approval.

Dispatch backends:
    --agent sdk (default): Claude Agent SDK for code phases (when repo_path
        is set) and LLMDispatcher for structured phases. OPENAI_API_KEY is
        optional — gate summaries are skipped if not set.
    --agent inline: Prompts emitted to stdout for the calling agent.

    The legacy ``api`` backend was removed in #183.
"""
import argparse
import json
import logging
import re
import shutil
import sys
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import jsonschema
import yaml

from orchestrator.engine import Engine
from orchestrator.gates import HumanGate
from orchestrator.llm_dispatch import LLMDispatcher
from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)


class IterationOutcome(str, Enum):
    """Outcome of a single iteration — used by run_campaign to decide next step."""
    COMPLETED = "COMPLETED"    # Final iteration, transitioned to DONE
    CONTINUE = "CONTINUE"      # Non-final iteration, stopped before DONE
    ABORTED = "ABORTED"        # Human aborted at a gate
    REDESIGN = "REDESIGN"      # Human rejected, needs redesign

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"
DEFAULTS_PATH = Path(__file__).resolve().parent / "defaults.yaml"
_ARM_TYPE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# Phase ordering for resume logic. PRE_WORK (issue #167) sits between
# INIT and DESIGN; CRITIC (issue #87) sits between DESIGN and
# HUMAN_DESIGN_GATE. Campaigns that opt into either pass through them;
# legacy campaigns skip both via the direct transitions.
_PHASE_ORDER = [
    "INIT", "PRE_WORK", "DESIGN", "CRITIC", "HUMAN_DESIGN_GATE",
    "EXECUTE_ANALYZE", "HUMAN_FINDINGS_GATE",
    "DONE",
]
_PHASE_INDEX = {p: i for i, p in enumerate(_PHASE_ORDER)}


# Sentinel file an operator writes via `nous stop <target>` to ask the
# orchestrator to wind down cleanly between phases / iterations. Lives
# at the campaign work_dir root (alongside state.json) and is consumed
# by ``check_stop_requested`` and removed by callers when honoured.
STOP_SENTINEL_NAME = "STOP"


class CampaignStopped(RuntimeError):
    """Raised when a stop sentinel was found mid-campaign.

    The campaign loop converts this into an ABORTED outcome and a
    ledger row tagged ``stopped_by_user``. The exception message
    mentions the sentinel path so the operator knows what to clear
    before resuming.
    """


def check_stop_requested(work_dir: Path) -> Path | None:
    """Return the STOP sentinel path if it exists, else None."""
    sentinel = Path(work_dir) / STOP_SENTINEL_NAME
    return sentinel if sentinel.exists() else None


def _read_stop_reason(sentinel: Path) -> str:
    """Read the optional reason text the operator wrote into the sentinel."""
    try:
        text = sentinel.read_text().strip()
    except OSError:
        return ""
    return text


def _raise_if_stopped(work_dir: Path, *, where: str) -> None:
    """Bail out cleanly if the operator left a STOP sentinel.

    ``where`` names the moment in the campaign loop (e.g.
    ``"before iteration 2"``) so the resulting error message orients
    the operator without forcing them to hunt through the source.
    """
    sentinel = check_stop_requested(work_dir)
    if sentinel is None:
        return
    reason = _read_stop_reason(sentinel)
    msg = (
        f"Campaign stopped by user at {where}. Sentinel: {sentinel}"
    )
    if reason:
        msg += f". Reason: {reason}"
    msg += (
        "\n\nDelete the sentinel file to resume "
        "(`rm <sentinel>`), or run `nous resume <target>` after the "
        "underlying issue is addressed."
    )
    raise CampaignStopped(msg)


# #187: which files MUST exist after DESIGN completes for the iteration
# to advance. Drives the structured "design_incomplete" diagnostic.
_REQUIRED_DESIGN_ARTIFACTS = ("problem.md", "bundle.yaml", "handoff_snapshot.md")


class DesignIncompleteError(RuntimeError):
    """DESIGN exited without producing the required artifacts (#187).

    Distinct from a validator failure (where the artifacts exist but
    are malformed). This error fires when one or more of bundle.yaml /
    problem.md / handoff_snapshot.md is missing on disk after the
    dispatcher returned — typically because the agent ran out of turns
    or pursued the experiment instead of authoring the bundle.

    The orchestrator catches this and writes a structured retry_log
    entry with ``failure_type: "design_incomplete"`` so the operator
    sees what went wrong without grepping for missing files.
    """

    def __init__(self, missing: list[str], iter_dir: Path, max_turns: int):
        self.missing = list(missing)
        self.iter_dir = Path(iter_dir)
        self.max_turns = max_turns
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        missing_lines = "\n".join(f"  - {m}" for m in self.missing)
        log_path = self.iter_dir / "inputs" / "executor_log.jsonl"
        legacy_log_path = self.iter_dir / "executor_log.jsonl"
        return (
            f"DESIGN incomplete for {self.iter_dir.name}. Missing "
            f"required artifacts:\n"
            f"{missing_lines}\n\n"
            f"The agent did not commit a complete design. Likely causes:\n"
            f"  1. max_turns exhaustion (current limit: {self.max_turns}). "
            f"Consider raising via the per-campaign max_turns block (#186) "
            f"or tightening the campaign brief.\n"
            f"  2. The agent ran the main experiment in DESIGN instead "
            f"of authoring bundle.yaml. Check whether the campaign brief "
            f"explicitly forbids running the experiment in DESIGN scope.\n"
            f"  3. API stall / timeout. The SDK streaming log is at\n"
            f"     {log_path}\n"
            f"     (or, on legacy campaigns predating #190, at\n"
            f"     {legacy_log_path}).\n"
            f"  4. Pre-flight or transport failure. Check retry_log.jsonl\n"
            f"     for transient-error history.\n"
            f"\n"
            f"For full context, look at "
            f"{self.iter_dir / 'design_log.md'} (the agent's working notes "
            f"this turn) and the metrics-row count in llm_metrics.jsonl."
        )


def _missing_design_artifacts(iter_dir: Path) -> list[str]:
    """Return the list of required DESIGN artifacts that don't exist (#187)."""
    return [
        name for name in _REQUIRED_DESIGN_ARTIFACTS
        if not (iter_dir / name).exists()
    ]


def _apply_pre_authored_bundle(
    iter_dir: Path,
    *,
    bundle_path: Path,
    problem_md_path: Path | None,
    handoff_md_path: Path | None,
    campaign: dict,
) -> None:
    """Skip DESIGN by copying a pre-authored bundle into ``iter_dir`` (#188).

    For paper-reproduction campaigns the experiment is fully specified
    in advance — the agent shouldn't re-derive the design each run, both
    for cost and for determinism (the agent might author a slightly
    different bundle each time). This helper validates the bundle, copies
    it, stubs the missing companion artifacts when the user didn't
    provide them, and writes a ``bundle_manifest.json`` so reviewers can
    verify which inputs were pre-authored.
    """
    import hashlib
    import shutil

    if not bundle_path.exists():
        raise FileNotFoundError(
            f"Pre-authored bundle not found: {bundle_path}"
        )

    bundle_text = bundle_path.read_text()
    try:
        bundle_doc = yaml.safe_load(bundle_text)
    except yaml.YAMLError as exc:
        raise ValueError(
            f"Pre-authored bundle is not valid YAML ({bundle_path}): {exc}"
        ) from exc

    schema = yaml.safe_load(
        (SCHEMAS_DIR / "bundle.schema.yaml").read_text()
    )
    try:
        jsonschema.validate(bundle_doc, schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(
            f"Pre-authored bundle failed schema validation "
            f"({bundle_path}): {exc.message}"
        ) from exc

    iter_dir.mkdir(parents=True, exist_ok=True)
    target_bundle = iter_dir / "bundle.yaml"
    target_bundle.write_text(bundle_text)

    target_problem = iter_dir / "problem.md"
    if problem_md_path is not None:
        if not problem_md_path.exists():
            raise FileNotFoundError(
                f"Pre-authored problem.md not found: {problem_md_path}"
            )
        shutil.copyfile(problem_md_path, target_problem)
    else:
        rq = campaign.get("research_question", "(no research_question set)")
        target_problem.write_text(
            f"# Problem (pre-authored)\n\n"
            f"This iteration uses a pre-authored bundle (#188). "
            f"The driving research question is:\n\n"
            f"> {rq}\n\n"
            f"See `bundle.yaml` for the experiment specification and "
            f"`bundle_manifest.json` for provenance.\n"
        )

    target_handoff = iter_dir / "handoff_snapshot.md"
    if handoff_md_path is not None:
        if not handoff_md_path.exists():
            raise FileNotFoundError(
                f"Pre-authored handoff_snapshot.md not found: {handoff_md_path}"
            )
        shutil.copyfile(handoff_md_path, target_handoff)
    else:
        metadata = (bundle_doc or {}).get("metadata", {}) if isinstance(bundle_doc, dict) else {}
        family = metadata.get("family", "(family unset)")
        target_handoff.write_text(
            f"# Handoff snapshot (pre-authored)\n\n"
            f"- Bundle source: pre_authored (issue #188)\n"
            f"- Bundle family: {family}\n"
            f"- Source path: {bundle_path}\n"
            f"\n"
            f"This handoff is auto-generated because the user supplied "
            f"a bundle directly via `--bundle`. The downstream "
            f"EXECUTE_ANALYZE phase reads `bundle.yaml`; this file "
            f"satisfies the validator's whitelist and gives reviewers "
            f"a pointer to the original.\n"
        )

    sha256 = hashlib.sha256(bundle_text.encode("utf-8")).hexdigest()
    manifest = {
        "bundle_source": "pre_authored",
        "bundle_path": str(bundle_path),
        "bundle_sha256": sha256,
        "problem_md_source": (
            "pre_authored" if problem_md_path is not None else "auto_stub"
        ),
        "handoff_snapshot_md_source": (
            "pre_authored" if handoff_md_path is not None else "auto_stub"
        ),
    }
    atomic_write(
        iter_dir / "bundle_manifest.json",
        json.dumps(manifest, indent=2) + "\n",
    )


def _save_human_feedback(iter_dir: Path, phase: str, reason: str) -> None:
    """Append human gate feedback to structured human_feedback.json."""
    logger = logging.getLogger(__name__)
    fb_path = iter_dir / "human_feedback.json"
    if fb_path.exists():
        try:
            store = json.loads(fb_path.read_text())
        except json.JSONDecodeError as exc:
            logger.warning(
                "Corrupt human_feedback.json at %s: %s. "
                "Prior feedback entries will be lost.",
                fb_path, exc,
            )
            store = {"design": [], "findings": []}
    else:
        store = {"design": [], "findings": []}
    if not isinstance(store, dict):
        logger.warning(
            "human_feedback.json at %s has unexpected type %s. "
            "Prior feedback entries will be lost.",
            fb_path, type(store).__name__,
        )
        store = {"design": [], "findings": []}
    entries = store.setdefault(phase, [])
    entries.append({
        "attempt": len(entries) + 1,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    atomic_write(fb_path, json.dumps(store, indent=2) + "\n")


_YAML_FENCE_RE = re.compile(r"```yaml\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


_HANDOFF_RE = re.compile(r"^#{1,3}\s*Handoff\s*:?\s*$", re.MULTILINE | re.IGNORECASE)


def _split_design_output(raw: str, iter_dir: Path) -> None:
    """Split merged design output into problem.md, bundle.yaml, and handoff.md."""
    # Extract handoff FIRST to avoid yaml fences in handoff confusing bundle parsing
    handoff_md = ""
    handoff_match = _HANDOFF_RE.search(raw)
    if handoff_match:
        handoff_md = raw[handoff_match.start():].strip()
        raw_before_handoff = raw[:handoff_match.start()]
    else:
        logger.warning(
            "Design output does not contain a '## Handoff' section. "
            "Executor will run without designer context."
        )
        raw_before_handoff = raw

    matches = _YAML_FENCE_RE.findall(raw_before_handoff)
    if not matches:
        raise RuntimeError(
            "Design agent did not produce a ```yaml``` code fence. "
            "Cannot extract hypothesis bundle from response."
        )
    bundle_yaml_str = matches[-1]
    bundle = yaml.safe_load(bundle_yaml_str)
    if not isinstance(bundle, dict):
        raise RuntimeError(
            f"Expected YAML object from design agent, got {type(bundle).__name__}"
        )

    schema = yaml.safe_load((SCHEMAS_DIR / "bundle.schema.yaml").read_text())
    jsonschema.validate(bundle, schema)

    last_fence_start = raw_before_handoff.rfind("```yaml")
    if last_fence_start == -1:
        last_fence_start = raw_before_handoff.rfind("```YAML")

    problem_md = raw_before_handoff[:last_fence_start].rstrip()
    if problem_md.endswith("---"):
        problem_md = problem_md[:-3].rstrip()

    iter_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(iter_dir / "problem.md", problem_md + "\n")
    atomic_write(
        iter_dir / "bundle.yaml",
        yaml.safe_dump(bundle, default_flow_style=False, sort_keys=False),
    )
    if handoff_md:
        # Save per-iteration snapshot for audit
        atomic_write(iter_dir / "handoff_snapshot.md", handoff_md + "\n")
        # Update campaign-level handoff (the living document)
        atomic_write(iter_dir.parent.parent / "handoff.md", handoff_md + "\n")


def _enter_phase(engine, phase):
    """Transition to phase if needed. Returns True if phase work should run."""
    current_idx = _PHASE_INDEX[engine.phase]
    target_idx = _PHASE_INDEX[phase]
    if current_idx > target_idx:
        return False
    if engine.phase != phase:
        engine.transition(phase)
    return True


def _resolve_objective(campaign: dict):
    """Resolve campaign.yaml's objective block to an ObjectiveSpec, or None.

    Issue #177: the iteration finalize step calls update_best_found with
    this objective. Legacy campaigns without `objective` or `objective_preset`
    fall through to the legacy status-based ranking inside update_best_found.
    """
    if not isinstance(campaign, dict):
        return None
    from orchestrator.composite_score import ObjectiveSpec, get_preset

    if (preset := campaign.get("objective_preset")):
        try:
            return get_preset(str(preset))
        except ValueError:
            return None

    obj = campaign.get("objective")
    if isinstance(obj, dict) and obj.get("weights"):
        try:
            return ObjectiveSpec(
                weights={str(k): float(v) for k, v in obj["weights"].items()},
                metric_extractors=dict(obj.get("metric_extractors") or {}),
                deploy_threshold=float(obj.get("deploy_threshold", 0.1)),
            )
        except (TypeError, ValueError):
            return None
    return None


def finalize_iteration(
    *,
    work_dir: Path,
    iter_dir: Path,
    iteration: int,
    campaign: dict,
) -> None:
    """Run the deterministic post-gate finalize steps for an iteration.

    Public seam (issue #177) so integration tests can drive the same
    code path that ``run_iteration`` calls after HUMAN_FINDINGS_GATE
    approves. The sort_bench dry-run on 2026-05-25 surfaced the gap:
    ``update_best_found`` shipped in PR #172 with passing unit tests
    but no caller — this function is the caller.

    Steps (deterministic Python, no LLM):
      1. Classify principle_updates.json in place — fill empirical_content
         / derivation_type from text heuristics (issue #179).
      2. Merge ``principle_updates.json`` into ``principles.json``.
      3. Re-rank candidates and atomically rewrite ``best_found.json``
         (issue #168 / #177).
      4. Surface validator warnings for any residual unclassified
         domain principles (issue #179, #86).
      5. Regenerate per-campaign ``CLAUDE.md`` so the next iteration's
         session sees the updated principles + handoff (issue #131).

    Tolerant of partial fixtures: missing principle_updates.json,
    missing findings.json, and CLAUDE.md regeneration failures all
    soft-fail — the iteration's terminal artifacts (``best_found.json``,
    ``principles.json``) are still written.
    """
    from orchestrator.composite_score import update_best_found
    from orchestrator.principles_classifier import classify_principle_updates_in_place
    from orchestrator.validate import validate_principles_have_empirical_content

    # Classify BEFORE merge so principles.json reflects the tags on its
    # very first write (issue #179).
    classify_principle_updates_in_place(iter_dir)

    _merge_principles(work_dir, iter_dir)

    objective = _resolve_objective(campaign)
    update_best_found(work_dir, objective=objective, top_k=5)

    # Surface validator warnings for residual unclassified domain
    # principles. Advisory only — doesn't roll back the merge.
    principles_path = work_dir / "principles.json"
    if principles_path.exists():
        try:
            store = json.loads(principles_path.read_text())
            for warning in validate_principles_have_empirical_content(
                store.get("principles", []),
            ):
                logger.warning("%s", warning)
        except (OSError, json.JSONDecodeError):
            pass

    # CLAUDE.md regenerate is best-effort; failure here doesn't roll back
    # the merged principles or the best_found ranking.
    try:
        from orchestrator.claude_md import regenerate_from_disk
        regenerate_from_disk(work_dir, campaign, iteration=iteration)
    except (OSError, RuntimeError) as exc:
        logger.warning("Failed to regenerate CLAUDE.md: %s", exc)


def _merge_principles(work_dir: Path, iter_dir: Path) -> None:
    """Merge principle_updates.json into the shared principles.json store."""
    updates_path = iter_dir / "principle_updates.json"
    if not updates_path.exists():
        return
    updates = json.loads(updates_path.read_text())
    if not updates:
        return
    if not isinstance(updates, list):
        raise RuntimeError(
            f"principle_updates.json should be a list, got {type(updates).__name__}. "
            f"Check {updates_path}"
        )
    for i, p in enumerate(updates):
        if not isinstance(p, dict) or "id" not in p:
            raise RuntimeError(f"principle_updates.json entry {i} missing 'id': {p!r:.200}")
    principles_path = work_dir / "principles.json"
    if principles_path.exists():
        store = json.loads(principles_path.read_text())
    else:
        store = {"principles": []}
    existing = {p["id"]: p for p in store["principles"]}
    for p in updates:
        existing[p["id"]] = p
    store["principles"] = list(existing.values())
    atomic_write(principles_path, json.dumps(store, indent=2) + "\n")


def setup_work_dir(run_id: str, repo_path: str | None = None) -> Path:
    """Create and initialize a working directory from templates.

    If repo_path is provided, the campaign directory is created inside
    the target repo at .nous/<run_id>/. Otherwise falls back to creating
    <run_id>/ in the current directory.

    Also writes a per-campaign ``.claude/settings.json`` permission policy
    (issue #135) so dispatchers can pass ``--settings <path>`` instead of
    ``--dangerously-skip-permissions``.
    """
    from orchestrator.settings_template import (
        render_campaign_settings,
        settings_path_for,
        write_campaign_settings,
    )

    if repo_path:
        work_dir = Path(repo_path) / ".nous" / run_id
    else:
        work_dir = Path(run_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    for t in ["state.json", "ledger.json", "principles.json"]:
        dest = work_dir / t
        if not dest.exists():
            shutil.copy(TEMPLATES_DIR / t, dest)
    state = json.loads((work_dir / "state.json").read_text())
    state["run_id"] = run_id
    atomic_write(work_dir / "state.json", json.dumps(state, indent=2) + "\n")

    # Per-campaign permission policy. Idempotent: don't overwrite a settings
    # file the user has hand-edited.
    settings_path = settings_path_for(work_dir)
    if not settings_path.exists():
        bin_dir = Path(__file__).resolve().parent.parent / "bin"
        stop_hook = bin_dir / "nous-execute-stop"
        plan_enforcer = bin_dir / "nous-plan-enforcer"
        settings = render_campaign_settings(
            work_dir=work_dir,
            repo_path=Path(repo_path) if repo_path else None,
            stop_hook_path=stop_hook if stop_hook.exists() else None,
            pre_tool_use_hook_path=plan_enforcer if plan_enforcer.exists() else None,
        )
        write_campaign_settings(settings_path, settings)

    return work_dir


def _generate_gate_summary(
    dispatcher, iter_dir: Path, iteration: int, gate_type: str,
    *, campaign: dict | None = None,
) -> Path | None:
    """Generate a gate summary file. Returns the path, or None on failure.

    When ``campaign`` is provided and contains a non-empty ``channels`` list,
    also fires off a per-channel notification (#130) with the rendered
    summary. Channel failures are logged at warning and never block the gate.
    """
    summary_path = iter_dir / f"gate_summary_{gate_type}.json"
    try:
        dispatcher.dispatch(
            "summarizer", "summarize-gate",
            output_path=summary_path,
            iteration=iteration,
            perspective=gate_type,
        )
    except (RuntimeError, FileNotFoundError, OSError) as exc:
        logger = logging.getLogger(__name__)
        logger.warning("Gate summary generation failed: %s", exc)
        print(f"  (Gate summary skipped: {exc})")
        return None

    # Channel notification (#130 Phase A): outbound only; the campaign still
    # blocks on terminal input for the actual decision.
    if campaign:
        channels = campaign.get("channels")
        if channels:
            try:
                from orchestrator.channels import notify_gate
                summary = json.loads(summary_path.read_text())
                results = notify_gate(
                    channels, summary=summary, gate_type=gate_type,
                    iter_dir=iter_dir,
                )
                ok = sum(1 for r in results if r.get("ok"))
                if ok:
                    print(f"  (notified {ok}/{len(results)} channel(s))")
            except (json.JSONDecodeError, OSError, RuntimeError) as exc:
                logger = logging.getLogger(__name__)
                logger.warning("Channel notification failed: %s", exc)

    return summary_path


def run_iteration(
    campaign: dict,
    work_dir: Path,
    iteration: int = 1,
    model: str | None = None,
    final: bool = True,
    auto_approve: bool = False,
    timeout: int = 1800,
    agent: str = "sdk",
    max_cli_retries: int | None = None,
    pre_authored_bundle: Path | None = None,
    pre_authored_problem_md: Path | None = None,
    pre_authored_handoff_md: Path | None = None,
) -> IterationOutcome:
    """Run a single iteration of the Nous loop.

    Phases: DESIGN → HUMAN_DESIGN_GATE → EXECUTE_ANALYZE → HUMAN_FINDINGS_GATE → DONE

    Args:
        final: If True (default), transitions to DONE after principle merge.
        auto_approve: If True, all human gates are automatically approved.
        agent: Dispatch backend — "sdk" (default) uses the Claude Agent SDK
            for code phases (when repo_path is set); "inline" emits prompts
            to stdout for the calling agent. The legacy "api" backend was
            removed in #183.
        max_cli_retries: Max retries for transient SDK failures (None = unbounded).

    Returns:
        An IterationOutcome value: COMPLETED, CONTINUE, ABORTED, or REDESIGN.
    """
    # #183: validate the agent value before any state inspection so the
    # migration error is the first thing legacy callers see.
    if agent == "api":
        raise ValueError(
            "agent='api' (legacy claude -p subprocess) was removed in #183. "
            "Use agent='sdk' (default) — install with `pip install nous` and "
            "the claude-agent-sdk dependency lands automatically."
        )
    if agent not in ("sdk", "inline"):
        raise ValueError(
            f"Unknown agent backend: {agent!r}. Valid values: 'sdk', 'inline'."
        )

    engine = Engine(work_dir)
    repo_path = campaign.get("target_system", {}).get("repo_path")

    # Load defaults.yaml, then overlay campaign.models
    defaults = {}
    if DEFAULTS_PATH.exists():
        defaults = yaml.safe_load(DEFAULTS_PATH.read_text()) or {}
    default_models = defaults.get("models", {})
    default_max_turns = defaults.get("max_turns", {})
    campaign_models = campaign.get("models", {})
    # #186: campaign-level max_turns overrides defaults.yaml. Schema
    # accepts an object {design, execute_analyze, report}; we read it
    # the same way as `models:`.
    campaign_max_turns = campaign.get("max_turns", {}) or {}

    def _model_for(phase_key: str) -> str:
        return campaign_models.get(phase_key) or default_models.get(phase_key) or model or "aws/claude-sonnet-4-5"

    def _max_turns_for(phase_key: str) -> int:
        # Resolution order (#186): campaign > defaults > hardcoded fallback.
        v = campaign_max_turns.get(phase_key)
        if v is not None:
            return int(v)
        v = default_max_turns.get(phase_key)
        if v is not None:
            return int(v)
        return 25

    from orchestrator.inline_dispatch import InlineDispatcher
    if agent == "inline":
        inline_dispatcher = InlineDispatcher(
            work_dir=work_dir, campaign=campaign, timeout=timeout,
        )
        cli_dispatcher = inline_dispatcher
        llm_dispatcher = inline_dispatcher
    else:
        # SDK mode: code-access dispatcher only when repo_path is set.
        from orchestrator.sdk_dispatch import SDKDispatcher
        cli_dispatcher = (
            SDKDispatcher(
                work_dir=work_dir, campaign=campaign,
                model=_model_for("design"), timeout=timeout,
                max_turns=_max_turns_for("design"),
                max_retries=max_cli_retries,
            ) if repo_path else None
        )
        llm_dispatcher = LLMDispatcher(work_dir=work_dir, campaign=campaign, model=_model_for("design"))
    gate = HumanGate(auto_response="approve") if auto_approve else HumanGate()

    iter_dir = work_dir / "runs" / f"iter-{iteration}"
    for sub in ("inputs", "results", "patches"):
        (iter_dir / sub).mkdir(parents=True, exist_ok=True)

    if engine.phase == "DONE":
        print(f"Iteration {iteration} already complete.")
        return IterationOutcome.COMPLETED

    if engine.phase != "INIT":
        print(f"\n  Resuming from {engine.phase}\n")

    # ─── DESIGN ───────────────────────────────────────────────────────────
    if _enter_phase(engine, "DESIGN"):
        print(f"\n{'='*60}")
        if pre_authored_bundle is not None:
            # #188: experiment is fully pre-specified — skip the agent
            # turn entirely. Cheaper, deterministic, and reviewer-friendly.
            print(f"  DESIGN — applying pre-authored bundle ({pre_authored_bundle})")
            print(f"{'='*60}")
            _apply_pre_authored_bundle(
                iter_dir,
                bundle_path=Path(pre_authored_bundle),
                problem_md_path=(
                    Path(pre_authored_problem_md)
                    if pre_authored_problem_md is not None else None
                ),
                handoff_md_path=(
                    Path(pre_authored_handoff_md)
                    if pre_authored_handoff_md is not None else None
                ),
                campaign=campaign,
            )
            print(f"  -> {iter_dir / 'bundle.yaml'} (pre_authored)")
            print(f"  -> {iter_dir / 'bundle_manifest.json'}")
            # Fall through to validation; required artifacts now exist.
            from orchestrator.validate import validate_design
            result = validate_design(iter_dir)
            if result["status"] == "fail":
                raise RuntimeError(
                    f"Pre-authored design artifacts failed validation:\n"
                    + "\n".join(f"  - {e}" for e in result["errors"])
                )
            print(f"  -> {iter_dir / 'problem.md'}")
            # Skip the dispatcher path below.
            _skip_design_dispatch = True
        else:
            _skip_design_dispatch = False
            print(f"  DESIGN — exploring system and creating hypothesis bundle")
            print(f"{'='*60}")
        design_dispatcher = cli_dispatcher or llm_dispatcher
        if _skip_design_dispatch:
            pass  # already finished above
        elif cli_dispatcher:
            # CLI path: agent writes files directly to iter_dir
            design_dispatcher.dispatch(
                "planner", "design",
                output_path=iter_dir / "design_log.md", iteration=iteration,
            )
        else:
            # LLM API path or stub: dispatch and check if files were written directly
            output_file = iter_dir / "design_raw.md"
            design_dispatcher.dispatch(
                "planner", "design",
                output_path=output_file, iteration=iteration,
            )
            # If the dispatcher wrote individual files (StubDispatcher),
            # skip the text split. Otherwise parse the merged output.
            if not (iter_dir / "bundle.yaml").exists():
                raw_response = output_file.read_text()
                _split_design_output(raw_response, iter_dir)
                output_file.unlink()
        # #187: surface the structured "design_incomplete" diagnostic
        # BEFORE running schema validation. When required artifacts are
        # missing, the operator needs hints (max_turns exhaustion, agent
        # ran the experiment in DESIGN, etc.), not a raw "X not found".
        missing = _missing_design_artifacts(iter_dir)
        if missing:
            from orchestrator.metrics import log_retry_event
            log_retry_event(work_dir / "llm_metrics.jsonl", {
                "iteration": iteration,
                "phase": "design",
                "failure_type": "design_incomplete",
                "missing_artifacts": missing,
                "max_turns": _max_turns_for("design"),
            })
            raise DesignIncompleteError(
                missing=missing,
                iter_dir=iter_dir,
                max_turns=_max_turns_for("design"),
            )
        # Validate design artifacts regardless of dispatch path
        from orchestrator.validate import validate_design
        result = validate_design(iter_dir)
        if result["status"] == "fail":
            raise RuntimeError(
                f"Design artifacts failed validation:\n"
                + "\n".join(f"  - {e}" for e in result["errors"])
            )
        print(f"  -> {iter_dir / 'problem.md'}")
        print(f"  -> {iter_dir / 'bundle.yaml'}")

    # ─── HUMAN DESIGN GATE ────────────────────────────────────────────────
    if _enter_phase(engine, "HUMAN_DESIGN_GATE"):
        print(f"\n{'='*60}")
        print(f"  HUMAN DESIGN GATE")
        print(f"{'='*60}")
        summary_path = _generate_gate_summary(llm_dispatcher, iter_dir, iteration, "design", campaign=campaign)
        # Issue #159: render complexity-tier panel from the bundle so tier
        # escalations are surfaced for human review (deterministic Python,
        # no LLM cost).
        try:
            from orchestrator.complexity_tier import format_tier_summary
            tier_panel = format_tier_summary(
                iteration=iteration,
                bundle_path=iter_dir / "bundle.yaml",
                work_dir=work_dir,
            )
        except (OSError, RuntimeError):
            tier_panel = None
        decision, reason = gate.prompt(
            "Review the hypothesis bundle. Approve?",
            summary_path=str(summary_path) if summary_path else None,
            files=[str(iter_dir / "bundle.yaml"), str(iter_dir / "problem.md")],
            tier_panel=tier_panel or None,
        )
        if decision == "reject":
            _save_human_feedback(iter_dir, "design", reason or "(Rejected without specific feedback)")
            print("Design rejected. Re-run after revising.")
            engine.transition("DESIGN")
            return IterationOutcome.REDESIGN
        if decision == "abort":
            print("Aborted.")
            return IterationOutcome.ABORTED

    # ─── EXECUTE + ANALYZE ────────────────────────────────────────────────
    experiment_dir = experiment_id = None
    if _enter_phase(engine, "EXECUTE_ANALYZE"):
        print(f"\n{'='*60}")
        print(f"  EXECUTE + ANALYZE — building, running, and analyzing")
        print(f"{'='*60}")
        if cli_dispatcher:
            cli_dispatcher.model = _model_for("execute_analyze")
            cli_dispatcher.max_turns = _max_turns_for("execute_analyze")
        exec_dispatcher = cli_dispatcher or llm_dispatcher
        if repo_path:
            from orchestrator.worktree import (
                create_experiment_worktree,
                remove_experiment_worktree,
            )
            experiment_dir, experiment_id = create_experiment_worktree(
                Path(repo_path), iteration,
            )
            (iter_dir / ".experiment_id").write_text(experiment_id)
            print(f"  Experiment worktree: {experiment_dir}")
        if cli_dispatcher:
            import contextlib
            ctx = cli_dispatcher.override_cwd(experiment_dir) if experiment_dir else contextlib.nullcontext()
            with ctx:
                exec_dispatcher.dispatch(
                    "executor", "execute-analyze",
                    output_path=iter_dir / "executor_log.md",
                    iteration=iteration,
                )
        else:
            output_file = iter_dir / "execute_analyze_output.json"
            exec_dispatcher.dispatch(
                "executor", "execute-analyze",
                output_path=output_file,
                iteration=iteration,
            )
            if not (iter_dir / "findings.json").exists():
                combined = json.loads(output_file.read_text())
                missing = {"plan", "findings", "principle_updates"} - set(combined.keys())
                if missing:
                    raise RuntimeError(
                        f"execute-analyze output missing keys: {sorted(missing)}"
                    )
                atomic_write(
                    iter_dir / "experiment_plan.yaml",
                    yaml.safe_dump(combined["plan"], default_flow_style=False, sort_keys=False),
                )
                atomic_write(
                    iter_dir / "findings.json",
                    json.dumps(combined["findings"], indent=2) + "\n",
                )
                atomic_write(
                    iter_dir / "principle_updates.json",
                    json.dumps(combined["principle_updates"], indent=2) + "\n",
                )
        # Validate artifacts — trust the agent, log warning on failure
        from orchestrator.validate import validate_execution
        result = validate_execution(iter_dir)
        if result["status"] == "fail":
            logger.warning(
                "Executor artifacts failed post-check validation: %s",
                result["errors"],
            )
        # Clean up worktree only on success
        if repo_path and experiment_id:
            remove_experiment_worktree(Path(repo_path), experiment_id)

    # Validate findings schema
    findings_path = iter_dir / "findings.json"
    if not findings_path.exists():
        raise RuntimeError(f"{findings_path} not found.")
    findings = json.loads(findings_path.read_text())
    findings_schema = json.loads((SCHEMAS_DIR / "findings.schema.json").read_text())
    try:
        jsonschema.validate(findings, findings_schema)
    except jsonschema.ValidationError as exc:
        raise RuntimeError(
            f"findings.json failed schema validation: {exc.message}"
        ) from exc

    # ─── HUMAN FINDINGS GATE ──────────────────────────────────────────────
    if _enter_phase(engine, "HUMAN_FINDINGS_GATE"):
        print(f"\n{'='*60}")
        print(f"  HUMAN FINDINGS GATE")
        print(f"{'='*60}")
        summary_path = _generate_gate_summary(llm_dispatcher, iter_dir, iteration, "findings", campaign=campaign)
        decision, reason = gate.prompt(
            "Review the findings. Approve?",
            summary_path=str(summary_path) if summary_path else None,
            files=[str(iter_dir / "findings.json")],
        )
        if decision == "reject":
            _save_human_feedback(iter_dir, "findings", reason or "(Rejected without specific feedback)")
            print("Findings rejected. Re-running execution.")
            engine.transition("EXECUTE_ANALYZE")
            return IterationOutcome.REDESIGN
        if decision == "abort":
            print("Aborted.")
            return IterationOutcome.ABORTED

    # ─── FINALIZE: merge principles + write best_found.json + CLAUDE.md ───
    # Issue #177: the sort_bench dry-run on 2026-05-25 surfaced that
    # update_best_found (#168) had no caller in the production path.
    # finalize_iteration is the caller. Tests drive it directly.
    finalize_iteration(
        work_dir=work_dir, iter_dir=iter_dir,
        iteration=iteration, campaign=campaign,
    )
    print(f"  -> Principles merged into {work_dir / 'principles.json'}")
    print(f"  -> best_found.json updated at {work_dir / 'best_found.json'}")

    if final:
        engine.transition("DONE")
        print(f"\n{'='*60}")
        print(f"  DONE — iteration {iteration} complete")
        print(f"{'='*60}")
        print(f"\nOutput in: {iter_dir}")
        print(f"Principles: {work_dir / 'principles.json'}")
        return IterationOutcome.COMPLETED
    else:
        print(f"\n  Iteration {iteration} complete — ready for next iteration.")
        return IterationOutcome.CONTINUE


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a single Nous iteration.",
        epilog="Example: python run_iteration.py examples/campaign.yaml",
    )
    parser.add_argument("campaign", help="Path to campaign.yaml")
    parser.add_argument("--model", default=None,
                        help="Fallback model name (default: from defaults.yaml)")
    parser.add_argument("--run-id", default=None,
                        help="Working directory name (default: derived from campaign)")
    parser.add_argument("--auto-approve", action="store_true",
                        help="Auto-approve all human gates (skip interactive prompts)")
    parser.add_argument("--timeout", type=int, default=1800,
                        help="Timeout in seconds for claude -p calls (default: 1800)")
    parser.add_argument("--max-cli-retries", type=int, default=10,
                        help="Max retries for claude -p failures (-1 = unbounded, default: 10)")
    parser.add_argument("--agent", choices=["inline", "sdk"], default="sdk",
                        help="Dispatch backend: 'sdk' (default) uses the Claude "
                             "Agent SDK for code phases; 'inline' emits prompts "
                             "to stdout for the calling agent.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    campaign_path = Path(args.campaign)
    if not campaign_path.exists():
        print(f"Error: {campaign_path} not found", file=sys.stderr)
        sys.exit(1)

    campaign = yaml.safe_load(campaign_path.read_text())

    schema = yaml.safe_load((SCHEMAS_DIR / "campaign.schema.yaml").read_text())
    try:
        jsonschema.validate(campaign, schema)
    except jsonschema.ValidationError as exc:
        print(
            f"Error: {campaign_path} is not a valid campaign config.\n"
            f"  {exc.message}\n\n"
            f"See examples/campaign.yaml for a working example.",
            file=sys.stderr,
        )
        sys.exit(1)

    run_id = args.run_id or campaign.get("run_id") or campaign_path.parent.name + "-run"
    repo_path = campaign.get("target_system", {}).get("repo_path")
    work_dir = setup_work_dir(run_id, repo_path=repo_path)
    print(f"Working directory: {work_dir.resolve()}")

    run_iteration(
        campaign, work_dir, model=args.model,
        auto_approve=args.auto_approve, timeout=args.timeout,
        agent=args.agent,
        max_cli_retries=None if args.max_cli_retries == -1 else args.max_cli_retries,
    )


if __name__ == "__main__":
    main()
