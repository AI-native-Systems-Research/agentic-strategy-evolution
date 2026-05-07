"""Deterministic experiment execution for the Nous orchestrator.

Reads an experiment_plan.yaml and replays its commands via subprocess.
No LLM calls — purely deterministic execution. Commands are expected
to be pre-validated by the plan-execution agent.
"""
import json
import logging
import shutil
import subprocess
from pathlib import Path

from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS = 12000


def execute_plan(
    plan: dict,
    cwd: Path,
    iter_dir: Path,
    *,
    timeout: int = 300,
    reset_cmd: str | None = None,
) -> dict:
    """Replay a pre-validated experiment plan and collect results.

    Arms run independently — a failure in one arm does not block others.
    No retries — the plan-execution agent already validated all commands.

    Args:
        plan: Parsed experiment_plan.yaml dict.
        cwd: Working directory for commands (typically the worktree).
        iter_dir: Iteration directory — results are written here.
        timeout: Per-command timeout in seconds.
        reset_cmd: Shell command run before every condition to restore clean
            state (e.g., ``"git checkout -- ."``).

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

    # Persist patches from worktree into the experiment directory
    patches_src = cwd / "patches"
    if patches_src.is_dir():
        patches_dst = iter_dir / "patches"
        if patches_dst.exists():
            shutil.rmtree(patches_dst)
        shutil.copytree(patches_src, patches_dst)
        logger.info("Copied patches/ to %s", patches_dst)

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
