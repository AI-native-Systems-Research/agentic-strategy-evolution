"""Baseline arms: l2 and nous_prompt. N sequential Claude Code sessions with paste-forward and a `done` flag.

Ported from the bench-framework branch (PR #291): l2 = claude_methodology_loop, nous_prompt =
claude_arm_structured_loop. Changes for this study, applied identically to both arms:
- same task prompt + output contract as Nous;
- each session ends by writing final/done.json {"done": bool, "why": str}; the loop stops on done=true;
- sessions use the same Claude Code binary as Nous (the claude-agent-sdk bundled CLI) via `claude -p`,
  stream-json transcripts kept, no web tools;
- a crashed session is recorded and ends the run (no retries).

Usage: loop_arm.py <arm> <task_prompt_file> <workspace> <max_sessions> <log_dir>
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOUS = HERE.parents[2]
CLAUDE = str(Path.home() / "mlsys_runs/nous/.venv/lib/python3.11/site-packages/claude_agent_sdk/_bundled/claude")
MODEL = "claude-opus-4-6"

L2_METHODOLOGY = """Approach this systematically:
- Form hypotheses before running experiments. Predict what
  you expect to observe and why.
- Run controlled experiments.
- When your prediction is wrong, think carefully about why.
- Track what you learn. Build on prior findings rather than
  starting from scratch each time."""

DONE_RULE = """When you finish this session, write `final/done.json` as {"done": true|false, "why": "one sentence"}.
Set done to true only if you are confident the research question is fully answered and final/answer.json is complete;
otherwise false, and another session will continue from your report."""


def _sub(t, subs):
    return re.sub(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", lambda m: subs.get(m.group(1).strip(), m.group(0)), t)


def nous_methodology(task_text, ws, n, prior):
    """Nous's full methodology prompts, neutral placeholder fills (as in bench-framework's arm_structured_loop)."""
    md = Path.home() / "mlsys_runs" / "nous" / "prompts" / "methodology"
    iter_dir = f"runs/iter-{n}"
    for sub in ("inputs", "results", "patches"):
        (Path(ws) / iter_dir / sub).mkdir(parents=True, exist_ok=True)
    prev = "(none — this is the first iteration)" if n == 1 else "\n\n".join(
        f"### Iteration {i + 1} output\n\n{o}".strip() for i, o in enumerate(prior))
    subs = {"research_question": task_text, "iteration": str(n), "iteration_mode": "(none)", "mode_guidance": "(none)",
            "iter_dir": iter_dir, "nous_dir": str(ws), "target_system": "BLIS", "system_description": "(none)",
            "observable_metrics": "(none)", "controllable_knobs": "(none)", "active_principles": "(none)",
            "previous_handoff": prev, "previous_findings": prev, "execution_environment": "(none)", "max_turns": "120",
            "ledger_summary": "(none)", "final_principles": "(none)", "results_summary": "(none)",
            "retry_log_summary": "(none)", "bundle_amendments_summary": "(none)", "brief_amendments_summary": "(none)",
            "problem_md": "(none)", "worktree_constraint": "(none)", "repo_context": "(none)", "condition_reset": "(none)",
            "design_handoff": "(none)", "human_feedback": "(none)", "bundle_yaml": "(none)"}
    parts = []
    for name, title in (("design.md", "DESIGN PHASE"), ("execute_analyze.md", "EXECUTE & ANALYZE PHASE"),
                        ("report.md", "REPORT PHASE")):
        parts.append(f"## METHODOLOGY — {title} INSTRUCTIONS\n\n" + _sub((md / name).read_text(), subs).rstrip())
    return "\n\n---\n\n".join(parts)


def build_prompt(arm, task_text, ws, n, total, prior):
    prior_block = "" if n == 1 else (
        "Here is what you found in prior iterations:\n\n--- Prior findings ---\n" +
        "\n\n".join(f"### Iteration {i + 1}\n\n{o}".strip() for i, o in enumerate(prior)) + "\n---\n\n")
    if arm == "l2":
        head = f"{task_text.rstrip()}\n\n{L2_METHODOLOGY}\n\n"
    else:
        head = f"# Research question\n\n{task_text.rstrip()}\n\n---\n\n{nous_methodology(task_text, ws, n, prior)}\n\n---\n\n"
    tail = (f"This is iteration {n} of at most {total}. " +
            ("Continue your investigation. Build on what you found before. " if n > 1 else "") +
            "Report your findings and what you would investigate next.\n\n" + DONE_RULE)
    return head + prior_block + tail


def run_session(prompt, ws, log_path, env):
    cmd = [CLAUDE, "-p", "--output-format", "stream-json", "--verbose", "--model", MODEL,
           "--dangerously-skip-permissions", "--disallowedTools", "WebSearch,WebFetch"]
    t0 = time.time()
    with open(log_path, "w") as lf:
        p = subprocess.run(cmd, input=prompt, cwd=ws, stdout=lf, stderr=subprocess.STDOUT, text=True, env=env,
                           timeout=6 * 3600)
    result, cost = None, None
    for line in open(log_path, errors="ignore"):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "result":
            result, cost = ev, ev.get("total_cost_usd")
    ok = p.returncode == 0 and result is not None and not result.get("is_error") and result.get("subtype") == "success"
    return dict(ok=ok, returncode=p.returncode, final=(result or {}).get("result", ""), cli_cost=cost,
                subtype=(result or {}).get("subtype"), wall=round(time.time() - t0, 1),
                num_turns=(result or {}).get("num_turns"))


def main(arm, task_file, ws, max_sessions, log_dir):
    task_text = Path(task_file).read_text()
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(os.path.join(ws, "final"), exist_ok=True)
    env = dict(os.environ)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = env.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS", "32000")
    prior, sessions, status, declared_done = [], [], "max_iterations", False
    for n in range(1, max_sessions + 1):
        done_p = Path(ws) / "final" / "done.json"
        if done_p.exists():
            done_p.unlink()
        s = run_session(build_prompt(arm, task_text, ws, n, max_sessions, prior), ws,
                        os.path.join(log_dir, f"session-{n}.jsonl"), env)
        s["n"] = n
        sessions.append(s)
        snap = Path(log_dir).parent / "snapshots" / f"iter-{n}" / "final"
        snap.mkdir(parents=True, exist_ok=True)
        for f in ("answer.json", "done.json"):
            if (Path(ws) / "final" / f).exists():
                (snap / f).write_text((Path(ws) / "final" / f).read_text())
        json.dump(sessions, open(os.path.join(log_dir, "sessions.json"), "w"), indent=1)
        if not s["ok"]:
            status = "crashed"
            break
        prior.append(s["final"])
        try:
            d = json.load(open(done_p))
            if d.get("done") is True:
                status, declared_done = "done", True
                break
        except (OSError, json.JSONDecodeError):
            pass
    json.dump(dict(status=status, declared_done=declared_done, iterations_used=len(sessions)),
              open(os.path.join(log_dir, "loop_status.json"), "w"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5])
