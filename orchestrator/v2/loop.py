"""Nous v2 campaign loop (spec 3.2).

Drives the BASELINE → DESIGN → EXECUTE → REPORT lifecycle in one session.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .hooks import HookState, build_hooks
from .session import Session
from .stop_rule import (
    best_changed,
    check_stop,
    claims_changed,
    principles_changed,
)
from .validators import bundle_hash, validate_artifact, ValidatorContext

logger = logging.getLogger(__name__)

_LEGACY_KEYS = frozenset({
    "critic", "pre_work", "arm_sweep", "parallel_arms",
    "complexity_tiers", "iteration_mode",
})

_REQUIRED_KEYS = ("research_question", "target_system")


@dataclass
class CampaignConfig:
    research_question: str
    run_id: str
    max_iterations: int
    target_system: dict
    prompts: dict = field(default_factory=dict)
    effort: str | None = None
    human_gates: bool = False
    secrets: list[str] = field(default_factory=list)
    min_improvement: float = 0
    stall_iterations: int = 2
    task_type: str | None = None
    session_scope: str = "campaign"
    experiment_commands: list[str] = field(default_factory=list)
    task_limits: dict | None = None
    objective: dict | None = None


def parse_campaign_config(raw: dict) -> CampaignConfig:
    """Parse and validate a campaign.yaml dict into CampaignConfig."""
    for key in _REQUIRED_KEYS:
        if key not in raw:
            raise ValueError(f"campaign.yaml missing required key: {key}")

    for key in _LEGACY_KEYS & raw.keys():
        logger.warning("campaign.yaml: ignoring legacy key %r", key)

    return CampaignConfig(
        research_question=raw["research_question"],
        run_id=raw.get("run_id", "unnamed"),
        max_iterations=raw.get("max_iterations", 5),
        target_system=raw["target_system"],
        prompts=raw.get("prompts", {}),
        effort=raw.get("effort"),
        human_gates=raw.get("human_gates", False),
        secrets=raw.get("secrets", []),
        min_improvement=raw.get("min_improvement", 0),
        stall_iterations=raw.get("stall_iterations", 2),
        task_type=raw.get("task_type"),
        session_scope=raw.get("session_scope", "campaign"),
        experiment_commands=raw.get("experiment_commands", []),
        task_limits=raw.get("task_limits"),
        objective=raw.get("objective"),
    )


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        logger.warning("corrupt JSON in %s", path.name)
        return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _merge_principles(
    existing: list[dict], updates: dict | None
) -> list[dict]:
    """Apply principle_updates to the active principles list."""
    if updates is None:
        return existing
    result = list(existing)
    by_id = {p["id"]: i for i, p in enumerate(result)}
    for u in updates.get("updates", []):
        uid = u.get("id")
        if uid is None:
            continue
        action = u.get("action", "add")
        text = u.get("text", "")
        if action == "add":
            result.append({"id": uid, "text": text})
        elif action == "revise":
            idx = by_id.get(uid)
            if idx is not None:
                result[idx] = {"id": uid, "text": text}
        elif action == "remove":
            result = [p for p in result if p["id"] != uid]
    return result


class Campaign:
    """Drives a Nous v2 campaign through its phases."""

    def __init__(
        self,
        config: CampaignConfig,
        work_dir: Path,
        client_factory: Callable,
    ) -> None:
        self._config = config
        self._work_dir = work_dir
        self._client_factory = client_factory
        self._ledger: list[dict] = []
        self._principles: list[dict] = []
        self._prev_findings: dict | None = None

    async def run(self) -> dict:
        """Execute the full campaign. Returns summary dict."""
        hook_state = HookState(
            work_dir=self._work_dir,
            secrets={k: "***" for k in self._config.secrets},
            experiment_commands=self._config.experiment_commands,
        )
        hooks = build_hooks(hook_state)
        session = Session(
            client_factory=self._client_factory,
            options={
                "work_dir": str(self._work_dir),
                "effort": self._config.effort,
                "hooks": hooks,
            },
        )
        await session.connect()
        try:
            return await self._run_phases(session, hook_state)
        finally:
            await session.disconnect()

    async def _run_phases(
        self, session: Session, hook_state: HookState
    ) -> dict:
        hook_state.phase = "BASELINE"
        hook_state.iteration = 0
        await self._baseline(session)
        self._commit_phase(0, "BASELINE")

        stop_reason: str | None = None
        for iteration in range(1, self._config.max_iterations + 1):
            iter_dir = self._work_dir / f"iter-{iteration}"
            iter_dir.mkdir(parents=True, exist_ok=True)

            hook_state.phase = "DESIGN"
            hook_state.iteration = iteration
            await self._design(session, iteration)
            self._commit_phase(iteration, "DESIGN")
            locked_hash = self._lock_bundle(iter_dir)
            hook_state.phase = "EXECUTE"
            await self._execute(session, iteration)
            self._commit_phase(iteration, "EXECUTE")
            prereg = self._check_bundle_hash(iter_dir, locked_hash)

            findings = _read_json(iter_dir / "findings.json") or {}
            pu = _read_json(iter_dir / "principle_updates.json")

            cc = claims_changed(self._prev_findings, findings)
            bc = best_changed(
                self._prev_findings, findings,
                direction=self._objective_direction(),
                min_improvement=self._config.min_improvement,
            )
            pc = principles_changed(pu)

            self._principles = _merge_principles(self._principles, pu)
            _write_json(self._work_dir / "principles.json", self._principles)

            problem = _read_json(iter_dir / "problem.json") or {}
            cn = problem.get("claims_needed")

            entry = {
                "iteration": iteration,
                "bundle_hash": locked_hash,
                "claims_changed": cc,
                "best_changed": bc,
                "principles_changed": pc,
                "prereg_violation": prereg,
                "status": "ok",
                "stop_reason": None,
            }
            self._ledger.append(entry)
            _write_json(self._work_dir / "ledger.json", self._ledger)
            self._prev_findings = findings

            stop_reason = check_stop(
                iteration=iteration,
                findings=findings,
                principle_updates=pu,
                ledger=self._ledger[:-1],
                max_iterations=self._config.max_iterations,
                stall_iterations=self._config.stall_iterations,
                halt_path=self._work_dir / "halt.json",
                stop_sentinel_path=self._work_dir / "STOP",
                current_claims_changed=cc,
                current_best_changed=bc,
                claims_needed=cn,
            )

            if stop_reason is not None:
                entry["stop_reason"] = stop_reason
                _write_json(self._work_dir / "ledger.json", self._ledger)
                break

        if stop_reason is None:
            stop_reason = "max_iterations"
            if self._ledger:
                self._ledger[-1]["stop_reason"] = stop_reason
                _write_json(self._work_dir / "ledger.json", self._ledger)

        hook_state.phase = "REPORT"
        await self._report(session)
        last_iter = len(self._ledger)
        self._commit_phase(last_iter, "REPORT")

        return {"stop_reason": stop_reason, "iterations": last_iter}

    async def _baseline(self, session: Session) -> None:
        task_hint = ""
        if not self._config.task_type:
            task_hint = (
                " Determine the task_type (debug/verify/optimize/policy/"
                "explain/other) and include task_type_reason."
            )
        prompt = (
            "BASELINE phase. Do not design hypotheses yet. "
            "Get one real observation of the current system and "
            f"write baseline.json.{task_hint}"
        )
        await session.turn(prompt)

    async def _design(self, session: Session, iteration: int) -> None:
        baseline = _read_json(self._work_dir / "baseline.json")
        if baseline is None:
            raise ValueError("baseline.json missing or invalid; cannot proceed to DESIGN")

        principles_text = ""
        if self._principles:
            principles_text = "\n\nActive principles:\n" + json.dumps(
                self._principles, indent=2
            )
        prompt = (
            f"Iteration {iteration}, DESIGN phase. "
            f"Read state/digest.json and baseline.json. "
            f"Frame each prediction as a change relative to the baseline. "
            f"Write iter-{iteration}/problem.json, "
            f"iter-{iteration}/bundle.json, "
            f"iter-{iteration}/plan.json."
            f"{principles_text}"
        )
        await session.turn(prompt)

    async def _execute(self, session: Session, iteration: int) -> None:
        prompt = (
            f"Iteration {iteration}, EXECUTE phase. "
            f"Run plan.json; fix anything that does not run. "
            f"If a run has wait_for, it will be polled automatically. "
            f"Write iter-{iteration}/findings.json "
            f"and iter-{iteration}/principle_updates.json."
        )
        await session.turn(prompt)

    async def _report(self, session: Session) -> None:
        prompt = "REPORT phase. Write answer.json and report.md."
        await session.turn(prompt)

    def _lock_bundle(self, iter_dir: Path) -> str:
        bundle = _read_json(iter_dir / "bundle.json")
        if bundle is None:
            raise ValueError(f"bundle.json missing at {iter_dir.name} after DESIGN")
        h = bundle_hash(bundle)
        _write_json(iter_dir / ".bundle.locked.json", bundle)
        return h

    def _check_bundle_hash(self, iter_dir: Path, locked_hash: str) -> bool:
        bundle = _read_json(iter_dir / "bundle.json")
        if bundle is None or not locked_hash:
            return False
        current_hash = bundle_hash(bundle)
        if current_hash != locked_hash:
            locked = _read_json(iter_dir / ".bundle.locked.json")
            if locked:
                _write_json(iter_dir / "bundle.json", locked)
            return True
        return False

    def _commit_phase(self, iteration: int, phase: str) -> None:
        """Commit the target worktree if there are changes."""
        target = self._config.target_system.get("path")
        if not target:
            return
        target_path = Path(target)
        if not (target_path / ".git").exists():
            return
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(target_path), capture_output=True, text=True,
                timeout=30,
            )
            if not status.stdout.strip():
                return
            subprocess.run(
                ["git", "add", "-A"],
                cwd=str(target_path), capture_output=True, timeout=30,
            )
            msg = f"nous: iter-{iteration} {phase}"
            if iteration == 0:
                msg = f"nous: {phase}"
            subprocess.run(
                ["git", "commit", "-m", msg, "--allow-empty"],
                cwd=str(target_path), capture_output=True, timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            logger.warning("failed to commit target worktree after %s", phase)

    def _objective_direction(self) -> str:
        obj = self._config.objective
        if obj and isinstance(obj, dict):
            return obj.get("direction", "increase")
        return "increase"
