"""Nous v2 campaign loop (spec 3.2).

Drives the BASELINE → DESIGN → EXECUTE → REPORT lifecycle in one session.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .cost import CostMeter, load_prices
from .hooks import HookState, build_hooks
from .preflight import run_preflight
from .resume import build_fallback_message, load_campaign_state, resume_phase
from .robustness import FailureBreaker, check_wait_condition, write_halt
from .session import Session
from .stop_rule import (
    best_changed,
    check_stop,
    claims_changed,
    principles_changed,
)
from .validators import bundle_hash, validate_artifact, ValidatorContext

logger = logging.getLogger(__name__)


def iter_dir(work_dir: Path, iteration: int) -> Path:
    """Return the canonical iteration directory: work_dir/runs/iter-N."""
    return work_dir / "runs" / f"iter-{iteration}"


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

    ts = raw["target_system"]
    if not isinstance(ts, dict) or "repo_path" not in ts:
        raise ValueError(
            "campaign.yaml: target_system must contain 'repo_path' "
            "(the path to the target git repo)"
        )

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

    def _init_meter(self) -> None:
        defaults_path = Path(__file__).resolve().parent.parent / "defaults.yaml"
        self._meter = CostMeter(load_prices(defaults_path))

    def _build_hooks_and_session_opts(self) -> tuple[HookState, dict, dict]:
        hook_state = HookState(
            work_dir=self._work_dir,
            secrets={k: os.environ.get(k, "") for k in self._config.secrets},
            experiment_commands=self._config.experiment_commands,
        )
        hooks = build_hooks(hook_state)
        session_opts = {
            "work_dir": str(self._work_dir),
            "effort": self._config.effort,
            "hooks": hooks,
            "cwd": self._config.target_system.get("repo_path"),
        }
        return hook_state, hooks, session_opts

    async def run(self) -> dict:
        """Execute the full campaign. Returns summary dict."""
        self._init_meter()
        hook_state, hooks, session_opts = self._build_hooks_and_session_opts()

        preflight_errors = await run_preflight(hooks, work_dir=self._work_dir)
        if preflight_errors:
            raise ValueError(
                "Preflight failed:\n" + "\n".join(f"  - {e}" for e in preflight_errors)
            )

        session = Session(
            client_factory=self._client_factory,
            options=session_opts,
        )
        await session.connect()
        try:
            return await self._run_phases_from(
                session, hook_state, "BASELINE", 0,
            )
        finally:
            await session.disconnect()

    async def resume(self, *, note: str | None = None) -> dict:
        """Resume a campaign from state.json, or start fresh if missing."""
        self._init_meter()
        hook_state, hooks, session_opts = self._build_hooks_and_session_opts()

        state = load_campaign_state(self._work_dir)
        if state is None:
            return await self.run()

        saved_phase, saved_iteration = resume_phase(state)
        session_id = state.get("session_id")
        use_fallback = (
            session_id is None
            or self._config.session_scope == "iteration"
        )

        if not use_fallback:
            session_opts["resume"] = session_id

        self._reload_state(saved_iteration)

        session = Session(
            client_factory=self._client_factory,
            options=session_opts,
        )
        await session.connect()
        try:
            if use_fallback:
                digest = _read_json(self._work_dir / "state" / "digest.json")
                msg = build_fallback_message(
                    phase=saved_phase,
                    iteration=saved_iteration,
                    digest=digest,
                    note=note,
                )
                await session.turn(msg)

            return await self._run_phases_from(
                session, hook_state, saved_phase, saved_iteration, note=note,
            )
        finally:
            await session.disconnect()

    def _reload_state(self, up_to_iteration: int) -> None:
        """Reload ledger, principles, and prev_findings from disk."""
        ledger = _read_json(self._work_dir / "ledger.json")
        if isinstance(ledger, list):
            self._ledger = ledger
        principles = _read_json(self._work_dir / "principles.json")
        if isinstance(principles, list):
            self._principles = principles
        if up_to_iteration >= 1:
            prev_iter = up_to_iteration - 1 if up_to_iteration > 1 else 1
            prev_findings = _read_json(
                iter_dir(self._work_dir, prev_iter) / "findings.json"
            )
            if prev_findings:
                self._prev_findings = prev_findings

    async def _run_phases_from(
        self,
        session: Session,
        hook_state: HookState,
        start_phase: str,
        start_iteration: int,
        *,
        note: str | None = None,
    ) -> dict:
        """Resume the campaign loop from a given phase/iteration."""
        breaker = FailureBreaker()
        skip_baseline = start_phase != "BASELINE" or start_iteration > 0
        skip_design_for = start_iteration if start_phase in ("EXECUTE", "REPORT") else 0

        if not skip_baseline:
            hook_state.phase = "BASELINE"
            hook_state.iteration = 0
            self._meter.set_phase("BASELINE")
            self._update_state_phase("BASELINE", 0)
            await self._baseline(session)
            self._commit_phase(0, "BASELINE")

        first_iter = max(start_iteration, 1)
        if start_phase == "REPORT":
            hook_state.phase = "REPORT"
            self._meter.set_phase("REPORT")
            self._update_state_phase("REPORT", start_iteration)
            await self._report(session)
            last_iter = len(self._ledger) or start_iteration
            self._commit_phase(last_iter, "REPORT")
            return {"stop_reason": "resumed_report", "iterations": last_iter}

        stop_reason: str | None = None
        for iteration in range(first_iter, self._config.max_iterations + 1):
            idir = iter_dir(self._work_dir, iteration)
            idir.mkdir(parents=True, exist_ok=True)

            do_design = not (iteration == skip_design_for)

            if do_design:
                hook_state.phase = "DESIGN"
                hook_state.iteration = iteration
                self._meter.set_phase("DESIGN")
                self._update_state_phase("DESIGN", iteration)
                try:
                    await self._design(session, iteration)
                except Exception as exc:
                    fp = breaker.record(type(exc).__name__, "DESIGN", str(exc))
                    if fp:
                        write_halt(self._work_dir, fp, "DESIGN", str(exc))
                        stop_reason = "halt"
                        break
                    raise
                self._commit_phase(iteration, "DESIGN")
                locked_hash = self._lock_bundle(idir)
            else:
                locked_hash = self._lock_bundle(idir) if (idir / "bundle.json").exists() else ""

            hook_state.phase = "EXECUTE"
            self._meter.set_phase("EXECUTE")
            self._update_state_phase("EXECUTE", iteration)
            pending_waits = self._get_pending_waits(idir)
            hook_state.pending_wait_for = [r["wait_for"] for r in pending_waits]
            execute_note = note if iteration == first_iter else None
            await self._execute(session, iteration, note=execute_note)
            hook_state.pending_wait_for = []
            await self._poll_and_resume(
                session, idir, pending_waits, iteration, breaker,
            )
            self._commit_phase(iteration, "EXECUTE")

            status = await self._repair_phase(
                session, hook_state, idir, "EXECUTE",
                ["findings", "principle_updates"],
            )
            prereg = self._check_bundle_hash(idir, locked_hash)

            findings = _read_json(idir / "findings.json") or {}
            pu = _read_json(idir / "principle_updates.json")

            cc = claims_changed(self._prev_findings, findings)
            bc = best_changed(
                self._prev_findings, findings,
                direction=self._objective_direction(),
                min_improvement=self._config.min_improvement,
            )
            pc = principles_changed(pu)

            self._principles = _merge_principles(self._principles, pu)
            _write_json(self._work_dir / "principles.json", self._principles)

            problem = _read_json(idir / "problem.json") or {}
            cn = problem.get("claims_needed")

            iter_cost = self._meter.total()
            entry: dict[str, Any] = {
                "iteration": iteration,
                "bundle_hash": locked_hash,
                "claims_changed": cc,
                "best_changed": bc,
                "principles_changed": pc,
                "prereg_violation": prereg,
                "status": status,
                "stop_reason": None,
                "cost_meter_usd": iter_cost["cost_usd"],
                "tokens": {
                    "input": iter_cost["input_tokens"],
                    "output": iter_cost["output_tokens"],
                },
            }
            if execute_note:
                entry["note"] = execute_note
            self._ledger.append(entry)
            _write_json(self._work_dir / "ledger.json", self._ledger)
            self._prev_findings = findings

            if status == "partial":
                fp = breaker.record("ValidationError", "EXECUTE", "repair exhausted")
                if fp:
                    write_halt(self._work_dir, fp, "EXECUTE", "repair exhausted")

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
        self._meter.set_phase("REPORT")
        last_iter = len(self._ledger)
        self._update_state_phase("REPORT", last_iter)
        await self._report(session)
        self._commit_phase(last_iter, "REPORT")

        return {"stop_reason": stop_reason, "iterations": last_iter}

    async def _repair_phase(
        self,
        session: Session,
        hook_state: HookState,
        phase_dir: Path,
        phase: str,
        artifact_types: list[str],
    ) -> str:
        """Validate phase artifacts; send up to 2 repair messages if needed.

        Returns "ok" or "partial".
        """
        for attempt in range(3):  # initial check + 2 repairs
            errors = self._validate_phase_artifacts(phase_dir, artifact_types)
            if not errors:
                return "ok"
            if attempt >= 2:
                break
            error_text = "\n".join(f"  - {e}" for e in errors)
            logger.warning("Repair attempt %d for %s: %s", attempt + 1, phase, error_text)
            await session.turn(
                f"Repair {phase}: the following validation errors must be fixed:\n{error_text}",
                on_message=self._meter.record,
            )
        logger.warning("Repair exhausted for %s, marking partial", phase)
        return "partial"

    def _validate_phase_artifacts(
        self, phase_dir: Path, artifact_types: list[str]
    ) -> list[str]:
        """Run validators on phase artifacts, return error list."""
        all_errors: list[str] = []
        for artifact_type in artifact_types:
            path = phase_dir / f"{artifact_type}.json"
            if not path.exists():
                all_errors.append(f"{artifact_type}: file not found")
                continue
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                all_errors.append(f"{artifact_type}: invalid JSON — {exc}")
                continue
            ctx = ValidatorContext(work_dir=self._work_dir, iter_dir=phase_dir)
            errors = validate_artifact(artifact_type, data, ctx)
            for e in errors:
                all_errors.append(f"{artifact_type}: {e}")
        return all_errors

    def _get_pending_waits(self, phase_dir: Path) -> list[dict]:
        """Return plan.json runs that have wait_for entries."""
        plan = _read_json(phase_dir / "plan.json")
        if not plan:
            return []
        return [r for r in plan.get("runs", []) if r.get("wait_for")]

    async def _poll_and_resume(
        self,
        session: Session,
        phase_dir: Path,
        pending_waits: list[dict],
        iteration: int,
        breaker: FailureBreaker,
    ) -> list[str]:
        """Poll all wait_for conditions together; send resume when any finish.

        Returns list of timed-out run ids.
        """
        if not pending_waits:
            return []

        remaining = {r["id"]: r["wait_for"] for r in pending_waits}
        timed_out: list[str] = []
        max_polls = 240  # 240 × 60s = 4h
        ev_loop = asyncio.get_event_loop()

        for _ in range(max_polls):
            done = [
                rid for rid, wf in remaining.items()
                if check_wait_condition(wf)
            ]
            for rid in done:
                del remaining[rid]
            if done:
                ids_str = ", ".join(done)
                logger.info("wait_for satisfied for runs: %s", ids_str)
                if remaining:
                    await session.turn(
                        f"Runs {ids_str} finished; continue EXECUTE. "
                        f"Runs still pending: {', '.join(remaining)}.",
                        on_message=self._meter.record,
                    )
                else:
                    await session.turn(
                        f"Runs {ids_str} finished; continue EXECUTE. "
                        f"Write runs/iter-{iteration}/findings.json "
                        f"and runs/iter-{iteration}/principle_updates.json.",
                        on_message=self._meter.record,
                    )
            if not remaining:
                break
            await ev_loop.run_in_executor(None, time.sleep, 60.0)
        else:
            timed_out = list(remaining)
            for rid in timed_out:
                logger.warning("wait_for timed out for run %s", rid)
                breaker.record("TimeoutError", "EXECUTE", f"wait_for timed out: {rid}")
            await session.turn(
                f"Runs {', '.join(timed_out)} timed out. "
                f"Write findings for completed runs only.",
                on_message=self._meter.record,
            )

        return timed_out

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
        await session.turn(prompt, on_message=self._meter.record)

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
            f"Write runs/iter-{iteration}/problem.json, "
            f"runs/iter-{iteration}/bundle.json, "
            f"runs/iter-{iteration}/plan.json."
            f"{principles_text}"
        )
        await session.turn(prompt, on_message=self._meter.record)

    async def _execute(
        self, session: Session, iteration: int, *, note: str | None = None,
    ) -> None:
        prompt = (
            f"Iteration {iteration}, EXECUTE phase. "
            f"Run plan.json; fix anything that does not run. "
            f"If a run has wait_for, it will be polled automatically. "
            f"Write runs/iter-{iteration}/findings.json "
            f"and runs/iter-{iteration}/principle_updates.json."
        )
        if note:
            prompt += f"\n\nHuman note: {note}"
        await session.turn(prompt, on_message=self._meter.record)

    async def _report(self, session: Session) -> None:
        prompt = "REPORT phase. Write answer.json and report.md."
        await session.turn(prompt, on_message=self._meter.record)

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
        target = self._config.target_system.get("repo_path")
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

    def _update_state_phase(self, phase: str, iteration: int) -> None:
        """Write phase and iteration to state.json for resume."""
        state_path = self._work_dir / "state.json"
        existing: dict[str, Any] = {}
        if state_path.exists():
            try:
                existing = json.loads(state_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        existing["phase"] = phase
        existing["iteration"] = iteration
        _write_json(state_path, existing)

    def _objective_direction(self) -> str:
        obj = self._config.objective
        if obj and isinstance(obj, dict):
            return obj.get("direction", "increase")
        return "increase"
