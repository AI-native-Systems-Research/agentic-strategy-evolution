# Architecture

This document describes the internal architecture of the Nous framework: what each component does, how they interact, and the design decisions behind them.

## Design Philosophy

Nous separates **deterministic orchestration** from **AI reasoning**. The orchestrator is a Python state machine — it never calls an LLM. It owns phase transitions, checkpointing, gate enforcement, and fast-fail rules. AI agents are external processes invoked by the orchestrator with structured prompts and schema-governed outputs.

This separation exists because:
- The orchestrator must be auditable and predictable — you need to trust that gates cannot be bypassed, fast-fail rules fire correctly, and state is always recoverable.
- AI agents are stochastic and expensive — isolating them makes the system testable without LLM calls and lets you swap agent implementations without touching control flow.

## System Overview

```
                    ┌─────────────────────────────────────┐
                    │          Orchestrator (Python)       │
                    │                                      │
                    │  ┌──────────┐    ┌───────────────┐  │
                    │  │  Engine   │───▶│  state.json   │  │
                    │  │ (states)  │    │  (checkpoint)  │  │
                    │  └────┬─────┘    └───────────────┘  │
                    │       │                              │
                    │  ┌────▼─────┐    ┌───────────────┐  │
                    │  │ Dispatch │───▶│  Agent (LLM)  │  │
                    │  └────┬─────┘    └───────┬───────┘  │
                    │       │                  │           │
                    │       │          schema-validated    │
                    │       │            artifacts         │
                    │       │                  │           │
                    │  ┌────▼─────┐    ┌──────▼────────┐  │
                    │  │  Gates   │    │  Fast-Fail    │  │
                    │  │ (human)  │    │  (rules)      │  │
                    │  └──────────┘    └───────────────┘  │
                    └─────────────────────────────────────┘

                    ┌─────────────────────────────────────┐
                    │           Campaign Directory         │
                    │                                      │
                    │  campaign.yaml   state.json          │
                    │  ledger.json     principles.json     │
                    │  problem.md      summary.json        │
                    │  runs/iter-N/    trace.jsonl         │
                    │    bundle.yaml   findings.json       │
                    │    experiment_plan.json (real exec)  │
                    │    experiment_results.json (real exec)│
                    │    investigation_summary.json         │
                    │    metrics/      reviews/            │
                    └─────────────────────────────────────┘
```

## Components

### Engine (`orchestrator/engine.py`)

The engine owns the 11-state state machine and checkpoint/resume.

**State machine:**

```
INIT ──▶ FRAMING ──▶ DESIGN ──▶ DESIGN_REVIEW ──▶ HUMAN_DESIGN_GATE
                        ▲            │                    │
                        │            │ (CRITICAL)         │ (reject)
                        └────────────┘                    │
                        ▲                                 │
                        └─────────────────────────────────┘
                                                          │ (approve)
                                                          ▼
         ┌──────────── RUNNING ◀──────────────────────────┘
         │               ▲
         ▼               │ (CRITICAL or reject)
    FINDINGS_REVIEW ─────┘
         │
         ▼
    HUMAN_FINDINGS_GATE
         │
         ├──▶ TUNING ──▶ EXTRACTION ──▶ DONE
         │                    │
         └──▶ EXTRACTION ◀───┘
                    │
                    └──▶ DESIGN  (next iteration, counter increments)
```

**Key behaviors:**
- `transition(to_state)` validates against the transition table, updates the timestamp, and atomically writes `state.json`.
- Iteration counter increments only on the EXTRACTION → DESIGN transition (starting a new iteration). Loopbacks from DESIGN_REVIEW → DESIGN (critical findings) do NOT increment — they are revisions within the same iteration.
- The DONE state is terminal — no transitions out.

**Atomic writes:** State is written to a temporary file, fsynced, then renamed over `state.json`. This prevents data loss if the process crashes mid-write. The in-memory state is only updated after the disk write succeeds, so state never diverges.

### Dispatch (`orchestrator/dispatch.py`)

The dispatcher invokes AI agents by role and phase, passing structured input and writing schema-validated output.

**Agent roles:**

