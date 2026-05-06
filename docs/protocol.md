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

Each iteration follows 7 phases: INIT → DESIGN → HUMAN_DESIGN_GATE → EXECUTE_ANALYZE → VALIDATE → HUMAN_FINDINGS_GATE → DONE.

Two LLM calls per iteration (both via `claude -p`): Opus for DESIGN, Sonnet for EXECUTE_ANALYZE. VALIDATE and principle merge are Python-only.

### DESIGN (Planner, Opus)

The Planner agent explores the target system, validates assumptions, then produces two artifacts:

**Problem framing** (`problem.md`):
- Research question — what mechanism or behavior is under investigation
- Baseline — current system behavior without intervention, with metrics
- Experimental conditions — input characteristics, scale parameters, environment configuration
- Success criteria — quantitative thresholds for success
- Constraints — what cannot be changed (resource limits, SLOs, compatibility)
- Prior knowledge — relevant principles from earlier iterations

**Hypothesis bundle** (`bundle.yaml`):
The agent decomposes the investigation into a structured set of falsifiable predictions — a hypothesis bundle.

### HUMAN_DESIGN_GATE

Human approval gate (hard stop). The human sees the hypothesis bundle. If the human rejects, the Planner revises (loops back to DESIGN). If approved, the bundle advances to execution.

### EXECUTE_ANALYZE (Executor, Sonnet)

A single `claude -p` session handles the entire execution pipeline:

1. Receives the approved hypothesis bundle
2. Explores the target repo, discovers build commands
3. Produces `experiment_plan.yaml` with exact shell commands per arm
4. Runs the commands in an isolated git worktree, captures stdout/stderr per condition
5. Compares observed metrics against predictions
6. Produces `findings.json` and `principle_updates.json`

When `repo_path` is set, execution runs in an isolated git worktree. The worktree ID is persisted to `.experiment_id` for crash recovery.

**Key artifacts:**
- `experiment_plan.yaml` — exact commands per arm
- `execution_results.json` — stdout/stderr/metrics per condition
- `findings.json` — prediction vs outcome comparison
- `principle_updates.json` — proposed principle inserts/updates/prunes

### VALIDATE (Python-only)

The Python orchestrator:
1. Replays `experiment_plan.yaml` for reproducibility verification
2. Merges principle updates into `principles.json` by ID (upsert, no LLM)

The ledger records one row per completed iteration, including prediction accuracy.

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
2. **HUMAN_FINDINGS_GATE** (after VALIDATE) — the human sees findings and principle updates, then approves (→ DONE), rejects (→ EXECUTE_ANALYZE), or aborts.

Human gates cannot be bypassed. They are the mechanism by which domain expertise enters the loop.

## Fast-Fail Rules

The orchestrator enforces three rules to avoid wasted work:

1. **H-main refuted** — skip remaining ablation/robustness arms, proceed to principle merge and findings gate. The mechanism does not work; running more arms is pointless.
2. **H-control-negative fails** — the mechanism is confounded (it produces effects where it should not). Return to Design for a revised bundle.
3. **Single dominant component (>80% of total effect)** — simplify the strategy by dropping minor components. The compound mechanism adds complexity without proportional benefit.

## Stopping Criteria

A campaign stops when:
- The `--max-iterations` limit is reached (default: 10, configurable via CLI flag or `max_iterations` in `campaign.yaml`)
- The human aborts at any gate
- Consecutive iterations produce null or marginal results (no new principles extracted)
- The human decides the research question has been sufficiently answered
- The principle store has stabilized (no inserts, updates, or prunes for N iterations)

## Orchestrator

The orchestrator is a Python state machine — NOT an LLM. It owns:
- Phase transitions between 7 states
- Checkpoint/resume via `state.json`
- Agent dispatch (invoke `claude -p` agents with structured prompts)
- Gate logic (pause for human approval)
- Fast-fail enforcement

### State Machine

```
INIT -> DESIGN -> HUMAN_DESIGN_GATE -> EXECUTE_ANALYZE -> VALIDATE -> HUMAN_FINDINGS_GATE -> DONE

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
| Python | VALIDATE | experiment_plan, principle_updates | `principles.json` | — |

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
  trace.jsonl         — observability log
  summary.json        — campaign rollup (generated at end)
```

## Investigation Summary

After each non-final iteration, the orchestrator produces a bounded investigation summary (`investigation_summary.json`). This summary captures:

- **What was tested** — the hypothesis family and arms
- **Key findings** — what was confirmed, refuted, or unexpected
- **Principles changed** — which principles were inserted, updated, or pruned
- **Open questions** — what remains unanswered
- **Suggested next direction** — where the next iteration should focus

The next iteration's Design prompt receives this summary alongside the active principles and campaign context. This keeps agent context at O(summary) regardless of campaign depth — the Planner does not need to read the full history of all prior iterations.

The full ledger (`ledger.json`) remains on disk for audit and analysis but is not passed to agents. The deterministic ledger module (`orchestrator/ledger.py`) appends one row per iteration with prediction accuracy and principle changes, without any LLM calls.
