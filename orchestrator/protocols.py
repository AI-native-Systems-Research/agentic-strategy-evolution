"""Protocol definitions for Nous orchestrator components.

These protocols define the contracts that real implementations must satisfy.
Phase 1 provides stub implementations; future phases will add real ones.
"""
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class Dispatcher(Protocol):
    """Contract for agent dispatch — produces schema-conformant artifacts."""

    def dispatch(
        self,
        role: str,
        phase: str,
        *,
        output_path: Path,
        iteration: int,
        perspective: str | None = None,
        h_main_result: str = "CONFIRMED",
    ) -> None: ...


@runtime_checkable
class Gate(Protocol):
    """Contract for human approval gates."""

    def prompt(
        self,
        question: str,
        artifact_path: str | None = None,
        reviews: list[str] | None = None,
    ) -> str: ...
