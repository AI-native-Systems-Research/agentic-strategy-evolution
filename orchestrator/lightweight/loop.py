"""Nous Lightweight campaign: Claude investigates freely in one session; Nous records, checks and challenges.

No phases. One task message; the agent works as it would alone, keeping notebook.jsonl
(hypothesis before each test, result with evidence) and finishing with answer.json. Nous:
- records every Bash command (hooks, runs.jsonl) and commits the campaign worktree;
- at Stop, blocks only while answer.json or the notebook fails its checks;
- asks the agent to run `repro` if runs.jsonl has no successful run of it (Nous never runs it);
- runs one independent challenger (a fresh, read-only session) that names the strongest untested
  reason the conclusion could be wrong; the agent runs that test and updates the answer;
- exports evidence and writes final_check.json.
Cost is measured and reported only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions

from .config import CampaignConfig, validator_limits
from .cost import CostMeter, load_prices
from .effort import CUT_RESUME_MSG, EFFORT_LADDER, EffortManager
from .final_check import _check_repro, check_answer
from .hooks import DEFAULT_EXPERIMENT_COMMANDS, HookState, build_hooks
from .notebook import check_notebook, summary
from .prompts import load_checklist
from .resume import build_fallback_message, load_campaign_state, update_state
from .session import DEFAULT_MODEL, ContextOverflowError, Session
from .validators import read_json, resolve_evidence_path, validate_answer_file

logger = logging.getLogger(__name__)

_METHOD = Path(__file__).resolve().parents[2] / "prompts" / "lightweight" / "method.md"
EVIDENCE_DIR = "nous_evidence"  # answer evidence copied into the target repo
EXPERIMENTS_DIR = ".nous-experiments"  # the campaign's code worktree: <repo>/.nous-experiments/<run_id>/
MAX_STOP_BLOCKS = 6  # consecutive Stop blocks before the stop is allowed (the repair turns take over)
MAX_REPAIRS = 2
CHALLENGER_MODEL = "claude-sonnet-5-5"  # reads and judges only; a smaller model is enough
CHALLENGER_TIMEOUT_S = 15 * 60  # a hung reviewer is skipped, like any other reviewer failure
CHALLENGER_TOOLS_DENIED = ["Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch"]

CONTINUE_MSG = ("Continue the investigation. When every part of the question is answered, write "
                "{answer} (see the method) and stop.")
RESUME_FRESH_MSG = ("\n\nThis is a resumed campaign: continue from the existing notebook ({notebook}) and the "
                    "work already in the working copy rather than starting over.")
REPRO_MSG = ("Run the repro command from answer.json exactly as written, from the repository root, and fix "
             "answer.json until it succeeds.")


def method_text(task_type: str | None) -> str:
    text = _METHOD.read_text()
    checklist = load_checklist(task_type) if task_type else None
    return text + ("\n\n" + checklist if checklist else "")


def challenger_prompt(question: str, work_dir: Path) -> str:
    return (
        "You are an independent reviewer of a finished investigation. You did not do the work.\n\n"
        f"Research question:\n{question}\n\n"
        f"Read {work_dir / 'answer.json'} and {work_dir / 'notebook.jsonl'}, and any file they cite.\n"
        "Find the single strongest reason the main conclusion could be wrong or overstated that the "
        "recorded measurements do NOT already rule out (for example: a regime or setting never tested, "
        "a confound, a comparison against the wrong baseline, an effect explained away without a test, "
        "a sub-question left unanswered).\n"
        "Reply with only one JSON object: {\"gap\": true, \"test\": \"<one concrete measurement or check "
        "that would settle it>\", \"why\": \"<one sentence>\"} or {\"gap\": false, \"why\": \"<one sentence>\"}."
    )


def parse_verdict(text: str) -> dict | None:
    """The last JSON object in the reviewer's reply, if it has a boolean `gap`."""
    for m in reversed(list(re.finditer(r"\{[^{}]*\}", text or "", re.DOTALL))):
        try:
            d = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict) and isinstance(d.get("gap"), bool):
            return d
    return None


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


