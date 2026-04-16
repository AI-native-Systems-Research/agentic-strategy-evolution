# Data Model Guide

Nous uses 8 schema-governed artifacts to drive the investigation loop. This guide explains each one in plain English.

## How They Fit Together

`campaign.yaml` describes the target system and configures the reviewer panel. `state.json` drives the loop. Each iteration produces a `bundle.yaml` (experiment plan) and `findings.json` (results). The `ledger.json` records what happened. `principles.json` accumulates knowledge across iterations. `trace.jsonl` logs everything. `summary.json` wraps it all up at the end.

```
campaign.yaml       "What system?"          Target system, reviewers, prompts
    │
    ▼
state.json          "Where are we?"         Drives the loop
    │
    ▼
bundle.yaml         "What are we testing?"  Experiment plan for this iteration
    │
    ▼
findings.json       "What happened?"        Prediction vs outcome, arm by arm
    │
    ├──▶ ledger.json       "What happened each iteration?"  Append-only history
    ├──▶ principles.json   "What have we learned?"          Living knowledge base
    └──▶ trace.jsonl       "What happened under the hood?"  Activity log
                                                             │
                                                             ▼
                                              summary.json   "How did the campaign go?"
                                                             Final report card
```

## 0. campaign.yaml — "What system are we investigating?"

**Schema:** `schemas/campaign.schema.yaml`

The campaign configuration. Describes the target system, configures the reviewer panel, and points to prompt layers. Created once during setup (with Claude assistance) and referenced by `state.json` via `config_ref`.

| Section | What it configures |
|---|---|
| `target_system.name` / `description` | What system Nous is investigating |
| `target_system.observable_metrics` | What you can measure (latency, throughput, error rate, etc.) |
| `target_system.controllable_knobs` | What you can change (algorithms, configs, resource limits) |
| `review.design_perspectives` | Reviewer perspectives for design review (default: 5) |
| `review.findings_perspectives` | Reviewer perspectives for findings review (default: 10) |
| `review.max_review_rounds` | Maximum convergence rounds per gate |
| `prompts.methodology_layer` | Path to generic Nous methodology prompts |
| `prompts.domain_adapter_layer` | Path to domain-specific prompt overrides (null until generated) |

The template ships with 5 design perspectives (statistical rigor, causal sufficiency, confound risk, generalization, mechanism clarity). Campaigns may use fewer or more depending on the domain — the schema requires at least 1.

## 1. state.json — "Where are we right now?"

**Schema:** `schemas/state.schema.json`

A bookmark. It tells the orchestrator what phase we're in, which iteration we're on, and what we're investigating. If the process crashes, it resumes from here.

| Field | What it means |
|---|---|
| `phase` | Which step of the loop (INIT, FRAMING, DESIGN, DESIGN_REVIEW, HUMAN_DESIGN_GATE, RUNNING, FINDINGS_REVIEW, HUMAN_FINDINGS_GATE, TUNING, EXTRACTION, DONE) |
| `iteration` | How many times we've gone around the loop (0 = haven't started yet) |
| `run_id` | A name for this campaign |
| `family` | What mechanism we're currently exploring (e.g., "routing-signals") |
| `timestamp` | When this was last updated |
| `config_ref` | Path to the campaign configuration file (null before setup) |

The orchestrator writes this atomically (temp file + rename) so a crash never leaves a corrupt checkpoint.

## 2. ledger.json — "What happened in each iteration?"

**Schema:** `schemas/ledger.schema.json`

A log book. One row per completed experiment. Append-only — never edited, only added to. This is how you look back and see the full history of a campaign.

Each row records:

| Field | What it means |
|---|---|
| `iteration` / `family` / `timestamp` | Which experiment, when |
| `candidate_id` | What strategy was tested |
| `h_main_result` | Did the main hypothesis work? (CONFIRMED / REFUTED / PARTIALLY_CONFIRMED) |
| `ablation_results` | Did each component matter individually? |
| `control_result` | Did the negative control pass? (proves mechanism, not noise) |
| `robustness_result` | Does it hold under different conditions? |
| `prediction_accuracy` | How many arms did we predict correctly? (e.g., 4/6 = 66.7%) |
| `principles_extracted` | What principles were added, updated, or pruned this iteration |
| `frontier_update` | What should we explore next? |
| `domain_metrics` | Optional domain-specific metrics (e.g., memory usage, compilation time) |

## 3. principles.json — "What have we learned?"

**Schema:** `schemas/principles.schema.json`

