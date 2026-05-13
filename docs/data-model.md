# Data Model Guide

Nous uses 11 schema-governed artifacts to drive the investigation loop. This guide explains each one in plain English.

## How They Fit Together

`campaign.yaml` describes the target system. `state.json` drives the loop. Each iteration produces a `bundle.yaml` (hypothesis bundle), `experiment_plan.yaml` (exact commands), `execution_results.json` (raw output), `findings.json` (analysis), and `principle_updates.json` (proposed principle changes). The `ledger.json` records what happened. `principles.json` accumulates knowledge across iterations.

```
campaign.yaml       "What system?"          Target system, prompts
    │
    ▼
state.json          "Where are we?"         Drives the loop
    │
    ▼
bundle.yaml         "What are we testing?"  Hypothesis bundle for this iteration
    │                                        ▲
    ▼                                        │ (injected into design prompt)
experiment_plan.yaml "How to run it?"         Exact commands per arm
    │                                        │
    ▼                                        │
execution_results.json "Raw output"          Stdout/stderr per condition
    │                                        │
    ▼                                        │
findings.json       "What happened?"         │
    │                                        │
    ├──▶ ledger.json                 handoff.md
    │       "What happened each iteration?"  "What does the next agent need?"
    │                                        Exploration context for next iteration
    └──▶ principles.json   "What have we learned?"   Living knowledge base
```

## 0. campaign.yaml — "What system are we investigating?"

**Schema:** `schemas/campaign.schema.yaml`

The campaign configuration. Describes the target system and points to prompt layers. Created once during setup (with Claude assistance) and referenced by `state.json` via `config_ref`.

| Section | What it configures |
|---|---|
| `research_question` | The guiding research question for this campaign |
| `target_system.name` / `description` | What system Nous is investigating |
| `target_system.observable_metrics` | (Optional) What agents can measure — provided as hints, or discovered from code |
| `target_system.controllable_knobs` | (Optional) What agents can change — provided as hints, or discovered from code |
| `target_system.repo_path` | (Optional) Path to target system git repo — enables code-access agents and worktree isolation |
| `review` | (Legacy, unused) Automated review configuration |
| `prompts.methodology_layer` | Path to generic Nous methodology prompts |
| `prompts.domain_adapter_layer` | Path to domain-specific prompt overrides (null until generated) |


## 1. state.json — "Where are we right now?"

**Schema:** `schemas/state.schema.json`

A bookmark. It tells the orchestrator what phase we're in, which iteration we're on, and what we're investigating. If the process crashes, it resumes from here.

| Field | What it means |
|---|---|
| `phase` | Which step of the loop (INIT, DESIGN, HUMAN_DESIGN_GATE, EXECUTE_ANALYZE, HUMAN_FINDINGS_GATE, DONE) |
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

Each arm is a triple: **prediction** (quantitative claim), **mechanism** (causal explanation), **diagnostic** (what to investigate if wrong). Arms may also carry optional **code_changes** (file/intent/rationale triples describing what code to modify) and a **metadata** object for domain-specific extensions.

## 4b. experiment_plan.yaml — "What commands to run?"

**Schema:** `schemas/experiment_plan.schema.yaml`

The experiment plan. Produced by the executor during EXECUTE_ANALYZE. Contains exact shell commands to run for each arm, making experiments reproducible and auditable.

| Section | What it means |
|---|---|
| `metadata.iteration` | Which iteration this plan is for |
| `metadata.bundle_ref` | Path to the hypothesis bundle this plan implements |
| `setup[]` | Optional setup commands (build, install, etc.) |
| `arms[].arm_id` | Which hypothesis arm |
| `arms[].conditions[].name` | Condition name (e.g., "baseline-seed42") |
| `arms[].conditions[].cmd` | Exact shell command to execute |
| `arms[].conditions[].output` | Optional: path to output file to capture |
| `arms[].conditions[].inputs` | Optional: array of input file paths created by the agent |
| `arms[].conditions[].description` | Optional human description |

Located at `runs/iter-N/experiment_plan.yaml`. The agent writes the plan first, then executes it. All output paths use absolute paths to `runs/iter-N/results/` so files persist after worktree cleanup.

## 4b2. patches/ — "What code changes were made?"

Directory at `runs/iter-N/patches/`. Only present in evolve mode (when bundle arms have `code_changes`). Each file is a git diff named by arm type (e.g., `h-main.patch`). The agent creates patches, saves them here, and references them in the experiment plan.

