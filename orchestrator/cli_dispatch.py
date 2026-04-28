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
import subprocess
from contextlib import contextmanager
from pathlib import Path

import yaml

from orchestrator.llm_dispatch import LLMDispatcher
from orchestrator.prompt_loader import PromptLoader
from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)


class CLIDispatcher:
    """Dispatch agent roles via `claude -p` subprocess.

    Implements the same Dispatcher protocol as LLMDispatcher.
    Used for planner and executor roles that need code/shell access.

    Shares LLMDispatcher's routing table and delegates context building
    to a temporary LLMDispatcher (with dummy completion_fn — no API key needed).
    """

    # Reuse the same routing table from LLMDispatcher
    _ROUTES = LLMDispatcher._ROUTES

    def __init__(
        self,
        work_dir: Path,
        campaign: dict,
        model: str = "aws/claude-opus-4-6",
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

    @contextmanager
    def override_cwd(self, cwd: Path):
        """Temporarily override the subprocess working directory."""
        old = self._cwd
        self._cwd = cwd
        try:
            yield
        finally:
            self._cwd = old

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

    # Reuse LLMDispatcher's static parsing/validation methods
    _extract_fenced_content = staticmethod(LLMDispatcher._extract_fenced_content)

    def _call_claude(self, prompt: str) -> str:
        """Invoke `claude -p` with the prompt on stdin, return stdout."""
        cmd = ["claude", "-p", "--model", self.model]
        cwd = self._cwd if self._cwd and self._cwd.exists() else None
        logger.info(
            "Calling claude -p (model=%s, cwd=%s, timeout=%ds, prompt=%d chars)",
            self.model, cwd, self.timeout, len(prompt),
        )
        print(f"    Waiting for claude -p ({self.model})...", flush=True)
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

        logger.info("claude -p returned (%d chars)", len(result.stdout))
        return result.stdout
