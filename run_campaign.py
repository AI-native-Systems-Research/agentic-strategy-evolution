#!/usr/bin/env python3
"""Run a multi-iteration Nous campaign.

Usage:
    python run_campaign.py examples/blis/campaign.yaml --max-iterations 5

Runs iterations in a loop: each iteration runs the full Nous loop
(FRAMING → DESIGN → REVIEW → RUNNING → EXTRACTION), then appends a
ledger row, generates an investigation summary, and prompts whether to
continue.  The investigation summary is injected into the next iteration's
design prompt so that each hypothesis bundle is informed by all prior learning.

Set your LLM API key before running:
    export OPENAI_API_KEY=sk-...
    (or set OPENAI_BASE_URL for a proxy endpoint)
"""
import argparse
import json
import logging
import sys
from pathlib import Path

import jsonschema
import yaml

from orchestrator.engine import Engine
from orchestrator.gates import HumanGate
from orchestrator.ledger import append_ledger_row
from orchestrator.llm_dispatch import LLMDispatcher
from run_iteration import (
    IterationOutcome,
    run_iteration,
    setup_work_dir,
    SCHEMAS_DIR,
)

logger = logging.getLogger(__name__)


def run_campaign(
    campaign: dict,
    work_dir: Path,
    *,
    max_iterations: int = 10,
    model: str = "aws/claude-opus-4-6",
    auto_approve: bool = False,
) -> None:
    """Run a multi-iteration Nous campaign.

    Loops through iterations, calling run_iteration() for each one.
    After each non-final iteration: appends a ledger row, generates an
    investigation summary, and prompts the human to continue or stop.

    Args:
        campaign: Parsed campaign.yaml dict.
        work_dir: Working directory (must already be initialized).
        max_iterations: Maximum number of iterations to run.
        model: LLM model name.
        auto_approve: If True, all human gates (including continue gate)
            are automatically approved.
    """
    continue_gate = (
        HumanGate(auto_response="approve") if auto_approve else HumanGate()
    )

    for i in range(1, max_iterations + 1):
        is_last = (i == max_iterations)
        print(f"\n{'#'*60}")
        print(f"  CAMPAIGN — Iteration {i} of {max_iterations}")
        print(f"{'#'*60}")

        outcome = run_iteration(
            campaign, work_dir, iteration=i, model=model, final=is_last,
            auto_approve=auto_approve,
        )

        if outcome == IterationOutcome.COMPLETED:
            print(f"\n  Campaign complete after {i} iteration(s).")
            return

        if outcome == IterationOutcome.ABORTED:
            print(f"\n  Campaign aborted at iteration {i}.")
            print("  Engine state preserved for potential resume.")
            return

        if outcome == IterationOutcome.REDESIGN:
            print(f"\n  Iteration {i} returned REDESIGN.")
            print("  The engine has been rewound. Re-run the campaign to resume.")
            return

        # outcome == CONTINUE — non-final iteration completed extraction
        if outcome != IterationOutcome.CONTINUE:
            raise ValueError(f"Unexpected outcome: {outcome}")

        # Post-iteration: ledger + investigation summary
        append_ledger_row(work_dir, i)

        dispatcher = LLMDispatcher(
            work_dir=work_dir, campaign=campaign, model=model,
        )
        iter_dir = work_dir / "runs" / f"iter-{i}"
        dispatcher.dispatch(
            "extractor", "summarize",
            output_path=iter_dir / "investigation_summary.json",
            iteration=i,
        )
        print(f"  -> {iter_dir / 'investigation_summary.json'}")

        # Human gate: continue?
        print(f"\n{'='*60}")
        print(f"  CONTINUE GATE — Iteration {i} complete")
        print(f"{'='*60}")
        decision = continue_gate.prompt(
            f"Continue to iteration {i + 1}?",
        )
        if decision != "approve":
            engine = Engine(work_dir)
            engine.transition("DONE")
            print(f"\n  Campaign stopped after {i} iteration(s).")
            return

        # Advance engine from EXTRACTION → DESIGN (increments iteration)
        engine = Engine(work_dir)
        engine.transition("DESIGN")
        print(f"\n  Advancing to iteration {i + 1}...")

    print(f"\n  Campaign reached max_iterations ({max_iterations}).")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a multi-iteration Nous campaign.",
        epilog="Example: python run_campaign.py examples/blis/campaign.yaml --max-iterations 5",
    )
    parser.add_argument("campaign", help="Path to campaign.yaml")
    parser.add_argument("--max-iterations", type=int, default=10,
                        help="Maximum iterations (default: 10)")
    parser.add_argument("--model", default="aws/claude-opus-4-6",
                        help="Model name (default: aws/claude-opus-4-6)")
    parser.add_argument("--run-id", default=None,
                        help="Working directory name (default: derived from campaign)")
    parser.add_argument("--auto-approve", action="store_true",
                        help="Auto-approve all human gates (skip interactive prompts)")
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
            f"See examples/blis/campaign.yaml for a working example.",
            file=sys.stderr,
        )
        sys.exit(1)

    # CLI --max-iterations overrides campaign.yaml; campaign.yaml is fallback.
    if args.max_iterations != 10:
        max_iter = args.max_iterations
    else:
        max_iter = campaign.get("max_iterations", args.max_iterations)

    run_id = args.run_id or campaign_path.parent.name + "-run"
    work_dir = setup_work_dir(run_id)
    print(f"Working directory: {work_dir.resolve()}")
    print(f"Max iterations: {max_iter}")

    run_campaign(
        campaign, work_dir,
        max_iterations=max_iter, model=args.model,
        auto_approve=args.auto_approve,
    )


if __name__ == "__main__":
    main()
