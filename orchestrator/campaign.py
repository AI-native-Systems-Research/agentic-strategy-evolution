#!/usr/bin/env python3
"""Run a multi-iteration Nous campaign.

Usage:
    python run_campaign.py examples/campaign.yaml --max-iterations 5

    # Inline mode — embed inside an agent framework:
    python run_campaign.py examples/campaign.yaml --agent inline

Runs iterations in a loop: each iteration runs the full Nous loop
(DESIGN → EXECUTE_ANALYZE → DONE), then appends a ledger row
and prompts whether to continue. The designer's handoff.md (a living
campaign-level document) and previous findings feed the next iteration's
design prompt so that each hypothesis bundle is informed by all prior learning.

Dispatch backends:
    --agent api (default): Uses CLIDispatcher for code phases (when repo_path
        is set) and LLMDispatcher for structured phases. OPENAI_API_KEY is
        optional — gate summaries are skipped if not set.
    --agent inline: Emits prompts to stdout for the calling agent to reason
        about. No subprocess, no API key — the agent that invoked run_campaign.py
        sees the prompt and writes artifacts directly. Ideal for embedded use
        inside agent frameworks (e.g., Hive strategist).
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
from orchestrator.inline_dispatch import InlineDispatcher
from orchestrator.ledger import append_failed_row, append_ledger_row
from orchestrator.llm_dispatch import LLMDispatcher
from orchestrator.metrics import summarize_metrics
from orchestrator.iteration import (
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


def _generate_report(
    campaign: dict, work_dir: Path, model: str | None,
    agent: str = "api", timeout: int = 1800,
) -> None:
    """Generate report.md summarizing the campaign."""
    try:
        resolved = _resolve_model(campaign, "report", model)
        if agent == "inline":
            dispatcher = InlineDispatcher(
                work_dir=work_dir, campaign=campaign, timeout=timeout,
            )
        else:
            dispatcher = LLMDispatcher(work_dir=work_dir, campaign=campaign, model=resolved)
        dispatcher.dispatch(
            "extractor", "report",
            output_path=work_dir / "report.md",
            iteration=0,
        )
        print(f"  -> {work_dir / 'report.md'}")
    except (RuntimeError, FileNotFoundError, OSError) as exc:
        logger.warning("Report generation failed: %s", exc)
        print(f"  Report generation skipped: {exc}")


def _resume_completed_campaign(work_dir: Path, max_iterations: int) -> int:
    """Decide where to resume a campaign and, if DONE, advance it.

    Returns the iteration number to start the campaign loop from:
      * INIT (fresh):     1
      * Mid-flight:       engine.iteration (resume in-progress iteration)
      * DONE (finished):  completed + 1 after transitioning DONE -> DESIGN,
                          provided completed < max_iterations; else 1

    A corrupt ledger is logged at warning level; it never raises.
    """
    from orchestrator.engine import Engine

    engine = Engine(work_dir)

    # Mid-flight: resume the in-progress iteration
    if engine.phase not in ("INIT", "DONE"):
        start = engine.iteration
        if start < 1:
            logger.warning(
                "state.json has iteration=%d (< 1); starting fresh.", start,
            )
            return 1
        if start > max_iterations:
            logger.warning(
                "Mid-flight iteration %d exceeds max_iterations=%d; "
                "raise max_iterations to resume this campaign.",
                start, max_iterations,
            )
            return start
        logger.info(
            "Resuming mid-flight campaign at iteration %d "
            "(phase=%s, max_iterations=%d)",
            start, engine.phase, max_iterations,
        )
        return start

    if engine.phase == "INIT":
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
    agent: str = "api",
    max_cli_retries: int | None = None,
) -> None:
    """Run a multi-iteration Nous campaign.

    Loops through iterations, calling run_iteration() for each one.
    After each non-final iteration: appends a ledger row and prompts
    the human to continue or stop.

    Args:
        campaign: Parsed campaign.yaml dict.
        work_dir: Working directory (must already be initialized).
        max_iterations: Maximum number of iterations to run.
        model: LLM model name.
        auto_approve: If True, all human gates (including continue gate)
            are automatically approved.
        agent: Dispatch backend — "inline" emits prompts to stdout,
            "api" uses the OpenAI-compatible LLM API.
        max_cli_retries: Max retries for transient claude -p failures (None = unbounded).
    """
    continue_gate = (
        HumanGate(auto_response="approve") if auto_approve else HumanGate()
    )

    # Pre-flight: validate CLI + credentials before starting the campaign
    repo_path = campaign.get("target_system", {}).get("repo_path")
    if agent != "inline" and repo_path:
        from orchestrator.cli_dispatch import CLIDispatcher
        preflight_dispatcher = CLIDispatcher(
            work_dir=work_dir, campaign=campaign,
            model=_resolve_model(campaign, "design", model),
            max_retries=max_cli_retries,
        )
        preflight_dispatcher.preflight_check()

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

            try:
                outcome = run_iteration(
                    campaign, work_dir, iteration=i, model=model, final=is_last,
                    auto_approve=auto_approve, timeout=timeout, agent=agent,
                    max_cli_retries=max_cli_retries,
                )
            except Exception as exc:
                logger.error("Iteration %d failed permanently: %s", i, exc)
                print(f"\n  Iteration {i} FAILED: {exc}")
                append_failed_row(work_dir, i, str(exc))
                outcome = None
                break

            if outcome == IterationOutcome.REDESIGN:
                if redesign_attempt < max_redesigns:
                    print(f"\n  Design rejected — retrying iteration {i}...")
                    continue
                else:
                    print(f"\n  Max redesigns ({max_redesigns}) reached. Stopping.")
                    _write_metrics_summary(work_dir)
                    return
            break  # any non-REDESIGN outcome exits the retry loop

        if outcome is None:
            # Iteration failed permanently — advance to next
            if is_last:
                break
            engine = Engine(work_dir)
            engine.force_phase("DESIGN")
            continue

        if outcome == IterationOutcome.COMPLETED:
            append_ledger_row(work_dir, i)
            print(f"\n  Campaign complete after {i} iteration(s).")
            _generate_report(campaign, work_dir, model, agent=agent, timeout=timeout)
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

        # Post-iteration: ledger
        append_ledger_row(work_dir, i)

        iter_dir = work_dir / "runs" / f"iter-{i}"

        # Generate continue gate summary
        gate_summary_path = iter_dir / "gate_summary_continue.json"
        try:
            resolved = _resolve_model(campaign, "report", model)
            if agent == "inline":
                dispatcher = InlineDispatcher(
                    work_dir=work_dir, campaign=campaign, timeout=timeout,
                )
            else:
                dispatcher = LLMDispatcher(
                    work_dir=work_dir, campaign=campaign,
                    model=resolved,
                )
            dispatcher.dispatch(
                "summarizer", "summarize-gate",
                output_path=gate_summary_path,
                iteration=i,
                perspective="continue",
            )
        except (RuntimeError, FileNotFoundError, OSError) as exc:
            logger.warning("Continue gate summary generation failed: %s", exc)
            print(f"  (Continue gate summary skipped: {exc})")
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
            _generate_report(campaign, work_dir, model, agent=agent, timeout=timeout)
            _write_metrics_summary(work_dir)
            return

        # Advance: HUMAN_FINDINGS_GATE → DONE → DESIGN (increments iteration)
        engine = Engine(work_dir)
        engine.transition("DONE")
        engine.transition("DESIGN")
        print(f"\n  Advancing to iteration {i + 1}...")

    print(f"\n  Campaign reached max_iterations ({max_iterations}).")
    _generate_report(campaign, work_dir, model, agent=agent, timeout=timeout)
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
    parser.add_argument("--max-cli-retries", type=int, default=10,
                        help="Max retries for claude -p failures (-1 = unbounded, default: 10)")
    parser.add_argument("--agent", choices=["inline", "api"], default="api",
                        help="Dispatch backend: 'inline' emits prompts to stdout for the "
                             "calling agent (no subprocess, no API key), "
                             "'api' uses the LLM API (default: api)")
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
    repo_path = campaign.get("target_system", {}).get("repo_path")
    work_dir = setup_work_dir(run_id, repo_path=repo_path)
    print(f"Working directory: {work_dir.resolve()}")
    print(f"Max iterations: {max_iter}")

    run_campaign(
        campaign, work_dir,
        max_iterations=max_iter, model=args.model,
        auto_approve=args.auto_approve, timeout=args.timeout,
        agent=args.agent,
        max_cli_retries=None if args.max_cli_retries == -1 else args.max_cli_retries,
    )


if __name__ == "__main__":
    main()
