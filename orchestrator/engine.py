"""State machine engine for the Nous orchestrator.

Owns phase transitions and state.json checkpoint/resume.
This is NOT an LLM — it is a deterministic script.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

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
    """Orchestrator state machine with checkpoint/resume."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = Path(work_dir)
        self.state_path = self.work_dir / "state.json"
        self.state = self._load_state()

    def _load_state(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text())
        raise FileNotFoundError(f"No state.json found at {self.state_path}")

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
        # Increment iteration when looping back to DESIGN from EXTRACTION
        if current == "EXTRACTION" and to_state == "DESIGN":
            self.state["iteration"] += 1
        self.state["phase"] = to_state
        self.state["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._save_state()

    def _save_state(self) -> None:
        self.state_path.write_text(json.dumps(self.state, indent=2) + "\n")
