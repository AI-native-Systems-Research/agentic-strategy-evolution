# AIDE as a Frontier-CS baseline — adapter spec

## Decision

Add **AIDE** (Weco AI) as a fourth agent baseline next to vanilla-Claude, Engram-style,
and Nous. We use **AIDE's own source unmodified** and add a thin **adapter** that teaches it
two things it does not natively know: (1) write C++17 instead of Kaggle-Python, and (2) score a
node with the Frontier-CS go-judge instead of asking an LLM to read a metric off stdout. AIDE's
*method* — the tree search over solution drafts (draft / debug / improve) and its node-selection
policy — is used **as-is**. We are not reimplementing the methodology.

## What AIDE is

- Paper: *AIDE: AI-Driven Exploration in the Space of Code*, Jiang, Schmidt, Srikanth, Xu, Kaplan,
  Jacenko, Wu. **arXiv:2502.13138 (2025)**, Weco AI. arXiv preprint only (not a Nature/venue paper;
  its results appear inside OpenAI's MLE-bench, arXiv:2410.07095). Verify author order on arXiv
  before citing.
- Code: https://github.com/WecoAI/aideml — **MIT licensed** (`LICENSE`, "Copyright (c) 2024 Weco AI Ltd").
  Python, `pip install -e .`. Cloned locally at `~/frontier/aideml`.

### AIDE's algorithm (what we keep, verbatim from the code)

- `Agent.search_policy()` (`aide/agent.py`): draft until `num_drafts` (default 5) drafts exist; else
  with prob `debug_prob` (0.5) debug a random buggy leaf whose `debug_depth <= max_debug_depth` (3);
  else greedily `improve` the best node. **Not MCTS/UCT — greedy-best + stochastic debug.**
- Operators: `_draft` (from scratch), `_debug` (fix a buggy node), `_improve` (one atomic change to
  the best node). `step()` dispatches to one per iteration; `agent.steps` (default 20) iterations.
- `Journal`/`Node` tree, `get_best_node()` ranks by `MetricValue` honoring `metric_maximize`.

**All of the above is inherited unchanged.** The adapter only overrides domain-specific leaves.

## What must change, and why

| AIDE assumption (in code) | Why it breaks on Frontier-CS | Adapter response |
|---|---|---|
| `interpreter.py` runs the solution with `exec(compile(code))` **in-process Python** | Our solution is a C++17 file compiled + run by a Docker go-judge | Replace the exec callback: write `solution.cpp`, call `frontier eval`, return the judge result |
| `parse_exec_result` asks a **feedback LLM** to read a validation metric off stdout | We already have an objective 0-100 score; an LLM re-read adds cost + a direction-flip risk | Override `parse_exec_result`: set `node.metric` directly from the judge score |
| `_draft/_improve/_debug` prompts say "Kaggle grandmaster … Python … `submission.csv` … `./input`" | Steers the model to Python ML code, not competitive-programming C++ | Override the three operator prompt builders to request one self-contained C++17 program |
| `data_preview` wants a `./input` data dir | No tabular data for algorithmic tasks | Override `update_data_preview` to a no-op |

## Adapter design

**One new file, zero edits to AIDE's source:** `experiments/frontiercs/gen/aide_frontier.py`.

It imports the installed `aide` package and reuses `frontier_gen`'s judge helpers
(`statement`, `evaluate`). It defines:

1. **`FrontierAgent(aide.agent.Agent)`** — subclass overriding only:
   - `_draft`, `_improve`, `_debug`: identical control flow to AIDE, but the prompt text requests
     "a single self-contained C++17 program for this competitive-programming problem; read stdin,
     write stdout; maximize the 0-100 partial-credit score." Reuses the inherited
     `plan_and_code_query`, so plan+code splitting is unchanged.
   - `parse_exec_result(node, exec_result)`: parse the judge score the exec callback stashed in
     `exec_result.term_out`; set `node.is_buggy` (True iff compile/runtime failure or score is None)
     and `node.metric = MetricValue(score, maximize=True)` or `WorstMetricValue()`. **No LLM call.**
   - `update_data_preview`: sets `self.data_preview = ""`.
2. **`make_exec_callback(pid, workdir, ...)`** — returns `cb(code, reset=True)` that writes
   `workdir/solution.cpp`, runs `evaluate(pid, sol)` (→ `frontier eval algorithmic <pid> <sol> --json`),
   and returns an `aide.interpreter.ExecutionResult` whose `term_out[0]` is
   `"__SCORE__ <score> <status>"` and `exc_type` is set on judge failure. This is the exact seam
   AIDE's `run()` already uses (`exec_callback=interpreter.run`); we just pass a different callback.
3. **A run loop** mirroring `aide/run.py` but without the Kaggle workspace prep: build an OmegaConf
   `cfg` (agent.search knobs, `code.model`, `exec.timeout`), `Journal(metric_maximize=True)`,
   `FrontierAgent`, then `while len(journal) < steps: agent.step(exec_callback)`. Writes the best
   node's code to the output `solution.cpp` and a pred JSON (`final_score`, per-node scores, tree
   size, step count).

### LLM routing (litellm)

AIDE's `determine_provider` hard-routes any `claude-*` model to its **Anthropic SDK** backend,
which (a) ignores `OPENAI_BASE_URL` and (b) breaks against the installed anthropic SDK
(`Messages.create() got an unexpected keyword argument 'temperature'`). So the adapter overrides it
with a one-line hook — `aide.backend.determine_provider = lambda m: "openai"` — sending every call
through `backend_openai`, which honors `OPENAI_BASE_URL` and uses the chat-completions API for
non-OpenAI model names. This is the adapter's single routing hook; AIDE's source stays untouched.

