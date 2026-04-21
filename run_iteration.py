#!/usr/bin/env python3
"""Run a single Nous iteration.

Usage:
    python run_iteration.py examples/blis/campaign.yaml

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
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import jsonschema
import yaml

from orchestrator.engine import Engine
from orchestrator.fastfail import check_fast_fail, FastFailAction
from orchestrator.gates import HumanGate
from orchestrator.llm_dispatch import LLMDispatcher
from orchestrator.util import atomic_write

TEMPLATES_DIR = Path(__file__).parent / "templates"
SCHEMAS_DIR = Path(__file__).parent / "schemas"

# Phase ordering for resume logic
_PHASE_ORDER = [
    "INIT", "FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
    "RUNNING", "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE", "TUNING",
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


def _run_single_command(
    cmd: str, *, work_dir: Path, timeout: int, label: str,
) -> None:
    """Run a single shell command. Raises RuntimeError on failure."""
    args = shlex.split(cmd)
    print(f"    [{label}] Running: {cmd}")
    try:
        result = subprocess.run(
            args, cwd=work_dir, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Command timed out after {timeout}s for arm '{label}': {cmd}"
        )
    if result.returncode != 0:
        stderr_tail = result.stderr[-2000:] if result.stderr else "(no stderr)"
        raise RuntimeError(
            f"Command failed (exit {result.returncode}) for arm '{label}': {cmd}\n"
            f"stderr: {stderr_tail}"
        )
    print(f"    [{label}] Completed (exit 0)")


def _read_metrics(path: Path, *, label: str) -> dict:
    """Read and validate a metrics JSON file."""
    if not path.exists():
        raise RuntimeError(
            f"Metrics file not found for arm '{label}': {path}. "
            f"The simulator may have crashed before writing output."
        )
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Metrics file for arm '{label}' contains invalid JSON: {path}. "
            f"Error: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError(
            f"Metrics file for arm '{label}' must contain a JSON object, "
            f"got {type(data).__name__}: {path}"
        )
    return data


def run_experiment_commands(
    plan: dict,
    *,
    work_dir: Path,
    iter_dir: Path,
    timeout: int = 300,
    allowed_executable: str | None = None,
) -> dict:
    """Execute experiment commands from the plan and collect metrics.

    Args:
        allowed_executable: If set, every command must start with this
            executable (derived from campaign run_command). Prevents the
            LLM from generating commands that run arbitrary binaries.

    Returns dict with metrics keyed by label: {"baseline": {...}, "h-main": {...}, ...}
    """
    metrics_dir = iter_dir / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    # Validate all commands before executing any
    all_entries = [("baseline", plan["baseline"])] + [
        (e["arm_type"], e) for e in plan["experiments"]
    ]
    for label, entry in all_entries:
        cmd = entry["command"]
        if "{metrics_path}" not in cmd:
            raise RuntimeError(
                f"Experiment command for '{label}' missing {{metrics_path}} placeholder. "
                f"Command: {cmd}"
            )
        if allowed_executable:
            actual = shlex.split(cmd)[0]
            if actual != allowed_executable:
                raise RuntimeError(
                    f"Experiment command for '{label}' uses executable '{actual}' "
                    f"but campaign run_command uses '{allowed_executable}'. "
                    f"Commands must be based on the campaign's run_command template."
                )

    # Run baseline
    baseline_metrics_path = metrics_dir / "baseline.json"
    cmd = plan["baseline"]["command"].replace("{metrics_path}", str(baseline_metrics_path))
    _run_single_command(cmd, work_dir=work_dir, timeout=timeout, label="baseline")
    results["baseline"] = _read_metrics(baseline_metrics_path, label="baseline")

    # Run each arm
    _ARM_TYPE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
    for exp in plan["experiments"]:
        arm = exp["arm_type"]
        if not _ARM_TYPE_RE.match(arm):
            raise RuntimeError(f"Invalid arm_type '{arm}': must match [a-zA-Z0-9_-]+")
        arm_metrics_path = metrics_dir / f"{arm}.json"
        cmd = exp["command"].replace("{metrics_path}", str(arm_metrics_path))
        _run_single_command(cmd, work_dir=work_dir, timeout=timeout, label=arm)
        results[arm] = _read_metrics(arm_metrics_path, label=arm)

    return results


def run_iteration(
    campaign: dict,
    work_dir: Path,
    iteration: int = 1,
    model: str = "aws/claude-opus-4-6",
) -> None:
    """Run a single iteration of the Nous loop.

    Supports resume: if the process crashes, re-running picks up from the
    last committed phase in state.json. Phases already completed are skipped.
    """
    engine = Engine(work_dir)
    dispatcher = LLMDispatcher(work_dir=work_dir, campaign=campaign, model=model)
    gate = HumanGate()

    iter_dir = work_dir / "runs" / f"iter-{iteration}"

    if engine.phase == "DONE":
        print(f"Iteration {iteration} already complete.")
        return

    if engine.phase != "INIT":
        print(f"\n  Resuming from {engine.phase}\n")

    # FRAMING
    if _enter_phase(engine, "FRAMING"):
        print(f"\n{'='*60}")
        print(f"  FRAMING — defining the problem")
        print(f"{'='*60}")
        dispatcher.dispatch(
            "planner", "frame",
            output_path=iter_dir / "problem.md", iteration=iteration,
        )
        print(f"  -> {iter_dir / 'problem.md'}")

    # DESIGN
    if _enter_phase(engine, "DESIGN"):
        print(f"\n{'='*60}")
        print(f"  DESIGN — creating hypothesis bundle")
        print(f"{'='*60}")
        dispatcher.dispatch(
            "planner", "design",
            output_path=iter_dir / "bundle.yaml", iteration=iteration,
        )
        print(f"  -> {iter_dir / 'bundle.yaml'}")

    # DESIGN REVIEW
    if _enter_phase(engine, "DESIGN_REVIEW"):
        print(f"\n{'='*60}")
        print(f"  DESIGN REVIEW — {len(campaign['review']['design_perspectives'])} reviewers")
        print(f"{'='*60}")
        for perspective in campaign["review"]["design_perspectives"]:
            dispatcher.dispatch(
                "reviewer", "review-design",
                output_path=iter_dir / "reviews" / f"review-{perspective}.md",
                iteration=iteration, perspective=perspective,
            )
            print(f"  -> review-{perspective}.md")

    # HUMAN DESIGN GATE
    if _enter_phase(engine, "HUMAN_DESIGN_GATE"):
        print(f"\n{'='*60}")
        print(f"  HUMAN DESIGN GATE")
        print(f"{'='*60}")
        decision = gate.prompt(
            "Review the hypothesis bundle and reviews. Approve?",
            artifact_path=str(iter_dir / "bundle.yaml"),
            reviews=[str(p) for p in sorted((iter_dir / "reviews").glob("review-*.md"))],
        )
        if decision == "reject":
            print("Design rejected. Re-run after revising the campaign config.")
            engine.transition("DESIGN")
            return
        if decision == "abort":
            print("Aborted.")
            return

    # RUNNING (executor)
    if _enter_phase(engine, "RUNNING"):
        execution = campaign["target_system"].get("execution")
        if execution and execution.get("run_command"):
            # Real execution mode
            print(f"\n{'='*60}")
            print(f"  RUNNING — real experiment execution")
            print(f"{'='*60}")

            repo_path = execution.get("repo_path")
            timeout = execution.get("timeout", 300)
            experiment_dir = None
            experiment_id = None

            try:
                # Create worktree if repo_path is set
                if repo_path:
                    from orchestrator.worktree import (
                        create_experiment_worktree,
                        remove_experiment_worktree,
                    )
                    experiment_dir, experiment_id = create_experiment_worktree(
                        Path(repo_path), iteration,
                    )
                    cmd_work_dir = experiment_dir
                    print(f"  Experiment worktree: {experiment_dir}")
                else:
                    cmd_work_dir = Path(".")

                # Run setup commands
                for cmd in execution.get("setup_commands", []):
                    _run_single_command(
                        cmd, work_dir=cmd_work_dir, timeout=timeout, label="setup",
                    )

                # Step 1: LLM designs experiment commands
                dispatcher.dispatch(
                    "executor", "run-plan",
                    output_path=iter_dir / "experiment_plan.json",
                    iteration=iteration,
                )
                plan = json.loads((iter_dir / "experiment_plan.json").read_text())
                print(f"  -> {iter_dir / 'experiment_plan.json'}")

                # Step 2: Run commands, collect metrics
                run_cmd_template = execution.get("run_command", "")
                expected_exe = shlex.split(run_cmd_template)[0] if run_cmd_template else None
                metrics_results = run_experiment_commands(
                    plan,
                    work_dir=cmd_work_dir,
                    iter_dir=iter_dir,
                    timeout=timeout,
                    allowed_executable=expected_exe,
                )

                # Write results to disk for the analyze phase to read
                atomic_write(
                    iter_dir / "experiment_results.json",
                    json.dumps(metrics_results, indent=2) + "\n",
                )
                print(f"  -> {iter_dir / 'experiment_results.json'}")

                # Run cleanup commands
                for cmd in execution.get("cleanup_commands", []):
                    _run_single_command(
                        cmd, work_dir=cmd_work_dir, timeout=timeout, label="cleanup",
                    )

                # Step 3: LLM analyzes real metrics, produces findings
                dispatcher.dispatch(
                    "executor", "run-analyze",
                    output_path=iter_dir / "findings.json",
                    iteration=iteration,
                )
                print(f"  -> {iter_dir / 'findings.json'}")

            finally:
                # Clean up worktree
                if repo_path and experiment_id:
                    from orchestrator.worktree import remove_experiment_worktree
                    remove_experiment_worktree(Path(repo_path), experiment_id)
        else:
            # Analysis mode (no execution config)
            print(f"\n{'='*60}")
            print(f"  RUNNING — analysis mode (no execution config)")
            print(f"{'='*60}")
            dispatcher.dispatch(
                "executor", "run",
                output_path=iter_dir / "findings.json", iteration=iteration,
            )
            print(f"  -> {iter_dir / 'findings.json'}")

    # Validate findings against schema, then check fast-fail rules
    findings = json.loads((iter_dir / "findings.json").read_text())
    findings_schema = json.loads((SCHEMAS_DIR / "findings.schema.json").read_text())
    try:
        jsonschema.validate(findings, findings_schema)
    except jsonschema.ValidationError as exc:
        print(
            f"Error: findings.json failed schema validation: {exc.message}",
            file=sys.stderr,
        )
        sys.exit(1)
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
        engine.transition("RUNNING")
        return
    else:
        if ff == FastFailAction.SIMPLIFY:
            print("  ** Dominant component >80% — consider simplifying the model.")
            print("     Proceeding to findings review with this note.")

        # FINDINGS REVIEW (runs for both SIMPLIFY and CONTINUE)
        if _enter_phase(engine, "FINDINGS_REVIEW"):
            print(f"\n{'='*60}")
            print(f"  FINDINGS REVIEW — {len(campaign['review']['findings_perspectives'])} reviewers")
            print(f"{'='*60}")
            for perspective in campaign["review"]["findings_perspectives"]:
                dispatcher.dispatch(
                    "reviewer", "review-findings",
                    output_path=iter_dir / "reviews" / f"review-findings-{perspective}.md",
                    iteration=iteration, perspective=perspective,
                )
                print(f"  -> review-findings-{perspective}.md")

        # HUMAN FINDINGS GATE
        if _enter_phase(engine, "HUMAN_FINDINGS_GATE"):
            print(f"\n{'='*60}")
            print(f"  HUMAN FINDINGS GATE")
            print(f"{'='*60}")
            decision = gate.prompt("Review the findings and reviews. Approve?")
            if decision == "reject":
                print("Findings rejected. Re-running executor.")
                engine.transition("RUNNING")
                return
            if decision == "abort":
                print("Aborted.")
                return

        _enter_phase(engine, "TUNING")
        _enter_phase(engine, "EXTRACTION")

    # EXTRACTION
    print(f"\n{'='*60}")
    print(f"  EXTRACTION — extracting principles")
    print(f"{'='*60}")
    dispatcher.dispatch(
        "extractor", "extract",
        output_path=work_dir / "principles.json", iteration=iteration,
    )
    print(f"  -> {work_dir / 'principles.json'}")

    # DONE
    engine.transition("DONE")
    print(f"\n{'='*60}")
    print(f"  DONE — iteration {iteration} complete")
    print(f"{'='*60}")
    print(f"\nOutput in: {iter_dir}")
    print(f"Principles: {work_dir / 'principles.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a single Nous iteration.",
        epilog="Example: python run_iteration.py examples/blis/campaign.yaml",
    )
    parser.add_argument("campaign", help="Path to campaign.yaml")
    parser.add_argument("--model", default="aws/claude-opus-4-6",
                        help="Model name (default: aws/claude-opus-4-6)")
    parser.add_argument("--run-id", default=None,
                        help="Working directory name (default: derived from campaign)")
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
            f"See examples/blis/campaign.yaml for a working example.",
            file=sys.stderr,
        )
        sys.exit(1)

    run_id = args.run_id or campaign_path.parent.name + "-run"
    work_dir = setup_work_dir(run_id)
    print(f"Working directory: {work_dir.resolve()}")

    run_iteration(campaign, work_dir, model=args.model)


if __name__ == "__main__":
    main()
