"""In-process hooks: record Bash commands, gate Stop, write a digest before compaction."""

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
from .validators import read_json

logger = logging.getLogger(__name__)


DEFAULT_EXPERIMENT_COMMANDS: list[str] = [
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
    phase: str = "INVESTIGATE"  # recorded in each runs.jsonl row
    iteration: int = 0  # recorded as `iter` in each runs.jsonl row
    secrets: dict[str, str] = field(default_factory=dict)
    experiment_commands: list[str] = field(default_factory=list)
    cwd: str | None = None  # the working copy
    now: Callable[[], float] = field(default=time.time)


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
        error = hook_input.get("error", "")
        m = _EXIT_CODE_RE.search(error)
        exit_code = int(m.group(1)) if m else -1
        row = _build_row(state, hook_input, exit_code=exit_code, background=False)
        _append_runs_jsonl(state.work_dir, row)
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
        baseline = read_json(state.work_dir / "baseline.json")
        digest["baseline"] = None
        if baseline is not None:
            digest["baseline"] = {
                "task_type": baseline.get("task_type"),
                "command": baseline.get("command"),
                "git_sha": baseline.get("git_sha"),
                "noise": baseline.get("noise"),
            }

        # Kept so the digest format stays the same; Lightweight writes no principles.json
        principles = read_json(state.work_dir / "principles.json")
        digest["principles"] = principles if principles is not None else []

        # Kept so the digest format stays the same; Lightweight has no iteration dirs
        digest["last_findings"] = None
        digest["active_hypotheses"] = []

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


def build_hooks(state: HookState, stop_hook: Callable) -> dict[str, list[HookMatcher]]:
    """Build the hooks dict for ClaudeAgentOptions.hooks; *stop_hook* gates the end of a turn."""
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
                hooks=[stop_hook],
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