Env: `OPENAI_BASE_URL=<litellm-root>/v1` (the openai SDK appends `/chat/completions`, so it must be
the `/v1` root; the adapter normalizes this automatically) and `OPENAI_API_KEY=<key>`, model
`claude-opus-4-6`. DIRECT to the gateway over VPN, never the tunnel.

**Bedrock user-slot fix:** AIDE packs the whole prompt into the **system** message with
`user_message=None`. The litellm gateway's Bedrock-backed Claude rejects a system-only request
(`bedrock requires at least one non-system message`). The adapter wraps `query` (patched into
`aide.agent`, since agent.py binds the name at import) to relocate a system-only prompt into the
user slot, content unchanged. Second adapter hook; still no AIDE source edit.

**C++ code-extraction fix:** AIDE's `extract_code` (`utils/response.py`) keeps only fenced blocks
that pass `is_valid_python_script()`, so **C++ is always discarded and every node ends up codeless**
(symptom: "Plan + code extraction failed", all nodes buggy with score None). The adapter patches
`aide.agent.extract_code` with a C++-aware extractor that returns the largest ```cpp/c++``` block.
Third adapter hook; still no AIDE source edit.

### The three adapter hooks (summary)

All live in `aide_frontier.py`; AIDE's source is unmodified:
1. `determine_provider → "openai"` — route Claude through the litellm chat API, not the Anthropic SDK.
2. `query` user-slot relocation — satisfy Bedrock's "needs a non-system message".
3. `extract_code` → C++-aware — stop AIDE discarding non-Python code.

Plus the subclass overrides (operator prompts, judge scoring, data-preview no-op) described above.

**Compat note:** `backend_openai.query` converts `max_tokens` → `max_output_tokens` (a Responses-API
param) even on the chat path, which the chat-completions endpoint rejects. We never pass
`max_tokens` (AIDE's `plan_and_code_query` doesn't, and we bypass the only other caller — the
feedback reviewer), so the bug is not triggered. We also bypass AIDE's only function-calling path
(the reviewer), so plain chat completions suffice.

### Determinism

`metric_maximize=True` is passed straight to the `Journal`, so `get_best_node` ranks by raw score
descending. Because we score from the judge (not the LLM reviewer), node metrics are fully
deterministic given the generated code.

### Fidelity statement (for the paper)

> AIDE's source is used unmodified (MIT). A ~150-line adapter subclasses `Agent` to (a) request
> C++17 instead of Kaggle-Python in the draft/debug/improve prompts and (b) score each node with the
> Frontier-CS go-judge instead of AIDE's LLM stdout-reviewer. AIDE's tree search — `search_policy`,
> `Journal`, `Node`, `get_best_node`, and the draft/debug/improve control flow — is inherited
> unchanged.

### Cost accounting (for the cost-matched comparison, not the smoketest)

AIDE's `backend.query` does not surface token usage to us. For parity with the other agents'
uniform cost ($15/M in, $75/M out), wrap `aide.backend.query` to accumulate `usage` per call, or
run to a fixed `steps` budget as a first cut. Smoketest uses a small fixed `steps`.

## Install

```bash
python3.11 -m venv ~/frontier/aide-venv
~/frontier/aide-venv/bin/pip install -U pip
~/frontier/aide-venv/bin/pip install -e ~/frontier/aideml
```

## Smoketest (proof it runs end-to-end)

Judge sanity first (no LLM): score a reference solution.
```bash
~/frontier/Frontier-CS/.venv/bin/frontier eval algorithmic 44 \
  ~/frontier/Frontier-CS/algorithmic/solutions/44/deepseekreasoner_1.cpp --json
```

Then a cheap AIDE run (small tree) on one real task:
```bash
export OPENAI_BASE_URL="https://ete-litellm.ai-models.vpc-int.res.ibm.com/v1"
export OPENAI_API_KEY=<key>
~/frontier/aide-venv/bin/python \
  experiments/frontiercs/gen/aide_frontier.py 44 \
  --model claude-opus-4-6 --steps 4 --num-drafts 2 \
  --out experiments/frontiercs/artifacts/mac/preds/p44.aide-smoke.json \
  --logdir ~/frontier/gen_logs
```

### Expected output (success criteria)

- The run drafts C++ (not Python), compiles cleanly, and the judge returns a 0-100 score for at
  least one node.
- The pred JSON has a numeric `final_score` and a `nodes` list with per-node `(stage, score)`;
  tree size == `steps`.
- At least one `improve` or `debug` step occurs after the drafts (proves the search loop, not just
  one-shot generation).

## Risks / caveats

- **Prompt steering:** AIDE's drafts are ML-shaped; getting clean competitive-programming C++ may
  need one or two prompt-wording passes. If the model still emits Python, tighten the operator
  prompt.
- **Compile-error routing:** a node must be marked `is_buggy` on compile failure so the search sends
  it to `_debug`. The callback sets `exc_type` and includes the judge/compiler message in
  `term_out` so `_debug` has something to fix.
- **No external AIDE-on-Frontier-CS number exists** to validate against (we are early movers on this
  benchmark); fidelity rests on the unmodified-search claim above.
- Colima Docker must be up; `data`/`submissions` dirs chmod 777 (known go-judge bind-mount issue).
