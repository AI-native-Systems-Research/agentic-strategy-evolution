"""State machine engine for the Nous orchestrator.

Owns phase transitions and state.json checkpoint/resume.
This is NOT an LLM — it is a deterministic script.

state.json semantics
--------------------

The on-disk ``last_entered_phase`` field reflects the **last phase the
engine entered**, not the **currently active phase**. The two are not
the same — artifact writes within a phase do not trigger state.json
updates, so during a long phase you'll see the entry-time value linger
even though the phase has been working for many seconds. After the
phase finishes its work, the value continues to linger until the next
``transition()`` is called and the new phase is entered.

This was renamed from ``phase`` in #236; the legacy key is read for
backward compat (in-flight runs from older versions) and migrated to
the new key on the next ``transition()`` or ``force_phase()``.

If you need a more aggressive progress signal (e.g. for a status
dashboard polling at sub-second granularity), watch the iteration
artifact directory's mtimes rather than ``state.json``.
"""
import json
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, overload

from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)

# #236: the canonical on-disk key is ``last_entered_phase``. The legacy
# key ``phase`` is accepted on load for backward compat (in-flight runs)
# and migrated to the new key on the next save. Required-keys validation
# uses the canonical name; legacy state.json files are normalized in
# memory before the check runs.
_PHASE_KEY = "last_entered_phase"
_LEGACY_PHASE_KEY = "phase"
_REQUIRED_STATE_KEYS = {_PHASE_KEY, "iteration", "run_id", "family", "timestamp"}


@overload
def read_phase_field(state: Mapping[str, Any]) -> str | None: ...
@overload
def read_phase_field(state: Mapping[str, Any], default: str) -> str: ...
def read_phase_field(
    state: Mapping[str, Any],
    default: str | None = None,
) -> str | None:
    """Return state.json's ``last_entered_phase``, falling back to the
    legacy ``phase`` key (#236).

    Use this in any code that reads state.json **without** going
    through ``Engine`` — e.g., status dashboards, the campaign index,
    warm-start probes. Code that holds an ``Engine`` should read
    ``engine.last_entered_phase`` (or its alias ``engine.phase``)
    instead.
    """
    if _PHASE_KEY in state:
        return state[_PHASE_KEY]
    if _LEGACY_PHASE_KEY in state:
        return state[_LEGACY_PHASE_KEY]
    return default


class Phase(str, Enum):
    """All valid orchestrator phases."""

    INIT = "INIT"
    PRE_WORK = "PRE_WORK"
    DESIGN = "DESIGN"
    CRITIC = "CRITIC"
    HUMAN_DESIGN_GATE = "HUMAN_DESIGN_GATE"
    EXECUTE_ANALYZE = "EXECUTE_ANALYZE"
    HUMAN_FINDINGS_GATE = "HUMAN_FINDINGS_GATE"
    DONE = "DONE"


