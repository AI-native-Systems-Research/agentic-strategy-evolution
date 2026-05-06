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
    reset_cmd: str | None = None,
) -> dict:
    """Execute an experiment plan and collect results.

    Arms run independently — a failure in one arm does not block others.
    On retry, only failed arms are re-run; successful arms are preserved.

    Args:
        plan: Parsed experiment_plan.yaml dict.
        cwd: Working directory for commands (typically the worktree).
        iter_dir: Iteration directory — results are written here.
        revision_fn: Called on failure with (plan, error_info) → revised plan.
            If None, failures are terminal.
        max_revisions: Max number of plan revision rounds.
        timeout: Per-command timeout in seconds.
        reset_cmd: Optional shell command run in ``cwd`` before every condition
            (including on revision retries). Used to restore a clean baseline
            between conditions (e.g., ``"git checkout -- ."`` in a git worktree).
            If the reset fails, the condition is recorded as failed with the
            reset's exit code and the condition's own cmd is skipped. The
            recorded ``cmd`` is still the condition's cmd; only ``exit_code``,
            ``stdout_tail``, and ``stderr_tail`` reflect the reset, with
            ``[RESET FAILED] <reset_cmd>`` appended to stderr_tail.

    Returns:
        The execution_results dict (also written to iter_dir/execution_results.json).
    """
    cwd = Path(cwd)
    iter_dir = Path(iter_dir)
    results_dir = iter_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # Run setup (fails fast — prerequisite for all arms)
    try:
        setup_results = _run_setup(plan.get("setup", []), cwd, timeout)
    except CommandError as exc:
        logger.warning("Setup failed: %s", exc)
        print(f"    Setup failed: {exc}. Continuing with empty results.", flush=True)
        results = {"setup_results": [], "arms": []}
        output = {"plan_ref": f"runs/{iter_dir.name}/experiment_plan.yaml", **results}
        atomic_write(iter_dir / "execution_results.json", json.dumps(output, indent=2) + "\n")
        return output

    # Run all arms (failures recorded, not raised)
    arm_results = _run_all_arms(plan["arms"], cwd, results_dir, timeout, reset_cmd)

    # Retry loop: only re-run failed arms
    revisions_used = 0
    while True:
        failed_arms = _get_failed_arm_ids(arm_results)
        if not failed_arms:
            break  # all arms passed

        if revision_fn is None or revisions_used >= max_revisions:
            logger.warning(
                "Arms failed %s, no more revisions (used %d/%d).",
                failed_arms, revisions_used, max_revisions,
            )
            print(
                f"    {len(failed_arms)} arm(s) failed — no more revisions. "
                f"Continuing with partial results.",
                flush=True,
            )
            break

        revisions_used += 1
        # Build error info from first failure
        first_failure = _first_failed_condition(arm_results)
        error_info = {
            "failed_step": first_failure["step"],
            "cmd": first_failure["cmd"],
            "exit_code": first_failure["exit_code"],
            "stderr_tail": first_failure["stderr_tail"],
            "stdout_tail": first_failure["stdout_tail"],
        }
        error_path = iter_dir / f"execution_error_v{revisions_used}.json"
        atomic_write(error_path, json.dumps(error_info, indent=2) + "\n")

        logger.warning(
            "Arms failed %s (revision %d/%d).",
            failed_arms, revisions_used, max_revisions,
        )
        print(
            f"    {len(failed_arms)} arm(s) failed — requesting revised plan "
            f"(revision {revisions_used}/{max_revisions})...",
            flush=True,
        )

        try:
            plan = revision_fn(plan, error_info)
        except Exception as rev_exc:
            logger.warning(
                "Revision failed (%s): %s. Keeping partial results.",
                type(rev_exc).__name__, rev_exc,
            )
            print(f"    Revision failed ({type(rev_exc).__name__}). Continuing with partial results.", flush=True)
            break

        # Save revised plan
        revised_path = iter_dir / f"experiment_plan_v{revisions_used + 1}.yaml"
        atomic_write(
            revised_path,
            yaml.safe_dump(plan, default_flow_style=False, sort_keys=False),
        )

        # Re-run only failed arms from the revised plan
        retry_arms = [a for a in plan["arms"] if a["arm_id"] in failed_arms]
        retry_results = _run_all_arms(retry_arms, cwd, results_dir, timeout, reset_cmd)

        # Merge: replace failed arms with retry results
        retry_by_id = {r["arm_id"]: r for r in retry_results}
        arm_results = [
            retry_by_id[a["arm_id"]] if a["arm_id"] in retry_by_id else a
            for a in arm_results
        ]

    results = {"setup_results": setup_results, "arms": arm_results}
    output = {"plan_ref": f"runs/{iter_dir.name}/experiment_plan.yaml", **results}
    atomic_write(iter_dir / "execution_results.json", json.dumps(output, indent=2) + "\n")
    logger.info("Wrote execution_results.json (%d arms)", len(arm_results))
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


