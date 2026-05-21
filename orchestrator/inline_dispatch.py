"""Inline dispatch for the Nous orchestrator.

Emits prompts to stdout so the calling CLI agent reasons about them
directly — no subprocess, no API key. The agent writes artifacts to
the iteration directory as instructed by the prompt.

This dispatcher is designed for environments where Nous runs inside
an existing CLI agent session (e.g., a Hive strategist agent using
Copilot CLI or Claude Code). The agent sees the prompt as part of its
tool output and responds in its own conversation turn.

Usage:
    python run_campaign.py examples/campaign.yaml --agent inline
"""
import json
import logging
import os
import sys
import time
from pathlib import Path

import jsonschema
import yaml

from orchestrator.llm_dispatch import LLMDispatcher
from orchestrator.metrics import log_metrics
from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)

RESPONSE_TIMEOUT_SEC = 300
RESPONSE_POLL_INTERVAL_SEC = 2


class InlineDispatcher(LLMDispatcher):
    """Dispatch agent roles by emitting prompts to stdout.

    The calling agent reads the prompt, reasons about it, and writes
    its response to a designated file. This dispatcher polls for that
    file and processes it.

    For design and execute-analyze phases, the agent writes artifacts
    directly to iter_dir (same as CLIDispatcher). For structured phases
    (gate summaries), the agent writes a JSON response file.
    """

    def __init__(
        self,
        work_dir: Path,
        campaign: dict,
        model: str = "inline",
        prompts_dir: Path | None = None,
        timeout: int = 300,
    ) -> None:
        super().__init__(
            work_dir=work_dir,
            campaign=campaign,
            model=model,
            prompts_dir=prompts_dir,
            completion_fn=lambda **kw: (_ for _ in ()).throw(
                RuntimeError("InlineDispatcher does not use the completion API")
            ),
        )
        self.timeout = timeout

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
        """Emit prompt to stdout and wait for agent response."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self._current_role = role
        self._current_phase = phase

        template, fmt, schema_name = self._route(role, phase)
        context = self._build_context(role, phase, iteration, perspective)
        prompt = self.loader.load(template, context)

        iter_dir = output_path.parent
        response_path = iter_dir / f".nous_response_{role}_{phase.replace('-', '_')}"
        response_path.unlink(missing_ok=True)
        self._clean_stale_artifacts(iter_dir, phase)

        if phase in ("design", "execute-analyze"):
            fmt = None
            schema_name = None

        self._emit_prompt(role, phase, prompt, fmt, schema_name, iter_dir, response_path)

        t0 = time.time()
        response = self._wait_for_response(response_path, output_path, iter_dir, phase, t0)

        self._log_inline_metrics(role, phase, t0)

        if fmt is None:
            atomic_write(output_path, response)
        else:
            try:
                data = self._extract_fenced_content(response, fmt)
            except (json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
                logger.warning(
                    "Parse failed for %s/%s (%s). Agent response may need correction.",
                    role, phase, exc,
                )
                raise RuntimeError(
                    f"Could not parse agent response for {role}/{phase}: {exc}"
                ) from exc

            if schema_name is not None:
                try:
                    self._validate(data, schema_name)
                except jsonschema.ValidationError as exc:
                    logger.warning(
                        "Schema validation failed for %s/%s: %s",
                        role, phase, exc.message,
                    )
                    raise RuntimeError(
                        f"Agent response for {role}/{phase} failed schema validation: {exc.message}"
                    ) from exc

            if fmt == "yaml":
                atomic_write(
                    output_path,
                    yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
                )
            else:
                atomic_write(output_path, json.dumps(data, indent=2) + "\n")

        logger.info("InlineDispatcher: role=%s phase=%s -> %s", role, phase, output_path)

    def _emit_prompt(
        self,
        role: str,
        phase: str,
        prompt: str,
        fmt: str | None,
        schema_name: str | None,
        iter_dir: Path,
        response_path: Path,
    ) -> None:
        """Print the prompt and response instructions to stdout."""
        separator = "=" * 70
        print(f"\n{separator}", flush=True)
        print(f"  NOUS INLINE DISPATCH — {role}/{phase}", flush=True)
        print(f"{separator}\n", flush=True)
        print(prompt, flush=True)
        print(f"\n{separator}", flush=True)
        print(f"  RESPONSE INSTRUCTIONS", flush=True)
        print(f"{separator}\n", flush=True)

        if phase == "design":
            print(
                f"Write your response as files in: {iter_dir}\n\n"
                f"Required files:\n"
                f"  {iter_dir}/problem.md    — Problem framing (markdown)\n"
                f"  {iter_dir}/bundle.yaml   — Hypothesis bundle (YAML)\n"
                f"  {iter_dir}/handoff.md    — Handoff notes for executor (markdown, optional)\n\n"
                f"After writing all files, create the signal file:\n"
                f"  touch {response_path}\n",
                flush=True,
            )
        elif phase == "execute-analyze":
            print(
                f"Write your response as files in: {iter_dir}\n\n"
                f"Required files:\n"
                f"  {iter_dir}/experiment_plan.yaml  — Experiment plan\n"
                f"  {iter_dir}/findings.json         — Findings with metrics\n"
                f"  {iter_dir}/principle_updates.json — Principle updates (list, can be empty [])\n\n"
                f"After writing all files, create the signal file:\n"
                f"  touch {response_path}\n",
                flush=True,
            )
        elif fmt is not None:
            print(
                f"Write your response to: {response_path}\n\n"
                f"The response MUST be a ```{fmt}``` code fence containing valid {fmt.upper()}.\n",
                flush=True,
            )
            if schema_name:
                schema_path = Path(__file__).parent / "schemas" / schema_name
                if schema_path.exists():
                    print(f"Schema: {schema_path}\n", flush=True)
        else:
            print(
                f"Write your response (plain text/markdown) to: {response_path}\n",
                flush=True,
            )

        print(f"{separator}\n", flush=True)

    def _wait_for_response(
        self,
        response_path: Path,
        output_path: Path,
        iter_dir: Path,
        phase: str,
        t0: float,
    ) -> str:
        """Poll for the signal file, then verify required artifacts exist."""
        deadline = t0 + self.timeout

        while time.time() < deadline:
            if phase == "design":
                if response_path.exists():
                    missing = self._check_design_artifacts(iter_dir)
                    if missing:
                        raise RuntimeError(
                            f"Signal file exists but required design artifacts are missing: "
                            f"{', '.join(missing)}. The agent must write all files before "
                            f"touching {response_path}."
                        )
                    return f"Design artifacts written to {iter_dir}"

            elif phase == "execute-analyze":
                if response_path.exists():
                    missing = self._check_execute_artifacts(iter_dir)
                    if missing:
                        raise RuntimeError(
                            f"Signal file exists but required execution artifacts are missing: "
                            f"{', '.join(missing)}. The agent must write all files before "
                            f"touching {response_path}."
                        )
                    return f"Execution artifacts written to {iter_dir}"

            elif response_path.exists():
                content = response_path.read_text()
                if not content.strip():
                    time.sleep(RESPONSE_POLL_INTERVAL_SEC)
                    continue
                return content

            time.sleep(RESPONSE_POLL_INTERVAL_SEC)

        raise RuntimeError(
            f"Timed out after {self.timeout}s waiting for agent response at {response_path}. "
            f"The agent should write its response and then touch {response_path}."
        )

    @staticmethod
    def _clean_stale_artifacts(iter_dir: Path, phase: str) -> None:
        """Remove artifacts from previous runs so polling starts clean."""
        if phase == "design":
            for name in ("problem.md", "bundle.yaml", "handoff.md"):
                (iter_dir / name).unlink(missing_ok=True)
        elif phase == "execute-analyze":
            for name in ("experiment_plan.yaml", "findings.json", "principle_updates.json"):
                (iter_dir / name).unlink(missing_ok=True)

    @staticmethod
    def _check_design_artifacts(iter_dir: Path) -> list[str]:
        """Return list of missing required design artifact names."""
        required = {"problem.md": iter_dir / "problem.md", "bundle.yaml": iter_dir / "bundle.yaml"}
        return [name for name, path in required.items() if not path.exists()]

    @staticmethod
    def _check_execute_artifacts(iter_dir: Path) -> list[str]:
        """Return list of missing required execution artifact names."""
        required = {
            "experiment_plan.yaml": iter_dir / "experiment_plan.yaml",
            "findings.json": iter_dir / "findings.json",
            "principle_updates.json": iter_dir / "principle_updates.json",
        }
        return [name for name, path in required.items() if not path.exists()]

    def _log_inline_metrics(self, role: str, phase: str, t0: float) -> None:
        """Log basic timing metrics for inline dispatch."""
        duration_ms = int((time.time() - t0) * 1000)
        log_metrics(self._metrics_path, {
            "dispatcher": "inline",
            "role": role,
            "phase": phase,
            "model": "inline-agent",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0,
            "duration_ms": duration_ms,
            "num_turns": 1,
        })
