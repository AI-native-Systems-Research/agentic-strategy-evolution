#!/usr/bin/env python3
"""Sandboxed driver for the Claude baseline: plain Claude Code via the same claude_agent_sdk Nous uses.

Runs inside sandbox-exec (launched by claude_sdk_research_runner.py). Session 1 sends the task prompt;
when a session ends below the target score, it resumes the same conversation with a push to keep
improving, unless the next resume cannot fit under the budget. The parent enforces the hard $50 cap.
"""
import asyncio, glob, json, re, sys, time
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, query

import cost_meter as C

cfg = json.loads(Path(sys.argv[1]).read_text())
run = Path(cfg["run_dir"])
log = open(run / "stream.jsonl", "a")


def best_measured():
    scores = [float(m.group(1)) for f in glob.glob(str(run / "measured" / "*"))
              if (m := re.search(r"_score([0-9.]+)\.(py|cpp)$", f))]
    return max(scores, default=-1.0)


async def session(prompt, resume):
    opts = ClaudeAgentOptions(
        model=cfg["model"], cwd=str(run), max_turns=cfg["max_turns"],
        system_prompt={"type": "preset", "preset": "claude_code"},
        permission_mode="bypassPermissions",
        disallowed_tools=["WebSearch", "WebFetch"],
        continue_conversation=resume,
        **({"env": {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(cfg["max_output_tokens"])}}
           if cfg.get("max_output_tokens") else {}))
    turns = 0
    async for msg in query(prompt=prompt, options=opts):
        turns += 1
        log.write(json.dumps({"ts": time.time(), "type": type(msg).__name__, "content": str(msg)[:4000]}) + "\n"); log.flush()
    return turns


async def main():
    n, crashes = 0, 0
    while True:
        n += 1
        before = C.transcript_cost(run)
        if n == 1:
            prompt = cfg["prompt"]
        else:
            b = best_measured()
            prompt = cfg["continue"].format(score=f"{b:g}" if b >= 0 else "0")
        print(f"[driver] session {n} start cost=${before:.2f}", flush=True)
        try:
            turns = await session(prompt, resume=n > 1)
        except Exception as e:  # only with continue_on_crash; the default baseline lets a CLI crash end the run
            if not cfg.get("continue_on_crash"):
                raise
            crashes += 1
            print(f"[driver] session {n} crashed ({type(e).__name__}: {str(e)[:160]}); crash {crashes}", flush=True)
            if crashes >= 8:
                print("[driver] 8 CLI crashes, stopping", flush=True); return
            continue
        after = C.transcript_cost(run)
        print(f"[driver] session {n} ended turns={turns} cost=${after:.2f} best={best_measured()}", flush=True)
        if best_measured() >= cfg["max_score"]:
            print("[driver] max score reached", flush=True); return
        # a resume re-sends the whole context in its first call; stop if that cannot fit under the cap
        resume_est = (after - before) / max(turns, 1) * 4 + 2.0
        if after + resume_est >= cfg["budget"]:
            print("[driver] no room to resume under budget", flush=True); return


asyncio.run(main())