# Valid transitions: from_state -> set of valid to_states (immutable)
#
# PRE_WORK (issue #167) is opt-in: campaigns may go INIT → PRE_WORK → DESIGN
# OR INIT → DESIGN. Legacy campaigns without a pre_work_script keep the
# direct path; new campaigns that want cheap pre-iter exploration go through
# PRE_WORK.
#
# CRITIC (issue #87) is opt-in between DESIGN and HUMAN_DESIGN_GATE: campaigns
# may go DESIGN → CRITIC → HUMAN_DESIGN_GATE OR DESIGN → HUMAN_DESIGN_GATE
# (legacy). Adds a deterministic "can this experiment fail?" check that
# composes with #85 (ground_truth), #86 (empirical_content), #88 (theory_references).
TRANSITIONS: MappingProxyType[str, frozenset[str]] = MappingProxyType({
    "INIT":                frozenset({"DESIGN", "PRE_WORK"}),
    "PRE_WORK":            frozenset({"DESIGN"}),
    "DESIGN":              frozenset({"HUMAN_DESIGN_GATE", "CRITIC"}),
    "CRITIC":              frozenset({"HUMAN_DESIGN_GATE"}),
    "HUMAN_DESIGN_GATE":   frozenset({"EXECUTE_ANALYZE", "DESIGN"}),
    "EXECUTE_ANALYZE":     frozenset({"HUMAN_FINDINGS_GATE"}),
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
    def last_entered_phase(self) -> str:
        """The last phase the engine entered.

        NOT necessarily the currently active phase — see the module
        docstring for the entry-only semantics caveat (#236).
        """
        return self._state[_PHASE_KEY]

    @property
    def phase(self) -> str:
        """Alias for :pyattr:`last_entered_phase` (#236).

        Kept for source compatibility — most callers in the orchestrator
        already use ``engine.phase``. New code should prefer
        ``engine.last_entered_phase`` for clarity.
        """
        return self._state[_PHASE_KEY]

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
        # #236 migration: legacy state.json files use ``phase``; rename
        # in-memory before the required-keys check so validation reports
        # the canonical key in error messages. The next save writes the
        # canonical name, dropping the legacy key.
        if _PHASE_KEY not in state and _LEGACY_PHASE_KEY in state:
            state[_PHASE_KEY] = state.pop(_LEGACY_PHASE_KEY)
        missing = _REQUIRED_STATE_KEYS - state.keys()
        if missing:
            raise ValueError(f"state.json missing required keys: {missing}")
        # Validate phase is a recognized state
        if state[_PHASE_KEY] not in ALL_STATES:
            raise ValueError(
                f"state.json has unrecognized phase '{state[_PHASE_KEY]}'. "
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
        current = self._state[_PHASE_KEY]
        if current not in TRANSITIONS:
            raise ValueError(f"Unknown state: {current}")
        if to_state not in TRANSITIONS[current]:
            raise ValueError(
                f"Invalid transition: {current} -> {to_state}. "
                f"Valid: {TRANSITIONS[current]}"
            )
        # Build candidate state before writing to disk.
        # #194: increment iteration whenever we leave INIT (iter-1 begins,
        # whether via PRE_WORK or directly to DESIGN) and whenever DONE
        # transitions to DESIGN (iter-N+1 begins). Pre-#194, the counter
        # only ticked on DONE→DESIGN, so state.iteration stayed at 0
        # throughout iter-1 even though artifacts lived at runs/iter-1/.
        new_state = dict(self._state)
        if current == "INIT":
            new_state["iteration"] += 1
        elif current == "DONE" and to_state == "DESIGN":
            new_state["iteration"] += 1
        new_state[_PHASE_KEY] = to_state
        new_state["timestamp"] = datetime.now(timezone.utc).isoformat()
        # #236: drop the legacy key on save so a migrated state.json
        # doesn't carry both names.
        new_state.pop(_LEGACY_PHASE_KEY, None)
        self._save_state(new_state)
        self._state = new_state
        logger.info("Transition: %s -> %s (iteration=%d)", current, to_state, new_state["iteration"])

    def force_phase(self, phase: str) -> None:
        """Force the engine to a specific phase, bypassing transition validation.

        Used for recovery after a failed iteration where the engine may be
        in any intermediate state.
        """
        if phase not in ALL_STATES:
            raise ValueError(
                f"'{phase}' is not a recognized phase. "
                f"Valid phases: {sorted(s.value for s in Phase)}"
            )
        new_state = dict(self._state)
        new_state["iteration"] += 1
        new_state[_PHASE_KEY] = phase
        new_state["timestamp"] = datetime.now(timezone.utc).isoformat()
        new_state.pop(_LEGACY_PHASE_KEY, None)
        self._save_state(new_state)
        self._state = new_state
        logger.info("Force phase: -> %s (iteration=%d)", phase, new_state["iteration"])

    def _save_state(self, state: dict) -> None:
        atomic_write(self.state_path, json.dumps(state, indent=2) + "\n")
