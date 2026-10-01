#!/usr/bin/env python3
"""AIDE (Weco AI, arXiv:2502.13138) as a Frontier-CS algorithmic baseline.

We use AIDE's source UNMODIFIED (installed `aide` package, MIT). This file is a thin adapter that
teaches AIDE two things it does not natively know, while reusing its tree search as-is:

  1. Write C++17, not Kaggle-Python  -> override the draft/debug/improve prompt builders.
  2. Score a node with the Frontier-CS go-judge, not an LLM reading stdout -> override
     parse_exec_result + supply a compile+judge exec callback.

Everything that IS AIDE's method -- search_policy (greedy-best + stochastic debug), Journal/Node,
get_best_node, the per-step draft/debug/improve dispatch -- is inherited unchanged from aide.agent.

See experiments/frontiercs/artifacts/mac/AIDE_ADAPTER.md for the full spec.

LLM routing: set OPENAI_BASE_URL=<litellm-root>/v1 and OPENAI_API_KEY; model e.g. claude-opus-4-6.
AIDE's determine_provider sends non-OpenAI model names through the openai-compatible chat API, so
the litellm gateway is used with no change to AIDE's backend.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf

import aide.backend as _aide_backend
from aide.agent import Agent
from aide.journal import Journal, Node
from aide.interpreter import ExecutionResult
from aide.utils.metric import MetricValue, WorstMetricValue

# Force AIDE's OpenAI-compatible backend for every call. AIDE's determine_provider() hard-routes any
# "claude-*" model to its Anthropic SDK path (which also ignores OPENAI_BASE_URL); we instead send all
# calls through backend_openai, which honors OPENAI_BASE_URL and uses the chat-completions API for
# non-OpenAI model names. This is the single routing hook of the adapter; AIDE's source is untouched.
_aide_backend.determine_provider = lambda model: "openai"

# AIDE packs the whole prompt into the SYSTEM message with user_message=None. The litellm gateway's
# Bedrock-backed Claude rejects a system-only request ("bedrock requires at least one non-system
# message"). Relocate a system-only prompt into the user slot (content unchanged) before dispatch.
# agent.py binds `query` at import (`from .backend import query`), so we patch the name in aide.agent.
import aide.agent as _aide_agent

_orig_query = _aide_backend.query


def _query_user_slot(system_message=None, user_message=None, **kw):
    if user_message is None and system_message is not None:
        system_message, user_message = None, system_message
    return _orig_query(system_message=system_message, user_message=user_message, **kw)


_aide_agent.query = _query_user_slot


# AIDE's extract_code() validates every fenced block with is_valid_python_script() and discards
# anything that is not valid Python, so C++ is always dropped and nodes end up code-less. Replace it
# with a C++-aware extractor: take the largest ```cpp/c++``` block (the full program). Patched into
# aide.agent, where plan_and_code_query() looks the name up.
def _extract_cpp_code(text):
    if not text:
        return ""
    blocks = re.findall(r"```(?:cpp|c\+\+|c)?\s*\n(.*?)```", text, re.DOTALL)
    blocks = [b.strip() for b in blocks if b.strip()]
    if blocks:
        return max(blocks, key=len)
    if "#include" in text or "int main" in text:
        return text.strip()
    return ""


_aide_agent.extract_code = _extract_cpp_code

FRONTIER = os.environ.get("FRONTIER_DIR", os.path.expanduser("~/frontier/Frontier-CS"))
FEVAL = os.environ.get("FEVAL_BIN", f"{FRONTIER}/.venv/bin/frontier")

SCORE_TAG = "__SCORE__"


# ----- Frontier-CS judge helpers (shell out to the frontier CLI; identical contract to frontier_gen) -----
def statement(pid: int) -> str:
    p = Path(FRONTIER) / "algorithmic" / "problems" / str(pid) / "statement.txt"
    if p.exists():
        return p.read_text()
    r = subprocess.run(f"{FEVAL} show algorithmic {pid}", shell=True, text=True,
                       capture_output=True, cwd=FRONTIER)
    return r.stdout


def evaluate(pid: int, sol_path: Path, timeout: int = 600):
    """Return (score, status, raw) by invoking the go-judge on sol_path."""
    r = subprocess.run(
        f"{FEVAL} eval algorithmic {pid} {shlex.quote(str(sol_path))} --json",
        shell=True, text=True, capture_output=True, timeout=timeout, cwd=FRONTIER)
    blob = (r.stdout or "") + "\n" + (r.stderr or "")
    best = None
    for m in re.finditer(r"\{[^{}]*\"score\"[^{}]*\}", blob):
        try:
            best = json.loads(m.group(0))
        except Exception:
            pass
    if best is None:
        for line in reversed(blob.splitlines()):
            line = line.strip()
            if line.startswith("{") and "score" in line:
                try:
                    best = json.loads(line)
                    break
                except Exception:
                    pass
    if best is None:
        return None, "parse_error", blob[-800:]
    return best.get("score"), best.get("status", "?"), best


CPP_RULES = (
    "This is a competitive-programming optimization problem. Scoring is CONTINUOUS partial credit "
    "from 0 to 100 (higher is better); your goal is to MAXIMIZE it, not merely to be correct.\n"
    "- Write a SINGLE self-contained C++17 source file. No Python, no external files, no data "
    "directories, no submission.csv. Read from standard input, write to standard output.\n"
    "- Match the problem's Output section EXACTLY (line count, separators, token order); a correct "
    "algorithm can score ~0 from a format mismatch.\n"
    "- Respect the per-test time limit: a solution that exceeds it scores 0 on that test even if the "
    "answer is correct, so size your iteration counts/restarts to finish comfortably on the largest "
    "inputs.\n"
    "- Do not use bits/stdc++.h if portability is a concern; include the standard headers you need."
)


class FrontierAgent(Agent):
    """AIDE Agent specialized to Frontier-CS C++17 tasks.

    Overrides ONLY the domain-specific leaves: the three operator prompt builders (ask for C++17
    instead of Kaggle-Python), node scoring (use the go-judge, not the LLM reviewer), and the data
    preview (no tabular input exists). search_policy / step / Journal selection are inherited.
    """

    def update_data_preview(self):  # no ./input data dir for algorithmic tasks
        self.data_preview = ""

    # --- operator prompts: same control flow as aide.agent, C++ wording instead of Kaggle-Python ---
    def _draft(self) -> Node:
        prompt: Any = {
            "Introduction": (
                "You are an expert competitive programmer. Devise a strong solution strategy for the "
                "problem below and implement it as a single self-contained C++17 program."),
            "Task description": self.task_desc,
            "Memory": self.journal.generate_summary(),
            "Instructions": {},
        }
        prompt["Instructions"] |= self._cpp_resp_fmt
        prompt["Instructions"] |= {"Solution sketch guideline": [
            "This first solution should be a reasonable, correct baseline for the problem.",
            "Take the Memory section into account; do not repeat an approach already tried.",
            "The sketch should be 3-5 sentences.",
        ]}
        prompt["Instructions"] |= self._cpp_impl_guideline
        plan, code = self.plan_and_code_query(prompt)
        return Node(plan=plan, code=code)

    def _improve(self, parent_node: Node) -> Node:
        prompt: Any = {
            "Introduction": (
                "You are an expert competitive programmer. You are given a working C++17 solution "
                "below and should improve it to increase the 0-100 partial-credit score. First outline "
                "one specific, atomic improvement, then implement it as a full C++17 program."),
            "Task description": self.task_desc,
            "Memory": self.journal.generate_summary(),
            "Previous solution": {"Code": _wrap_cpp(parent_node.code)},
            "Instructions": {},
        }
        prompt["Instructions"] |= self._cpp_resp_fmt
        prompt["Instructions"] |= {"Solution improvement sketch guideline": [
            "Propose a SINGLE actionable, atomic improvement (better heuristic, stronger local search, "
            "smarter construction, tighter time budget use) so its effect is measurable.",
            "Be specific. The sketch should be 3-5 sentences.",
            "Take the Memory section into account.",
        ]}
        prompt["Instructions"] |= self._cpp_impl_guideline
        plan, code = self.plan_and_code_query(prompt)
        return Node(plan=plan, code=code, parent=parent_node)

    def _debug(self, parent_node: Node) -> Node:
        prompt: Any = {
            "Introduction": (
                "You are an expert competitive programmer. Your previous C++17 solution failed to "
                "compile or run correctly. Using the execution output below, diagnose the specific "
                "cause and produce a fixed, full C++17 program."),
            "Task description": self.task_desc,
            "Previous (buggy) implementation": _wrap_cpp(parent_node.code),
            "Execution output": _wrap_text(parent_node.term_out),
            "Instructions": {},
        }
        prompt["Instructions"] |= self._cpp_resp_fmt
        prompt["Instructions"] |= {"Bugfix sketch guideline": [
            "Briefly (3-5 sentences) describe the root cause and the fix.",
        ]}
        prompt["Instructions"] |= self._cpp_impl_guideline
        plan, code = self.plan_and_code_query(prompt)
        return Node(plan=plan, code=code, parent=parent_node)

    @property
    def _cpp_resp_fmt(self):
        return {"Response format": (
            "Respond with a brief solution outline in natural language (3-5 sentences), then a SINGLE "
            "markdown code block (```cpp ... ```) containing the complete C++17 program. No extra "
            "headings or text.")}

    @property
    def _cpp_impl_guideline(self):
        return {"Implementation guideline": [
            "The code must be a single-file, self-contained C++17 program that compiles with g++ -O2.",
            "Read all input from stdin and write the answer to stdout, matching the Output section.",
            "Do not skip any part of the code; output the full program.",
            "Your response must contain exactly one code block.",
            CPP_RULES,
        ]}

    # --- scoring: use the real judge, not AIDE's LLM stdout-reviewer (deterministic, no tokens) ---
    def parse_exec_result(self, node: Node, exec_result: ExecutionResult):
        node.absorb_exec_result(exec_result)
        score, status = _parse_score_tag(exec_result.term_out)
        node.analysis = f"go-judge: status={status}, score={score}"
        node.is_buggy = (exec_result.exc_type is not None) or (score is None)
        node.metric = WorstMetricValue() if node.is_buggy else MetricValue(float(score), maximize=True)


def _wrap_cpp(code: str) -> str:
    return f"```cpp\n{code}\n```"


def _wrap_text(text: str) -> str:
    return f"```\n{text}\n```"


def _parse_score_tag(term_out):
    joined = "".join(term_out) if isinstance(term_out, list) else str(term_out)
    m = re.search(rf"{re.escape(SCORE_TAG)}\s+(\S+)\s+(\S+)", joined)
    if not m:
        return None, "no_score"
    raw, status = m.group(1), m.group(2)
    try:
        return float(raw), status
    except ValueError:
        return None, status


def make_exec_callback(pid, workdir: Path, judge_timeout=600):
    """Compile+judge exec callback, drop-in for AIDE's interpreter.run.

    Writes the generated C++ to solution.cpp, runs the go-judge, and returns an ExecutionResult whose
    term_out carries '__SCORE__ <score> <status>' plus the judge/compiler message (so _debug has
    something to fix). exc_type is set on judge failure so the search routes the node to _debug.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    def cb(code, reset=True):
        t0 = time.time()
        sol = workdir / "solution.cpp"
        sol.write_text(code)
        try:
            score, status, raw = evaluate(pid, sol, timeout=judge_timeout)
        except subprocess.TimeoutExpired:
            score, status, raw = None, "judge_timeout", "judge timed out"
        exec_time = time.time() - t0
        failed = score is None or (isinstance(status, str) and any(
            k in status.lower() for k in ("error", "compile", "fail", "timeout")))
        exc_type = None if (score is not None and not failed) else (status or "JudgeError")
        term = [f"{SCORE_TAG} {score} {status}\n", f"judge detail: {json.dumps(raw)[:1200]}\n"]
        return ExecutionResult(term_out=term, exec_time=exec_time,
                               exc_type=exc_type, exc_info=None, exc_stack=None)

    return cb