| Role | Invoked During | Produces |
|---|---|---|
| **Planner** | FRAMING, DESIGN | `problem.md`, `bundle.yaml` |
| **Executor** | RUNNING | `experiment_plan.json`, `experiment_results.json`, `findings.json` |
| **Reviewer** | DESIGN_REVIEW, FINDINGS_REVIEW | `review-*.md` |
| **Extractor** | EXTRACTION, post-iteration | Updated `principles.json`, `investigation_summary.json` |
| **Summarizer** | Before each human gate | `gate_summary_*.json` |

**Implementations:**

- `StubDispatcher` (`dispatch.py`) produces valid, schema-conformant artifacts without calling any LLM. Used for testing the orchestrator loop.
- `LLMDispatcher` (`llm_dispatch.py`) calls a real LLM via the OpenAI SDK, parses structured output from code fences, validates against schemas, and writes artifacts atomically. Works with any OpenAI-compatible endpoint. This is the production dispatcher.
- `CLIDispatcher` (`cli_dispatch.py`) invokes `claude -p` as a subprocess, giving agents code access and shell tools. Used for planner and executor roles when the campaign specifies a `repo_path`. Shares the same routing table and prompt templates as `LLMDispatcher`, but sends prompts via stdin to the Claude CLI instead of calling an API endpoint. The agent can read files, grep code, and run commands in the target repo.

**Dispatch interface:**
```python
dispatcher.dispatch(
    role="executor",           # which agent
    phase="run",               # which phase
    output_path=path,          # where to write
    iteration=1,               # current iteration
)
```

Both dispatchers satisfy the `Dispatcher` protocol (`protocols.py`).

## LLM Dispatch (Phase 2)

`LLMDispatcher` is the real dispatcher that replaces stub agents with LLM-driven agents.

### Two-Layer Prompt System

Prompts have two layers:

| Layer | Source | Content |
|-------|--------|---------|
| **Methodology layer** | Ships with Nous (`prompts/methodology/`) | Generic scientific method: "check for confounds", "is the causal mechanism plausible?", "are 3 seeds enough?" |
| **Domain adapter layer** | Generated per system from `campaign.yaml` | System-specific vocabulary, metrics, knobs, experiment commands |

The methodology layer is 9 prompt templates (one per role+phase combination). At dispatch time, `PromptLoader` renders each template by replacing `{{placeholder}}` markers with domain-specific context from `campaign.yaml`:

- `{{target_system}}`, `{{system_description}}` — from `campaign.yaml`
- `{{observable_metrics}}`, `{{controllable_knobs}}` — from `campaign.yaml`
- `{{active_principles}}` — formatted from `principles.json`
- Phase-specific context: `{{bundle_yaml}}`, `{{findings_json}}`, `{{perspective_name}}`

### Schema Validation with Retry

For structured outputs (bundle YAML, findings JSON, principles JSON), the dispatcher:

1. Extracts content from a code fence (`` ```yaml `` or `` ```json ``)
2. Parses and validates against the relevant JSON Schema
3. On validation failure: retries once, sending the error message as feedback
4. On second failure: raises `RuntimeError`

Markdown outputs (problem framing, reviews) are written directly without validation.

### Executor Modes

The executor operates in one of two modes, chosen automatically based on `campaign.yaml`:

**Real execution mode** (when `target_system.execution` is present):

1. **Plan** — LLM designs shell commands for the baseline and each hypothesis arm (`executor/run-plan` route, produces `experiment_plan.json`)
2. **Run** — Orchestrator executes each command via `subprocess`, collecting metrics from JSON files written by the target system
3. **Analyze** — LLM compares predictions to real metrics (`executor/run-analyze` route, produces `findings.json`)

Commands run with `shell=False` (via `shlex.split`) for safety, with configurable timeouts. If `execution.repo_path` is set, the orchestrator creates a git worktree for isolation and cleans it up afterward.

**Analysis mode** (no `execution` config):

The executor reasons about the target system based on its understanding of the code and mechanisms, but does not run actual experiments. The `executor/run` route produces `findings.json` directly from LLM analysis.

This design is backward-compatible — existing campaigns without `execution` config continue to work unchanged.

