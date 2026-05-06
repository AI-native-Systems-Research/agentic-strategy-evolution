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
import sys
from datetime import datetime, timezone
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
    CONTINUE = "CONTINUE"      # Non-final iteration, stopped before DONE
    ABORTED = "ABORTED"        # Human aborted at a gate
    REDESIGN = "REDESIGN"      # Human rejected, needs redesign

TEMPLATES_DIR = Path(__file__).parent / "templates"
SCHEMAS_DIR = Path(__file__).parent / "schemas"
DEFAULTS_PATH = Path(__file__).parent / "defaults.yaml"
_ARM_TYPE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# Phase ordering for resume logic
_PHASE_ORDER = [
    "INIT", "DESIGN", "HUMAN_DESIGN_GATE",
    "EXECUTE_ANALYZE", "VALIDATE", "HUMAN_FINDINGS_GATE",
    "DONE",
]
_PHASE_INDEX = {p: i for i, p in enumerate(_PHASE_ORDER)}


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


def _split_design_output(raw: str, iter_dir: Path) -> None:
    """Split merged design output into problem.md and bundle.yaml."""
    matches = _YAML_FENCE_RE.findall(raw)
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

    last_fence_start = raw.rfind("```yaml")
    if last_fence_start == -1:
        last_fence_start = raw.rfind("```YAML")
    problem_md = raw[:last_fence_start].rstrip()
    if problem_md.endswith("---"):
        problem_md = problem_md[:-3].rstrip()

    iter_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(iter_dir / "problem.md", problem_md + "\n")
    atomic_write(
        iter_dir / "bundle.yaml",
        yaml.safe_dump(bundle, default_flow_style=False, sort_keys=False),
    )


