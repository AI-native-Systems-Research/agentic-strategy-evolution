# Nous Protocol

A domain-agnostic methodology for hypothesis-driven experimentation on software systems using AI agents.

## Overview

Nous is a framework that runs the scientific method on software systems. Two properties make it work:

1. **Hypothesis-driven experimentation** — the agent forms a falsifiable claim, designs a controlled experiment to test it, and learns from the outcome either way. Refuted hypotheses are as valuable as confirmed ones.
2. **Compounding knowledge** — principles extracted from iteration N constrain the design space of iteration N+1. The system gets smarter over time.

The framework consists of a deterministic orchestrator (not an LLM) that drives two AI agent roles through a structured 7-phase loop with 2 LLM calls and 2 human gates per iteration, producing schema-governed artifacts at each stage.

## Preconditions

All four preconditions must hold for a system to be investigated with Nous:

| Precondition | What it means |
|---|---|
| **Observable metrics** | The system produces measurable outputs (latency, throughput, error rate, utilization). |
| **Controllable policy space** | There are knobs to turn — algorithms, configurations, scheduling policies, routing rules, resource limits. |
| **Reproducible execution** | A simulator, testbed, or staging environment exists with controlled conditions and multiple seeds. |
| **Decomposable mechanisms** | System behavior arises from interacting components that can be reasoned about individually. |

## The Iteration Loop

Each iteration follows 6 phases: INIT → DESIGN → HUMAN_DESIGN_GATE → EXECUTE_ANALYZE → HUMAN_FINDINGS_GATE → DONE.

Two LLM calls per iteration (both via `claude -p`): Opus for DESIGN, Sonnet for EXECUTE_ANALYZE. Both agents write artifacts directly to the campaign directory and run `nous validate` before claiming done. The orchestrator runs a post-check after each agent as a safety net.

### DESIGN (Planner, Opus)

The Planner agent explores the target system, validates assumptions, then produces three artifacts:

**Problem framing** (`problem.md`):
- Research question — what mechanism or behavior is under investigation
- Baseline — current system behavior without intervention, with metrics
- Experimental conditions — input characteristics, scale parameters, environment configuration
- Success criteria — quantitative thresholds for success
- Constraints — what cannot be changed (resource limits, SLOs, compatibility)
- Prior knowledge — relevant principles from earlier iterations

**Hypothesis bundle** (`bundle.yaml`):
The agent decomposes the investigation into a structured set of falsifiable predictions — a hypothesis bundle.

**Handoff** (`handoff_snapshot.md`):
A structured context document for the executor and the next iteration's designer. Contains key discoveries, code map, dead ends, exclusion reasoning, and current status. This is a living document — each iteration's designer reads the previous handoff and curates it (keeps relevant entries, removes outdated ones, adds new findings).

The agent runs `nous validate design` before finishing. If validation fails, it reads the errors and fixes the artifacts.

### HUMAN_DESIGN_GATE

Human approval gate (hard stop). The human sees the hypothesis bundle. If the human rejects, the Planner revises (loops back to DESIGN). If approved, the bundle advances to execution.

### EXECUTE_ANALYZE (Executor, Sonnet)

A single `claude -p` session handles the entire execution pipeline:

1. Reads the designer's handoff — uses validated commands and code map instead of re-exploring
2. Creates any input files needed by commands (configs, workloads) in `inputs/`
3. Writes `experiment_plan.yaml` with exact commands per arm (plan first, execute second)
4. Creates patches for code-change arms (evolve mode), saves to `patches/`
5. Runs the plan in an isolated git worktree, writes results to `results/`
6. Compares observed metrics against predictions
7. Writes `findings.json` and `principle_updates.json`
8. Runs `nous validate execution` — retries until all artifacts pass

All file paths (inputs, outputs) use absolute paths to the campaign directory so they persist after worktree cleanup.

**Key artifacts:**
- `experiment_plan.yaml` — exact commands per arm
- `execution_results.json` — stdout/stderr/metrics per condition
- `findings.json` — prediction vs outcome comparison
- `principle_updates.json` — proposed principle inserts/updates/prunes

### HUMAN_FINDINGS_GATE

Human approval gate. The human sees findings and principle updates. If the human rejects, execution loops back to EXECUTE_ANALYZE. If approved, the iteration completes.

### DONE → Next Iteration

After DONE, the orchestrator transitions to DESIGN (incrementing the iteration counter) for the next iteration. Principles from iteration N constrain the design space of iteration N+1.

Refuted predictions are the most valuable source of principles — they reveal where the model of the system was wrong.

## Hypothesis Bundles

A bundle is a structured set of **arms**, each a *(prediction, mechanism, diagnostic)* triple:

- **Prediction** — a quantitative claim with a measurable success/failure threshold
- **Mechanism** — a causal explanation of how/why the predicted effect occurs
- **Diagnostic** — what to investigate if the prediction is wrong

### Arm Types

| Arm | Tests | Purpose |
|---|---|---|
| **H-main** | Does the mechanism work, and why? | Primary hypothesis — predicted effect + causal explanation |
| **H-ablation** | Which components matter? | One arm per component — tests individual contribution |
| **H-super-additivity** | Do components interact non-linearly? | Tests whether compound effect exceeds sum of parts |
| **H-control-negative** | Where should the effect vanish? | Confirms mechanism specificity by testing a regime where it should not help |
| **H-robustness** | Does it generalize? | Tests across workloads, resources, and scale |