def build_cfg(model, steps, num_drafts, debug_prob, max_debug_depth, exec_timeout):
    """Minimal OmegaConf cfg exposing only the attributes aide.agent.Agent reads."""
    return OmegaConf.create({
        "agent": {
            "steps": steps,
            "k_fold_validation": 1,
            "expose_prediction": False,
            "data_preview": False,
            "metric_maximize": True,
            "code": {"model": model, "temp": 0.5},
            "feedback": {"model": model, "temp": 0.5},  # unused: scoring bypasses the reviewer
            "search": {"max_debug_depth": max_debug_depth,
                       "debug_prob": debug_prob, "num_drafts": num_drafts},
        },
        "exec": {"timeout": exec_timeout},
    })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pid", type=int)
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--num-drafts", type=int, default=5)
    ap.add_argument("--debug-prob", type=float, default=0.5)
    ap.add_argument("--max-debug-depth", type=int, default=3)
    ap.add_argument("--judge-timeout", type=int, default=600)
    ap.add_argument("--label", default="aide")
    ap.add_argument("--logdir", default=os.path.expanduser("~/frontier/gen_logs"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.environ.get("OPENAI_BASE_URL") or not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_BASE_URL (litellm root) and OPENAI_API_KEY in the env.")
    # AIDE's openai SDK client appends /chat/completions to the base_url, so it must point at the
    # /v1 API root. frontier_gen uses the bare root for its own raw POSTs; normalize here (own process).
    _bu = os.environ["OPENAI_BASE_URL"].rstrip("/")
    if not _bu.endswith("/v1"):
        os.environ["OPENAI_BASE_URL"] = _bu + "/v1"

    workdir = Path(args.logdir) / f"frontier_{args.pid}_{args.label}_aide"
    workdir.mkdir(parents=True, exist_ok=True)
    stmt = statement(args.pid)
    task_desc = f"# Frontier-CS algorithmic problem #{args.pid}\n\n{CPP_RULES}\n\n## Problem statement\n{stmt}"

    cfg = build_cfg(args.model, args.steps, args.num_drafts, args.debug_prob,
                    args.max_debug_depth, args.judge_timeout)
    journal = Journal(metric_maximize=True)
    agent = FrontierAgent(task_desc=task_desc, cfg=cfg, journal=journal)
    exec_cb = make_exec_callback(args.pid, workdir, judge_timeout=args.judge_timeout)

    t0 = time.time()
    while len(journal) < args.steps:
        agent.step(exec_callback=exec_cb)
        best = journal.get_best_node()
        bs = (best.metric.value if best and best.metric and best.metric.value is not None else None)
        n = journal.nodes[-1]
        print(f"[step {len(journal)}/{args.steps}] stage={n.stage_name} "
              f"score={None if n.metric is None else n.metric.value} buggy={n.is_buggy} best={bs}",
              flush=True)
    elapsed = time.time() - t0

    best = journal.get_best_node()
    best_score = best.metric.value if best and best.metric and best.metric.value is not None else None
    if best is not None:
        (workdir / "solution.cpp").write_text(best.code)

    nodes_summary = [{
        "step": nd.step, "stage": nd.stage_name, "is_buggy": nd.is_buggy,
        "score": (None if (nd.metric is None or nd.metric.value is None) else nd.metric.value),
    } for nd in journal.nodes]

    pred = {
        "pid": args.pid, "agent": "aide", "method": "AIDE (unmodified search) + Frontier adapter",
        "model": args.model, "label": args.label,
        "final_score": best_score, "elapsed_sec": round(elapsed, 1),
        "steps": args.steps, "num_drafts": args.num_drafts,
        "tree_size": len(journal.nodes),
        "n_good": len(journal.good_nodes), "n_buggy": len(journal.buggy_nodes),
        "nodes": nodes_summary,
        "best_solution_path": str(workdir / "solution.cpp"),
        "aide_paper": "arXiv:2502.13138", "aide_repo": "github.com/WecoAI/aideml",
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(pred, indent=2))
    print(f"RESULT pid={args.pid} agent=aide final_score={best_score} "
          f"tree={len(journal.nodes)} elapsed={elapsed:.0f}s -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
