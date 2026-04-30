"""Deterministic experiment execution for the Nous orchestrator.

Reads an experiment_plan.yaml and runs its commands via subprocess.
No LLM calls — purely deterministic execution.

On failure, an optional revision_fn callback can be used to request
a corrected plan from an LLM agent (e.g., CLIDispatcher.revise_plan).
"""
import json
import logging
import subprocess
from collections.abc import Callable
from pathlib import Path

import yaml

from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS = 12000


def execute_plan(
    plan: dict,
    cwd: Path,
    iter_dir: Path,
    *,
    revision_fn: Callable[[dict, dict], dict] | None = None,
    max_revisions: int = 3,
    timeout: int = 300,
) -> dict:
    """Execute an experiment plan and collect results.

    Args:
        plan: Parsed experiment_plan.yaml dict.
        cwd: Working directory for commands (typically the worktree).
        iter_dir: Iteration directory — results are written here.
        revision_fn: Called on failure with (plan, error_info) → revised plan.
            If None, failures are terminal.
        max_revisions: Max number of plan revision rounds.
        timeout: Per-command timeout in seconds.

    Returns:
        The execution_results dict (also written to iter_dir/execution_results.json).
    """
    cwd = Path(cwd)
    iter_dir = Path(iter_dir)
    results_dir = iter_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    revisions_used = 0

    while True:
        try:
            results = _execute_plan_once(plan, cwd, results_dir, timeout)
            break
        except CommandError as exc:
            if revision_fn is None or revisions_used >= max_revisions:
                # Save partial results and continue to analysis instead of crashing
                logger.warning(
                    "Command failed, no more revisions (used %d/%d): %s",
                    revisions_used, max_revisions, exc,
                )
                print(
                    f"    Command failed — no more revisions available. "
                    f"Continuing with partial results.",
                    flush=True,
                )
                results = _collect_partial_results(plan, results_dir, cwd)
                break
            revisions_used += 1
            logger.warning(
                "Command failed (revision %d/%d): %s",
                revisions_used, max_revisions, exc,
            )
            print(
                f"    Command failed — requesting revised plan "
                f"(revision {revisions_used}/{max_revisions})...",
                flush=True,
            )
            error_info = {
                "failed_step": exc.step,
                "cmd": exc.cmd,
                "exit_code": exc.exit_code,
                "stderr_tail": _truncate(exc.stderr),
                "stdout_tail": _truncate(exc.stdout),
            }
            # Persist error for debugging
            error_path = iter_dir / f"execution_error_v{revisions_used}.json"
            atomic_write(error_path, json.dumps(error_info, indent=2) + "\n")
            logger.info("Saved error info to %s", error_path)
            try:
                plan = revision_fn(plan, error_info)
            except (RuntimeError, OSError) as rev_exc:
                logger.warning("Revision failed: %s. Continuing with partial results.", rev_exc)
                print(f"    Revision failed. Continuing with partial results.", flush=True)
                results = _collect_partial_results(plan, results_dir, cwd)
                break
            # Save revised plan for audit trail
            revised_path = iter_dir / f"experiment_plan_v{revisions_used + 1}.yaml"
            atomic_write(
                revised_path,
                yaml.safe_dump(plan, default_flow_style=False, sort_keys=False),
            )
            logger.info("Saved revised plan to %s", revised_path)

    # Write execution_results.json
    output = {
        "plan_ref": f"runs/{iter_dir.name}/experiment_plan.yaml",
        **results,
    }
    atomic_write(iter_dir / "execution_results.json", json.dumps(output, indent=2) + "\n")
    logger.info("Wrote execution_results.json (%d arms)", len(results.get("arms", [])))
    return output


class CommandError(Exception):
    """Raised when a command in the experiment plan fails."""

    def __init__(self, step: str, cmd: str, exit_code: int, stdout: str, stderr: str):
        self.step = step
        self.cmd = cmd
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"Step '{step}' failed: cmd={cmd!r}, exit_code={exit_code}")


