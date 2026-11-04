"""Nous v3 campaign: Claude investigates freely in one session; Nous records, checks and challenges.

No phases. One task message; the agent works as it would alone, keeping notebook.jsonl
(hypothesis before each test, result with evidence) and finishing with answer.json. Nous:
- records every Bash command (v2 hooks, runs.jsonl) and commits the campaign worktree;
- at Stop, blocks only while answer.json or the notebook fails its checks;
- asks the agent to rerun `repro` if it never ran as written;
- runs one independent challenger (a fresh, read-only session) that names the strongest untested
  reason the conclusion could be wrong; the agent runs that test and updates the answer;
- exports evidence and writes final_check.json.
Cost is measured and reported only.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

from orchestrator.v2.final_check import _check_repro, check_answer
from orchestrator.v2.loop import Campaign as V2Campaign
from orchestrator.v2.prompts import load_checklist
from orchestrator.v2.resume import load_campaign_state, update_state
from orchestrator.v2.validators import read_json, validate_phase_artifacts

from .notebook import check_notebook, summary

logger = logging.getLogger(__name__)

_METHOD = Path(__file__).resolve().parents[2] / "prompts" / "v3" / "method.md"
MAX_STOP_BLOCKS = 6  # consecutive Stop blocks before the stop is allowed (the repair turns take over)
MAX_REPAIRS = 2
CHALLENGER_MODEL = "claude-sonnet-5-5"  # reads and judges only; a smaller model is enough
CHALLENGER_TOOLS_DENIED = ["Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch"]

CONTINUE_MSG = ("Continue the investigation. When every part of the question is answered, write "
                "{answer} (see the method) and stop.")
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


class Campaign(V2Campaign):
    """One free session, a notebook, a final gate and one challenger."""

    def __init__(self, config, work_dir: Path, client_factory: Callable,
                 challenger_factory: Callable | None = None) -> None:
        super().__init__(config, work_dir, client_factory)
        self._challenger_factory = challenger_factory or client_factory

    # ── checks ──────────────────────────────────────────────────────────

    def _answer_errors(self) -> list[str]:
        if not (self._work_dir / "answer.json").is_file():
            return ["answer.json: not written yet"]
        repo = Path(self._code_dir) if self._code_dir else None
        return (validate_phase_artifacts(self._work_dir, self._work_dir, ["answer"], **self._limits())
                + check_notebook(self._work_dir, repo))

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

    def _build_hooks_and_session_opts(self):
        hook_state, hooks, opts = super()._build_hooks_and_session_opts()
        hook_state.phase = "INVESTIGATE"
        hooks["Stop"] = [HookMatcher(matcher="", hooks=[self._stop_hook()], timeout=120.0)]
        opts["method_text"] = method_text(self._config.task_type)
        return hook_state, hooks, opts

    # ── the campaign ────────────────────────────────────────────────────

    async def run(self) -> dict:
        self._init_meter()
        self._prepare_code_dir()
        _, _, opts = self._build_hooks_and_session_opts()
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
        self._init_meter(state.get("session_costs"))
        self._prepare_code_dir()
        _, _, opts = self._build_hooks_and_session_opts()
        if state.get("session_id"):
            opts["resume"] = state["session_id"]
        session = await self._start_session(opts)
        try:
            msg = CONTINUE_MSG.format(answer=self._work_dir / "answer.json")
            if not state.get("session_id"):  # fresh session: give the task again
                msg = self._task_message()
            await self._turn(session, msg + (f"\n\nHuman note: {note}" if note else ""))
            return await self._finish(session)
        finally:
            await session.disconnect()

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
            update_state(self._work_dir, phase="CHALLENGE")
            await self._turn(session, (
                "An independent reviewer read your answer and evidence and asks for one more check:\n"
                f"{challenge['test']}\n(Reason: {challenge.get('why', '')})\n"
                "Run it, record the hypothesis and result in your notebook, and update answer.json if the "
                "result changes or qualifies your conclusion."))
            status = await self._repair_answer(session)
        self._export_evidence()
        self._commit_phase(1, "ANSWER")
        report = check_answer(self._work_dir, self._limits())
        report.update(notebook=summary(self._work_dir),
                      notebook_errors=check_notebook(self._work_dir, Path(self._code_dir) if self._code_dir else None),
                      challenger=challenge, status=status)
        (self._work_dir / "final_check.json").write_text(json.dumps(report, indent=2))
        cost = self._meter.total()
        self._ledger = [{"iteration": 1, "status": status, "stop_reason": "answered" if status == "ok" else "partial",
                         "cost_meter_usd": cost["cost_usd"],
                         "tokens": {"input": cost["input_tokens"], "output": cost["output_tokens"]},
                         "repro_recorded": report["repro_recorded"], "nous_version": 3}]
        self._save_ledger()
        update_state(self._work_dir, phase="DONE")
        return {"stop_reason": self._ledger[0]["stop_reason"], "iterations": 1}

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
        try:
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
        except Exception as exc:  # the challenger is advice; it never stops a campaign
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
