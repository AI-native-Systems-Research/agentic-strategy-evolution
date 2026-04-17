#!/usr/bin/env python3
"""Run a single Nous iteration.

Usage:
    python run_iteration.py examples/blis/campaign.yaml

Creates a working directory named after the target system, copies templates,
and runs one full iteration with human gates for approval.

Set your LLM API key before running:
    export ANTHROPIC_API_KEY=sk-...
    export OPENAI_API_KEY=sk-...
    (or any LiteLLM-supported provider)
"""
import argparse
import json
import logging
import shutil
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


def run_iteration(
    campaign: dict,
    work_dir: Path,
    iteration: int = 1,
    model: str = "aws/claude-opus-4-6",
) -> None:
    """Run a single iteration of the Nous loop."""
    engine = Engine(work_dir)
    dispatcher = LLMDispatcher(work_dir=work_dir, campaign=campaign, model=model)
    gate = HumanGate()

    iter_dir = work_dir / "runs" / f"iter-{iteration}"

    # FRAMING
    print(f"\n{'='*60}")
    print(f"  FRAMING — defining the problem")
    print(f"{'='*60}")
    engine.transition("FRAMING")
    dispatcher.dispatch(
        "planner", "frame",
        output_path=iter_dir / "problem.md", iteration=iteration,
    )
    print(f"  -> {iter_dir / 'problem.md'}")

    # DESIGN
    print(f"\n{'='*60}")
    print(f"  DESIGN — creating hypothesis bundle")
    print(f"{'='*60}")
    engine.transition("DESIGN")
    dispatcher.dispatch(
        "planner", "design",
        output_path=iter_dir / "bundle.yaml", iteration=iteration,
    )
    print(f"  -> {iter_dir / 'bundle.yaml'}")

    # DESIGN REVIEW
    print(f"\n{'='*60}")
    print(f"  DESIGN REVIEW — {len(campaign['review']['design_perspectives'])} reviewers")
    print(f"{'='*60}")
    engine.transition("DESIGN_REVIEW")
    for perspective in campaign["review"]["design_perspectives"]:
        dispatcher.dispatch(
            "reviewer", "review-design",
            output_path=iter_dir / "reviews" / f"review-{perspective}.md",
            iteration=iteration, perspective=perspective,
        )
        print(f"  -> review-{perspective}.md")

    # HUMAN DESIGN GATE
    print(f"\n{'='*60}")
    print(f"  HUMAN DESIGN GATE")
    print(f"{'='*60}")
    engine.transition("HUMAN_DESIGN_GATE")
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
    print(f"\n{'='*60}")
    print(f"  RUNNING — executor analyzing the system")
    print(f"{'='*60}")
    engine.transition("RUNNING")
    dispatcher.dispatch(
        "executor", "run",
        output_path=iter_dir / "findings.json", iteration=iteration,
    )
    print(f"  -> {iter_dir / 'findings.json'}")

    # Fast-fail check
    findings = json.loads((iter_dir / "findings.json").read_text())
    ff = check_fast_fail(findings)
    if ff == FastFailAction.SKIP_TO_EXTRACTION:
        print("  ** H-main REFUTED — skipping to extraction")
        # Advance state machine through required intermediate states
        # (no human prompt — fast-fail overrides the gate)
        engine.transition("FINDINGS_REVIEW")
        engine.transition("HUMAN_FINDINGS_GATE")
        engine.transition("EXTRACTION")
    elif ff == FastFailAction.REDESIGN:
        print("  ** Control-negative REFUTED — mechanism confounded.")
        print("     The experiment needs redesign. Re-run after revising the campaign.")
        # Advance to RUNNING so the next run can re-execute
        engine.transition("FINDINGS_REVIEW")
        engine.transition("HUMAN_FINDINGS_GATE")
        engine.transition("RUNNING")
        return
    else:
        # FINDINGS REVIEW
        print(f"\n{'='*60}")
        print(f"  FINDINGS REVIEW — {len(campaign['review']['findings_perspectives'])} reviewers")
        print(f"{'='*60}")
        engine.transition("FINDINGS_REVIEW")
        for perspective in campaign["review"]["findings_perspectives"]:
            dispatcher.dispatch(
                "reviewer", "review-findings",
                output_path=iter_dir / "reviews" / f"review-findings-{perspective}.md",
                iteration=iteration, perspective=perspective,
            )
            print(f"  -> review-findings-{perspective}.md")

        # HUMAN FINDINGS GATE
        print(f"\n{'='*60}")
        print(f"  HUMAN FINDINGS GATE")
        print(f"{'='*60}")
        engine.transition("HUMAN_FINDINGS_GATE")
        decision = gate.prompt("Review the findings and reviews. Approve?")
        if decision == "reject":
            print("Findings rejected. Re-running executor.")
            engine.transition("RUNNING")
            return
        if decision == "abort":
            print("Aborted.")
            return

        # TUNING -> EXTRACTION
        engine.transition("TUNING")
        engine.transition("EXTRACTION")

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
                        help="LiteLLM model string (default: aws/claude-opus-4-6)")
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
