"""Nous v2 campaign loop (spec 3.2).

Drives the BASELINE → DESIGN → EXECUTE → REPORT lifecycle in one session.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from .config import CampaignConfig
from .cost import CostMeter, load_prices
from .hooks import HookState, build_hooks
from .preflight import run_preflight
from .resume import build_fallback_message, load_campaign_state, resume_phase
from .robustness import FailureBreaker, poll_and_resume, write_halt
from .session import Session
from .final_check import check_answer
from .stop_rule import (
    best_changed,
    check_stop,
    claims_changed,
    principles_changed,
)
from .validators import bundle_hash, validate_phase_artifacts

logger = logging.getLogger(__name__)

# Re-export for backward compat
from .config import CampaignConfig, parse_campaign_config  # noqa: F811


def iter_dir(work_dir: Path, iteration: int) -> Path:
    return work_dir / "runs" / f"iter-{iteration}"


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


def _merge_principles(existing: list[dict], updates: dict | None) -> list[dict]:
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
        self, config: CampaignConfig, work_dir: Path, client_factory: Callable,
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

    async def _start_session(self, session_opts: dict) -> Session:
        session = Session(client_factory=self._client_factory, options=session_opts)
        await session.connect()
        return session

    async def run(self) -> dict:
        self._init_meter()
        hook_state, hooks, session_opts = self._build_hooks_and_session_opts()
        preflight_errors = await run_preflight(hooks, work_dir=self._work_dir)
        if preflight_errors:
            raise ValueError(
                "Preflight failed:\n" + "\n".join(f"  - {e}" for e in preflight_errors)
            )
        session = await self._start_session(session_opts)
        try:
            return await self._run_phases_from(session, hook_state, "BASELINE", 0)
        finally:
            await session.disconnect()

    async def resume(self, *, note: str | None = None) -> dict:
        self._init_meter()
        hook_state, hooks, session_opts = self._build_hooks_and_session_opts()

        state = load_campaign_state(self._work_dir)
        if state is None:
            return await self.run()

        saved_phase, saved_iteration = resume_phase(state)
        session_id = state.get("session_id")
        use_fallback = session_id is None or self._config.session_scope == "iteration"
        if not use_fallback:
            session_opts["resume"] = session_id
        self._reload_state(saved_iteration)

        session = await self._start_session(session_opts)
        try:
            if use_fallback:
                digest = _read_json(self._work_dir / "state" / "digest.json")
                msg = build_fallback_message(
                    phase=saved_phase, iteration=saved_iteration,
                    digest=digest, note=note,
                )
                await session.turn(msg, on_message=self._meter.record)
            return await self._run_phases_from(
                session, hook_state, saved_phase, saved_iteration, note=note,
            )
        finally:
            await session.disconnect()

    def _reload_state(self, up_to_iteration: int) -> None:
        ledger = _read_json(self._work_dir / "ledger.json")
        if isinstance(ledger, list):
            self._ledger = ledger
        principles = _read_json(self._work_dir / "principles.json")
        if isinstance(principles, list):
            self._principles = principles
        if up_to_iteration >= 1:
            prev_iter = max(up_to_iteration - 1, 1)
            prev = _read_json(iter_dir(self._work_dir, prev_iter) / "findings.json")
            if prev:
                self._prev_findings = prev

    async def _turn(self, session: Session, prompt: str) -> Any:
        return await session.turn(prompt, on_message=self._meter.record)

    async def _repair(self, session: Session, idir: Path, artifact_types: list[str]) -> str:
        for attempt in range(3):
            errors = validate_phase_artifacts(self._work_dir, idir, artifact_types)
            if not errors:
                return "ok"
            if attempt >= 2:
                break
            error_text = "\n".join(f"  - {e}" for e in errors)
            logger.warning("Repair attempt %d: %s", attempt + 1, error_text)
            await self._turn(session, f"Repair: fix these validation errors:\n{error_text}")
        logger.warning("Repair exhausted, marking partial")
        return "partial"

    async def _run_phases_from(
        self, session: Session, hook_state: HookState,
        start_phase: str, start_iteration: int, *, note: str | None = None,
    ) -> dict:
        breaker = FailureBreaker()
        skip_baseline = start_phase != "BASELINE" or start_iteration > 0
        skip_design_for = start_iteration if start_phase in ("EXECUTE", "REPORT") else 0

        if not skip_baseline:
            self._set_phase(hook_state, "BASELINE", 0)
            task_hint = "" if self._config.task_type else (
                " Determine the task_type (debug/verify/optimize/policy/"
                "explain/other) and include task_type_reason."
            )
            await self._turn(
                session,
                "BASELINE phase. Do not design hypotheses yet. "
                f"Get one real observation and write baseline.json.{task_hint}",
            )
            self._commit_phase(0, "BASELINE")

        first_iter = max(start_iteration, 1)
        if start_phase == "REPORT":
            self._set_phase(hook_state, "REPORT", start_iteration)
            await self._turn(session, "REPORT phase. Write answer.json and report.md.")
            last_iter = len(self._ledger) or start_iteration
            self._commit_phase(last_iter, "REPORT")
            self._record_final_check()
            return {"stop_reason": "resumed_report", "iterations": last_iter}

        stop_reason: str | None = None
        for iteration in range(first_iter, self._config.max_iterations + 1):
            idir = iter_dir(self._work_dir, iteration)
            idir.mkdir(parents=True, exist_ok=True)

            if iteration != skip_design_for:
                self._set_phase(hook_state, "DESIGN", iteration)
                baseline = _read_json(self._work_dir / "baseline.json")
                if baseline is None:
                    raise ValueError("baseline.json missing; cannot DESIGN")
                principles_text = ""
                if self._principles:
                    principles_text = "\n\nActive principles:\n" + json.dumps(self._principles, indent=2)
                try:
                    await self._turn(
                        session,
                        f"Iteration {iteration}, DESIGN phase. "
                        f"Read state/digest.json and baseline.json. "
                        f"Frame predictions relative to baseline. "
                        f"Write runs/iter-{iteration}/problem.json, "
                        f"runs/iter-{iteration}/bundle.json, "
                        f"runs/iter-{iteration}/plan.json.{principles_text}",
                    )
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

            # EXECUTE
            self._set_phase(hook_state, "EXECUTE", iteration)
            plan = _read_json(idir / "plan.json")
            pending_waits = [r for r in (plan or {}).get("runs", []) if r.get("wait_for")]
            hook_state.pending_wait_for = [r["wait_for"] for r in pending_waits]
            execute_note = note if iteration == first_iter else None
            exec_prompt = (
                f"Iteration {iteration}, EXECUTE phase. "
                f"Run plan.json; fix anything that does not run. "
                f"Write runs/iter-{iteration}/findings.json "
                f"and runs/iter-{iteration}/principle_updates.json."
            )
            if execute_note:
                exec_prompt += f"\n\nHuman note: {execute_note}"
            await self._turn(session, exec_prompt)
            hook_state.pending_wait_for = []

            async def metered_turn(prompt: str) -> Any:
                return await self._turn(session, prompt)
            await poll_and_resume(pending_waits, iteration, breaker, metered_turn)
            self._commit_phase(iteration, "EXECUTE")

            status = await self._repair(session, idir, ["findings", "principle_updates"])
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
            iter_cost = self._meter.iter_delta()
            entry: dict[str, Any] = {
                "iteration": iteration,
                "bundle_hash": locked_hash,
                "claims_changed": cc, "best_changed": bc,
                "principles_changed": pc, "prereg_violation": prereg,
                "status": status, "stop_reason": None,
                "cost_meter_usd": iter_cost["cost_usd"],
                "tokens": {"input": iter_cost["input_tokens"], "output": iter_cost["output_tokens"]},
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
                iteration=iteration, findings=findings, principle_updates=pu,
                ledger=self._ledger[:-1],
                max_iterations=self._config.max_iterations,
                stall_iterations=self._config.stall_iterations,
                halt_path=self._work_dir / "halt.json",
                stop_sentinel_path=self._work_dir / "STOP",
                current_claims_changed=cc, current_best_changed=bc,
                claims_needed=problem.get("claims_needed"),
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

        self._set_phase(hook_state, "REPORT", len(self._ledger))
        await self._turn(session, "REPORT phase. Write answer.json and report.md.")
        self._commit_phase(len(self._ledger), "REPORT")
        self._record_final_check()
        return {"stop_reason": stop_reason, "iterations": len(self._ledger)}

    def _record_final_check(self) -> None:
        """Spec 3.8: check answer.json against the record and log the result in the ledger."""
        report = check_answer(self._work_dir)
        if self._ledger:
            self._ledger[-1].update(
                repro_recorded=report["repro_recorded"],
                claims_matched_fraction=report["claims_matched_fraction"],
            )
            _write_json(self._work_dir / "ledger.json", self._ledger)
        _write_json(self._work_dir / "final_check.json", report)

    def _set_phase(self, hook_state: HookState, phase: str, iteration: int) -> None:
        hook_state.phase = phase
        hook_state.iteration = iteration
        self._meter.set_phase(phase)
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

    def _lock_bundle(self, idir: Path) -> str:
        bundle = _read_json(idir / "bundle.json")
        if bundle is None:
            raise ValueError(f"bundle.json missing at {idir.name} after DESIGN")
        h = bundle_hash(bundle)
        _write_json(idir / ".bundle.locked.json", bundle)
        return h

    def _check_bundle_hash(self, idir: Path, locked_hash: str) -> bool:
        bundle = _read_json(idir / "bundle.json")
        if bundle is None or not locked_hash:
            return False
        if bundle_hash(bundle) != locked_hash:
            locked = _read_json(idir / ".bundle.locked.json")
            if locked:
                _write_json(idir / "bundle.json", locked)
            return True
        return False

    def _commit_phase(self, iteration: int, phase: str) -> None:
        target = self._config.target_system.get("repo_path")
        if not target:
            return
        target_path = Path(target)
        if not (target_path / ".git").exists():
            return
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(target_path), capture_output=True, text=True, timeout=30,
            )
            if not status.stdout.strip():
                return
            subprocess.run(
                ["git", "add", "-A"],
                cwd=str(target_path), capture_output=True, timeout=30,
            )
            msg = f"nous: {phase}" if iteration == 0 else f"nous: iter-{iteration} {phase}"
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
