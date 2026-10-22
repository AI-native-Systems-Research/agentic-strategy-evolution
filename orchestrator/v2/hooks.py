"""Nous v2 in-process hooks (spec 3.3)."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk.types import HookMatcher

from .secrets import mask_secrets
from .validators import ValidatorContext, validate_artifact

logger = logging.getLogger(__name__)


DEFAULT_EXPERIMENT_COMMANDS: list[str] = [
    r"\bblis\s+run\b",
    r"\bpython3?\s+\S*(search|bench|run|sweep)\S*\.py\b",
    r"\bmake\s+bench",
]

_COMPILED_CACHE: dict[tuple[str, ...], list[re.Pattern[str]]] = {}


def _compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    key = tuple(patterns)
    if key not in _COMPILED_CACHE:
        _COMPILED_CACHE[key] = [re.compile(p) for p in patterns]
    return _COMPILED_CACHE[key]


def is_experiment_command(command: str, patterns: list[str]) -> bool:
    for pat in _compile_patterns(patterns):
        if pat.search(command):
            return True
    return False




@dataclass
class HookState:
    """Mutable state shared across all hook callbacks within a campaign."""

    work_dir: Path
    phase: str = "BASELINE"
    iteration: int = 0
    secrets: dict[str, str] = field(default_factory=dict)
    experiment_commands: list[str] = field(default_factory=list)
    consecutive_blocks: int = 0
    pending_wait_for: list[str] = field(default_factory=list)
    now: Callable[[], float] = field(default=time.time)
    # Campaign limits passed to every ValidatorContext (spec 3.4).
    limits: dict[str, Any] = field(default_factory=dict)



_PHASE_ARTIFACTS: dict[str, list[str]] = {
    "BASELINE": ["baseline"],
    "DESIGN": ["problem", "bundle", "plan"],
    "EXECUTE": ["findings", "principle_updates"],
    "REPORT": ["answer"],
}

_EXIT_CODE_RE = re.compile(r"Exit code (\d+)")




def _stringify_tool_response(tool_response: Any) -> str:
    """Ensure tool_response is a string for masking and byte counting."""
    if isinstance(tool_response, str):
        return tool_response
    return json.dumps(tool_response, default=str)


def _build_row(
    state: HookState, hook_input: dict, *, exit_code: int | None, background: bool,
) -> dict[str, Any]:
    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")
    response_str = _stringify_tool_response(hook_input.get("tool_response", ""))
    return {
        "ts": state.now(),
        "phase": state.phase,
        "iter": state.iteration,
        "tool_use_id": hook_input.get("tool_use_id", ""),
        "command": mask_secrets(command, state.secrets),
        "exit_code": exit_code,
        "output_bytes": len(response_str.encode("utf-8")),
        "cwd": tool_input.get("cwd", ""),
        "background": background,
        "agent_id": hook_input.get("session_id", ""),
        "experiment": is_experiment_command(command, state.experiment_commands),
    }


def make_post_tool_use_hook(state: HookState):
    """Create a PostToolUse callback that records Bash commands to runs.jsonl."""

    async def hook(hook_input: dict, _tool_use_id: str | None, _ctx: Any) -> dict:
        if hook_input.get("tool_name") != "Bash":
            return {}
        state.consecutive_blocks = 0
        is_bg = bool(hook_input.get("tool_input", {}).get("run_in_background", False))
        row = _build_row(state, hook_input, exit_code=None if is_bg else 0, background=is_bg)
        _append_runs_jsonl(state.work_dir, row)
        return {}

    return hook




def make_post_tool_use_failure_hook(state: HookState):
    """Create a PostToolUseFailure callback that records failed Bash commands."""

    async def hook(hook_input: dict, _tool_use_id: str | None, _ctx: Any) -> dict:
        if hook_input.get("tool_name") != "Bash":
            return {}
        state.consecutive_blocks = 0
        error = hook_input.get("error", "")
        m = _EXIT_CODE_RE.search(error)
        exit_code = int(m.group(1)) if m else -1
        row = _build_row(state, hook_input, exit_code=exit_code, background=False)
        _append_runs_jsonl(state.work_dir, row)
        return {}

    return hook




def make_stop_hook(state: HookState):
    """Create a Stop callback that validates phase artifacts before allowing stop."""

    async def hook(hook_input: dict, _tool_use_id: str | None, _ctx: Any) -> dict:
        if state.consecutive_blocks >= 6:
            state.consecutive_blocks = 0
            return {}

        if state.pending_wait_for and _any_wait_pending(state.pending_wait_for):
            state.consecutive_blocks = 0
            return {}

        artifact_types = _PHASE_ARTIFACTS.get(state.phase, [])
        all_errors: list[str] = []

        for artifact_type in artifact_types:
            path = _artifact_path(state, artifact_type)
            if not path.exists():
                all_errors.append(f"{artifact_type}: file not found at {path.name}")
                continue

            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                all_errors.append(f"{artifact_type}: invalid JSON — {exc}")
                continue

            ctx = ValidatorContext(
                work_dir=state.work_dir, iter_dir=_iter_dir(state), **state.limits,
            )
            errors = validate_artifact(artifact_type, data, ctx)
            for e in errors:
                all_errors.append(f"{artifact_type}: {e}")

        if all_errors:
            state.consecutive_blocks += 1
            error_text = "\n".join(f"  - {e}" for e in all_errors)
            return {
                "decision": "block",
                "reason": f"Phase {state.phase} validation failed:\n{error_text}",
            }

        state.consecutive_blocks = 0
        return {}

    return hook




def make_precompact_hook(state: HookState):
    """Create a PreCompact callback that writes state/digest.json."""

    async def hook(hook_input: dict, _tool_use_id: str | None, _ctx: Any) -> dict:
        digest: dict[str, Any] = {
            "phase": state.phase,
            "iteration": state.iteration,
        }

        # Baseline summary
        baseline_path = state.work_dir / "baseline.json"
        if baseline_path.exists():
            try:
                baseline = json.loads(baseline_path.read_text())
                digest["baseline"] = {
                    "task_type": baseline.get("task_type"),
                    "command": baseline.get("command"),
                    "git_sha": baseline.get("git_sha"),
                    "noise": baseline.get("noise"),
                }
            except json.JSONDecodeError:
                logger.warning("corrupt baseline.json in digest")
                digest["baseline"] = None
        else:
            digest["baseline"] = None

        # Active principles
        principles_path = state.work_dir / "principles.json"
        if principles_path.exists():
            try:
                digest["principles"] = json.loads(principles_path.read_text())
            except json.JSONDecodeError:
                logger.warning("corrupt principles.json in digest")
                digest["principles"] = []
        else:
            digest["principles"] = []

        # Last findings summary and active hypotheses
        iter_dir = _iter_dir(state)
        digest["last_findings"] = None
        digest["active_hypotheses"] = []
        if iter_dir:
            findings_path = iter_dir / "findings.json"
            if findings_path.exists():
                try:
                    digest["last_findings"] = json.loads(findings_path.read_text())
                except json.JSONDecodeError:
                    logger.warning("corrupt findings.json in digest")

            bundle_path = iter_dir / "bundle.json"
            if bundle_path.exists():
                try:
                    bundle = json.loads(bundle_path.read_text())
                    digest["active_hypotheses"] = [
                        {"id": h.get("id"), "mechanism": h.get("mechanism")}
                        for h in bundle.get("hypotheses", [])
                    ]
                except json.JSONDecodeError:
                    logger.warning("corrupt bundle.json in digest")

        # Secret-mask the entire digest
        text = json.dumps(digest, indent=2)
        text = mask_secrets(text, state.secrets)

        digest_dir = state.work_dir / "state"
        digest_dir.mkdir(parents=True, exist_ok=True)
        try:
            (digest_dir / "digest.json").write_text(text + "\n")
        except OSError:
            logger.error("Failed to write digest.json", exc_info=True)

        return {}

    return hook




def build_hooks(state: HookState) -> dict[str, list[HookMatcher]]:
    """Build the hooks dict for ClaudeAgentOptions.hooks."""
    return {
        "PostToolUse": [
            HookMatcher(
                matcher="Bash",
                hooks=[make_post_tool_use_hook(state)],
                timeout=30.0,
            )
        ],
        "PostToolUseFailure": [
            HookMatcher(
                matcher="Bash",
                hooks=[make_post_tool_use_failure_hook(state)],
                timeout=30.0,
            )
        ],
        "Stop": [
            HookMatcher(
                matcher="",
                hooks=[make_stop_hook(state)],
                timeout=120.0,
            )
        ],
        "PreCompact": [
            HookMatcher(
                matcher="",
                hooks=[make_precompact_hook(state)],
                timeout=60.0,
            )
        ],
    }




def _append_runs_jsonl(work_dir: Path, row: dict) -> None:
    path = work_dir / "runs.jsonl"
    try:
        with open(path, "a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        logger.error("Failed to write runs.jsonl at %s", path, exc_info=True)


def _iter_dir(state: HookState) -> Path | None:
    if state.iteration <= 0:
        return None
    return state.work_dir / "runs" / f"iter-{state.iteration}"


def _any_wait_pending(wait_specs: list[str]) -> bool:
    """True if at least one wait_for condition is still unmet."""
    from .robustness import check_wait_condition
    return any(not check_wait_condition(spec) for spec in wait_specs)


def _artifact_path(state: HookState, artifact_type: str) -> Path:
    if artifact_type == "baseline":
        return state.work_dir / "baseline.json"
    if artifact_type == "answer":
        return state.work_dir / "answer.json"
    iter_dir = _iter_dir(state)
    if iter_dir is None:
        return state.work_dir / f"{artifact_type}.json"
    return iter_dir / f"{artifact_type}.json"
