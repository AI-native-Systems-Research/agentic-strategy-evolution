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
                    │  summary.json                        │
                    │  runs/iter-N/    trace.jsonl         │
                    │    problem.md    bundle.yaml          │
                    │    experiment_plan.yaml               │
                    │    execution_results.json              │
                    │    findings.json                      │
                    │    principle_updates.json             │
                    │    gate_summary_*.json                │
                    └─────────────────────────────────────┘
```

## Components

### Engine (`orchestrator/engine.py`)

The engine owns the 7-state state machine and checkpoint/resume.

**State machine:**

```
INIT ──▶ DESIGN ──▶ HUMAN_DESIGN_GATE
            ▲              │
            │ (reject)     │ (approve)
            └──────────────┘
                           │
                           ▼
                    EXECUTE_ANALYZE ──▶ VALIDATE ──▶ HUMAN_FINDINGS_GATE
                           ▲                              │
                           │ (reject)                     │ (approve)
                           └──────────────────────────────┘
                                                          │
                                                          ▼
                                                        DONE
                                                          │
                                                          └──▶ DESIGN (next iteration, counter increments)
```

**Valid transitions:**
- INIT → DESIGN
- DESIGN → HUMAN_DESIGN_GATE
- HUMAN_DESIGN_GATE → EXECUTE_ANALYZE (approve) | DESIGN (reject)
- EXECUTE_ANALYZE → VALIDATE
- VALIDATE → HUMAN_FINDINGS_GATE
- HUMAN_FINDINGS_GATE → DONE (approve) | EXECUTE_ANALYZE (reject)
- DONE → DESIGN (next iteration, increments counter)

**Key behaviors:**
- `transition(to_state)` validates against the transition table, updates the timestamp, and atomically writes `state.json`.
- Iteration counter increments only on the DONE → DESIGN transition (starting a new iteration). Loopbacks from HUMAN_DESIGN_GATE → DESIGN (reject) do NOT increment — they are revisions within the same iteration.
- The DONE state allows transition to DESIGN for the next iteration.

**Atomic writes:** State is written to a temporary file, fsynced, then renamed over `state.json`. This prevents data loss if the process crashes mid-write. The in-memory state is only updated after the disk write succeeds, so state never diverges.

### Dispatch (`orchestrator/dispatch.py`)

The dispatcher invokes AI agents by role and phase, passing structured input and writing schema-validated output.

**Agent roles:**

| Role | Invoked During | Produces |
|---|---|---|
| **Planner** (Opus, `claude -p`) | DESIGN | `problem.md`, `bundle.yaml` |
| **Executor** (Sonnet, `claude -p`) | EXECUTE_ANALYZE | `experiment_plan.yaml`, `execution_results.json`, `findings.json`, `principle_updates.json` |
| **Python orchestrator** | VALIDATE | Replays `experiment_plan.yaml`, merges principles by ID into `principles.json` (no LLM) |

**Implementations:**

- `StubDispatcher` (`dispatch.py`) produces valid, schema-conformant artifacts without calling any LLM. Used for testing the orchestrator loop.
- `CLIDispatcher` (`cli_dispatch.py`) invokes `claude -p` as a subprocess, giving agents code access and shell tools. Used for both the planner (DESIGN, Opus) and executor (EXECUTE_ANALYZE, Sonnet) roles. Sends prompts via stdin to the Claude CLI. The agent can read files, grep code, and run commands in the target repo. Supports `override_cwd()` context manager for temporarily pointing the executor at a git worktree.

**Dispatch interface:**
```python
dispatcher.dispatch(
    role="executor",           # which agent
    phase="execute-analyze",   # which phase
    output_path=path,          # where to write
    iteration=1,               # current iteration
)
```

Both dispatchers satisfy the `Dispatcher` protocol (`protocols.py`).

## CLI Dispatch

`CLIDispatcher` invokes `claude -p` for both agent roles. It satisfies the `Dispatcher` protocol from `orchestrator/protocols.py`.

### Prompt System

Prompts are templates in `prompts/methodology/` (one per role). At dispatch time, `PromptLoader` renders each template by replacing `{{placeholder}}` markers with domain-specific context from `campaign.yaml`:

- `{{target_system}}`, `{{system_description}}` — from `campaign.yaml`
- `{{observable_metrics}}`, `{{controllable_knobs}}` — from `campaign.yaml`
- `{{active_principles}}` — formatted from `principles.json`
- Phase-specific context: `{{bundle_yaml}}`, `{{findings_json}}`

### EXECUTE_ANALYZE: Merged Execution Pipeline

The executor agent (Sonnet, `claude -p`) handles the entire execution pipeline in a single session:

1. Receives the approved hypothesis bundle
2. Explores the target repo, discovers build commands
3. Produces `experiment_plan.yaml` with exact shell commands per arm
4. Runs the commands, captures stdout/stderr per condition
5. Compares observed metrics against predictions
6. Produces `findings.json` and `principle_updates.json`

The VALIDATE phase (Python-only) then replays `experiment_plan.yaml` for reproducibility verification and merges principles by ID into `principles.json`.

### Model Configuration

Two `claude -p` calls per iteration:

| Phase | Model | Role |
|-------|-------|------|
| DESIGN | Opus | Planner — explores, frames, designs hypothesis bundle |
| EXECUTE_ANALYZE | Sonnet | Executor — builds, patches, runs, analyzes, extracts |

### Simplified Campaign

With `CLIDispatcher`, a campaign configuration can be as simple as:

```yaml
research_question: "What drives latency in my system?"
target_system:
  name: "My System"
  description: "A service that processes requests."
  repo_path: /path/to/repo