class Campaign:
    """One free session, a notebook, a final gate and one challenger."""

    def __init__(self, config: CampaignConfig, work_dir: Path, client_factory: Callable,
                 challenger_factory: Callable | None = None) -> None:
        self._config = config
        self._work_dir = work_dir
        self._client_factory = client_factory
        self._challenger_factory = challenger_factory or client_factory
        self._ledger: list[dict] = []
        self._turns_ok = 0
        self._effort = EffortManager(config.effort)
        self._prev_cost = 0.0  # spend recorded before a resume
        # The agent works and Nous commits in one campaign worktree, never the user's
        # checkout. _prepare_code_dir() sets it; a non-git repo_path is used as is.
        self._code_dir: str | None = config.target_system.get("repo_path")
        self._commits = False

    # ── working copy ────────────────────────────────────────────────────

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

    def _commit(self) -> None:
        """Commit the campaign worktree; never the user's checkout or the work dir."""
        if not self._commits or not self._code_dir:
            return
        target_path = Path(self._code_dir).resolve()
        work = self._work_dir.resolve()
        spec = ["."]
        if work.is_relative_to(target_path) and work != target_path:
            spec.append(f":(exclude){work.relative_to(target_path).as_posix()}")
        steps = (["add", "-A", "--", *spec], ["commit", "-q", "-m", "nous: iter-1 ANSWER"])
        try:
            for args in steps:
                r = subprocess.run(
                    ["git", *args], cwd=str(target_path), capture_output=True, text=True, timeout=30,
                )
                if r.returncode != 0:
                    if args[0] == "commit" and "nothing" in r.stdout + r.stderr:
                        return
                    logger.warning("git %s failed after ANSWER: %s", args[0], (r.stderr or r.stdout).strip())
                    return
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("failed to commit target worktree after ANSWER: %s", exc)

    # ── session ─────────────────────────────────────────────────────────

    def _init_meter(self, session_costs: dict | None = None) -> None:
        defaults_path = Path(__file__).resolve().parent.parent / "defaults.yaml"
        self._meter = CostMeter(load_prices(defaults_path), session_costs)

    def _limits(self) -> dict:
        limits = validator_limits(self._config, self._work_dir)
        if self._code_dir:
            limits["repo_dir"] = Path(self._code_dir)
        return limits

    def _session_opts(self) -> dict:
        hook_state = HookState(
            work_dir=self._work_dir,
            phase="INVESTIGATE",
            secrets={k: os.environ.get(k, "") for k in self._config.secrets},
            experiment_commands=self._config.experiment_commands or DEFAULT_EXPERIMENT_COMMANDS,
            cwd=self._code_dir,
        )
        return {
            "work_dir": str(self._work_dir),
            "method_text": method_text(self._config.task_type),
            "model": self._config.model or DEFAULT_MODEL,
            "effort": self._config.effort,
            "hooks": build_hooks(hook_state, self._stop_hook()),
            "cwd": self._code_dir,
        }

    async def _start_session(self, session_opts: dict) -> Session:
        session = Session(client_factory=self._client_factory, options=session_opts)
        await session.connect()
        return session

    async def _turn(self, session: Session, prompt: str) -> Any:
        """One turn; on an output cut-off, resume one effort level lower."""
        if session.effort != self._effort.level:
            await session.reconnect(self._effort.level)
        try:
            result = await session.turn(prompt, on_message=self._meter.record)
        except ContextOverflowError as exc:  # once, a fresh session from the digest
            state = load_campaign_state(self._work_dir) or {}
            logger.warning("context full (%s); continuing in a fresh session", exc)
            await session.restart_fresh()
            await session.turn(build_fallback_message(
                phase=state.get("phase", "BASELINE"), iteration=state.get("iteration", 0),
                digest=read_json(self._work_dir / "state" / "digest.json"), note=None,
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

    # ── checks ──────────────────────────────────────────────────────────

    def _answer_errors(self) -> list[str]:
        if not (self._work_dir / "answer.json").is_file():
            return ["answer.json: not written yet"]
        repo = Path(self._code_dir) if self._code_dir else None
        return validate_answer_file(self._work_dir, **self._limits()) + check_notebook(self._work_dir, repo)

    def _stop_hook(self):
        blocks = {"n": 0}

        async def hook(_input: dict, _id: str | None, _ctx: Any) -> dict:
            # Only an answer that exists but fails its checks blocks; no answer yet means the agent
            # paused, and Nous sends a continue message instead.
            if not (self._work_dir / "answer.json").is_file() or blocks["n"] >= MAX_STOP_BLOCKS:
                blocks["n"] = 0
                return {}
            errors = self._answer_errors()
            if not errors:
                blocks["n"] = 0
                return {}
            blocks["n"] += 1
            return {"decision": "block",
                    "reason": "Fix these before you stop:\n" + "\n".join(f"  - {e}" for e in errors[:10])}

        return hook

    # ── the campaign ────────────────────────────────────────────────────

    async def run(self) -> dict:
        self._init_meter()
        self._prepare_code_dir()
        opts = self._session_opts()
        session = await self._start_session(opts)
        try:
            update_state(self._work_dir, phase="INVESTIGATE", iteration=1)
            await self._turn(session, self._task_message())
            return await self._finish(session)
        finally:
            await session.disconnect()

    async def resume(self, *, note: str | None = None) -> dict:
        state = load_campaign_state(self._work_dir)
        if state is None:
            return await self.run()
        ledger = read_json(self._work_dir / "ledger.json")
        prev = ledger[0] if isinstance(ledger, list) and ledger and isinstance(ledger[0], dict) else None
        if state.get("phase") == "DONE" and prev:  # finished: report, never redo the work
            return {"stop_reason": prev.get("stop_reason", "answered"), "iterations": 1}
        # An earlier process's spend: its ledger row, else the figure saved on entering CHALLENGE
        self._prev_cost = (prev or {}).get("cost_meter_usd", state.get("cost_usd", 0.0))
        self._init_meter(state.get("session_costs"))
        self._prepare_code_dir()
        opts = self._session_opts()
        human = f"\n\nHuman note: {note}" if note else ""

        async def attempt(resumed: bool) -> dict:
            session = await self._start_session(opts)
            try:
                if resumed:
                    msg = CONTINUE_MSG.format(answer=self._work_dir / "answer.json")
                else:  # fresh session: the task again, plus where the earlier work is
                    msg = self._task_message() + RESUME_FRESH_MSG.format(
                        notebook=self._work_dir / "notebook.jsonl")
                await self._turn(session, msg + human)
                return await self._finish(session)
            finally:
                await session.disconnect()

        if state.get("session_id"):
            opts["resume"] = state["session_id"]
            self._turns_ok = 0
            try:
                return await attempt(True)
            except Exception as exc:  # a stale session id: start fresh
                if self._turns_ok:
                    raise
                logger.warning("resume of session %s failed (%s); starting fresh", state["session_id"], exc)
                opts.pop("resume")
        return await attempt(False)

    def _task_message(self) -> str:
        return (f"{self._config.research_question}\n\n"
                f"Keep your notebook at {self._work_dir / 'notebook.jsonl'} and finish by writing "
                f"{self._work_dir / 'answer.json'} (see the method).{self._working_copy_note()}")

    async def _finish(self, session) -> dict:
        nudges = 0
        while not (self._work_dir / "answer.json").is_file() and nudges < self._config.max_iterations:
            nudges += 1
            await self._turn(session, CONTINUE_MSG.format(answer=self._work_dir / "answer.json"))
        status = await self._repair_answer(session)
        if status == "ok":
            answer = read_json(self._work_dir / "answer.json") or {}
            if (self._work_dir / "runs.jsonl").is_file() and not _check_repro(self._work_dir, answer.get("repro")):
                await self._turn(session, REPRO_MSG)
                status = await self._repair_answer(session)
        challenge = await self._challenge() if status == "ok" else None
        if challenge and challenge.get("gap") and challenge.get("test"):
            update_state(self._work_dir, phase="CHALLENGE", session_costs=self._meter.session_costs,
                         cost_usd=self._cost_usd())
            await self._turn(session, (
                "An independent reviewer read your answer and evidence and asks for one more check:\n"
                f"{challenge['test']}\n(Reason: {challenge.get('why', '')})\n"
                "Run it, record the hypothesis and result in your notebook, and update answer.json if the "
                "result changes or qualifies your conclusion."))
            status = await self._repair_answer(session)
        self._export_evidence()
        self._commit()
        report = check_answer(self._work_dir, self._limits())
        report.update(notebook=summary(self._work_dir),
                      notebook_errors=check_notebook(self._work_dir, Path(self._code_dir) if self._code_dir else None),
                      challenger=challenge, status=status)
        (self._work_dir / "final_check.json").write_text(json.dumps(report, indent=2))
        cost = {**self._meter.total(), "cost_usd": self._cost_usd()}
        # "nous_version": 3 is kept so ledger.json reads as before for existing tooling
        self._ledger = [{"iteration": 1, "status": status, "stop_reason": "answered" if status == "ok" else "partial",
                         "cost_meter_usd": cost["cost_usd"],
                         "tokens": {"input": cost["input_tokens"], "output": cost["output_tokens"]},
                         "repro_recorded": report["repro_recorded"], "nous_version": 3}]
        self._save_ledger()
        update_state(self._work_dir, phase="DONE")
        return {"stop_reason": self._ledger[0]["stop_reason"], "iterations": 1}

    def _cost_usd(self) -> float:
        """This process's meter plus any spend before a resume."""
        return self._meter.total()["cost_usd"] + self._prev_cost

    async def _repair_answer(self, session) -> str:
        for attempt in range(MAX_REPAIRS + 1):
            errors = self._answer_errors()
            if not errors:
                return "ok"
            if attempt == MAX_REPAIRS:
                break
            await self._turn(session, "Fix these before you stop:\n" + "\n".join(f"  - {e}" for e in errors[:10]))
        return "partial"

    async def _challenge(self) -> dict | None:
        """One fresh, read-only reviewer session. Any failure skips the challenge (never blocks)."""
        opts = ClaudeAgentOptions(
            model=CHALLENGER_MODEL, cwd=str(self._work_dir),
            system_prompt={"type": "preset", "preset": "claude_code"}, permission_mode="bypassPermissions",
            disallowed_tools=CHALLENGER_TOOLS_DENIED, setting_sources=["project", "local"],
            add_dirs=[self._code_dir] if self._code_dir else [])
        text, client = "", None

        async def exchange() -> None:
            nonlocal text, client
            client = self._challenger_factory(opts)
            await client.connect()
            await client.query(challenger_prompt(self._config.research_question, self._work_dir))
            async for msg in client.receive_response():
                self._meter.record(msg)
                for block in getattr(msg, "content", None) or []:
                    t = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
                    if t:
                        text = t
                if getattr(msg, "result", None):
                    text = msg.result

        try:
            await asyncio.wait_for(exchange(), CHALLENGER_TIMEOUT_S)
        except Exception as exc:  # the challenger is advice; it never stops a campaign
            if isinstance(exc, asyncio.TimeoutError):
                exc = TimeoutError(f"no reply within {CHALLENGER_TIMEOUT_S}s")
            logger.warning("challenger failed (%s); skipped", exc)
            return {"gap": None, "error": str(exc)[:300]}
        finally:
            try:
                if client is not None:
                    await client.disconnect()
            except Exception:
                pass
        verdict = parse_verdict(text)
        return verdict or {"gap": None, "error": "no verdict", "reply": text[:500]}

    # ── deliverable ─────────────────────────────────────────────────────

    def _export_evidence(self) -> None:
        """Make answer.json self-contained in the deliverable: copy each claim's evidence file
        into <repo>/nous_evidence/<path relative to its root> (and the same path under the work
        dir, so the final check still resolves it). A file already in the repo is cited in place.
        Per the output contract, `evidence` becomes that path string; the structured
        {path, key, value} item moves to `evidence_detail`."""
        repo = self._code_dir
        answer = read_json(self._work_dir / "answer.json")
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