## 4b3. inputs/ — "What input files did the agent create?"

Directory at `runs/iter-N/inputs/`. Contains agent-created input files needed by experiment commands (config files, workload specs, policy definitions). The agent writes these here instead of `/tmp/` so the experiment is reproducible. Referenced in the plan's `inputs` array per condition.

## 4b4. results/ — "What did the experiments produce?"

Directory at `runs/iter-N/results/`. Contains experiment output files organized by arm (e.g., `results/h-main/baseline-s42.json`). The agent writes results here using absolute paths so they survive worktree cleanup.

## 4c. execution_results.json — "What did the commands produce?"

No schema — internal artifact written during EXECUTE_ANALYZE.

Contains the raw output of every command from the experiment plan. Used within the same EXECUTE_ANALYZE session to produce findings.

| Section | What it means |
|---|---|
| `plan_ref` | Path to the experiment plan |
| `setup_results[]` | Output of setup commands (cmd, exit_code, stdout_tail, stderr_tail) |
| `arms[].arm_id` | Which arm |
| `arms[].conditions[].name` | Condition name |
| `arms[].conditions[].cmd` | Command that was run |
| `arms[].conditions[].exit_code` | 0 = success |
| `arms[].conditions[].stdout_tail` | Last 4000 chars of stdout |
| `arms[].conditions[].stderr_tail` | Last 4000 chars of stderr |
| `arms[].conditions[].output_content` | Content of output file (if specified in plan) |

Located at `runs/iter-N/execution_results.json`. Full stdout/stderr are also saved per condition at `runs/iter-N/results/<arm_id>/<name>.stdout` and `.stderr`.

## 5. findings.json — "What actually happened?"

**Schema:** `schemas/findings.schema.json`

The experiment results. Compares what we predicted to what we observed, arm by arm.

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


## 6. handoff.md — "What does the next agent need to know?"

Produced by the designer agent as part of its output. A structured context transfer document that serves two audiences: the executor agent in the same iteration and the designer agent in the next iteration.

| Section | What it captures |
|---|---|
| Goal | Actionable directive for the executor |
| Key Discoveries | 3-7 verified technical findings with measurements |
| System Interface | Validated build/run commands and output format |
| Code Map | Troubleshooting index: file:line, what's there, when to look |
| Code Targets | Per-arm patch locations (if code changes needed) |
| What I Tried That Didn't Work | Dead ends to avoid |
| What I Excluded and Why | Scoping decisions and rationale |
| Evolution of Thinking | How understanding shifted during exploration |
| Current Status | Validated / uncertain / suggested next |
| Warnings & Constraints | Gotchas with evidence |

The living document is at `handoff.md` (campaign root). Per-iteration snapshots are saved at `runs/iter-N/handoff_snapshot.md` for audit. The executor and next iteration's designer both read the campaign-level file.

## 6b. gate_summary_*.json — "What should I know before deciding?"

**Schema:** `schemas/gate_summary.schema.json`

A human-readable summary produced before each human gate. Designed to help the human make an approve/reject/abort decision without reading raw artifacts.

| Field | What it means |
|---|---|
| `gate_type` | Which gate: `design` or `findings` |
| `summary` | 1-3 sentence plain-language summary of what's being decided |
| `key_points` | Bullet points with specific numbers, metrics, and hypothesis references |

Located at `runs/iter-N/gate_summary_<type>.json`. Generated on the fly before each gate — not persisted across sessions.

## Dispatch and Prompt Templates

The orchestrator invokes agents through a dispatcher. Two implementations exist:

- `StubDispatcher` (`orchestrator/dispatch.py`) — produces deterministic, schema-valid artifacts without LLM calls. Used for testing.
- `CLIDispatcher` (`orchestrator/cli_dispatch.py`) — invokes `claude -p` as a subprocess, giving agents code access and shell tools. Used for both the planner (DESIGN, Opus) and executor (EXECUTE_ANALYZE, Sonnet) roles.

`CLIDispatcher` reads `campaign.yaml` at construction time and injects domain-specific context (target system name, metrics, knobs, active principles) into prompt templates from `prompts/methodology/`. The DESIGN phase produces both `problem.md` and `bundle.yaml` in a single dispatch — the raw output is split by `_split_design_output()` in `run_iteration.py`.

