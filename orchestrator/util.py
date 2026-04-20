"""Shared utilities for the Nous orchestrator."""
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def atomic_write(path: Path, data: str | bytes) -> None:
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
        except OSError as exc:
            logger.debug("Failed to close fd during cleanup: %s", exc)
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError as exc:
            logger.debug("Failed to remove temp file %s during cleanup: %s", tmp, exc)
        raise