def _enter_phase(engine, phase):
    """Transition to phase if needed. Returns True if phase work should run."""
    current_idx = _PHASE_INDEX[engine.phase]
    target_idx = _PHASE_INDEX[phase]
    if current_idx > target_idx:
        return False
    if engine.phase != phase:
        engine.transition(phase)
    return True


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

    Phases: DESIGN → HUMAN_DESIGN_GATE → EXECUTE_ANALYZE → VALIDATE → HUMAN_FINDINGS_GATE → DONE

    Args:
        final: If True (default), transitions to DONE after principle merge.
        auto_approve: If True, all human gates are automatically approved.

    Returns:
        An IterationOutcome value: COMPLETED, CONTINUE, ABORTED, or REDESIGN.
    """
    engine = Engine(work_dir)
    repo_path = campaign.get("target_system", {}).get("repo_path")

    # Load defaults.yaml, then overlay campaign.models
    defaults = {}
    if DEFAULTS_PATH.exists():
        defaults = yaml.safe_load(DEFAULTS_PATH.read_text()) or {}
    default_models = defaults.get("models", {})
    default_max_turns = defaults.get("max_turns", {})
    campaign_models = campaign.get("models", {})

    def _model_for(phase_key: str) -> str:
        return campaign_models.get(phase_key) or default_models.get(phase_key) or model or "aws/claude-sonnet-4-5"

    def _max_turns_for(phase_key: str) -> int:
        return default_max_turns.get(phase_key, 25)

    # CLIDispatcher for code-access roles; LLMDispatcher for API-only phases
    from orchestrator.cli_dispatch import CLIDispatcher
    cli_dispatcher = (
        CLIDispatcher(
            work_dir=work_dir, campaign=campaign,
            model=_model_for("design"), timeout=timeout,
            max_turns=_max_turns_for("design"),
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

    # ─── DESIGN ───────────────────────────────────────────────────────────
    if _enter_phase(engine, "DESIGN"):
        print(f"\n{'='*60}")
        print(f"  DESIGN — exploring system and creating hypothesis bundle")
        print(f"{'='*60}")
        design_dispatcher = cli_dispatcher or llm_dispatcher
        design_dispatcher.dispatch(
            "planner", "design",
            output_path=iter_dir / "design_raw.md", iteration=iteration,
        )
        raw_response = (iter_dir / "design_raw.md").read_text()
        _split_design_output(raw_response, iter_dir)
        (iter_dir / "design_raw.md").unlink()
        print(f"  -> {iter_dir / 'problem.md'}")
        print(f"  -> {iter_dir / 'bundle.yaml'}")

    # ─── HUMAN DESIGN GATE ────────────────────────────────────────────────
    if _enter_phase(engine, "HUMAN_DESIGN_GATE"):
        print(f"\n{'='*60}")
        print(f"  HUMAN DESIGN GATE")
        print(f"{'='*60}")
        summary_path = _generate_gate_summary(llm_dispatcher, iter_dir, iteration, "design")
        decision, reason = gate.prompt(
            "Review the hypothesis bundle. Approve?",
            summary_path=str(summary_path) if summary_path else None,
            files=[str(iter_dir / "bundle.yaml"), str(iter_dir / "problem.md")],
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
        try:
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
            if experiment_dir and cli_dispatcher:
                with cli_dispatcher.override_cwd(experiment_dir):
                    exec_dispatcher.dispatch(
                        "executor", "execute-analyze",
                        output_path=iter_dir / "execute_analyze_output.json",
                        iteration=iteration,
                    )
            else:
                exec_dispatcher.dispatch(
                    "executor", "execute-analyze",
                    output_path=iter_dir / "execute_analyze_output.json",
                    iteration=iteration,
                )
            # Split combined output into separate artifacts
            combined = json.loads((iter_dir / "execute_analyze_output.json").read_text())
            missing = {"plan", "findings", "principle_updates"} - set(combined.keys())
            if missing:
                raise RuntimeError(
                    f"execute-analyze agent output missing keys: {sorted(missing)}. "
                    f"Got: {sorted(combined.keys())}. See {iter_dir / 'execute_analyze_output.json'}"
                )
            plan_data = combined["plan"]
            atomic_write(
                iter_dir / "experiment_plan.yaml",
                yaml.safe_dump(plan_data, default_flow_style=False, sort_keys=False),
            )
            atomic_write(
                iter_dir / "findings.json",
                json.dumps(combined["findings"], indent=2) + "\n",
            )
            atomic_write(
                iter_dir / "principle_updates.json",
                json.dumps(combined["principle_updates"], indent=2) + "\n",
            )
            print(f"  -> {iter_dir / 'experiment_plan.yaml'}")
            print(f"  -> {iter_dir / 'findings.json'}")
            print(f"  -> {iter_dir / 'principle_updates.json'}")
        except BaseException:
            if repo_path and experiment_id:
                from orchestrator.worktree import remove_experiment_worktree
                remove_experiment_worktree(Path(repo_path), experiment_id)
            raise

    # ─── VALIDATE ─────────────────────────────────────────────────────────
    if _enter_phase(engine, "VALIDATE"):
        print(f"\n{'='*60}")
        print(f"  VALIDATE — replaying plan for reproducibility")
        print(f"{'='*60}")
        # Recover worktree reference on resume
        if not experiment_dir and repo_path:
            eid_path = iter_dir / ".experiment_id"
            if eid_path.exists():
                experiment_id = eid_path.read_text().strip()
                experiment_dir = Path(repo_path) / ".nous-experiments" / experiment_id

        try:
            from orchestrator.executor import execute_plan
            plan = yaml.safe_load((iter_dir / "experiment_plan.yaml").read_text())
            execute_plan(
                plan,
                cwd=experiment_dir or Path(repo_path) if repo_path else iter_dir,
                iter_dir=iter_dir,
                reset_cmd="git checkout -- ." if experiment_dir else None,
            )
            print(f"  -> {iter_dir / 'execution_results.json'}")
        finally:
            if repo_path and experiment_id:
                from orchestrator.worktree import remove_experiment_worktree
                remove_experiment_worktree(Path(repo_path), experiment_id)

    # Validate findings and check fast-fail rules
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

    ff = check_fast_fail(findings)
    if ff == FastFailAction.REDESIGN:
        print("  ** Control-negative REFUTED and h-main not confirmed — mechanism confounded.")
        print("     The experiment needs redesign.")
        engine.transition("EXECUTE_ANALYZE")
        return IterationOutcome.REDESIGN
    if ff == FastFailAction.SKIP_TO_MERGE:
        print("  ** H-main REFUTED — skipping to principle merge")
    if ff == FastFailAction.SIMPLIFY:
        print("  ** Dominant component >80% — consider simplifying the model.")

    # ─── HUMAN FINDINGS GATE ──────────────────────────────────────────────
    if _enter_phase(engine, "HUMAN_FINDINGS_GATE"):
        print(f"\n{'='*60}")
        print(f"  HUMAN FINDINGS GATE")
        print(f"{'='*60}")
        summary_path = _generate_gate_summary(llm_dispatcher, iter_dir, iteration, "findings")
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

    # ─── PRINCIPLE MERGE (Python, no LLM) ─────────────────────────────────
    _merge_principles(work_dir, iter_dir)
    print(f"  -> Principles merged into {work_dir / 'principles.json'}")

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
    work_dir = setup_work_dir(run_id)
    print(f"Working directory: {work_dir.resolve()}")

    run_iteration(
        campaign, work_dir, model=args.model,
        auto_approve=args.auto_approve, timeout=args.timeout,
    )


if __name__ == "__main__":
    main()
