"""Nous v2 campaign loop (spec 3.2).

Drives the BASELINE → DESIGN → EXECUTE → REPORT lifecycle in one session.
"""

from __future__ import annotations

import functools
import json
import logging
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from .config import CampaignConfig, parse_campaign_config, validator_limits  # noqa: F401 (re-export)
from .cost import CostMeter, load_prices
from .hooks import DEFAULT_EXPERIMENT_COMMANDS, HookState, build_hooks
from .preflight import run_preflight
from .resume import build_fallback_message, load_campaign_state, resume_phase, update_state
from .robustness import FailureBreaker, poll_and_resume, write_halt
from .prompts import build_system_prompt
from .effort import CUT_RESUME_MSG, EFFORT_LADDER, EffortManager
from .session import DEFAULT_MODEL, ContextOverflowError, Session
from .final_check import _check_repro, check_answer
from .stop_rule import (
    best_changed,
    check_stop,
    claims_changed,
    principles_changed,
    unmet_requirements,
)
from .validators import (bundle_hash, campaign_record, evidence_hint, read_json as _read_json,
                         resolve_evidence_path, validate_phase_artifacts)

logger = logging.getLogger(__name__)

EVIDENCE_DIR = "nous_evidence"  # answer evidence copied into the target repo
EXPERIMENTS_DIR = ".nous-experiments"  # the campaign's code worktree: <repo>/.nous-experiments/<run_id>/
REPRO_REPAIR_MSG = ("Run the repro command from answer.json exactly as written, from the "
                    "repository root, and fix answer.json until it succeeds.")


def iter_dir(work_dir: Path, iteration: int) -> Path:
    return work_dir / "runs" / f"iter-{iteration}"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _as_number(text: str) -> int | float | None:
    try:
        return int(text)
    except ValueError:
        try:
            x = float(text)
        except ValueError:
            return None
        return x if math.isfinite(x) else None


