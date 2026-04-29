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

import jsonschema
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
    to an internal LLMDispatcher instance (with dummy completion_fn — no
    API key needed).
    """

    # Reuse the same routing table from LLMDispatcher
    _ROUTES = LLMDispatcher._ROUTES

    def __init__(
        self,
        work_dir: Path,
        campaign: dict,
        model: str = "aws/claude-sonnet-4-5",
        prompts_dir: Path | None = None,
        timeout: int = 1800,
        max_turns: int = 25,
    ) -> None:
        self.work_dir = Path(work_dir)
        LLMDispatcher._validate_campaign(campaign)
        self.campaign = campaign
        self.model = model
        self.timeout = timeout
        self.max_turns = max_turns
        resolved_prompts_dir = (
            prompts_dir
            or Path(__file__).parent.parent / "prompts" / "methodology"
        )
        self.loader = PromptLoader(resolved_prompts_dir)
        # Shared LLMDispatcher for context building only (completion_fn is never called).
        self._context_builder = LLMDispatcher(
            work_dir=work_dir,
            campaign=campaign,
            model=model,
            prompts_dir=resolved_prompts_dir,
            completion_fn=lambda **kw: (_ for _ in ()).throw(
                RuntimeError("CLIDispatcher: completion_fn should never be called")
            ),
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

    def revise_plan(self, plan: dict, error_info: dict) -> dict:
        """Call claude -p to revise a failed experiment plan.

        Used by orchestrator/executor.py when a command fails during
        the EXECUTING phase.  Returns the corrected plan dict.
        """
        context = {
            "experiment_plan_yaml": yaml.safe_dump(
                plan, default_flow_style=False, sort_keys=False,
            ),
            "error_info": json.dumps(error_info, indent=2),
        }
        prompt = self.loader.load("run_plan_revise", context)
        response = self._call_claude(prompt)
        data = self._extract_fenced_content(response, "yaml")
        LLMDispatcher._validate(data, "experiment_plan.schema.yaml")
        return data

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
            try:
                data = self._extract_fenced_content(response, fmt)
            except (json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
                logger.warning(
                    "Parse failed for %s/%s (%s), retrying with feedback.",
                    role, phase, exc,
                )
                data = self._retry_parse(prompt, response, exc, fmt)

            if schema_name is not None:
                try:
                    LLMDispatcher._validate(data, schema_name)
                except jsonschema.ValidationError as exc:
                    logger.warning(
                        "Schema validation failed for %s/%s, retrying: %s",
                        role, phase, exc.message,
                    )
                    data = self._retry_schema(prompt, exc, fmt, schema_name)

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
        """Build prompt context — delegates to shared LLMDispatcher instance."""
        return self._context_builder._build_context(role, phase, iteration, perspective)

    # Reuse LLMDispatcher's static parsing/validation methods
    _extract_fenced_content = staticmethod(LLMDispatcher._extract_fenced_content)

    def _retry_parse(
        self,
        original_prompt: str,
        original_response: str,
        error: Exception,
        fmt: str,
    ) -> dict:
        """Retry when claude -p output couldn't be parsed."""
        feedback = (
            f"Your previous response could not be parsed.\n\n"
            f"Error: {error}\n\n"
            f"Please output ONLY a ```{fmt}``` code fence with valid "
            f"{fmt.upper()} inside. No explanation outside the fence."
        )
        retry_prompt = f"{original_prompt}\n\n---\n\n{feedback}"
        retry_response = self._call_claude(retry_prompt)
        try:
            return self._extract_fenced_content(retry_response, fmt)
        except (json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
            raise RuntimeError(
                f"claude -p retry response could not be parsed as {fmt}: {exc}"
            ) from exc

    def _retry_schema(
        self,
        original_prompt: str,
        error: jsonschema.ValidationError,
        fmt: str,
        schema_name: str,
    ) -> dict:
        """Retry when claude -p output failed schema validation."""
        feedback = (
            f"Your output failed schema validation:\n{error.message}\n\n"
            f"Please fix the issue and return only the corrected "
            f"{fmt} in a code fence."
        )
        retry_prompt = f"{original_prompt}\n\n---\n\n{feedback}"
        retry_response = self._call_claude(retry_prompt)
        try:
            data = self._extract_fenced_content(retry_response, fmt)
        except (json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
            raise RuntimeError(
                f"claude -p retry response could not be parsed as {fmt}: {exc}"
            ) from exc
        LLMDispatcher._validate(data, schema_name)
        return data

    def _call_claude(self, prompt: str, max_turns: int | None = None) -> str:
        """Invoke `claude -p` with the prompt on stdin, return stdout."""
        cmd = ["claude", "-p", "--model", self.model]
        turns = max_turns or self.max_turns
        cmd += ["--max-turns", str(turns)]
        cwd = self._cwd
        if cwd and not cwd.exists():
            raise RuntimeError(
                f"CLIDispatcher cwd does not exist: {cwd}. "
                f"Check that 'repo_path' in campaign.yaml is correct, "
                f"or that the experiment worktree was created successfully."
            )
        logger.info(
            "Calling claude -p (model=%s, cwd=%s, timeout=%ds, max_turns=%d, prompt=%d chars)",
            self.model, cwd, self.timeout, turns, len(prompt),
        )
        print(f"    Waiting for claude -p ({self.model}, max_turns={turns})...", flush=True)
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
