"""Agent dispatch for the Nous orchestrator.

Loads prompt template, invokes LLM API (or stub), writes output.
Default: StubDispatcher that produces valid schema-conformant artifacts
without calling any LLM.
"""
import json
from pathlib import Path

import yaml


class StubDispatcher:
    """Produces valid, schema-conformant stub artifacts for testing."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = Path(work_dir)

    def dispatch(
        self,
        role: str,
        phase: str,
        *,
        output_path: Path,
        iteration: int = 1,
        perspective: str | None = None,
        h_main_result: str = "CONFIRMED",
    ) -> None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        match role:
            case "planner":
                self._write_bundle(output_path, iteration)
            case "executor":
                self._write_findings(output_path, iteration, h_main_result)
            case "reviewer":
                self._write_review(output_path, perspective or "general")
            case "extractor":
                self._write_principles(output_path, iteration)
            case _:
                raise ValueError(f"Unknown role: {role}")

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
        path.write_text(yaml.dump(bundle, default_flow_style=False, sort_keys=False))

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
            "discrepancy_analysis": "Stub analysis: all predictions within expected range."
            if h_main_result == "CONFIRMED"
            else "Stub analysis: H-main refuted, mechanism does not hold.",
        }
        path.write_text(json.dumps(findings, indent=2) + "\n")

    def _write_review(self, path: Path, perspective: str) -> None:
        path.write_text(
            f"# Review — {perspective}\n\n"
            f"**Severity:** SUGGESTION\n\n"
            f"No CRITICAL or IMPORTANT findings.\n"
            f"Stub review from {perspective} perspective.\n"
        )

    def _write_principles(self, path: Path, iteration: int) -> None:
        store = json.loads(path.read_text()) if path.exists() else {"principles": []}
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
                "status": "active",
            }
        )
        path.write_text(json.dumps(store, indent=2) + "\n")
