"""CLI-based agent dispatch for the Nous orchestrator.

Invokes `claude -p` as a subprocess for agents that need code access
and shell tools (planner, executor). Uses the same routing table and
prompt templates as LLMDispatcher, but sends the prompt via stdin to
`claude -p` instead of calling an LLM API.

Agents dispatched via CLIDispatcher can:
- Read files and grep code in the target repo
- Run shell commands (executor)
- Reason about code structure to discover metrics, knobs, and execution methods
"""
import json
import logging
import re
import subprocess
from pathlib import Path

import jsonschema
import yaml

from orchestrator.llm_dispatch import LLMDispatcher
from orchestrator.prompt_loader import PromptLoader
from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)

_FENCE_RE = {
    "yaml": re.compile(r"```yaml\s*\n(.*?)```", re.DOTALL | re.IGNORECASE),
    "json": re.compile(r"```json\s*\n(.*?)```", re.DOTALL | re.IGNORECASE),
}


class CLIDispatcher:
    """Dispatch agent roles via `claude -p` subprocess.

    Implements the same Dispatcher protocol as LLMDispatcher.
    Used for planner and executor roles that need code/shell access.

    Shares LLMDispatcher's routing table and uses its own PromptLoader
    and context builder — does NOT instantiate LLMDispatcher.
    """

    # Reuse the same routing table from LLMDispatcher
    _ROUTES = LLMDispatcher._ROUTES

    def __init__(
        self,
        work_dir: Path,
        campaign: dict,
        model: str = "claude-sonnet-4-20250514",
        prompts_dir: Path | None = None,
        timeout: int = 600,
    ) -> None:
        self.work_dir = Path(work_dir)
        self.campaign = campaign
        self.model = model
        self.timeout = timeout
        self.loader = PromptLoader(
            prompts_dir
            or Path(__file__).parent.parent / "prompts" / "methodology"
        )
        repo_path = campaign.get("target_system", {}).get("repo_path")
        self._cwd = Path(repo_path) if repo_path else None

    def dispatch(
        self,
        role: str,
        phase: str,
        *,
        output_path: Path,
        iteration: int,
        perspective: str | None = None,
        h_main_result: str = "CONFIRMED",
    ) -> None:
        """Dispatch via claude -p subprocess."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        template, fmt, schema_name = self._route(role, phase)
        context = self._build_context(role, phase, iteration, perspective)
        prompt = self.loader.load(template, context)

        response = self._call_claude(prompt)

        if fmt is None:
            # Plain markdown — write directly
            atomic_write(output_path, response)
        else:
            data = self._extract_fenced_content(response, fmt)
            if schema_name is not None:
                LLMDispatcher._validate(data, schema_name)

            if fmt == "yaml":
                atomic_write(
                    output_path,
                    yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
                )
            else:
                atomic_write(output_path, json.dumps(data, indent=2) + "\n")

        logger.info(
            "CLIDispatcher: role=%s phase=%s -> %s", role, phase, output_path
        )

    def _route(
        self, role: str, phase: str
    ) -> tuple[str, str | None, str | None]:
        key = (role, phase)
        if key not in self._ROUTES:
            raise ValueError(f"Unknown role/phase combination: {role}/{phase}")
        return self._ROUTES[key]

    def _build_context(
        self,
        role: str,
        phase: str,
        iteration: int,
        perspective: str | None,
    ) -> dict[str, str]:
        """Build prompt context — mirrors LLMDispatcher._build_context."""
        # Delegate to a temporary LLMDispatcher for context building.
        # This is a pure data method — the completion_fn is never called.
        inner = LLMDispatcher(
            work_dir=self.work_dir,
            campaign=self.campaign,
            model=self.model,
            prompts_dir=self.loader.prompts_dir,
            completion_fn=lambda **kw: (_ for _ in ()).throw(
                RuntimeError("CLIDispatcher: completion_fn should never be called")
            ),
        )
        return inner._build_context(role, phase, iteration, perspective)

    @staticmethod
    def _extract_fenced_content(text: str, fmt: str) -> dict:
        """Extract and parse content from a code-fenced block.

        Same logic as LLMDispatcher._extract_fenced_content.
        """
        pattern = _FENCE_RE.get(fmt)
        if pattern is None:
            raise ValueError(f"Unsupported format: {fmt}")

        matches = pattern.findall(text)
        if matches:
            raw = matches[-1]
        else:
            raise ValueError(
                f"No ```{fmt}``` code fence found in claude -p output "
                f"({len(text)} chars). Expected fenced {fmt} block."
            )

        parsed = yaml.safe_load(raw) if fmt == "yaml" else json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(
                f"Expected a {fmt} object, got {type(parsed).__name__}"
            )
        return parsed

    def _call_claude(self, prompt: str) -> str:
        """Invoke `claude -p` with the prompt on stdin, return stdout."""
        cmd = ["claude", "-p", "--model", self.model]
        cwd = self._cwd if self._cwd and self._cwd.exists() else None
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=self.timeout,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "claude CLI not found. Install Claude Code: "
                "https://docs.anthropic.com/en/docs/claude-code"
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"claude -p timed out after {self.timeout}s. "
                "The agent may be stuck."
            )

        if result.returncode != 0:
            stderr_tail = result.stderr[-2000:] if result.stderr else "(no stderr)"
            raise RuntimeError(
                f"claude -p exited with code {result.returncode}.\n"
                f"stderr: {stderr_tail}"
            )

        return result.stdout
