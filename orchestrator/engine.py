"""State machine engine for the Nous orchestrator.

Owns phase transitions and state.json checkpoint/resume.
This is NOT an LLM — it is a deterministic script.
"""
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType

logger = logging.getLogger(__name__)

_REQUIRED_STATE_KEYS = {"phase", "iteration", "run_id", "family", "timestamp"}


class Phase(str, Enum):
    """All valid orchestrator phases."""

    INIT = "INIT"
    DESIGN = "DESIGN"
    HUMAN_DESIGN_GATE = "HUMAN_DESIGN_GATE"
    EXECUTE_ANALYZE = "EXECUTE_ANALYZE"
    VALIDATE = "VALIDATE"
    HUMAN_FINDINGS_GATE = "HUMAN_FINDINGS_GATE"
    DONE = "DONE"


# Valid transitions: from_state -> set of valid to_states (immutable)
TRANSITIONS: MappingProxyType[str, frozenset[str]] = MappingProxyType({
    "INIT":                frozenset({"DESIGN"}),
    "DESIGN":              frozenset({"HUMAN_DESIGN_GATE"}),
    "HUMAN_DESIGN_GATE":   frozenset({"EXECUTE_ANALYZE", "DESIGN"}),
    "EXECUTE_ANALYZE":     frozenset({"VALIDATE"}),
    "VALIDATE":            frozenset({"HUMAN_FINDINGS_GATE"}),
    "HUMAN_FINDINGS_GATE": frozenset({"DONE", "EXECUTE_ANALYZE"}),
    "DONE":                frozenset({"DESIGN"}),
})

# All recognized states (for validation)
ALL_STATES = frozenset(Phase)


class Engine:
    """Orchestrator state machine with checkpoint/resume.

    Requires state.json to already exist in work_dir.
    Use templates/state.json to initialize a new campaign.
    """

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = Path(work_dir)
        self.state_path = self.work_dir / "state.json"
        self._state = self._load_state()

    @property
    def state(self) -> dict:
        """Shallow copy of the current state (safe: state is always a flat dict)."""
        return dict(self._state)

    @property
    def phase(self) -> str:
        return self._state["phase"]

    @property
    def iteration(self) -> int:
        return self._state["iteration"]

    @property
    def run_id(self) -> str:
        return self._state["run_id"]

    def _load_state(self) -> dict:
        if not self.state_path.exists():
            raise FileNotFoundError(f"No state.json found at {self.state_path}")
        try:
            state = json.loads(self.state_path.read_text())
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Corrupt state.json at {self.state_path}: {e}. "
                f"Restore from backup or re-initialize from templates/state.json."
            ) from e
        missing = _REQUIRED_STATE_KEYS - state.keys()
        if missing:
            raise ValueError(f"state.json missing required keys: {missing}")
        # Validate phase is a recognized state
        if state["phase"] not in ALL_STATES:
            raise ValueError(
                f"state.json has unrecognized phase '{state['phase']}'. "
                f"Valid phases: {sorted(s.value for s in Phase)}"
            )
        return state

    def transition(self, to_state: str) -> None:
        # Validate target phase early — catches typos at the call site
        if to_state not in ALL_STATES:
            raise ValueError(
                f"'{to_state}' is not a recognized phase. "
                f"Valid phases: {sorted(s.value for s in Phase)}"
            )
        current = self._state["phase"]
        if current not in TRANSITIONS:
            raise ValueError(f"Unknown state: {current}")
        if to_state not in TRANSITIONS[current]:
            raise ValueError(
                f"Invalid transition: {current} -> {to_state}. "
                f"Valid: {TRANSITIONS[current]}"
            )
        # Build candidate state before writing to disk
        new_state = dict(self._state)
        if current == "DONE" and to_state == "DESIGN":
            new_state["iteration"] += 1
        new_state["phase"] = to_state
        new_state["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._save_state(new_state)
        self._state = new_state
        logger.info("Transition: %s -> %s (iteration=%d)", current, to_state, new_state["iteration"])

    def _save_state(self, state: dict) -> None:
        """Atomic write: write to temp file then rename."""
        data = json.dumps(state, indent=2) + "\n"
        fd, tmp = tempfile.mkstemp(dir=self.work_dir, suffix=".json.tmp")
        fd_closed = False
        try:
            os.write(fd, data.encode())
            os.fsync(fd)
            os.close(fd)
            fd_closed = True
            os.replace(tmp, str(self.state_path))
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