### Model Configuration

`LLMDispatcher` uses the OpenAI SDK and works with any OpenAI-compatible endpoint. Set `OPENAI_API_KEY` and `OPENAI_BASE_URL` environment variables, or pass them to the constructor:

```python
dispatcher = LLMDispatcher(work_dir=work_dir, campaign=campaign, model="gpt-4o")
dispatcher = LLMDispatcher(..., api_base="https://my-proxy.example.com", api_key="sk-...")
```

Default model: `aws/claude-opus-4-6`. The `completion_fn` constructor parameter allows test injection without mocking internals.

## CLI Dispatch (Phase 4.5)

`CLIDispatcher` invokes `claude -p` for agents that need code and shell access. It shares the same `Dispatcher` protocol, routing table, and prompt templates as `LLMDispatcher`.

### When to Use Which Dispatcher

| Dispatcher | When | Why |
|---|---|---|
| `LLMDispatcher` | Campaign has no `repo_path` (default) | Agent has all context in the prompt — no code access needed |
| `CLIDispatcher` | Campaign has `repo_path` set | Agent needs to read code, discover metrics/knobs, run commands |

The entry points (`run_iteration.py`, `run_campaign.py`) auto-select: if `target_system.repo_path` is set, planner and executor use `CLIDispatcher`. Reviewer, extractor, and summarizer always use `LLMDispatcher` (they operate on artifacts, not code).

### Simplified Campaign

With `CLIDispatcher`, a campaign configuration can be as simple as:

```yaml
research_question: "What drives latency in my system?"
target_system:
  name: "My System"
  description: "A service that processes requests."
  repo_path: /path/to/repo
```

The planner explores the codebase to discover observable metrics, controllable knobs, and execution methods. The full campaign format (with explicit metrics, knobs, and execution config) remains supported and takes precedence when provided.

### Code Change Intents

When using `CLIDispatcher`, the planner can include optional `code_changes` in bundle arms:

```yaml
arms:
  - type: h-main
    prediction: "TTFT decreases by 15-25%"
    mechanism: "SJF reorders by predicted compute cost"
    diagnostic: "Check scheduling order"
    code_changes:
      - file: scheduler/policy.go
        intent: "Replace FCFS with shortest-job-first"
        rationale: "Prefix-heavy requests have predictable cost"
```

The planner says **what and why** — the executor implements the actual changes in a git worktree.

### Ledger (`orchestrator/ledger.py`)

Deterministic module that appends a schema-conformant row to `ledger.json` after each iteration. Reads `findings.json`, `bundle.yaml`, and `principles.json` to extract: h_main_result, ablation_results, control_result, robustness_result, prediction accuracy, and principle changes. No LLM calls — purely deterministic computation.

### Gates (`orchestrator/gates.py`)

Human gates are hard stops that cannot be bypassed. They surface the artifact and review summaries, then wait for a decision.

**Valid decisions:**
- `approve` — advance to the next phase
- `reject` — loop back (HUMAN_DESIGN_GATE → DESIGN, HUMAN_FINDINGS_GATE → RUNNING)
- `abort` — end the campaign

**Testing modes:** `auto_approve=True` or `auto_response="reject"` for deterministic testing without human interaction.

**Where gates appear:**
1. After DESIGN_REVIEW — human sees the hypothesis bundle and all review summaries
2. After FINDINGS_REVIEW — human sees the findings and all review summaries
3. After EXTRACTION (multi-iteration only) — human decides whether to continue to the next iteration

### Gate Summaries (Phase 4.5)

Before each human gate, a summarizer agent produces a formatted summary (`gate_summary_*.json`). The summary includes a plain-language description and bullet points highlighting what matters for the decision. This replaces the raw truncated artifact dumps from earlier phases.

Gates display the summary first, then the raw artifact (for those who want full detail). If summary generation fails, the gate falls back to the previous behavior.

### Fast-Fail Rules (`orchestrator/fastfail.py`)

Pure functions that examine findings and return a recommended action. The orchestrator decides how to act on the recommendation.

**Rules in priority order:**