def _run_all_arms(
    arms: list[dict], cwd: Path, results_dir: Path, timeout: int,
    reset_cmd: str | None = None,
) -> list[dict]:
    """Run all arms, recording failures without stopping."""
    arm_results = []
    for arm in arms:
        arm_result = _run_arm(arm, cwd, results_dir, timeout, reset_cmd)
        arm_results.append(arm_result)
    return arm_results


def _get_failed_arm_ids(arm_results: list[dict]) -> list[str]:
    """Return arm_ids that have any non-zero exit_code condition."""
    failed = []
    for arm in arm_results:
        for cond in arm["conditions"]:
            if cond["exit_code"] != 0:
                failed.append(arm["arm_id"])
                break
    return failed


def _first_failed_condition(arm_results: list[dict]) -> dict:
    """Return info about the first failed condition (for error reporting)."""
    for arm in arm_results:
        for cond in arm["conditions"]:
            if cond["exit_code"] != 0:
                return {
                    "step": f"{arm['arm_id']}/{cond['name']}",
                    "cmd": cond["cmd"],
                    "exit_code": cond["exit_code"],
                    "stderr_tail": cond["stderr_tail"],
                    "stdout_tail": cond["stdout_tail"],
                }
    raise AssertionError(
        "_first_failed_condition called but no failed condition found. "
        "This indicates a bug in _get_failed_arm_ids or arm_results mutation."
    )


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


def _run_arm(
    arm: dict, cwd: Path, results_dir: Path, timeout: int,
    reset_cmd: str | None = None,
) -> dict:
    """Run all conditions in an arm. Records failures without raising."""
    arm_id = arm["arm_id"]
    arm_dir = results_dir / arm_id
    arm_dir.mkdir(parents=True, exist_ok=True)

    conditions = []
    for cond in arm["conditions"]:
        name = cond["name"]
        cmd = cond["cmd"]
        output_path = cond.get("output")

        if reset_cmd is not None:
            reset_res = _run_cmd(reset_cmd, cwd, timeout)
            if reset_res.returncode != 0:
                logger.warning(
                    "Reset failed for %s/%s (exit %d)",
                    arm_id, name, reset_res.returncode,
                )
                print(
                    f"    [{arm_id}] {name}: [reset failed, skipping] {reset_cmd}",
                    flush=True,
                )
                (arm_dir / f"{name}.stdout").write_text(reset_res.stdout)
                (arm_dir / f"{name}.stderr").write_text(reset_res.stderr)
                conditions.append({
                    "name": name,
                    "cmd": cmd,
                    "exit_code": reset_res.returncode,
                    "stdout_tail": _truncate(reset_res.stdout),
                    "stderr_tail": _truncate(
                        (reset_res.stderr or "") + f"\n[RESET FAILED] {reset_cmd}"
                    ),
                    "output_content": None,
                })
                continue

        print(f"    [{arm_id}] {name}: {cmd}", flush=True)
        result = _run_cmd(cmd, cwd, timeout)

        # Save stdout/stderr logs
        (arm_dir / f"{name}.stdout").write_text(result.stdout)
        (arm_dir / f"{name}.stderr").write_text(result.stderr)

        if result.returncode != 0:
            logger.warning("Condition %s/%s failed (exit %d)", arm_id, name, result.returncode)
            conditions.append({
                "name": name,
                "cmd": cmd,
                "exit_code": result.returncode,
                "stdout_tail": _truncate(result.stdout),
                "stderr_tail": _truncate(result.stderr),
                "output_content": None,
            })
            continue

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
    """Run a single shell command. Timeouts return exit_code=-1 instead of raising."""
    try:
        return subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args=cmd, returncode=-1,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "") + f"\n[TIMEOUT] Command timed out after {timeout}s",
        )


def _truncate(text: str, max_chars: int = _MAX_OUTPUT_CHARS) -> str:
    """Keep the last max_chars characters."""
    if len(text) <= max_chars:
        return text
    return f"...(truncated, showing last {max_chars} chars)...\n" + text[-max_chars:]
