"""Human gate logic for the Nous orchestrator.

Pauses execution, surfaces artifact + review summary, prompts for decision.
Supports auto-approve mode for testing.
"""
import logging
import os
import warnings
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class Decision(str, Enum):
    """Valid gate decisions."""

    APPROVE = "approve"
    REJECT = "reject"
    ABORT = "abort"


VALID_DECISIONS = frozenset(d.value for d in Decision)
_DECISIONS_DISPLAY = "/".join(d.value for d in Decision)


class HumanGate:
    """Gate that pauses for human approval."""

    def __init__(
        self,
        auto_approve: bool = False,
        auto_response: str | None = None,
    ) -> None:
        if auto_approve and auto_response is not None:
            raise ValueError(
                "Cannot specify both auto_approve=True and auto_response. "
                "Use one or the other."
            )
        if auto_approve:
            if os.environ.get("NOUS_ALLOW_AUTO_APPROVE") != "1":
                raise RuntimeError(
                    "auto_approve=True requires NOUS_ALLOW_AUTO_APPROVE=1 "
                    "environment variable. This prevents accidental bypass "
                    "of human gates in production."
                )
            warnings.warn(
                "HumanGate auto_approve=True: ALL human gates will be bypassed. "
                "This MUST only be used in testing.",
                stacklevel=2,
            )
            logger.warning("HumanGate created with auto_approve=True")
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
            logger.info("Gate auto-response: %s", self._response)
            return Decision(self._response).value
        # Interactive mode
        if artifact_path:
            print(f"\n--- Artifact: {artifact_path} ---")
            path = Path(artifact_path)
            if not path.exists():
                print(f"  WARNING: artifact file not found at {artifact_path}")
            else:
                try:
                    content = path.read_text()
                except (OSError, UnicodeDecodeError) as e:
                    print(f"  WARNING: could not read artifact: {e}")
                    content = ""
                if len(content) > 2000:
                    print(content[:2000])
                    print(f"\n  ... (truncated: showing 2000 of {len(content)} chars)")
                    print(f"  Full artifact: {artifact_path}")
                else:
                    print(content)
        if reviews:
            print(f"\n--- Reviews ({len(reviews)}) ---")
            for r in reviews:
                print(f"  - {r}")
        while True:
            try:
                answer = input(
                    f"\n{question} [{_DECISIONS_DISPLAY}]: "
                ).strip().lower()
            except EOFError:
                raise RuntimeError(
                    "Interactive input required but stdin reached EOF. "
                    "Use auto_approve=True for non-interactive environments."
                ) from None
            except KeyboardInterrupt:
                print("\nAborted by user.")
                logger.info("Gate aborted by KeyboardInterrupt")
                raise
            if answer in VALID_DECISIONS:
                logger.info("Gate decision: %s", answer)
                return Decision(answer).value
            print(f"Invalid. Choose from: {VALID_DECISIONS}")
