#!/usr/bin/env python3
"""Run a single Nous iteration.

Usage:
    python run_iteration.py examples/campaign.yaml

Creates a working directory named after the target system, copies templates,
and runs one full iteration with human gates for approval.

Set your LLM API key before running:
    export OPENAI_API_KEY=sk-...
    (or set OPENAI_BASE_URL for a proxy endpoint)
"""
import argparse
import json
import logging
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
from enum import Enum
from pathlib import Path

import jsonschema
import yaml

from orchestrator.engine import Engine
from orchestrator.fastfail import check_fast_fail, FastFailAction
from orchestrator.gates import HumanGate
from orchestrator.llm_dispatch import LLMDispatcher
from orchestrator.util import atomic_write


class IterationOutcome(str, Enum):
    """Outcome of a single iteration — used by run_campaign to decide next step."""
    COMPLETED = "COMPLETED"    # Final iteration, transitioned to DONE
    CONTINUE = "CONTINUE"      # Non-final iteration, stopped at EXTRACTION
    ABORTED = "ABORTED"        # Human aborted at a gate
    REDESIGN = "REDESIGN"      # Control-negative refuted, needs redesign

TEMPLATES_DIR = Path(__file__).parent / "templates"
SCHEMAS_DIR = Path(__file__).parent / "schemas"
DEFAULTS_PATH = Path(__file__).parent / "defaults.yaml"
_ARM_TYPE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# Phase ordering for resume logic
_PHASE_ORDER = [
    "INIT", "FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
    "PLAN_EXECUTION", "EXECUTING", "ANALYSIS",
    "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE", "TUNING",
    "EXTRACTION", "DONE",
]
_PHASE_INDEX = {p: i for i, p in enumerate(_PHASE_ORDER)}


def _enter_phase(engine, phase):
    """Transition to phase if needed. Returns True if phase work should run.

    Handles resume by skipping already-completed phases:
    - Past this phase: return False (skip)
    - At this phase: return True (redo work, no transition needed)
    - Before this phase: transition and return True
    """
    current_idx = _PHASE_INDEX[engine.phase]
    target_idx = _PHASE_INDEX[phase]
    if current_idx > target_idx:
        return False
    if engine.phase != phase:
        engine.transition(phase)
    return True


def setup_work_dir(run_id: str) -> Path:
    """Create and initialize a working directory from templates."""
    work_dir = Path(run_id)
    work_dir.mkdir(exist_ok=True)
    for t in ["state.json", "ledger.json", "principles.json"]:
        dest = work_dir / t
        if not dest.exists():
            shutil.copy(TEMPLATES_DIR / t, dest)
    state = json.loads((work_dir / "state.json").read_text())
    state["run_id"] = run_id
    atomic_write(work_dir / "state.json", json.dumps(state, indent=2) + "\n")
    return work_dir


def _generate_gate_summary(
    dispatcher, iter_dir: Path, iteration: int, gate_type: str,
) -> Path | None:
    """Generate a gate summary file. Returns the path, or None on failure."""
    summary_path = iter_dir / f"gate_summary_{gate_type}.json"
    try:
        dispatcher.dispatch(
            "summarizer", "summarize-gate",
            output_path=summary_path,
            iteration=iteration,
            perspective=gate_type,
        )
        return summary_path
    except (RuntimeError, FileNotFoundError, OSError) as exc:
        logger = logging.getLogger(__name__)
        logger.warning("Gate summary generation failed: %s", exc)
        return None


