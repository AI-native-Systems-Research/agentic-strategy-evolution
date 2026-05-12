"""Agent dispatch for the Nous orchestrator.

StubDispatcher produces valid schema-conformant artifacts without calling any
LLM, enabling end-to-end testing of the orchestrator loop.

For real LLM dispatch, see llm_dispatch.py (Phase 2).
"""
import json
import logging
import warnings
from pathlib import Path

import yaml

from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)


class StubDispatcher:
    """Produces valid, schema-conformant stub artifacts for testing."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = Path(work_dir)
        warnings.warn(
            "Using StubDispatcher — no real LLM calls will be made. "
            "All artifacts are synthetic.",
            stacklevel=2,
        )
        logger.warning("StubDispatcher instantiated — all artifacts are synthetic")

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
        """Dispatch a stub agent to produce a schema-conformant artifact.

        Args:
            iteration: 1-indexed human label for the experiment (used in
                artifact filenames and content). This is NOT the engine's
                0-indexed counter — callers should pass engine.iteration + 1.
        """
        _VALID_H_MAIN_RESULTS = {"CONFIRMED", "REFUTED"}
        if h_main_result not in _VALID_H_MAIN_RESULTS:
            raise ValueError(
                f"Invalid h_main_result: {h_main_result!r}. "
                f"Must be one of: {_VALID_H_MAIN_RESULTS}"
            )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        match role:
            case "planner":
                self._write_design_output(output_path, iteration)
            case "executor":
                if phase == "execute-analyze":
                    self._write_execute_analyze(output_path, iteration, h_main_result)
                else:
                    raise ValueError(f"Unknown phase for executor: {phase}")
            case "extractor":
                if phase == "report":
                    atomic_write(output_path, "# Stub Report\n\nNo real analysis performed.\n")
                else:
                    raise ValueError(f"Unknown phase for extractor: {phase}")
            case "summarizer":
                if phase != "summarize-gate":
                    raise ValueError(f"Unknown phase for summarizer: {phase}")
                self._write_gate_summary(output_path, perspective or "design")
            case _:
                raise ValueError(f"Unknown role: {role}")

        logger.info("Dispatched role=%s phase=%s -> %s", role, phase, output_path)

    def _write_design_output(self, path: Path, iteration: int) -> None:
        """Write design artifacts directly to iter_dir (mimics agent writing files)."""
        iter_dir = path.parent
        iter_dir.mkdir(parents=True, exist_ok=True)

        bundle = {
            "metadata": {
                "iteration": iteration,
                "family": "stub-family",
                "research_question": "Stub: does the mechanism work?",
            },
            "arms": [
                {
                    "type": "h-main",
                    "prediction": "Stub: >10% improvement",
                    "mechanism": "Stub: causal explanation",
                    "diagnostic": "Stub: check if effect exists",
                },
                {
                    "type": "h-control-negative",
                    "prediction": "Stub: no effect at low load",
                    "mechanism": "Stub: mechanism irrelevant without contention",
                    "diagnostic": "Stub: look for overhead",
                },
            ],
        }
        problem_md = (
            "## Research Question\n\n"
            "Stub: does the mechanism work?\n\n"
            "## System Interface\n\n"
            "Stub: system interface details.\n\n"
            "## Baseline Command\n\n"
            "```\necho 'stub baseline'\n```\n"
        )
        handoff_md = (
            "## Handoff\n\n"
            "### Goal\n"
            "Test whether the stub mechanism reduces latency under contention.\n\n"
            "### Key Discoveries\n"
            "- Mechanism is implemented at `src/stub.py:42` — toggles batch amortization\n"
            "- Baseline latency at default load: 50ms mean\n\n"
            "### System Interface\n"
            "- **Build:** `echo 'stub build'`\n"
            "- **Run baseline:** `echo 'stub baseline'`\n\n"
            "### Code Map\n"
            "- `src/stub.py:42` — mechanism toggle.\n\n"
            "### Warnings & Constraints\n"
            "- First request always cold.\n"
        )
        atomic_write(iter_dir / "problem.md", problem_md)
        atomic_write(
            iter_dir / "bundle.yaml",
            yaml.safe_dump(bundle, default_flow_style=False, sort_keys=False),
        )
        atomic_write(iter_dir / "handoff_snapshot.md", handoff_md)
        # Campaign-level handoff
        campaign_dir = iter_dir.parent.parent
        atomic_write(campaign_dir / "handoff.md", handoff_md)
        # Write a log to output_path
        atomic_write(path, "Stub designer: artifacts written directly to iter_dir.\n")

    def _write_execute_analyze(self, path: Path, iteration: int, h_main_result: str) -> None:
        """Write executor artifacts directly to iter_dir (mimics agent writing files)."""
        iter_dir = path.parent
        iter_dir.mkdir(parents=True, exist_ok=True)

        plan = {
            "metadata": {
                "iteration": iteration,
                "bundle_ref": f"runs/iter-{iteration}/bundle.yaml",
            },
            "setup": [
                {"cmd": "echo 'stub build'", "description": "Stub setup"},
            ],
            "arms": [
                {
                    "arm_id": "h-main",
                    "conditions": [
                        {
                            "name": "baseline",
                            "cmd": "echo '{\"latency_ms\": 50}'",
                        },
                        {
                            "name": "treatment",
                            "cmd": "echo '{\"latency_ms\": 40}'",
                        },
                    ],
                },
                {
                    "arm_id": "h-control-negative",
                    "conditions": [
                        {
                            "name": "control",
                            "cmd": "echo '{\"latency_ms\": 50}'",
                        },
                    ],
                },
            ],
        }
        findings = {
            "iteration": iteration,
            "bundle_ref": f"runs/iter-{iteration}/bundle.yaml",
            "arms": [
                {
                    "arm_type": "h-main",
                    "predicted": ">10% improvement",
                    "observed": "12.3% improvement"
                    if h_main_result == "CONFIRMED"
                    else "-2.1% regression",
                    "status": h_main_result,
                    "error_type": None
                    if h_main_result == "CONFIRMED"
                    else "direction",
                    "diagnostic_note": None
                    if h_main_result == "CONFIRMED"
                    else "Mechanism does not hold",
                },
                {
                    "arm_type": "h-control-negative",
                    "predicted": "no effect at low load",
                    "observed": "no significant effect",
                    "status": "CONFIRMED",
                    "error_type": None,
                    "diagnostic_note": None,
                },
            ],
            "experiment_valid": True,
            "discrepancy_analysis": "Stub analysis: all predictions within expected range."
            if h_main_result == "CONFIRMED"
            else "Stub analysis: H-main refuted, mechanism does not hold.",
        }
        principle_updates = [
            {
                "id": f"stub-principle-{iteration}",
                "statement": f"Stub principle extracted from iteration {iteration}",
                "confidence": "medium",
                "regime": "all",
                "evidence": [f"iteration-{iteration}-h-main"],
                "contradicts": [],
                "extraction_iteration": iteration,
                "mechanism": "Stub mechanism",
                "applicability_bounds": "stub",
                "superseded_by": None,
                "category": "domain",
                "status": "active",
            },
        ]

        atomic_write(
            iter_dir / "experiment_plan.yaml",
            yaml.safe_dump(plan, default_flow_style=False, sort_keys=False),
        )
        atomic_write(
            iter_dir / "findings.json",
            json.dumps(findings, indent=2) + "\n",
        )
        atomic_write(
            iter_dir / "principle_updates.json",
            json.dumps(principle_updates, indent=2) + "\n",
        )
        # Write a log to the output_path (what the orchestrator captures)
        atomic_write(path, "Stub executor: artifacts written directly to iter_dir.\n")

    def write_execution_results(self, path: Path, iteration: int) -> None:
        """Write stub execution results for integration tests."""
        results = {
            "plan_ref": f"runs/iter-{iteration}/experiment_plan.yaml",
            "setup_results": [
                {"cmd": "echo 'stub build'", "exit_code": 0, "stdout_tail": "stub build", "stderr_tail": ""},
            ],
            "arms": [
                {
                    "arm_id": "h-main",
                    "conditions": [
                        {
                            "name": "baseline",
                            "cmd": "echo '{\"latency_ms\": 50}'",
                            "exit_code": 0,
                            "stdout_tail": '{"latency_ms": 50}',
                            "stderr_tail": "",
                            "output_content": '{"latency_ms": 50}',
                        },
                        {
                            "name": "treatment",
                            "cmd": "echo '{\"latency_ms\": 40}'",
                            "exit_code": 0,
                            "stdout_tail": '{"latency_ms": 40}',
                            "stderr_tail": "",
                            "output_content": '{"latency_ms": 40}',
                        },
                    ],
                },
                {
                    "arm_id": "h-control-negative",
                    "conditions": [
                        {
                            "name": "control",
                            "cmd": "echo '{\"latency_ms\": 50}'",
                            "exit_code": 0,
                            "stdout_tail": '{"latency_ms": 50}',
                            "stderr_tail": "",
                            "output_content": '{"latency_ms": 50}',
                        },
                    ],
                },
            ],
        }
        atomic_write(path, json.dumps(results, indent=2) + "\n")

    def _write_gate_summary(self, path: Path, gate_type: str) -> None:
        summary = {
            "gate_type": gate_type,
            "summary": f"Stub: summary for {gate_type} gate.",
            "key_points": [
                f"Stub: key point 1 for {gate_type}",
                f"Stub: key point 2 for {gate_type}",
            ],
        }
        atomic_write(path, json.dumps(summary, indent=2) + "\n")
