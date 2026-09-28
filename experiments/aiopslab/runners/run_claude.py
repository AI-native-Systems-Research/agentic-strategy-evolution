"""Run one AIOpsLab problem with PLAIN Claude Code (L0, no Nous methodology), persist results.

Same base agent Nous wraps, driven headless (`claude -p`) on the task. Isolates methodology.

Usage:
    cd ~/aiopslab && poetry run python <this> <problem_id> [--model claude-opus-4-6]
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapter"))
from claude_agent import ClaudeCodeAgent  # noqa: E402
from aiopslab.orchestrator import Orchestrator  # noqa: E402

RESULTS_ROOT = Path(__file__).resolve().parents[1] / "results"


def task_type_from_pid(pid: str) -> str:
    for t in ("detection", "localization", "analysis", "mitigation"):
        if f"-{t}" in pid:
            return t
    return "detection"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("problem_id")
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--max-steps", type=int, default=2)
    ap.add_argument("--results-root", default=str(RESULTS_ROOT))
    args = ap.parse_args()

    ts = time.strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.results_root) / "plain_claude" / args.problem_id / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    agent = ClaudeCodeAgent(run_dir=run_dir, task_type=task_type_from_pid(args.problem_id),
                            problem_id=args.problem_id, model=args.model)
    orch = Orchestrator()
    orch.register_agent(agent, name="plain_claude")
    desc, instr, apis = orch.init_problem(args.problem_id)
    agent.init_context(desc, instr, apis)
    out = await orch.start_problem(max_steps=args.max_steps)

    results = out.get("results", {}) if isinstance(out, dict) else {}
    (run_dir / "results.json").write_text(json.dumps(results, indent=2, default=str))
    (run_dir / "meta.json").write_text(json.dumps(agent.meta, indent=2, default=str))
    print("== RESULTS ==", json.dumps(results, default=str))
    print("== META ==", json.dumps(agent.meta, default=str))
    print("== run_dir ==", run_dir)


if __name__ == "__main__":
    asyncio.run(main())