def run_iteration(
    campaign: dict,
    work_dir: Path,
    iteration: int = 1,
    model: str | None = None,
    final: bool = True,
    auto_approve: bool = False,
    timeout: int = 1800,
) -> IterationOutcome:
    """Run a single iteration of the Nous loop.

    Args:
        final: If True (default), transitions to DONE after extraction.
            If False, stops at EXTRACTION so run_campaign can continue
            with the next iteration.
        auto_approve: If True, all human gates are automatically approved.

    Returns:
        An IterationOutcome value: COMPLETED, CONTINUE, ABORTED, or REDESIGN.

    Supports resume: if the process crashes, re-running picks up from the
    last committed phase in state.json. Phases already completed are skipped.
    """
    engine = Engine(work_dir)
    repo_path = campaign.get("target_system", {}).get("repo_path")
    skip_reviews = campaign.get("skip_reviews", False)

    # Load defaults.yaml, then overlay campaign.models
    defaults = {}
    if DEFAULTS_PATH.exists():
        defaults = yaml.safe_load(DEFAULTS_PATH.read_text()) or {}
    default_models = defaults.get("models", {})
    default_max_turns = defaults.get("max_turns", {})
    campaign_models = campaign.get("models", {})

    def _model_for(phase_key: str) -> str:
        """Resolve model: campaign.models > defaults.yaml > --model flag."""
        return campaign_models.get(phase_key) or default_models.get(phase_key) or model or "aws/claude-sonnet-4-5"

    def _max_turns_for(phase_key: str) -> int:
        return default_max_turns.get(phase_key, 25)

    # CLIDispatcher for code-access roles (framing, execution); LLMDispatcher for everything else
    from orchestrator.cli_dispatch import CLIDispatcher
    cli_dispatcher = (
        CLIDispatcher(
            work_dir=work_dir, campaign=campaign,
            model=_model_for("framing"), timeout=timeout,
            max_turns=_max_turns_for("framing"),
        ) if repo_path else None
    )
    llm_dispatcher = LLMDispatcher(work_dir=work_dir, campaign=campaign, model=_model_for("design"))
    gate = HumanGate(auto_response="approve") if auto_approve else HumanGate()

    iter_dir = work_dir / "runs" / f"iter-{iteration}"

    if engine.phase == "DONE":
        print(f"Iteration {iteration} already complete.")
        return IterationOutcome.COMPLETED

    if engine.phase != "INIT":
        print(f"\n  Resuming from {engine.phase}\n")

    # FRAMING — uses CLI dispatcher if available (needs code access to discover metrics/knobs)
    if _enter_phase(engine, "FRAMING"):
        print(f"\n{'='*60}")
        print(f"  FRAMING — defining the problem")
        print(f"{'='*60}")
        frame_dispatcher = cli_dispatcher or llm_dispatcher
        frame_dispatcher.dispatch(
            "planner", "frame",
            output_path=iter_dir / "problem.md", iteration=iteration,
        )
        print(f"  -> {iter_dir / 'problem.md'}")

    # DESIGN — always LLM API (no code access needed, uses framing output)
    if _enter_phase(engine, "DESIGN"):
        print(f"\n{'='*60}")
        print(f"  DESIGN — creating hypothesis bundle")
        print(f"{'='*60}")
        llm_dispatcher.dispatch(
            "planner", "design",
            output_path=iter_dir / "bundle.yaml", iteration=iteration,
        )
        print(f"  -> {iter_dir / 'bundle.yaml'}")

    # DESIGN REVIEW
    if _enter_phase(engine, "DESIGN_REVIEW") and not skip_reviews:
        print(f"\n{'='*60}")
        print(f"  DESIGN REVIEW — {len(campaign['review']['design_perspectives'])} reviewers")
        print(f"{'='*60}")
        perspectives = campaign["review"]["design_perspectives"]
        def _run_design_review(p):
            llm_dispatcher.dispatch(
                "reviewer", "review-design",
                output_path=iter_dir / "reviews" / f"review-{p}.md",
                iteration=iteration, perspective=p,
            )
            return p
        with ThreadPoolExecutor(max_workers=len(perspectives)) as pool:
            futures = [pool.submit(_run_design_review, p) for p in perspectives]
            for f in as_completed(futures):
                print(f"  -> review-{f.result()}.md")

    # HUMAN DESIGN GATE
    if _enter_phase(engine, "HUMAN_DESIGN_GATE"):
        print(f"\n{'='*60}")
        print(f"  HUMAN DESIGN GATE")
        print(f"{'='*60}")
        summary_path = _generate_gate_summary(llm_dispatcher, iter_dir, iteration, "design")
        decision = gate.prompt(
            "Review the hypothesis bundle and reviews. Approve?",
            artifact_path=str(iter_dir / "bundle.yaml"),
            reviews=[str(p) for p in sorted((iter_dir / "reviews").glob("review-*.md"))],
            summary_path=str(summary_path) if summary_path else None,
        )
        if decision == "reject":
            print("Design rejected. Re-run after revising the campaign config.")
            engine.transition("DESIGN")
            return IterationOutcome.REDESIGN
        if decision == "abort":
            print("Aborted.")
            return IterationOutcome.ABORTED

    # PLAN_EXECUTION — executor (claude -p) produces experiment_plan.yaml
    experiment_dir = experiment_id = None
    if _enter_phase(engine, "PLAN_EXECUTION"):
        print(f"\n{'='*60}")
        print(f"  PLAN_EXECUTION — designing experiment commands")
        print(f"{'='*60}")
        # Use per-phase model + turn limit for plan execution
        if cli_dispatcher:
            cli_dispatcher.model = _model_for("plan_execution")
            cli_dispatcher.max_turns = _max_turns_for("plan_execution")
        plan_dispatcher = cli_dispatcher or llm_dispatcher
        try:
            if repo_path:
                from orchestrator.worktree import (
                    create_experiment_worktree,
                    remove_experiment_worktree,
                )
                experiment_dir, experiment_id = create_experiment_worktree(
                    Path(repo_path), iteration,
                )
                # Persist for resume
                (iter_dir / ".experiment_id").write_text(experiment_id)
                print(f"  Experiment worktree: {experiment_dir}")
            if experiment_dir and cli_dispatcher:
                with cli_dispatcher.override_cwd(experiment_dir):
                    plan_dispatcher.dispatch(
                        "executor", "plan-execution",
                        output_path=iter_dir / "experiment_plan.yaml",
                        iteration=iteration,
                    )
            else:
                plan_dispatcher.dispatch(
                    "executor", "plan-execution",
                    output_path=iter_dir / "experiment_plan.yaml",
                    iteration=iteration,
                )
            print(f"  -> {iter_dir / 'experiment_plan.yaml'}")
        except BaseException:
            if repo_path and experiment_id:
                from orchestrator.worktree import remove_experiment_worktree
                remove_experiment_worktree(Path(repo_path), experiment_id)
            raise

    # EXECUTING — orchestrator runs commands from plan (no LLM)
    if _enter_phase(engine, "EXECUTING"):
        print(f"\n{'='*60}")
        print(f"  EXECUTING — running experiment commands")
        print(f"{'='*60}")
        # Recover worktree reference on resume
        if not experiment_dir and repo_path:
            eid_path = iter_dir / ".experiment_id"
            if eid_path.exists():
                experiment_id = eid_path.read_text().strip()
                experiment_dir = Path(repo_path) / ".nous-experiments" / experiment_id

        revision_fn = None
        if cli_dispatcher and experiment_dir:
            def _revise(plan, error_info):
                with cli_dispatcher.override_cwd(experiment_dir):
                    return cli_dispatcher.revise_plan(plan, error_info)
            revision_fn = _revise

        try:
            from orchestrator.executor import execute_plan
            plan = yaml.safe_load((iter_dir / "experiment_plan.yaml").read_text())
            execute_plan(
                plan,
                cwd=experiment_dir or Path(repo_path) if repo_path else iter_dir,
                iter_dir=iter_dir,
                revision_fn=revision_fn,
            )
            print(f"  -> {iter_dir / 'execution_results.json'}")
        finally:
            if repo_path and experiment_id:
                from orchestrator.worktree import remove_experiment_worktree
                remove_experiment_worktree(Path(repo_path), experiment_id)

    # ANALYSIS — LLM API compares observed metrics vs predictions
    if _enter_phase(engine, "ANALYSIS"):
        print(f"\n{'='*60}")
        print(f"  ANALYSIS — comparing results to predictions")
        print(f"{'='*60}")
        llm_dispatcher.dispatch(
            "executor", "analyze",
            output_path=iter_dir / "findings.json", iteration=iteration,
        )
        print(f"  -> {iter_dir / 'findings.json'}")

    # Validate findings against schema, then check fast-fail rules
    findings_path = iter_dir / "findings.json"
    if not findings_path.exists():
        raise RuntimeError(
            f"{findings_path} not found. "
            f"The ANALYSIS phase may have failed to produce findings."
        )
    findings = json.loads(findings_path.read_text())
    findings_schema = json.loads((SCHEMAS_DIR / "findings.schema.json").read_text())
    try:
        jsonschema.validate(findings, findings_schema)
    except jsonschema.ValidationError as exc:
        raise RuntimeError(
            f"findings.json failed schema validation: {exc.message}"
        ) from exc
    ff = check_fast_fail(findings)
    if ff == FastFailAction.SKIP_TO_EXTRACTION:
        print("  ** H-main REFUTED — skipping to extraction")
        _enter_phase(engine, "FINDINGS_REVIEW")
        _enter_phase(engine, "HUMAN_FINDINGS_GATE")
        _enter_phase(engine, "EXTRACTION")
    elif ff == FastFailAction.REDESIGN:
        print("  ** Control-negative REFUTED — mechanism confounded.")
        print("     The experiment needs redesign. Re-run after revising the campaign.")
        _enter_phase(engine, "FINDINGS_REVIEW")
        _enter_phase(engine, "HUMAN_FINDINGS_GATE")
        engine.transition("PLAN_EXECUTION")
        return IterationOutcome.REDESIGN
    else:
        if ff == FastFailAction.SIMPLIFY:
            print("  ** Dominant component >80% — consider simplifying the model.")
            print("     Proceeding to findings review with this note.")

        # FINDINGS REVIEW (runs for both SIMPLIFY and CONTINUE)
        if _enter_phase(engine, "FINDINGS_REVIEW") and not skip_reviews:
            print(f"\n{'='*60}")
            print(f"  FINDINGS REVIEW — {len(campaign['review']['findings_perspectives'])} reviewers")
            print(f"{'='*60}")
            perspectives = campaign["review"]["findings_perspectives"]
            def _run_findings_review(p):
                llm_dispatcher.dispatch(
                    "reviewer", "review-findings",
                    output_path=iter_dir / "reviews" / f"review-findings-{p}.md",
                    iteration=iteration, perspective=p,
                )
                return p
            with ThreadPoolExecutor(max_workers=len(perspectives)) as pool:
                futures = [pool.submit(_run_findings_review, p) for p in perspectives]
                for f in as_completed(futures):
                    print(f"  -> review-findings-{f.result()}.md")

        # HUMAN FINDINGS GATE
        if _enter_phase(engine, "HUMAN_FINDINGS_GATE"):
            print(f"\n{'='*60}")
            print(f"  HUMAN FINDINGS GATE")
            print(f"{'='*60}")
            summary_path = _generate_gate_summary(llm_dispatcher, iter_dir, iteration, "findings")
            decision = gate.prompt(
                "Review the findings and reviews. Approve?",
                summary_path=str(summary_path) if summary_path else None,
            )
            if decision == "reject":
                print("Findings rejected. Re-running executor.")
                engine.transition("PLAN_EXECUTION")
                return IterationOutcome.REDESIGN
            if decision == "abort":
                print("Aborted.")
                return IterationOutcome.ABORTED

        _enter_phase(engine, "TUNING")
        _enter_phase(engine, "EXTRACTION")

    # EXTRACTION
    print(f"\n{'='*60}")
    print(f"  EXTRACTION — extracting principles")
    print(f"{'='*60}")
    llm_dispatcher.dispatch(
        "extractor", "extract",
        output_path=work_dir / "principles.json", iteration=iteration,
    )
    print(f"  -> {work_dir / 'principles.json'}")

    if final:
        engine.transition("DONE")
        print(f"\n{'='*60}")
        print(f"  DONE — iteration {iteration} complete")
        print(f"{'='*60}")
        print(f"\nOutput in: {iter_dir}")
        print(f"Principles: {work_dir / 'principles.json'}")
        return IterationOutcome.COMPLETED
    else:
        print(f"\n  Iteration {iteration} extraction complete — ready for next iteration.")
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

    # Validate campaign against schema for early, clear error messages
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
    work_dir = setup_work_dir(run_id)
    print(f"Working directory: {work_dir.resolve()}")

    run_iteration(
        campaign, work_dir, model=args.model,
        auto_approve=args.auto_approve, timeout=args.timeout,
    )


if __name__ == "__main__":
    main()