```

The planner explores the codebase to discover observable metrics, controllable knobs, and execution methods. The full campaign format (with explicit metrics and knobs) remains supported — provided values take precedence over what the planner discovers.

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
- `reject` — loop back (HUMAN_DESIGN_GATE → DESIGN, HUMAN_FINDINGS_GATE → EXECUTE_ANALYZE)
- `abort` — end the campaign

**Testing modes:** `auto_approve=True` or `auto_response="reject"` for deterministic testing without human interaction.

**Where gates appear:**
1. HUMAN_DESIGN_GATE — after DESIGN, human sees the hypothesis bundle
2. HUMAN_FINDINGS_GATE — after VALIDATE, human sees findings and principle updates

### Gate Summaries

Before each human gate, a formatted summary (`gate_summary_*.json`) is produced. The summary includes a plain-language description and bullet points highlighting what matters for the decision.

Gates display the summary first, then the raw artifact (for those who want full detail).

### Fast-Fail Rules (`orchestrator/fastfail.py`)

Pure functions that examine findings and return a recommended action. The orchestrator decides how to act on the recommendation.

**Rules in priority order:**

| Rule | Trigger | Action | Rationale |
|---|---|---|---|
| 1 | H-main refuted | `SKIP_TO_MERGE` | Mechanism doesn't work — skip to principle merge, proceed to findings gate |
| 2 | H-control-negative refuted | `REDESIGN` | Mechanism is confounded — it produces effects where it shouldn't |
| 3 | Dominant component >80% | `SIMPLIFY` | One component does all the work — drop the others |
| — | None of the above | `CONTINUE` | Proceed normally |

Rule 1 takes priority: if H-main is refuted, the control-negative result doesn't matter.

## Data Flow

### Within One Iteration

```
                    Planner (Opus)
                       │
                       ▼
              problem.md + bundle.yaml
                       │
                       ▼
              HUMAN_DESIGN_GATE (approve/reject/abort)
                       │
                       ▼
                  Executor (Sonnet)
                       │
                       ▼
         experiment_plan.yaml + execution_results.json
         + findings.json + principle_updates.json
                       │
                       ▼
                  VALIDATE (Python)
                       │
                       ▼
              principles.json (upsert by ID)
                       │
                       ▼
              HUMAN_FINDINGS_GATE (approve/reject/abort)
                       │
                       ▼
                     DONE
