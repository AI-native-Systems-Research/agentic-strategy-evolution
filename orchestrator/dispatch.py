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
                self._write_bundle(output_path, iteration)
            case "executor":
                if phase == "plan-execution":
                    self._write_experiment_plan(output_path, iteration)
                else:
                    self._write_findings(output_path, iteration, h_main_result)
            case "reviewer":
                self._write_review(output_path, perspective or "general")
            case "extractor":
                if phase == "summarize":
                    self._write_investigation_summary(output_path, iteration)
                else:
                    self._write_principles(output_path, iteration)
            case "summarizer":
                if phase != "summarize-gate":
                    raise ValueError(f"Unknown phase for summarizer: {phase}")
                self._write_gate_summary(output_path, perspective or "design")
            case _:
                raise ValueError(f"Unknown role: {role}")

        logger.info("Dispatched role=%s phase=%s -> %s", role, phase, output_path)

    def _write_bundle(self, path: Path, iteration: int) -> None:
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
        atomic_write(path, yaml.safe_dump(bundle, default_flow_style=False, sort_keys=False))

    def _write_experiment_plan(self, path: Path, iteration: int) -> None:
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
                            "output": "results/h-main/baseline.json",
                        },
                        {
                            "name": "treatment",
                            "cmd": "echo '{\"latency_ms\": 40}'",
                            "output": "results/h-main/treatment.json",
                        },
                    ],
                },
                {
                    "arm_id": "h-control-negative",
                    "conditions": [
                        {
                            "name": "control",
                            "cmd": "echo '{\"latency_ms\": 50}'",
                            "output": "results/h-control-negative/control.json",
                        },
                    ],
                },
            ],
        }
        atomic_write(path, yaml.safe_dump(plan, default_flow_style=False, sort_keys=False))

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

    def _write_findings(self, path: Path, iteration: int, h_main_result: str) -> None:
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
        atomic_write(path, json.dumps(findings, indent=2) + "\n")

    def _write_review(self, path: Path, perspective: str) -> None:
        atomic_write(
            path,
            f"# Review — {perspective}\n\n"
            f"**Severity:** SUGGESTION\n\n"
            f"No CRITICAL or IMPORTANT findings.\n"
            f"Stub review from {perspective} perspective.\n",
        )

    def _write_investigation_summary(self, path: Path, iteration: int) -> None:
        summary = {
            "iteration": iteration,
            "what_was_tested": f"Stub: hypothesis family tested in iteration {iteration}.",
            "key_findings": "Stub: H-main confirmed. No significant discrepancies.",
            "principles_changed": f"Stub: Inserted stub-principle-{iteration}.",
            "open_questions": "Stub: No open questions from stub iteration.",
            "suggested_next_direction": "Stub: Continue with next mechanism family.",
        }
        atomic_write(path, json.dumps(summary, indent=2) + "\n")

    def _write_principles(self, path: Path, iteration: int) -> None:
        if path.exists():
            try:
                store = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError) as e:
                raise RuntimeError(
                    f"Cannot read existing principles file at {path}: {e}. "
                    f"The file may be corrupt from a previous failed write."
                ) from e
            if "principles" not in store:
                raise RuntimeError(
                    f"Principles file at {path} is missing 'principles' key. "
                    f"Expected schema: {{'principles': [...]}}"
                )
        else:
            store = {"principles": []}
        store["principles"].append(
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
            }
        )
        atomic_write(path, json.dumps(store, indent=2) + "\n")

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
