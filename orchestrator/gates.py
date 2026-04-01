"""Human gate logic for the Nous orchestrator.

Pauses execution, surfaces artifact + review summary, prompts for decision.
Supports auto-approve mode for testing.
"""
from pathlib import Path

VALID_DECISIONS = {"approve", "reject", "abort"}


class HumanGate:
    """Gate that pauses for human approval."""

    def __init__(
        self,
        auto_approve: bool = False,
        auto_response: str | None = None,
    ) -> None:
        if auto_approve:
            self._response = "approve"
        elif auto_response:
            if auto_response not in VALID_DECISIONS:
                raise ValueError(f"Invalid auto_response: {auto_response}")
            self._response = auto_response
        else:
            self._response = None

    def prompt(
        self,
        question: str,
        artifact_path: str | None = None,
        reviews: list[str] | None = None,
    ) -> str:
        if self._response:
            return self._response
        # Interactive mode
        if artifact_path:
            print(f"\n--- Artifact: {artifact_path} ---")
            path = Path(artifact_path)
            if path.exists():
                print(path.read_text()[:2000])
        if reviews:
            print(f"\n--- Reviews ({len(reviews)}) ---")
            for r in reviews:
                print(f"  - {r}")
        while True:
            answer = input(f"\n{question} [{'/'.join(VALID_DECISIONS)}]: ").strip().lower()
            if answer in VALID_DECISIONS:
                return answer
            print(f"Invalid. Choose from: {VALID_DECISIONS}")
