# Real-Engram runs: setup + fairness notes

## What this is
Running the authors' real Engram (`mit-nms/Engram` @ commit 5295858, branch `engram`) instead of our
reimplementation, on Opus 4.6 via litellm, to compare against Nous on cloudcast + Frontier-CS tasks.

- Patch to run with Opus: `engram_opus_patch.diff` (adds `claude-opus-4-6` to the `--model` allowlist
  and the pricing table; nothing else touched). Engram pinned at commit 5295858.
- Engram already ships Frontier-CS support: `fcs_alg_<id>` / `fcs_res_<id>` problem types, its own
  `SystemBench/FrontierCS/frontier_cs_evaluator.py`, and `frontier_cs_repo` is a submodule of the SAME
  `FrontierCS/Frontier-CS` repo we use. So no custom adapter is needed; init the submodule and verify
  its scoring matches ours (or re-score Engram's best solution on our evaluator for apples-to-apples).
- Entrypoint: `examples/handoff_example_usage.py --problem_name {cloudcast|fcs_alg_<id>|fcs_res_<id>}
  --model claude-opus-4-6 --max_agents N --agent_timeout M --num_runs 1`. Agent runs in a `python:3.11`
  Docker sandbox with shell + a `run_simulation` tool (so it gets rich evaluator feedback, not a scalar).

## FAIRNESS NOTE (prompt asymmetry) — TODO revisit
Engram's cloudcast task prompt is heavily guided: it **reveals the expert target** ("~0.0023, cost
~$419"), **pushes MILP**, and **tells the agent NOT to use Steiner-tree heuristics**. Our Nous and
plain-Claude prompts reveal none of this (no target, no method hint).

Implication: a head-to-head where Engram's prompt hands over the target+method while Nous's does not is
not prompt-fair. To level it, we can give Nous (and Claude) a **matched prompt** that reveals the same
target/hint for cloudcast (and analogously for other tasks).

Decision (2026-10-01): note it now; do a Nous rerun with the matched prompt **if we need it** for the
comparison. Not blocking the current real-Engram runs.