def _merge_principles(existing: list[dict], updates: dict | None) -> list[dict]:
    if updates is None:
        return existing
    result = list(existing)
    for u in updates.get("updates", []):
        uid = u.get("id")
        if uid is None:
            continue
        action = u.get("action", "add")
        text = u.get("text", "")
        entry = {"id": uid, "text": text, **({"scope": u["scope"]} if u.get("scope") else {})}
        if action == "add":
            result.append(entry)
        elif action == "revise":
            result = [entry if p["id"] == uid else p for p in result]
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
        self._turns_ok = 0
        self._effort = EffortManager(config.effort)
        self._breaker = FailureBreaker()
        # Spec 3.1/D5: the agent works and Nous commits in one campaign worktree, never the
        # user's checkout. _prepare_code_dir() sets it; a non-git repo_path is used as is.
        self._code_dir: str | None = config.target_system.get("repo_path")
        self._commits = False

    def _prepare_code_dir(self) -> None:
        """Create (or reuse on resume) <repo>/.nous-experiments/<run_id>/ on branch nous/<run_id>."""
        repo = self._config.target_system.get("repo_path")
        is_git = bool(repo) and Path(repo).is_dir() and subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"], cwd=repo, capture_output=True, text=True,
        ).stdout.strip() == "true"
        if not is_git:
            logger.warning("repo_path %s is not a git repo: the agent works in it directly and "
                           "Nous makes no phase commits", repo)
            return
        wt = Path(repo).resolve() / EXPERIMENTS_DIR / self._config.run_id
        self._exclude_experiments_dir(repo)
        if not (wt / ".git").exists():
            branch = f"nous/{self._config.run_id}"
            has_branch = subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
                cwd=repo, capture_output=True).returncode == 0
            args = [str(wt), branch] if has_branch else ["-b", branch, str(wt), "HEAD"]
            try:
                r = subprocess.run(["git", "worktree", "add", "-q", *args], cwd=repo,
                                   capture_output=True, text=True, timeout=60)
            except (subprocess.TimeoutExpired, OSError) as exc:
                raise ValueError(f"Preflight failed:\n  - git worktree add {wt}: {exc}") from exc
            if r.returncode != 0:
                raise ValueError(f"Preflight failed:\n  - git worktree add {wt}: "
                                 f"{(r.stderr or r.stdout).strip()}")
        self._code_dir, self._commits = str(wt), True

    def _working_copy_note(self) -> str:
        """The agent reads repo_path in campaign.yaml; name the campaign copy so it works there."""
        repo = self._config.target_system.get("repo_path")
        if not self._commits or not self._code_dir or not repo:
            return ""
        return (f"\n\nYour working copy is {self._code_dir} (git branch nous/{self._config.run_id}), "
                f"a copy of {repo}. Build, run, edit and commit only in the working copy; never "
                f"change {repo}.")

    @staticmethod
    def _exclude_experiments_dir(repo: str) -> None:
        """Keep the user's checkout clean: list .nous-experiments/ in the per-clone
        info/exclude (never the committed .gitignore). repo may itself be a worktree."""
        r = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=repo,
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise ValueError(f"Preflight failed:\n  - git rev-parse --git-common-dir: "
                             f"{(r.stderr or r.stdout).strip()}")
        exclude = (Path(repo) / r.stdout.strip()).resolve() / "info" / "exclude"
        line = f"{EXPERIMENTS_DIR}/"
        text = exclude.read_text() if exclude.is_file() else ""
        if line not in text.splitlines():
            exclude.parent.mkdir(parents=True, exist_ok=True)
            exclude.write_text(text + ("" if not text or text.endswith("\n") else "\n") + line + "\n")

    def _breaker_record(self, exc_type: str, phase: str, message: str) -> str | None:
        fp = self._breaker.record(exc_type, phase, message)
        self._persist_breaker()
        return fp

    def _persist_breaker(self) -> None:
        update_state(self._work_dir, breaker_recent=self._breaker.recent)

    def _phase_failed(self, exc: Exception, phase: str) -> bool:
        """Spec 3.5: count a phase failure; True when the breaker trips (halt.json written)."""
        fp = self._breaker_record(type(exc).__name__, phase, str(exc))
        if fp:
            write_halt(self._work_dir, fp, phase, str(exc))
        return fp is not None

    def _init_meter(self, session_costs: dict | None = None) -> None:
        defaults_path = Path(__file__).resolve().parent.parent / "defaults.yaml"
        self._meter = CostMeter(load_prices(defaults_path), session_costs)

    def _build_hooks_and_session_opts(self) -> tuple[HookState, dict, dict]:
        hook_state = HookState(
            work_dir=self._work_dir,
            secrets={k: os.environ.get(k, "") for k in self._config.secrets},
            experiment_commands=self._config.experiment_commands or DEFAULT_EXPERIMENT_COMMANDS,
            limits=self._limits(),
            cwd=self._code_dir,
        )
        hooks = build_hooks(hook_state)
        session_opts = {
            "work_dir": str(self._work_dir),
            "method_text": build_system_prompt(self._config.task_type),
            "model": self._config.model or DEFAULT_MODEL,
            "effort": self._config.effort,
            "hooks": hooks,
            "cwd": self._code_dir,
        }
        return hook_state, hooks, session_opts

    def _limits(self) -> dict:
        limits = validator_limits(self._config, self._work_dir)
        if self._code_dir:
            limits["repo_dir"] = Path(self._code_dir)
        return limits

    async def _start_session(self, session_opts: dict) -> Session:
        session = Session(client_factory=self._client_factory, options=session_opts)
        await session.connect()
        return session

    async def run(self) -> dict:
        self._init_meter()
        self._prepare_code_dir()
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
        state = load_campaign_state(self._work_dir)
        if state is None:
            return await self.run()
        self._init_meter(state.get("session_costs"))  # a resumed session's CLI total is cumulative
        self._prepare_code_dir()
        hook_state, hooks, session_opts = self._build_hooks_and_session_opts()
        self._breaker = FailureBreaker(recent=state.get("breaker_recent"))
        # Keep the campaign-wide cut-off count across resume
        self._effort = EffortManager(self._config.effort, state.get("cut_offs", 0))

        saved_phase, saved_iteration = resume_phase(state)
        session_id = state.get("session_id")
        use_fallback = session_id is None or self._config.session_scope == "iteration"
        if not use_fallback:
            session_opts["resume"] = session_id
        self._reload_state(saved_iteration)

        async def attempt(fallback: bool) -> dict:
            session = await self._start_session(session_opts)
            try:
                if fallback:
                    digest = _read_json(self._work_dir / "state" / "digest.json")
                    await self._turn(session, build_fallback_message(
                        phase=saved_phase, iteration=saved_iteration, digest=digest, note=note,
                    ))
                return await self._run_phases_from(
                    session, hook_state, saved_phase, saved_iteration, note=note,
                )
            finally:
                await session.disconnect()

        if not use_fallback:
            self._turns_ok = 0
            try:
                return await attempt(False)
            except Exception as exc:  # spec 3.7: resume failed -> fresh session from digest
                if self._turns_ok:
                    raise
                logger.warning("resume of session %s failed (%s); starting fresh", session_id, exc)
                session_opts.pop("resume")
        return await attempt(True)

    def _reload_state(self, up_to_iteration: int) -> None:
        ledger = _read_json(self._work_dir / "ledger.json")
        if isinstance(ledger, list):
            self._ledger = ledger
        principles = _read_json(self._work_dir / "principles.json")
        if isinstance(principles, list):
            self._principles = principles
        if up_to_iteration > 1:  # iteration 1 has no previous findings
            prev = _read_json(iter_dir(self._work_dir, up_to_iteration - 1) / "findings.json")
            if prev:
                self._prev_findings = prev

    async def _turn(self, session: Session, prompt: str) -> Any:
        """One turn; on an output cut-off, resume one effort level lower (spec 3.10, B12)."""
        if session.effort != self._effort.level:  # phase reset after a cut
            await session.reconnect(self._effort.level)
        try:
            result = await session.turn(prompt, on_message=self._meter.record)
        except ContextOverflowError as exc:  # spec 3.10: once, a fresh session from the digest
            state = load_campaign_state(self._work_dir) or {}
            logger.warning("context full (%s); continuing in a fresh session", exc)
            await session.restart_fresh()
            await session.turn(build_fallback_message(
                phase=state.get("phase", "BASELINE"), iteration=state.get("iteration", 0),
                digest=_read_json(self._work_dir / "state" / "digest.json"), note=None,
            ), on_message=self._meter.record)
            result = await session.turn(prompt, on_message=self._meter.record)
        for _ in EFFORT_LADDER:  # bounded: a reply cut even at "low" is accepted as is
            if not session.cut:
                break
            self._effort.on_cut()
            self._effort.persist_cut_offs(self._work_dir / "state.json")
            await session.reconnect(self._effort.level)
            result = await session.turn(CUT_RESUME_MSG, on_message=self._meter.record)
        self._effort.on_success()
        self._turns_ok += 1
        return result

    async def _repair(self, session: Session, idir: Path, artifact_types: list[str]) -> str:
        for attempt in range(3):
            errors = validate_phase_artifacts(self._work_dir, idir, artifact_types, **self._limits())
            if not errors:
                return "ok"
            if attempt >= 2:
                break
            error_text = "\n".join(f"  - {e}" for e in errors)
            logger.warning("Repair attempt %d: %s", attempt + 1, error_text)
            await self._turn(session, f"Repair: fix these validation errors:\n{error_text}{evidence_hint(errors)}")
        logger.warning("Repair exhausted, marking partial")
        return "partial"

    async def _run_phases_from(
        self, session: Session, hook_state: HookState,
        start_phase: str, start_iteration: int, *, note: str | None = None,
    ) -> dict:
        breaker = self._breaker
        skip_baseline = (start_phase != "BASELINE" or start_iteration > 0) \
            and (self._work_dir / "baseline.json").is_file()  # resume re-runs a missing BASELINE
        skip_design_for = start_iteration if start_phase in ("EXECUTE", "REPORT") else 0

        if not skip_baseline:
            self._set_phase(hook_state, "BASELINE", 0)
            task_hint = "" if self._config.task_type else (
                " Determine the task_type (debug/verify/optimize/policy/"
                "explain/other) and include task_type_reason."
            )
            try:
                await self._turn(
                    session,
                    "BASELINE phase. Do not design hypotheses yet. "
                    f"Get one real observation and write {self._work_dir / 'baseline.json'}.{task_hint}"
                    f"{self._working_copy_note()}",
                )
            except Exception as exc:
                if not self._phase_failed(exc, "BASELINE"):
                    raise
            baseline_status = await self._repair(session, self._work_dir, ["baseline"])
            self._commit_phase(0, "BASELINE")
            if baseline_status != "ok":  # spec 3.5: no baseline, so no DESIGN; still answer
                logger.warning("no valid baseline.json after repair; going to REPORT")
                update_state(self._work_dir, baseline_status=baseline_status,
                             stop_reason="no_baseline")
                await self._report(session, hook_state, 0, 0)
                return {"stop_reason": "no_baseline", "iterations": 0}

        first_iter = max(start_iteration, 1)
        if start_phase == "REPORT":
            last_iter = len(self._ledger) or start_iteration
            await self._report(session, hook_state, start_iteration, last_iter, note=note)
            return {"stop_reason": "resumed_report", "iterations": last_iter}

        stop_reason: str | None = None
        for iteration in range(first_iter, self._config.max_iterations + 1):
            idir = iter_dir(self._work_dir, iteration)
            idir.mkdir(parents=True, exist_ok=True)

            design_status = "ok"
            if iteration != skip_design_for:
                self._set_phase(hook_state, "DESIGN", iteration)
                baseline = _read_json(self._work_dir / "baseline.json")
                if baseline is None:
                    raise ValueError("baseline.json missing; cannot DESIGN")
                principles_text = ""
                if self._principles:
                    principles_text = "\n\nActive principles:\n" + json.dumps(self._principles, indent=2)
                if iteration > 1:  # tell the agent what the stop rule still waits for (spec 3.6)
                    needed, hyps = campaign_record(self._work_dir, iteration - 1)
                    unmet = unmet_requirements({"hypotheses": hyps}, needed)
                    if unmet:
                        principles_text += "\n\nclaims_needed not yet met:\n" + "\n".join(f"- {u}" for u in unmet)
                try:
                    await self._turn(
                        session,
                        f"Iteration {iteration}, DESIGN phase. "
                        f"Read {self._work_dir / 'state' / 'digest.json'} and "
                        f"{self._work_dir / 'baseline.json'}. "
                        f"Frame predictions relative to baseline. "
                        f"Write {idir / 'problem.json'}, {idir / 'bundle.json'}, "
                        f"{idir / 'plan.json'}.{principles_text}",
                    )
                except Exception as exc:
                    if self._phase_failed(exc, "DESIGN"):
                        stop_reason = "halt"
                        break
                    raise
                design_status = await self._repair(session, idir, ["problem", "bundle", "plan"])
                self._commit_phase(iteration, "DESIGN")
                locked_hash = self._lock_bundle(idir)
            else:
                # Resume at EXECUTE: keep the original lock so a pre-crash edit still counts
                locked = _read_json(idir / ".bundle.locked.json")
                if locked is not None:
                    locked_hash = bundle_hash(locked)
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
                f"Use wait_for only for runs started in the background. "
                f"Write {idir / 'findings.json'} and {idir / 'principle_updates.json'}."
            )
            if execute_note:
                exec_prompt += f"\n\nHuman note: {execute_note}"
            try:
                await self._turn(session, exec_prompt)
            except Exception as exc:
                if self._phase_failed(exc, "EXECUTE"):
                    stop_reason = "halt"
                    break
                raise
            if not validate_phase_artifacts(
                self._work_dir, idir, ["findings", "principle_updates"], **self._limits(),
            ):
                pending_waits = []  # results are in: nothing left to wait for
            # Keep waits armed while polling so "still pending" turns are not Stop-gated
            await poll_and_resume(
                pending_waits, iteration, breaker, functools.partial(self._turn, session),
                cwd=hook_state.cwd,
            )
            hook_state.pending_wait_for = []
            self._persist_breaker()  # poll_and_resume may record wait_for timeouts
            self._commit_phase(iteration, "EXECUTE")

            status = await self._repair(session, idir, ["findings", "principle_updates"])
            if design_status == "partial":
                status = "partial"
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

            claims_needed, all_hyps = campaign_record(self._work_dir, iteration)
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
            self._save_ledger()
            self._prev_findings = findings

            if status == "ok":
                breaker.reset()
                self._persist_breaker()
            else:
                fp = self._breaker_record("ValidationError", "EXECUTE", "repair exhausted")
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
                claims_needed=claims_needed, status=status,
                claim_findings={"hypotheses": all_hyps},
            )
            if stop_reason is not None:
                entry["stop_reason"] = stop_reason
                self._save_ledger()
                break

        if stop_reason is None:
            stop_reason = "max_iterations"
            if self._ledger:
                self._ledger[-1]["stop_reason"] = stop_reason
                self._save_ledger()

        await self._report(session, hook_state, len(self._ledger), len(self._ledger))
        return {"stop_reason": stop_reason, "iterations": len(self._ledger)}

    async def _report(
        self, session: Session, hook_state: HookState,
        phase_iteration: int, commit_iteration: int, note: str | None = None,
    ) -> None:
        self._set_phase(hook_state, "REPORT", phase_iteration)
        msg = (
            f"REPORT phase. Write {self._work_dir / 'answer.json'} and {self._work_dir / 'report.md'}. "
            "`answer` answers every question and sub-question of the research question. "
            "`claims` are the quantitative conclusions, each value copied exactly from the cited file. "
            "`repro` is one command run from the repository root (no cd)."
        )
        await self._turn(session, msg + (f"\n\nHuman note: {note}" if note else ""))
        if await self._repair(session, self._work_dir, ["answer"]) == "ok":
            await self._repair_repro(session)
        self._export_evidence()
        self._commit_phase(commit_iteration, "REPORT")
        self._record_final_check()

    async def _repair_repro(self, session: Session) -> None:
        """The repro must have run as written (runs.jsonl); if not, one repair message, no loop.
        Without a hook record there is nothing to check against; the final check reports it."""
        answer = _read_json(self._work_dir / "answer.json")
        if (self._work_dir / "runs.jsonl").is_file() and isinstance(answer, dict) \
                and not _check_repro(self._work_dir, answer.get("repro")):
            await self._turn(session, REPRO_REPAIR_MSG)
            await self._repair(session, self._work_dir, ["answer"])

    def _export_evidence(self) -> None:
        """Make answer.json self-contained in the deliverable: copy each claim's evidence file
        into <repo>/nous_evidence/<path relative to its root> (and the same path under the work
        dir, so the final check still resolves it). A file already in the repo is cited in place.
        Per the output contract, `evidence` becomes that path string; the structured
        {path, key, value} item moves to `evidence_detail`."""
        repo = self._code_dir
        answer = _read_json(self._work_dir / "answer.json")
        if not repo or not isinstance(answer, dict):
            return
        repo_r, work_r = Path(repo).resolve(), self._work_dir.resolve()
        changed = False
        for claim in answer.get("claims") or []:
            if isinstance(claim, dict) and isinstance(claim.get("value"), str):
                num = _as_number(claim["value"])  # output contract: claim values are numbers
                if num is not None:
                    claim["value"], changed = num, True
            ev = claim.get("evidence") if isinstance(claim, dict) else None
            path = ev.get("path") if isinstance(ev, dict) else ev
            if not isinstance(path, str):
                continue
            src, _ = resolve_evidence_path(path, [work_r, repo_r, work_r / EVIDENCE_DIR])
            if src is None or not src.is_file():
                continue  # left as is; the final check reports it
            if src.is_relative_to(work_r):
                rel = src.relative_to(work_r).as_posix()
                new = rel if rel.startswith(EVIDENCE_DIR + "/") else f"{EVIDENCE_DIR}/{rel}"
                for root in (repo_r, work_r):
                    if (root / new).resolve() != src:
                        (root / new).parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, root / new)
            else:  # already in the repo: cite it in place
                new = src.relative_to(repo_r).as_posix()
            # Output contract: evidence is the path string; keep {path, key, value} as evidence_detail
            if isinstance(ev, dict):
                claim["evidence_detail"] = {**ev, "path": new}
            claim["evidence"] = new
            changed = True
        if changed:
            _write_json(self._work_dir / "answer.json", answer)

    def _save_ledger(self) -> None:
        _write_json(self._work_dir / "ledger.json", self._ledger)
        update_state(self._work_dir, session_costs=self._meter.session_costs)

    def _record_final_check(self) -> None:
        """Spec 3.8: check answer.json against the record and log the result in the ledger."""
        report = check_answer(self._work_dir, self._limits())
        if self._ledger:
            self._ledger[-1].update(
                report_cost_usd=self._meter.iter_delta()["cost_usd"],
                repro_recorded=report["repro_recorded"],
                claims_matched_fraction=report["claims_matched_fraction"],
            )
            self._save_ledger()
        _write_json(self._work_dir / "final_check.json", report)

    def _set_phase(self, hook_state: HookState, phase: str, iteration: int) -> None:
        hook_state.phase = phase
        hook_state.iteration = iteration
        update_state(self._work_dir, phase=phase, iteration=iteration)
        self._effort.reset()

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
        """Commit the campaign worktree (spec 3.1 / D5); never the user's checkout or work dir."""
        if not self._commits or not self._code_dir:
            return
        target_path = Path(self._code_dir).resolve()
        work = self._work_dir.resolve()
        spec = ["."]
        if work.is_relative_to(target_path) and work != target_path:
            spec.append(f":(exclude){work.relative_to(target_path).as_posix()}")
        msg = f"nous: {phase}" if iteration == 0 else f"nous: iter-{iteration} {phase}"
        steps = (["add", "-A", "--", *spec], ["commit", "-q", "-m", msg])
        try:
            for args in steps:
                r = subprocess.run(
                    ["git", *args], cwd=str(target_path), capture_output=True, text=True, timeout=30,
                )
                if r.returncode != 0:
                    if args[0] == "commit" and "nothing" in r.stdout + r.stderr:
                        return
                    logger.warning("git %s failed after %s: %s", args[0], phase, (r.stderr or r.stdout).strip())
                    return
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("failed to commit target worktree after %s: %s", phase, exc)

    def _objective_direction(self) -> str:
        obj = self._config.objective
        if obj and isinstance(obj, dict):
            return obj.get("direction", "increase")
        return "increase"
