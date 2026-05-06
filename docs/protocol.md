# Nous Protocol

A domain-agnostic methodology for hypothesis-driven experimentation on software systems using AI agents.

## Overview

Nous is a framework that runs the scientific method on software systems. Two properties make it work:

1. **Hypothesis-driven experimentation** — the agent forms a falsifiable claim, designs a controlled experiment to test it, and learns from the outcome either way. Refuted hypotheses are as valuable as confirmed ones.
2. **Compounding knowledge** — principles extracted from iteration N constrain the design space of iteration N+1. The system gets smarter over time.

The framework consists of a deterministic orchestrator (not an LLM) that drives four AI agent roles through a structured 4-phase loop, producing schema-governed artifacts at each stage.

## Preconditions

All four preconditions must hold for a system to be investigated with Nous:

| Precondition | What it means |
|---|---|
| **Observable metrics** | The system produces measurable outputs (latency, throughput, error rate, utilization). |
| **Controllable policy space** | There are knobs to turn — algorithms, configurations, scheduling policies, routing rules, resource limits. |
| **Reproducible execution** | A simulator, testbed, or staging environment exists with controlled conditions and multiple seeds. |
| **Decomposable mechanisms** | System behavior arises from interacting components that can be reasoned about individually. |

## The 4-Phase Loop

Each iteration follows four phases:

### Phase 1: Design (Problem Framing + Hypothesis Bundle)

The Planner agent performs both problem framing and hypothesis design in a single step. It explores the target system, validates assumptions, then produces two artifacts:

**Problem framing** (`problem.md`):
- Research question — what mechanism or behavior is under investigation
- Baseline — current system behavior without intervention, with metrics
- Experimental conditions — input characteristics, scale parameters, environment configuration
- Success criteria — quantitative thresholds for success
- Constraints — what cannot be changed (resource limits, SLOs, compatibility)
- Prior knowledge — relevant principles from earlier iterations

**Hypothesis bundle** (`bundle.yaml`):
The agent decomposes the investigation into a structured set of falsifiable predictions — a hypothesis bundle.

A bundle passes through:
1. AI Design Review (default: 5 independent perspectives, configurable per campaign via `campaign.yaml`)
2. Human Approval Gate (hard stop — human sees bundle + review summaries)

If the human rejects, the Planner revises. If approved, the bundle advances to execution.

### Phase 2: Plan, Execute, and Analyze

Execution is split into three checkpointable sub-phases:

**PLAN_EXECUTION** — The Executor agent (via `claude -p` with shell access) receives the approved hypothesis bundle and produces `experiment_plan.yaml` — a structured plan with exact shell commands per arm. The agent explores the target repo, discovers build commands, and designs reproducible experiment conditions.

**EXECUTING** — The Python orchestrator runs the commands from `experiment_plan.yaml` deterministically via `subprocess.run()`. No LLM calls. Stdout/stderr are captured per condition. If a command fails, an optional revision callback asks the LLM to correct the plan (max 3 retries). Results are written to `execution_results.json`.

**ANALYSIS** — The LLM API receives the execution results and compares observed metrics against predictions to produce `findings.json`.

When `repo_path` is set, PLAN_EXECUTION and EXECUTING run in an isolated git worktree. The worktree ID is persisted to `.experiment_id` for crash recovery.

**Key artifacts:**
- `experiment_plan.yaml` — exact commands per arm (PLAN_EXECUTION output)
- `execution_results.json` — stdout/stderr/metrics per condition (EXECUTING output)
- `findings.json` — prediction vs outcome comparison (ANALYSIS output)

Findings pass through:
1. AI Findings Review (default: 10 independent perspectives, configurable per campaign via `campaign.yaml`)
2. Human Approval Gate

The ledger records one row per completed iteration, including prediction accuracy.

### Phase 3: Bayesian Parameter Optimization

For confirmed mechanisms only. The protocol calls for Gaussian process optimization over the parameter space (e.g., 30-50 evaluations per strategy across 3+ seeds). This separates mechanism design (Phase 2) from parameter tuning, ensuring fair comparisons.

If H-main was refuted, this phase is skipped entirely (fast-fail).

### Phase 4: Principle Extraction and Iteration

The Extractor agent updates the principle store:
- **Insert** — add a new principle from confirmed or refuted findings
- **Update** — refine an existing principle's scope, confidence, or parameters
- **Prune** — mark a principle as superseded or refuted by new evidence

Refuted predictions are the most valuable source of principles — they reveal where the model of the system was wrong.

After extraction, the human decides: continue to the next iteration or stop the campaign.

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

## Review Protocol

### Multi-Perspective Review

Reviews run N independent perspectives in parallel. Each perspective examines the artifact from a different angle (e.g., statistical rigor, causal sufficiency, confound risk, generalization coverage, mechanism clarity).

### Convergence Gating

Reviews follow a convergence protocol:
1. Run all perspectives in parallel
2. Collect findings with severity levels: CRITICAL, IMPORTANT, SUGGESTION
3. If zero CRITICAL findings: advance to the human gate
4. If any CRITICAL findings: return to the authoring agent for revision
5. Re-run the full review after revision
6. Maximum 10 rounds per gate

