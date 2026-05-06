#!/usr/bin/env python3
"""Run a multi-iteration Nous campaign.

Usage:
    python run_campaign.py examples/campaign.yaml --max-iterations 5

Runs iterations in a loop: each iteration runs the full Nous loop
(FRAMING → DESIGN → REVIEW → PLAN_EXECUTION → EXECUTING → ANALYSIS → EXTRACTION), then appends a
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
from orchestrator.metrics import summarize_metrics
from run_iteration import (
    DEFAULTS_PATH,
    IterationOutcome,
    run_iteration,
    setup_work_dir,
    SCHEMAS_DIR,
)

logger = logging.getLogger(__name__)


def _resolve_model(campaign: dict, phase_key: str, cli_model: str | None) -> str:
    """Resolve model: campaign.models > defaults.yaml > --model flag."""
    campaign_models = campaign.get("models", {})
    if campaign_models.get(phase_key):
        return campaign_models[phase_key]
    if DEFAULTS_PATH.exists():
        defaults = yaml.safe_load(DEFAULTS_PATH.read_text()) or {}
        default_model = defaults.get("models", {}).get(phase_key)
        if default_model:
            return default_model
    return cli_model or "aws/claude-sonnet-4-5"


def _write_metrics_summary(work_dir: Path) -> None:
    """Write llm_metrics_summary.json and print a one-liner. Never raises."""
    try:
        metrics_path = work_dir / "llm_metrics.jsonl"
        summary = summarize_metrics(metrics_path)
        summary_path = work_dir / "llm_metrics_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2) + "\n")
        cost = summary.get("total_cost_usd", 0) or 0
        inp = summary.get("total_input_tokens", 0)
        out = summary.get("total_output_tokens", 0)
        calls = summary.get("total_calls", 0)
        print(f"\n  LLM usage: {calls} calls, {inp + out} tokens (in:{inp} out:{out}), ${cost:.4f}")
        print(f"  -> {summary_path}")
    except Exception as exc:
        logger.exception("Failed to write metrics summary")
        print(f"\n  Warning: could not write metrics summary: {exc}")


def _generate_report(campaign: dict, work_dir: Path, model: str | None) -> None:
    """Generate report.md summarizing the campaign."""
    try:
        resolved = _resolve_model(campaign, "report", model)
        dispatcher = LLMDispatcher(work_dir=work_dir, campaign=campaign, model=resolved)
        dispatcher.dispatch(
            "extractor", "report",
            output_path=work_dir / "report.md",
            iteration=0,
        )
        print(f"  -> {work_dir / 'report.md'}")
    except (RuntimeError, FileNotFoundError, OSError) as exc:
        logger.warning("Report generation failed: %s", exc)


def _resume_completed_campaign(work_dir: Path, max_iterations: int) -> int:
    """Decide whether to resume a DONE campaign and, if so, advance it.

    Resumes (transitions state DONE -> DESIGN and returns the next iteration
    number) only when all of:
      * state.phase == "DONE"
      * ledger.json exists and parses
      * the ledger has at least one real iteration row (iteration >= 1)
      * completed iterations < max_iterations

    In every other case — fresh campaign, mid-flight campaign, empty/corrupt
    ledger, or already at max_iterations — returns 1 and leaves state
    untouched. A corrupt ledger is logged at warning level so the user can
    repair it; it never raises.
    """
    from orchestrator.engine import Engine

    engine = Engine(work_dir)
    if engine.phase != "DONE":
        return 1

    ledger_path = work_dir / "ledger.json"
    if not ledger_path.exists():
        return 1

    try:
        ledger = json.loads(ledger_path.read_text())
        # iteration 0 is the synthetic baseline row; real iterations start at 1
        completed = max(
            (row["iteration"] for row in ledger.get("iterations", [])
             if isinstance(row, dict) and isinstance(row.get("iteration"), int)
             and row["iteration"] >= 1),
            default=0,
        )
    except (json.JSONDecodeError, OSError, TypeError, KeyError) as exc:
        logger.warning(
            "Could not read ledger at %s (%s: %s); starting fresh instead of resuming.",
            ledger_path, type(exc).__name__, exc,
        )
        return 1

    if completed == 0 or completed >= max_iterations:
        return 1

    print(
        f"  Resuming DONE campaign at iteration {completed + 1} "
        f"(max_iterations={max_iterations})"
    )
    engine.transition("DESIGN")
    return completed + 1


def run_campaign(
    campaign: dict,
    work_dir: Path,
    *,
    max_iterations: int = 10,
    model: str | None = None,
    auto_approve: bool = False,
    timeout: int = 1800,
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

    start_iter = _resume_completed_campaign(work_dir, max_iterations)

    max_redesigns = 3
    for i in range(start_iter, max_iterations + 1):
        is_last = (i == max_iterations)

        for redesign_attempt in range(max_redesigns + 1):
            print(f"\n{'#'*60}")
            if redesign_attempt > 0:
                print(f"  CAMPAIGN — Iteration {i} (redesign {redesign_attempt})")
            else:
                print(f"  CAMPAIGN — Iteration {i} of {max_iterations}")
            print(f"{'#'*60}")

            outcome = run_iteration(
                campaign, work_dir, iteration=i, model=model, final=is_last,
                auto_approve=auto_approve, timeout=timeout,
            )

            if outcome == IterationOutcome.REDESIGN:
                if redesign_attempt < max_redesigns:
                    print(f"\n  Design rejected — retrying iteration {i}...")
                    continue
                else:
                    print(f"\n  Max redesigns ({max_redesigns}) reached. Stopping.")
                    _write_metrics_summary(work_dir)
                    return
            break  # any non-REDESIGN outcome exits the retry loop

        if outcome == IterationOutcome.COMPLETED:
            append_ledger_row(work_dir, i)
            print(f"\n  Campaign complete after {i} iteration(s).")
            _generate_report(campaign, work_dir, model)
            _write_metrics_summary(work_dir)
            return

        if outcome == IterationOutcome.ABORTED:
            print(f"\n  Campaign aborted at iteration {i}.")
            print("  Engine state preserved for potential resume.")
            _write_metrics_summary(work_dir)
            return

        # outcome == CONTINUE — non-final iteration completed extraction
        if outcome != IterationOutcome.CONTINUE:
            raise ValueError(f"Unexpected outcome: {outcome}")

        # Post-iteration: ledger + investigation summary
        append_ledger_row(work_dir, i)

        dispatcher = LLMDispatcher(
            work_dir=work_dir, campaign=campaign,
            model=_resolve_model(campaign, "extraction", model),
        )
        iter_dir = work_dir / "runs" / f"iter-{i}"
        dispatcher.dispatch(
            "extractor", "summarize",
            output_path=iter_dir / "investigation_summary.json",
            iteration=i,
        )
        print(f"  -> {iter_dir / 'investigation_summary.json'}")

        # Generate continue gate summary
        gate_summary_path = iter_dir / "gate_summary_continue.json"
        try:
            dispatcher.dispatch(
                "summarizer", "summarize-gate",
                output_path=gate_summary_path,
                iteration=i,
                perspective="continue",
            )
        except (RuntimeError, FileNotFoundError, OSError) as exc:
            logger.warning("Continue gate summary generation failed: %s", exc)
            gate_summary_path = None

        # Human gate: continue?
        print(f"\n{'='*60}")
        print(f"  CONTINUE GATE — Iteration {i} complete")
        print(f"{'='*60}")
        decision, _reason = continue_gate.prompt(
            f"Continue to iteration {i + 1}?",
            summary_path=str(gate_summary_path) if gate_summary_path else None,
        )
        if decision != "approve":
            engine = Engine(work_dir)
            engine.transition("DONE")
            print(f"\n  Campaign stopped after {i} iteration(s).")
            _generate_report(campaign, work_dir, model)
            _write_metrics_summary(work_dir)
            return

        # Advance engine from EXTRACTION → DESIGN (increments iteration)
        engine = Engine(work_dir)
        engine.transition("DESIGN")
        print(f"\n  Advancing to iteration {i + 1}...")

    print(f"\n  Campaign reached max_iterations ({max_iterations}).")
    _generate_report(campaign, work_dir, model)
    _write_metrics_summary(work_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a multi-iteration Nous campaign.",
        epilog="Example: python run_campaign.py examples/campaign.yaml --max-iterations 5",
    )
    parser.add_argument("campaign", help="Path to campaign.yaml")
    parser.add_argument("--max-iterations", type=int, default=None,
                        help="Maximum iterations (default: 10)")
    parser.add_argument("--model", default=None,
                        help="Fallback model name. Overridden by campaign.yaml models: and defaults.yaml.")
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

    # CLI --max-iterations overrides campaign.yaml; campaign.yaml is fallback.
    if args.max_iterations is not None:
        max_iter = args.max_iterations
    else:
        max_iter = campaign.get("max_iterations", 10)

    run_id = args.run_id or campaign.get("run_id") or campaign_path.parent.name + "-run"
    work_dir = setup_work_dir(run_id)
    print(f"Working directory: {work_dir.resolve()}")
    print(f"Max iterations: {max_iter}")

    run_campaign(
        campaign, work_dir,
        max_iterations=max_iter, model=args.model,
        auto_approve=args.auto_approve, timeout=args.timeout,
    )


if __name__ == "__main__":
    main()
