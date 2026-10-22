"""Transient error classification for Nous v2 sessions (B9).

The retry layer (R4) uses ``is_transient()`` to decide whether a failed
turn should be retried or propagated.
"""

from __future__ import annotations


class TransientError(Exception):
    """Base class for errors that the retry layer should re-attempt."""


class ProcessError(TransientError):
    def __init__(self, exit_code: int, stderr: str = ""):
        self.exit_code = exit_code
        self.stderr = stderr
        super().__init__(f"SDK process exited with code {exit_code}")


class TimeoutError_(TransientError):
    """A turn exceeded its wall-clock budget."""


class APIServerError(TransientError):
    def __init__(self, status_code: int, body: str = ""):
        self.status_code = status_code
        self.body = body
        super().__init__(f"API returned {status_code}")


_TRANSIENT_MESSAGES = (
    "Fatal error in message reader",
)

_TRANSIENT_EXIT_CODES = frozenset({143})


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, TransientError):
        return True

    if isinstance(exc, (TimeoutError, OSError)) and "timed out" in str(exc).lower():
        return True

    msg = str(exc)

    if hasattr(exc, "exit_code"):
        if getattr(exc, "exit_code", None) in _TRANSIENT_EXIT_CODES:
            return True

    if any(pat in msg for pat in _TRANSIENT_MESSAGES):
        return True

    if hasattr(exc, "status_code"):
        code = getattr(exc, "status_code", None)
        if isinstance(code, int) and 500 <= code < 600:
            return True

    return False