def _execute_plan_once(
    plan: dict, cwd: Path, results_dir: Path, timeout: int,
) -> dict:
    """Execute the plan once, raising CommandError on first failure."""
    setup_results = _run_setup(plan.get("setup", []), cwd, timeout)
    arm_results = []
    for arm in plan["arms"]:
        arm_result = _run_arm(arm, cwd, results_dir, timeout)
        arm_results.append(arm_result)

    return {"setup_results": setup_results, "arms": arm_results}


def _run_setup(setup_cmds: list[dict], cwd: Path, timeout: int) -> list[dict]:
    """Run setup commands sequentially."""
    results = []
    for i, step in enumerate(setup_cmds):
        cmd = step["cmd"]
        desc = step.get("description", f"setup-{i}")
        print(f"    [setup] {desc}: {cmd}", flush=True)
        result = _run_cmd(cmd, cwd, timeout)
        results.append({
            "cmd": cmd,
            "exit_code": result.returncode,
            "stdout_tail": _truncate(result.stdout),
            "stderr_tail": _truncate(result.stderr),
        })
        if result.returncode != 0:
            raise CommandError(
                step=f"setup/{desc}",
                cmd=cmd,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
    return results


def _run_arm(arm: dict, cwd: Path, results_dir: Path, timeout: int) -> dict:
    """Run all conditions in an arm."""
    arm_id = arm["arm_id"]
    arm_dir = results_dir / arm_id
    arm_dir.mkdir(parents=True, exist_ok=True)

    conditions = []
    for cond in arm["conditions"]:
        name = cond["name"]
        cmd = cond["cmd"]
        output_path = cond.get("output")

        print(f"    [{arm_id}] {name}: {cmd}", flush=True)
        result = _run_cmd(cmd, cwd, timeout)

        # Save stdout/stderr logs
        (arm_dir / f"{name}.stdout").write_text(result.stdout)
        (arm_dir / f"{name}.stderr").write_text(result.stderr)

        if result.returncode != 0:
            raise CommandError(
                step=f"{arm_id}/{name}",
                cmd=cmd,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )

        # Read output file if specified
        output_content = None
        if output_path:
            full_output = cwd / output_path
            if full_output.exists():
                raw = full_output.read_text()
                output_content = _truncate(raw)
            else:
                logger.warning(
                    "Output file %s not found after running %s", full_output, cmd,
                )

        conditions.append({
            "name": name,
            "cmd": cmd,
            "exit_code": result.returncode,
            "stdout_tail": _truncate(result.stdout),
            "stderr_tail": _truncate(result.stderr),
            "output_content": output_content,
        })

    return {"arm_id": arm_id, "conditions": conditions}


def _run_cmd(cmd: str, cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    """Run a single shell command."""
    try:
        return subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise CommandError(
            step="timeout",
            cmd=cmd,
            exit_code=-1,
            stdout="",
            stderr=f"Command timed out after {timeout}s",
        )


def _collect_partial_results(plan: dict, results_dir: Path, cwd: Path) -> dict:
    """Collect whatever results exist from completed arms."""
    arms = []
    for arm in plan["arms"]:
        arm_id = arm["arm_id"]
        conditions = []
        for cond in arm["conditions"]:
            name = cond["name"]
            stdout_file = results_dir / arm_id / f"{name}.stdout"
            stderr_file = results_dir / arm_id / f"{name}.stderr"
            output_content = None
            if cond.get("output"):
                out_file = cwd / cond["output"]
                if out_file.exists():
                    output_content = _truncate(out_file.read_text())
            if stdout_file.exists() or stderr_file.exists():
                conditions.append({
                    "name": name,
                    "cmd": cond["cmd"],
                    "exit_code": None,
                    "stdout_tail": _truncate(stdout_file.read_text()) if stdout_file.exists() else "",
                    "stderr_tail": _truncate(stderr_file.read_text()) if stderr_file.exists() else "",
                    "output_content": output_content,
                })
        if conditions:
            arms.append({"arm_id": arm_id, "conditions": conditions})
    return {"partial": True, "setup_results": [], "arms": arms}


def _truncate(text: str, max_chars: int = _MAX_OUTPUT_CHARS) -> str:
    """Keep the last max_chars characters."""
    if len(text) <= max_chars:
        return text
    return f"...(truncated, showing last {max_chars} chars)...\n" + text[-max_chars:]
