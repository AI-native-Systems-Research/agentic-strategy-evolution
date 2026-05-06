"""CLI-based agent dispatch for the Nous orchestrator.

Invokes `claude -p` as a subprocess for agents that need code access
and shell tools (planner, executor).
"""
import json
import logging
import subprocess
from contextlib import contextmanager
from pathlib import Path

import jsonschema
import yaml

from orchestrator.llm_dispatch import LLMDispatcher
from orchestrator.metrics import log_metrics
from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)


class CLIDispatcher(LLMDispatcher):
    """Dispatch agent roles via `claude -p` subprocess.

    Inherits routing, context building, parsing, and validation from LLMDispatcher.
    Overrides the LLM call to use `claude -p` instead of the API.
    """

    def __init__(
        self,
        work_dir: Path,
        campaign: dict,
        model: str = "aws/claude-sonnet-4-5",
        prompts_dir: Path | None = None,
        timeout: int = 1800,
        max_turns: int = 25,
    ) -> None:
        super().__init__(
            work_dir=work_dir,
            campaign=campaign,
            model=model,
            prompts_dir=prompts_dir,
            completion_fn=lambda **kw: (_ for _ in ()).throw(
                RuntimeError("CLIDispatcher does not use the completion API")
            ),
        )
        self.timeout = timeout
        self.max_turns = max_turns
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

        self._current_role = role
        self._current_phase = phase

        template, fmt, schema_name = self._route(role, phase)
        context = self._build_context(role, phase, iteration, perspective)
        prompt = self.loader.load(template, context)

        response = self._call_claude(prompt)

        if fmt is None:
            atomic_write(output_path, response)
        else:
            try:
                data = self._extract_fenced_content(response, fmt)
            except (json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
                logger.warning(
                    "Parse failed for %s/%s (%s), retrying with feedback.",
                    role, phase, exc,
                )
                data = self._retry_cli_parse(prompt, exc, fmt)

            if schema_name is not None:
                try:
                    self._validate(data, schema_name)
                except jsonschema.ValidationError as exc:
                    logger.warning(
                        "Schema validation failed for %s/%s, retrying: %s",
                        role, phase, exc.message,
                    )
                    data = self._retry_cli_schema(prompt, exc, fmt, schema_name)

            if fmt == "yaml":
                atomic_write(
                    output_path,
                    yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
                )
            else:
                atomic_write(output_path, json.dumps(data, indent=2) + "\n")

        logger.info("CLIDispatcher: role=%s phase=%s -> %s", role, phase, output_path)

    def _retry_cli_parse(self, original_prompt: str, error: Exception, fmt: str) -> dict:
        feedback = (
            f"Your previous response could not be parsed.\n\n"
            f"Error: {error}\n\n"
            f"Please output ONLY a ```{fmt}``` code fence with valid "
            f"{fmt.upper()} inside. No explanation outside the fence."
        )
        response = self._call_claude(f"{original_prompt}\n\n---\n\n{feedback}")
        try:
            return self._extract_fenced_content(response, fmt)
        except (json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
            raise RuntimeError(
                f"claude -p retry response could not be parsed as {fmt}: {exc}"
            ) from exc

    def _retry_cli_schema(
        self, original_prompt: str, error: jsonschema.ValidationError,
        fmt: str, schema_name: str,
    ) -> dict:
        feedback = (
            f"Your output failed schema validation:\n{error.message}\n\n"
            f"Please fix the issue and return only the corrected "
            f"{fmt} in a code fence."
        )
        response = self._call_claude(f"{original_prompt}\n\n---\n\n{feedback}")
        try:
            data = self._extract_fenced_content(response, fmt)
        except (json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
            raise RuntimeError(
                f"claude -p retry response could not be parsed as {fmt}: {exc}"
            ) from exc
        self._validate(data, schema_name)
        return data

    def _call_claude(self, prompt: str, max_turns: int | None = None) -> str:
        """Invoke `claude -p` with the prompt on stdin."""
        cmd = ["claude", "-p", "--model", self.model, "--output-format", "json",
               "--dangerously-skip-permissions"]
        turns = max_turns or self.max_turns
        cmd += ["--max-turns", str(turns)]
        cwd = self._cwd
        if cwd and not cwd.exists():
            raise RuntimeError(
                f"CLIDispatcher cwd does not exist: {cwd}. "
                f"Check that 'repo_path' in campaign.yaml is correct."
            )
        logger.info(
            "Calling claude -p (model=%s, cwd=%s, timeout=%ds, max_turns=%d)",
            self.model, cwd, self.timeout, turns,
        )
        print(f"    Waiting for claude -p ({self.model}, max_turns={turns})...", flush=True)
        try:
            result = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True,
                cwd=cwd, timeout=self.timeout,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "claude CLI not found. Install Claude Code: "
                "https://docs.anthropic.com/en/docs/claude-code"
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"claude -p timed out after {self.timeout}s."
            )

        if result.returncode != 0:
            stderr_tail = result.stderr[-2000:] if result.stderr else "(no stderr)"
            stdout_tail = result.stdout[-2000:] if result.stdout else "(no stdout)"
            raise RuntimeError(
                f"claude -p exited with code {result.returncode}.\n"
                f"stderr: {stderr_tail}\nstdout: {stdout_tail}"
            )

        try:
            response_json = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.error("claude -p output not valid JSON; metrics not recorded.")
            return result.stdout

        usage = response_json.get("usage", {})
        log_metrics(self._metrics_path, {
            "dispatcher": "cli",
            "role": self._current_role,
            "phase": self._current_phase,
            "model": self.model,
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
            "cost_usd": response_json.get("total_cost_usd", 0),
            "duration_ms": response_json.get("duration_ms", 0),
            "num_turns": response_json.get("num_turns", 0),
        })

        if response_json.get("is_error"):
            raise RuntimeError(
                f"claude -p returned an error: {response_json.get('result', 'unknown')}"
            )

        response_text = response_json.get("result", "")
        logger.info(
            "claude -p returned (%d chars, $%.4f)",
            len(response_text), response_json.get("total_cost_usd", 0),
        )
        return response_text