The knowledge base. A living list of reusable lessons extracted from experiments. Each principle can be added, refined, or retired as new evidence comes in. This is what makes knowledge compound — principles from iteration N constrain iteration N+1.

Each principle has:

| Field | What it means |
|---|---|
| `id` | Unique identifier (e.g., "RP-1", "S-3") |
| `statement` | The insight (e.g., "SLO-gated admission control is non-zero-sum at saturation") |
| `confidence` | low / medium / high |
| `regime` | When does this apply? (e.g., "arrival_rate > 50% capacity") |
| `evidence` | Which experiments support this |
| `mechanism` | Why does it work? |
| `contradicts` | Which other principles disagree with this one |
| `extraction_iteration` | Which iteration produced this principle |
| `applicability_bounds` | Conditions under which this principle holds |
| `category` | domain (about the target system) or meta (about the investigation process) |
| `status` | active (in use), updated (refined), or pruned (retired) |
| `superseded_by` | If pruned, what replaced it |

**Operations:** Insert (new principle), Update (refine scope or confidence), Prune (mark as superseded or refuted).

## 4. bundle.yaml — "What are we testing this iteration?"

**Schema:** `schemas/bundle.schema.yaml`

The experiment plan. A set of hypotheses ("arms") designed together to test one mechanism. Each arm is a bet: "I predict X will happen because of Y, and if I'm wrong, check Z."

**Metadata:** iteration number, mechanism family, research question.

**Arms** — one or more of:

| Arm type | Question it answers |
|---|---|
| `h-main` | Does the mechanism work? (the primary hypothesis) |
| `h-ablation` | Does each component matter on its own? |
| `h-super-additivity` | Do the components together do more than the sum of parts? |
| `h-control-negative` | At low load, the strategy should have no effect (proves mechanism, not noise) |
| `h-robustness` | Does it hold across different workloads? |

Each arm is a triple: **prediction** (quantitative claim), **mechanism** (causal explanation), **diagnostic** (what to investigate if wrong). Arms may also carry an optional **metadata** object for domain-specific extensions.

## 5. findings.json — "What actually happened?"

**Schema:** `schemas/findings.schema.json`

The experiment results. Compares what we predicted to what we observed, arm by arm. This is what the fast-fail logic reads to decide whether to stop early.

| Field | What it means |
|---|---|
| `iteration` / `bundle_ref` | Which experiment this is for |
| `arms[]` | One entry per arm tested |
| `arms[].predicted` vs `arms[].observed` | What we expected vs what happened |
| `arms[].status` | CONFIRMED / REFUTED / PARTIALLY_CONFIRMED |
| `arms[].error_type` | If wrong: direction (opposite effect), magnitude (right direction, wrong amount), or regime (different conditions behave differently) |
| `arms[].diagnostic_note` | What we learned from the failure |
| `discrepancy_analysis` | Overall explanation of what went wrong/right |
| `arms[].metadata` | Optional domain-specific data attached to the arm result |
| `dominant_component_pct` | If one component accounts for >80% of the effect, triggers simplification |

**Fast-fail rules** read this artifact:
- H-main refuted → skip remaining arms, go to EXTRACTION
- H-control-negative refuted → mechanism confounded, go back to DESIGN
- Dominant component >80% → simplify the strategy

## 6. trace.jsonl — "What happened under the hood?"

**Schema:** `schemas/trace.schema.json`

An activity log. One JSON line per event — every LLM call, tool invocation, state transition, and gate decision. Used for debugging and cost tracking after a campaign.

| Field | What it means |
|---|---|
| `timestamp` / `run_id` | When and which campaign |
| `event_type` | `llm_call`, `tool_call`, `state_transition`, or `gate_decision` |
| `payload` | Event-specific details (tokens used, from/to state, approval decision, etc.) |

Phase 1 defines the envelope; Phase 4 will tighten per-event-type payload schemas.

## 7. summary.json — "How did the whole campaign go?"

**Schema:** `schemas/summary.schema.json`

The final report card, generated at the end of a campaign. Rolls everything into top-level stats.

| Field | What it means |
|---|---|
| `total_cost_usd` / `total_tokens` | How much it cost |
| `total_iterations` | How many times around the loop |
| `cost_by_phase` | Where the money went (DESIGN vs RUNNING, etc.) |
| `per_iteration_stats` | Cost and result for each iteration |
| `mechanism_families_investigated` | What areas were explored |
| `principles_inserted` / `updated` / `pruned` | Knowledge base changes |
| `final_principle_count` | How many active principles at the end |