| Rule | Trigger | Action | Rationale |
|---|---|---|---|
| 1 | H-main refuted | `SKIP_TO_EXTRACTION` | Mechanism doesn't work — running more arms is pointless |
| 2 | H-control-negative refuted | `REDESIGN` | Mechanism is confounded — it produces effects where it shouldn't |
| 3 | Dominant component >80% | `SIMPLIFY` | One component does all the work — drop the others |
| — | None of the above | `CONTINUE` | Proceed normally |

Rule 1 takes priority: if H-main is refuted, the control-negative result doesn't matter.

## Data Flow

### Within One Iteration

```
                    Planner
                       │
                       ▼
                  bundle.yaml ──▶ Reviewer (5 perspectives)
                       │                    │
                       │         ◀──── (if CRITICAL, loop back)
                       ▼
                  Human Gate (approve/reject/abort)
                       │
                       ▼
                    Executor
                       │
                       ├──▶ experiment_plan.json  (real execution only)
                       ├──▶ run commands, collect metrics
                       ├──▶ experiment_results.json
                       │
                       ▼
                 findings.json ──▶ Reviewer (10 perspectives)
                       │                    │
                       │         ◀──── (if CRITICAL, loop back)
                       ▼
                  Human Gate (approve/reject/abort)
                       │
                       ├──▶ EXTRACTION  (fast-fail: h-main refuted)
                       ├──▶ DESIGN      (fast-fail: h-control confounded)
                       ▼
                    Tuning (if H-main confirmed, no fast-fail)
                       │
                       ▼
                    Extractor
                       │
                       ▼
                 principles.json (insert / update / prune)
```

### Across Iterations

```
Iteration 1                    Iteration 2                    Iteration N
┌──────────────────┐          ┌──────────────────┐          ┌──────────────┐
│ Frame            │          │ Frame            │          │              │
│ Design           │          │ Design           │          │   ...        │
│ Execute          │   ───▶   │  (constrained by │   ───▶   │              │
│ Extract          │          │   principles)    │          │              │
│  → 2 principles  │          │ Execute          │          │              │
│                  │          │ Extract          │          │              │
│                  │          │  → 1 new,        │          │              │
│                  │          │    1 updated     │          │              │
└──────────────────┘          └──────────────────┘          └──────────────┘

principles.json grows and refines over time:
  iter 1: [P1, P2]
  iter 2: [P1, P2', P3]       (P2 updated, P3 inserted)
  iter 3: [P1, P2', P4]       (P3 pruned, P4 inserted)
```

Principles are hard constraints: the Planner must not design bundles that contradict active principles without explicit justification.

### Multi-Iteration Campaign Flow

`run_campaign.py` loops through iterations, adding post-iteration steps between each one:

```
for i in 1..max_iterations:
  ┌─────────────────────────────────────────────────────┐
  │  run_iteration(iteration=i, final=(i==max))         │
  │    FRAMING → DESIGN → REVIEW → RUNNING → EXTRACTION │
  └─────────────────────┬───────────────────────────────┘
                        │
                  (if not final)
                        │
              append_ledger_row(i)
              dispatch("extractor", "summarize")
                → investigation_summary.json
                        │
              CONTINUE GATE: "Continue to iteration i+1?"
                        │
              engine.transition("DESIGN")
                  (increments iteration counter)
                        │
                    next iteration
                  (summary injected into design prompt)
```

The investigation summary is bounded — it captures what was tested, key findings, open questions, and suggested next direction. This keeps agent context at O(summary) regardless of how many iterations have run.

The deterministic ledger (`orchestrator/ledger.py`) appends one row per iteration with prediction accuracy and principle changes, without any LLM calls.

## Schema Contracts

Every artifact exchanged between components is validated against a JSON Schema (Draft 2020-12). This ensures agents produce well-formed output and makes the system testable without LLMs.

