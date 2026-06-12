"""PRE_WORK phase — cheap deterministic exploration before iter-1 DESIGN (issue #167).

User feedback (2026-05-25): "30 minutes of exploration could give the
campaign a much better starting point than throwing it at the LLM cold
... investing in pre-work makes the LLM iterations more targeted."

Approach
--------
Two production runners + an injection seam for tests:

  1. Default Python runner (no campaign config needed): summarizes
     ``target_system.observable_metrics`` and ``controllable_knobs``
     into ``data_summary``. Zero LLM tokens, zero subprocess. The
     output is intentionally thin — the designer's prompt already
     reads ``campaign.yaml``, so this is just structured restatement.

  2. Subprocess runner (when ``campaign.pre_work_script`` is set): runs
     the user-supplied script as a subprocess and parses its stdout as
     JSON into a ``PreWorkResult``. This is the seam for domain-specific
     hand-tested exploration — clustering visualizations, candidate
     groupings, baseline computations.

Failure modes are tolerant: a non-zero exit, a JSON parse error, or a
missing script all yield an empty ``PreWorkResult`` so DESIGN proceeds
unchanged. The PRE_WORK phase is opportunistic, not load-bearing.

The ``runner=`` keyword on ``run_pre_work`` is the test injection seam —
it bypasses both production paths so tests never invoke a real
subprocess.

Engine integration: ``Phase.PRE_WORK`` lives between ``INIT`` and
``DESIGN`` in the transition map; both ``INIT → PRE_WORK → DESIGN`` and
``INIT → DESIGN`` (legacy) are valid. The campaign loop chooses based
on whether ``campaign.pre_work_script`` is set or the engine has been
explicitly directed to run pre-work.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 300


@dataclass
class PreWorkResult:
    """Structured output of the PRE_WORK phase.

    All fields optional. An all-None ``PreWorkResult`` is a valid
    "nothing to report" outcome — the campaign continues into DESIGN
    with no extra context.
    """
    data_summary: dict[str, Any] | None = None
    candidate_parameter_ranges: dict[str, Any] | None = None
    structural_groupings: list[Any] | None = None
    baseline_metrics: dict[str, Any] | None = None
    recommended_arms_for_iter1: list[Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Drop None fields before writing to disk — keeps the artifact tidy."""
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


PreWorkRunner = Callable[[dict], PreWorkResult]
"""Runner protocol: takes the campaign dict, returns a PreWorkResult."""


def _default_python_runner(campaign: dict) -> PreWorkResult:
    """Summary of campaign fields. Zero token cost. Deterministic.

    Intentionally minimal: the designer's prompt already reads
    campaign.yaml, so duplicating it here would just inflate context.
    The value-add is *normalization* — the designer reads one canonical
    structure regardless of whether the user populated optional
    campaign fields.
    """
    target = campaign.get("target_system", {}) if isinstance(campaign, dict) else {}
    if not isinstance(target, dict):
        return PreWorkResult()

    summary: dict[str, Any] = {}
    metrics = target.get("observable_metrics")
    if isinstance(metrics, list) and metrics:
        summary["observable_metrics"] = list(metrics)
    knobs = target.get("controllable_knobs")
    if isinstance(knobs, list) and knobs:
        summary["controllable_knobs"] = list(knobs)

    if not summary:
        return PreWorkResult()
    return PreWorkResult(data_summary=summary)


def _subprocess_runner(campaign: dict) -> PreWorkResult:
    """Run the user-supplied pre_work_script and parse its stdout JSON.

    Tolerant of failure: non-zero exit, JSON parse errors, and missing
    scripts all yield an empty PreWorkResult. Pre-work is opportunistic;
    a failed script must not break the campaign.
    """
    script = campaign.get("pre_work_script")
    if not script:
        return PreWorkResult()

    try:
        proc = subprocess.run(
            [str(script)],
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("pre_work_script %r failed to run: %s", script, exc)
        return PreWorkResult()

    if proc.returncode != 0:
        logger.warning(
            "pre_work_script %r exited with code %d; stderr=%r",
            script, proc.returncode, (proc.stderr or "")[:200],
        )
        return PreWorkResult()

    try:
        payload = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning(
            "pre_work_script %r emitted non-JSON stdout: %s", script, exc,
        )
        return PreWorkResult()

    if not isinstance(payload, dict):
        return PreWorkResult()

    return PreWorkResult(
        data_summary=payload.get("data_summary"),
        candidate_parameter_ranges=payload.get("candidate_parameter_ranges"),
        structural_groupings=payload.get("structural_groupings"),
        baseline_metrics=payload.get("baseline_metrics"),
        recommended_arms_for_iter1=payload.get("recommended_arms_for_iter1"),
    )


def run_pre_work(
    campaign: dict,
    *,
    runner: PreWorkRunner | None = None,
) -> PreWorkResult:
    """Execute the PRE_WORK phase.

    Args:
        campaign: Parsed campaign.yaml dict.
        runner: Optional injected runner. When set, takes precedence
            over both production paths — this is the test seam. When
            unset, ``pre_work_script`` selects the subprocess path;
            otherwise the default Python summarizer runs.

    Returns:
        PreWorkResult. May be empty (all-None) if no signal is available.
    """
    if runner is not None:
        return runner(campaign)
    if campaign.get("pre_work_script"):
        return _subprocess_runner(campaign)
    return _default_python_runner(campaign)


def write_pre_work(work_dir: Path, result: PreWorkResult) -> Path:
    """Atomically write ``pre_work.json`` to ``work_dir`` and return the path."""
    work_dir = Path(work_dir)
    target = work_dir / "pre_work.json"
    atomic_write(target, json.dumps(result.to_dict(), indent=2) + "\n")
    return target
