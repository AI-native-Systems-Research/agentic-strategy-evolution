"""Agent dispatch for the Nous orchestrator.

Real dispatcher (future): loads prompt template, invokes LLM API, writes output.
Phase 1: StubDispatcher produces valid schema-conformant artifacts without
calling any LLM, enabling end-to-end testing of the orchestrator loop.
"""
import json
import logging
import os
import tempfile
import warnings
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def _atomic_write(path: Path, data: str | bytes) -> None:
    """Write data to path atomically via temp file + fsync + rename."""
    if isinstance(data, str):
        data = data.encode()
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    fd_closed = False
    try:
        os.write(fd, data)
        os.fsync(fd)
        os.close(fd)
        fd_closed = True
        os.replace(tmp, str(path))
    except BaseException:
        try:
            if not fd_closed:
                os.close(fd)
        except OSError:
            pass
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        raise


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
                self._write_findings(output_path, iteration, h_main_result)
            case "reviewer":
                self._write_review(output_path, perspective or "general")
            case "extractor":
                self._write_principles(output_path, iteration)
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
        _atomic_write(path, yaml.safe_dump(bundle, default_flow_style=False, sort_keys=False))

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
        _atomic_write(path, json.dumps(findings, indent=2) + "\n")

    def _write_review(self, path: Path, perspective: str) -> None:
        _atomic_write(
            path,
            f"# Review — {perspective}\n\n"
            f"**Severity:** SUGGESTION\n\n"
            f"No CRITICAL or IMPORTANT findings.\n"
            f"Stub review from {perspective} perspective.\n",
        )

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
        _atomic_write(path, json.dumps(store, indent=2) + "\n")