| Schema | Format | Governs |
|---|---|---|
| `campaign.schema.yaml` | YAML | Campaign configuration (target system, execution, reviewer panel, prompt layers) |
| `experiment_plan.schema.json` | JSON | Executor experiment commands (baseline + per-arm commands) |
| `state.schema.json` | JSON | Orchestrator checkpoint (phase, iteration, run_id, config_ref) |
| `bundle.schema.yaml` | YAML | Hypothesis bundles (arms with predictions, mechanisms, diagnostics) |
| `findings.schema.json` | JSON | Prediction-vs-outcome tables with error classification |
| `investigation_summary.schema.json` | JSON | Bounded iteration summary for cross-iteration context |
| `principles.schema.json` | JSON | Principle store (statement, confidence, regime, evidence, category, status) |
| `ledger.schema.json` | JSON | Append-only iteration log with prediction accuracy and domain metrics |
| `summary.schema.json` | JSON | Campaign rollup (cost, tokens, principles extracted) |
| `trace.schema.json` | JSON | Observability events (LLM calls, state transitions, gate decisions) |

The bundle and campaign schemas use YAML format because they contain free-text fields that are more readable in YAML. All other schemas use JSON.

## Review Protocol

Reviews run N independent perspectives in parallel, each examining the artifact from a different angle (statistical rigor, causal sufficiency, confound risk, generalization, mechanism clarity). The perspective counts (default: 5 for design, 10 for findings) are configurable per campaign via `campaign.yaml`; the Phase 1 orchestrator dispatches reviews individually and enforcement of these counts is deferred to Phase 2 (agent prompts).

**Convergence gating:**
1. Run all perspectives in parallel
2. Collect findings with severity: CRITICAL, IMPORTANT, SUGGESTION
3. Zero CRITICAL → advance to human gate
4. Any CRITICAL → return to authoring agent for revision
5. Re-run full review after revision (max 10 rounds)

SUGGESTION items never block. IMPORTANT items are surfaced to the human reviewer but do not prevent advancement.

| Gate | Perspectives | After |
|---|---|---|
| Design Review | 5 (default) | Bundle design |
| Findings Review | 10 (default) | Experiment execution |

## Prediction Error Taxonomy

When a prediction is wrong, the error type determines what the system learns:

| Error Type | Meaning | System Response |
|---|---|---|
| **Direction** | Mechanism is fundamentally wrong | Prune or heavily revise the principle |
| **Magnitude** | Right mechanism, wrong strength | Update principle with calibrated bounds |
| **Regime** | Works under different conditions | Update principle with correct regime boundaries |

Direction errors are the most serious and most valuable — they reveal where the causal model is fundamentally flawed. In the BLIS case study, a direction error in iteration 1 (predicting <10% degradation, observing 62.4% degradation) redirected the entire scheduling investigation toward admission control.

## Crash Safety and Recovery

The orchestrator is designed for crash-safe operation:

- **Atomic state writes:** `state.json` is written to a temp file, fsynced, then renamed. A crash during write leaves the previous valid state intact.
- **Checkpoint/resume:** The engine loads state from `state.json` on construction. Kill the process at any point and restart — it resumes from the last committed state.
- **Append-only ledger:** `ledger.json` is logically append-only — rows are never modified or deleted. Implementation reads, appends, and atomically rewrites the file.
- **Idempotent extraction:** The extractor reads the existing `principles.json`, appends new principles, and writes back. Re-running extraction for the same iteration produces a duplicate (detectable by ID) rather than corruption.

## Extending Nous

### Using a Different Dispatcher

Nous ships with two dispatchers:

- `StubDispatcher` — deterministic stubs for testing
- `LLMDispatcher` — real LLM calls via OpenAI SDK

To create a custom dispatcher, implement the `Dispatcher` protocol from `orchestrator/protocols.py`. Your dispatcher must produce artifacts that pass schema validation — the orchestrator trusts the schema contract, not the content.

### Adding a New Arm Type

1. Add the type to the `enum` in `schemas/bundle.schema.yaml` (arm type) and `schemas/findings.schema.json` (arm_type)
2. Update `orchestrator/fastfail.py` if the new arm type has fast-fail implications
3. Add test cases to `tests/test_schemas.py` and `tests/test_fastfail.py`

### Adding a New Fast-Fail Rule

1. Add a new `FastFailAction` enum value
2. Add the rule to `check_fast_fail()` with appropriate priority ordering
3. Add test cases covering the rule and its interaction with existing rules