### Bundle Sizing Rules

| Iteration type | Required arms | Optional |
|---|---|---|
| New compound mechanism (>=2 components) | H-main, all H-ablation, H-super-additivity, H-control-negative | H-robustness |
| Component removal/simplification | H-main, H-control-negative, removal ablation | H-robustness |
| Single-component mechanism | H-main, H-control-negative | H-robustness |
| Parameter-only change | H-main only | — |
| Robustness sweep (post-confirmation) | H-robustness arms only | — |

## Prediction Error Taxonomy

When a prediction is wrong, the error type determines what the system learns:

| Error type | Meaning | Action |
|---|---|---|
| **Direction wrong** | Fundamental misunderstanding of the mechanism | Prune or heavily revise the principle |
| **Magnitude wrong** | Correct mechanism, inaccurate model of strength | Update principle with calibrated bounds |
| **Regime wrong** | Mechanism works under different conditions than predicted | Update principle with correct regime boundaries |

Direction errors are the most serious — they indicate the causal model is fundamentally flawed. Magnitude and regime errors refine understanding without invalidating the mechanism.

## Principle Extraction

The principle store is a living knowledge base. Each principle records:
- **Statement** — what the principle claims
- **Confidence** — low, medium, or high based on evidence strength
- **Regime** — conditions under which the principle holds
- **Evidence** — links to the iterations and arms that established it
- **Mechanism** — the causal explanation underlying the principle
- **Category** — domain (about the target system) or meta (about the investigation process)
- **Status** — active, updated, or pruned

Principles are hard constraints on subsequent iterations. The Planner must not design bundles that contradict active principles without explicit justification.

## Human Gates

Two hard stops require explicit human approval:

1. **HUMAN_DESIGN_GATE** (after DESIGN) — the human sees the hypothesis bundle, then approves, rejects (→ DESIGN), or aborts the campaign.
2. **HUMAN_FINDINGS_GATE** (after EXECUTE_ANALYZE) — the human sees findings and principle updates, then approves (→ DONE), rejects (→ EXECUTE_ANALYZE), or aborts.

Human gates cannot be bypassed. They are the mechanism by which domain expertise enters the loop.

## Stopping Criteria

A campaign stops when:
- The `--max-iterations` limit is reached (default: 10, configurable via CLI flag or `max_iterations` in `campaign.yaml`)
- The human aborts at any gate
- Consecutive iterations produce null or marginal results (no new principles extracted)
- The human decides the research question has been sufficiently answered
- The principle store has stabilized (no inserts, updates, or prunes for N iterations)

## Orchestrator

The orchestrator is a Python state machine — NOT an LLM. It owns:
- Phase transitions between 6 states
- Checkpoint/resume via `state.json`
- Agent dispatch (invoke `claude -p` agents with structured prompts)
- Gate logic (pause for human approval)

### State Machine

```
INIT -> DESIGN -> HUMAN_DESIGN_GATE -> EXECUTE_ANALYZE -> HUMAN_FINDINGS_GATE -> DONE

Backward/looping transitions:
  HUMAN_DESIGN_GATE -> DESIGN           (human rejects)
  HUMAN_FINDINGS_GATE -> EXECUTE_ANALYZE (human rejects)
  DONE -> DESIGN                        (next iteration, increments counter)
```

### Agent Roles

| Role | Phase | Reads | Writes | Model |
|---|---|---|---|---|
| Planner | DESIGN | campaign, principles | `problem.md`, `bundle.yaml` | Opus |
| Executor | EXECUTE_ANALYZE | bundle, problem | `experiment_plan.yaml`, `execution_results.json`, `findings.json`, `principle_updates.json` | Sonnet |

### File Layout

```
campaign-dir/
  campaign.yaml       — campaign configuration (target system, prompts)
  state.json          — investigation checkpoint
  ledger.json         — append-only iteration log
  principles.json     — living principle store
  runs/
    iter-N/
      problem.md      — problem framing
      bundle.yaml     — hypothesis bundle
      experiment_plan.yaml — exact commands per arm
      execution_results.json — stdout/stderr/metrics per condition
      findings.json    — prediction vs outcome
      principle_updates.json — proposed principle changes
      gate_summary_*.json — human-readable gate summaries
```

## Cross-Iteration Context

Each iteration's designer produces a `handoff.md` that captures the exploration context: key discoveries, code map, dead ends, exclusion reasoning, evolution of thinking, and current status. This handoff serves two audiences:

1. The **executor agent** in the same iteration — operational context for running experiments
2. The **designer agent** in the next iteration — exploration context to avoid re-discovering what's already known

The next iteration's Design prompt receives the previous `handoff.md` and `findings.json` directly — no intermediate summarization step. This gives the designer raw access to what was learned rather than a lossy summary.

The full ledger (`ledger.json`) remains on disk for audit and analysis but is not passed to agents. The deterministic ledger module (`orchestrator/ledger.py`) appends one row per iteration with prediction accuracy and principle changes, without any LLM calls.