```

### Across Iterations

```
Iteration 1                    Iteration 2                    Iteration N
┌──────────────────┐          ┌──────────────────┐          ┌──────────────┐
│ Design           │          │ Design           │          │              │
│ Execute          │   ───▶   │  (constrained by │   ───▶   │   ...        │
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

`run_campaign.py` loops through iterations:

```
for i in 1..max_iterations:
  ┌───────────────────────────────────────────────────────────┐
  │  run_iteration(iteration=i)                               │
  │    DESIGN → HUMAN_DESIGN_GATE → EXECUTE_ANALYZE           │
  │    → VALIDATE → HUMAN_FINDINGS_GATE → DONE                │
  └─────────────────────┬─────────────────────────────────────┘
                        │
                  (if not final)
                        │
              append_ledger_row(i)
                        │
              engine.transition("DESIGN")
                  (increments iteration counter)
                        │
                    next iteration
                  (principles injected into design prompt)
```

The deterministic ledger (`orchestrator/ledger.py`) appends one row per iteration with prediction accuracy and principle changes, without any LLM calls.

## Schema Contracts

Every artifact exchanged between components is validated against a JSON Schema (Draft 2020-12). This ensures agents produce well-formed output and makes the system testable without LLMs.

| Schema | Format | Governs |
|---|---|---|
| `campaign.schema.yaml` | YAML | Campaign configuration (target system, prompt layers) |
| `state.schema.json` | JSON | Orchestrator checkpoint (phase, iteration, run_id, config_ref) |
| `bundle.schema.yaml` | YAML | Hypothesis bundles (arms with predictions, mechanisms, diagnostics) |
| `experiment_plan.schema.yaml` | YAML | Experiment plans (exact commands per arm/condition) |
| `findings.schema.json` | JSON | Prediction-vs-outcome tables with error classification |
| `investigation_summary.schema.json` | JSON | Bounded iteration summary for cross-iteration context |
| `principles.schema.json` | JSON | Principle store (statement, confidence, regime, evidence, category, status) |
| `ledger.schema.json` | JSON | Append-only iteration log with prediction accuracy and domain metrics |
| `summary.schema.json` | JSON | Campaign rollup (cost, tokens, principles extracted) |
| `trace.schema.json` | JSON | Observability events (LLM calls, state transitions, gate decisions) |

The bundle and campaign schemas use YAML format because they contain free-text fields that are more readable in YAML. All other schemas use JSON.

## Human Review

Automated AI reviews (DESIGN_REVIEW, FINDINGS_REVIEW) have been removed. Quality control is now handled by:

1. **HUMAN_DESIGN_GATE** — the human reviews the hypothesis bundle directly after DESIGN
2. **HUMAN_FINDINGS_GATE** — the human reviews findings and principle updates after VALIDATE

This removes the multi-perspective automated review overhead while keeping humans in the loop at both decision points.

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
- **Idempotent principle merge:** The VALIDATE step reads the existing `principles.json`, upserts principles by ID, and writes back. Re-running for the same iteration produces a duplicate (detectable by ID) rather than corruption.

## Extending Nous

### Using a Different Dispatcher

Nous ships with two dispatchers:

- `StubDispatcher` — deterministic stubs for testing
- `CLIDispatcher` — real agent calls via `claude -p`

To create a custom dispatcher, implement the `Dispatcher` protocol from `orchestrator/protocols.py`. Your dispatcher must produce artifacts that pass schema validation — the orchestrator trusts the schema contract, not the content.

### Adding a New Arm Type

1. Add the type to the `enum` in `schemas/bundle.schema.yaml` (arm type) and `schemas/findings.schema.json` (arm_type)
2. Update `orchestrator/fastfail.py` if the new arm type has fast-fail implications
3. Add test cases to `tests/test_schemas.py` and `tests/test_fastfail.py`

### Adding a New Fast-Fail Rule

1. Add a new `FastFailAction` enum value
2. Add the rule to `check_fast_fail()` with appropriate priority ordering
3. Add test cases covering the rule and its interaction with existing rules
