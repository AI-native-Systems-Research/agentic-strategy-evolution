"""State machine engine for the Nous orchestrator.

Owns phase transitions and state.json checkpoint/resume.
This is NOT an LLM — it is a deterministic script.
"""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_REQUIRED_STATE_KEYS = {"phase", "iteration", "run_id", "family", "timestamp"}

# Valid transitions: from_state -> set of valid to_states
TRANSITIONS: dict[str, set[str]] = {
    "INIT":                {"FRAMING"},
    "FRAMING":             {"DESIGN"},
    "DESIGN":              {"DESIGN_REVIEW"},
    "DESIGN_REVIEW":       {"HUMAN_DESIGN_GATE", "DESIGN"},
    "HUMAN_DESIGN_GATE":   {"RUNNING", "DESIGN"},
    "RUNNING":             {"FINDINGS_REVIEW"},
    "FINDINGS_REVIEW":     {"HUMAN_FINDINGS_GATE", "RUNNING"},
    "HUMAN_FINDINGS_GATE": {"TUNING", "EXTRACTION", "RUNNING"},
    "TUNING":              {"EXTRACTION"},
    "EXTRACTION":          {"DESIGN", "DONE"},
}


class Engine:
    """Orchestrator state machine with checkpoint/resume.

    Requires state.json to already exist in work_dir.
    Use templates/state.json to initialize a new campaign.
    """

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = Path(work_dir)
        self.state_path = self.work_dir / "state.json"
        self.state = self._load_state()

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
        return state

    def transition(self, to_state: str) -> None:
        current = self.state["phase"]
        if current == "DONE":
            raise ValueError("Campaign is already DONE")
        if current not in TRANSITIONS:
            raise ValueError(f"Unknown state: {current}")
        if to_state not in TRANSITIONS[current]:
            raise ValueError(
                f"Invalid transition: {current} -> {to_state}. "
                f"Valid: {TRANSITIONS[current]}"
            )
        # Build candidate state before writing to disk
        new_state = dict(self.state)
        if current == "EXTRACTION" and to_state == "DESIGN":
            new_state["iteration"] += 1
        new_state["phase"] = to_state
        new_state["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._save_state(new_state)
        self.state = new_state

    def _save_state(self, state: dict) -> None:
        """Atomic write: write to temp file then rename."""
        data = json.dumps(state, indent=2) + "\n"
        fd, tmp = tempfile.mkstemp(dir=self.work_dir, suffix=".json.tmp")
        try:
            os.write(fd, data.encode())
            os.fsync(fd)
            os.close(fd)
            os.rename(tmp, str(self.state_path))
        except BaseException:
            os.close(fd)
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
