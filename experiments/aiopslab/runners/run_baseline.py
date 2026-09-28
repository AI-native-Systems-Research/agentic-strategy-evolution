"""Run one AIOpsLab problem with a baseline agent (plain-Claude / AIOpsLab shipped agent),
on the SAME model as Nous, and persist results.

Uses AIOpsLab's GenericOpenAIAgent (OpenAI-compatible; litellm) so the model matches
(claude-opus-4-6). This doubles as "plain Claude" (unstructured shell agent) and the
AIOpsLab baseline.

Usage:
    cd ~/aiopslab && poetry run python <this> <problem_id> [--model claude-opus-4-6]
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapter"))
from aiopslab.orchestrator import Orchestrator
from clients.generic_openai import GenericOpenAIAgent
from bedrock_client import BedrockSafeOpenAIClient  # noqa: E402

RESULTS_ROOT = Path(__file__).resolve().parents[1] / "results"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("problem_id")
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--label", default="aiopslab_generic")
    ap.add_argument("--results-root", default=str(RESULTS_ROOT))
    args = ap.parse_args()

    base_url = os.environ["OPENAI_COMPATIBLE_BASE_URL"]
    api_key = os.environ["OPENAI_COMPATIBLE_API_KEY"]

    ts = time.strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.results_root) / args.label / args.problem_id / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    agent = GenericOpenAIAgent(base_url=base_url, model=args.model, api_key=api_key)
    # Bedrock Claude rejects temperature+top_p together; swap in the safe client.
    agent.llm = BedrockSafeOpenAIClient(base_url=base_url, model=args.model, api_key=api_key)
    orch = Orchestrator()
    orch.register_agent(agent, name=args.label)
    desc, instr, apis = orch.init_problem(args.problem_id)
    agent.init_context(desc, instr, apis)
    out = await orch.start_problem(max_steps=args.max_steps)

    results = out.get("results", {}) if isinstance(out, dict) else {}
    meta = {"problem_id": args.problem_id, "model": args.model, "label": args.label,
            "max_steps": args.max_steps, "final_state": str(out.get("final_state"))}
    (run_dir / "results.json").write_text(json.dumps(results, indent=2, default=str))
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    print("== RESULTS ==", json.dumps(results, default=str))
    print("== META ==", json.dumps(meta, default=str))
    print("== run_dir ==", run_dir)


if __name__ == "__main__":
    asyncio.run(main())