SUGGESTION-level items do not block advancement. Only CRITICAL findings block the gate. IMPORTANT findings are surfaced to the human reviewer but do not prevent advancement to the gate.

> **Note:** The perspective counts (5 for design, 10 for findings) and the 10-round maximum are configurable defaults, set per campaign in `campaign.yaml`. The Phase 1 orchestrator skeleton dispatches reviews individually; enforcement of these counts is deferred to Phase 2 (agent prompts).

### Review Gates

| Gate | Perspectives | Reviews | Blocks on |
|---|---|---|---|
| Design Review | 5 (default) | After bundle design | Any CRITICAL finding |
| Findings Review | 10 (default) | After experiment execution | Any CRITICAL finding |

## Human Gates

Three hard stops require explicit human approval:

1. **Design Approval** (after Design Review) — the human sees the hypothesis bundle and all review summaries, then approves, rejects, or aborts the campaign.
2. **Findings Approval** (after Findings Review) — the human sees the findings and all review summaries, then approves, rejects, or aborts.
3. **Continue Gate** (after Extraction, multi-iteration only) — the human decides whether to continue to the next iteration or stop the campaign. This gate only appears when using `run_campaign.py`.

Human gates cannot be bypassed. They are the mechanism by which domain expertise enters the loop.

## Fast-Fail Rules

The orchestrator enforces three rules to avoid wasted work:

1. **H-main refuted** — skip remaining ablation/robustness arms, go directly to Principle Extraction. The mechanism does not work; running more arms is pointless.
2. **H-control-negative fails** — the mechanism is confounded (it produces effects where it should not). Return to Design for a revised bundle.
3. **Single dominant component (>80% of total effect)** — simplify the strategy by dropping minor components. The compound mechanism adds complexity without proportional benefit.

## Stopping Criteria

A campaign stops when:
- The `--max-iterations` limit is reached (default: 10, configurable via CLI flag or `max_iterations` in `campaign.yaml`)
- The human chooses to stop at the continue gate after any iteration
- Consecutive iterations produce null or marginal results (no new principles extracted)
- The human decides the research question has been sufficiently answered
- The principle store has stabilized (no inserts, updates, or prunes for N iterations)

## Orchestrator

The orchestrator is a Python state machine — NOT an LLM. It owns:
- Phase transitions between 11 states
- Checkpoint/resume via `state.json`
- Agent dispatch (invoke LLM agents with structured prompts)
- Gate logic (pause for human approval)
- Fast-fail enforcement

### State Machine

```
INIT -> DESIGN -> DESIGN_REVIEW -> HUMAN_DESIGN_GATE
  -> PLAN_EXECUTION -> EXECUTING -> ANALYSIS
  -> FINDINGS_REVIEW -> HUMAN_FINDINGS_GATE
  -> TUNING (if H-main confirmed) or EXTRACTION (if refuted)
  -> EXTRACTION -> DESIGN (next iteration) or DONE

Backward/looping transitions:
  DESIGN_REVIEW -> DESIGN              (CRITICAL findings in review)
  HUMAN_DESIGN_GATE -> DESIGN          (human rejects)
  FINDINGS_REVIEW -> PLAN_EXECUTION    (CRITICAL findings in review)
  HUMAN_FINDINGS_GATE -> PLAN_EXECUTION (human rejects)
  EXTRACTION -> DESIGN                 (next iteration, increments counter)
```

### Agent Roles

| Role | Phases | Reads | Writes | Shell |
|---|---|---|---|---|
| Planner | Design | all | `problem.md`, `bundle.yaml` | yes (via CLI) |
| Executor | Plan-Execution, Analyze | bundle, problem, exec results | `experiment_plan.yaml`, `findings.json` | yes (plan-execution) |
| Reviewer | Design Review, Findings Review | all | `review-*.md` | — |
| Extractor | Extract, Summarize | all | `principles.json`, `investigation_summary.json` | — |

### File Layout

```
campaign-dir/
  campaign.yaml       — campaign configuration (target system, reviewers, prompts)
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
      investigation_summary.json — bounded iteration summary
      gate_summary_*.json — human-readable gate summaries
      reviews/        — multi-perspective reviews
  trace.jsonl         — observability log
  summary.json        — campaign rollup (generated at end)
```

## Investigation Summary

After each non-final Extraction phase, the Extractor produces a bounded investigation summary (`investigation_summary.json`). This summary captures:

- **What was tested** — the hypothesis family and arms
- **Key findings** — what was confirmed, refuted, or unexpected
- **Principles changed** — which principles were inserted, updated, or pruned
- **Open questions** — what remains unanswered
- **Suggested next direction** — where the next iteration should focus

The next iteration's Design prompt receives this summary alongside the active principles and campaign context. This keeps agent context at O(summary) regardless of campaign depth — the Planner does not need to read the full history of all prior iterations.

The full ledger (`ledger.json`) remains on disk for audit and analysis but is not passed to agents. The deterministic ledger module (`orchestrator/ledger.py`) appends one row per iteration with prediction accuracy and principle changes, without any LLM calls.
