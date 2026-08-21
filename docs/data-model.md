# Data Model Guide

Nous drives the investigation loop through schema-governed artifacts on disk
(`orchestrator/schemas/`), plus a handful written without a JSON Schema of
their own. This guide explains each one in plain English. Sections 0-6b cover
the artifacts every campaign writes; section 7 covers the ones a
`kind: optimization` campaign adds, and notes which of those are
schema-governed and which are not.

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

A bookmark. It tells the orchestrator what phase we entered last, which iteration we're on, and what we're investigating. If the process crashes, it resumes from here.

| Field | What it means |
|---|---|
| `last_entered_phase` | The last phase the engine entered (INIT, PRE_WORK, DESIGN, CRITIC, HUMAN_DESIGN_GATE, EXECUTE_ANALYZE, HUMAN_FINDINGS_GATE, DONE). **Not** necessarily the currently active phase — see the caveat below (#236). |
| `iteration` | How many times we've gone around the loop (0 = haven't started yet) |
| `run_id` | A name for this campaign |
| `family` | What mechanism we're currently exploring (e.g., "routing-signals") |
| `timestamp` | When this was last updated (i.e., when `last_entered_phase` was last entered — *not* when an artifact was last written) |
| `config_ref` | Path to the campaign configuration file (null before setup) |
| `work_dir` | Absolute filesystem path to this campaign's work_dir, recorded at `setup_work_dir` (#239). Per-campaign source of truth; survives `NOUS_CAMPAIGN_PARENT` changes between runs. Machine-local — tools that travel state.json across machines must validate `Path(work_dir).exists()` before trusting it. Null before setup. |
| `repo_path` | Absolute path to the target system's repo, recorded at `setup_work_dir` (#239). Used for collision detection when `NOUS_CAMPAIGN_PARENT` is set (refusing to clobber a same-named campaign that targets a different repo) and to identify which target a campaign belongs to. Machine-local; null before setup or when authored without `target_system.repo_path`. |

The orchestrator writes this atomically (temp file + rename) so a crash never leaves a corrupt checkpoint.

**Entry-only semantics (#236).** `last_entered_phase` and `timestamp` are updated *only* when the engine transitions into a new phase. Artifact writes within a phase do not update them. So during a long phase, you'll see the entry-time values linger even though the phase is well underway and may have already produced artifacts. If you need a sub-second progress signal (e.g., for a status dashboard), watch the iteration artifact directory's mtimes (`runs/iter-N/*.json`, `runs/iter-N/*.yaml`) rather than `state.json`. The field was renamed from `phase` in #236 to make the entry-only semantics unambiguous; `orchestrator.engine` accepts the legacy key on load (in-flight pre-#236 runs) and migrates it to the canonical name on the next save.

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

## 7. Optimization campaign artifacts (`kind: optimization`)

Additive to the schemas above — every artifact described in sections 0-6b is
still written, unchanged in schema, for a `kind: optimization` campaign. See
[docs/optimization-campaign-guide.md](optimization-campaign-guide.md) for
the authoring guide these artifacts support, and its "The compiled policy"
section for how they fit together during a run.

Two locations matter, and the split is not cosmetic:

- **Work-dir root** — facts about the **epoch**: the compiled policy, the
  transition log, the report, the epoch-end record, and the build oracles'
  evidence. An epoch spans several iterations, so an epoch-scoped fact
  buried per-iteration would make "which epoch are we in?" a directory walk.
- **`runs/iter-N/`** — facts about one **iteration**: its design matrix, its
  runs, its fit, its recommendation or confirmation.

**Complete inventory.** The list below is what the code writes, not an
illustrative subset; the design spec's §3.9 table is the authority on what
must exist, and the code is the authority on the names. Two differ, and are
called out where they appear (`epoch_end-<epoch>.json` for the spec's
`epoch.json`; no `alias_map.json` — its content lives in `effects.json` and
`recommendation.json`).

| File | Location | Written by | Schema |
|---|---|---|---|
| `policy.json` | root | end of `verify` (`policy.write_policy`) | `schemas/policy.schema.json` |
| `policy.sha256` | root | same call | plain text |
| `transitions.jsonl` | root | every `step()` (`policy.append_transition`) | none |
| `report.json` | root | `report` (`stage_runner._run_report`) | `schemas/report.schema.json` |
| `epoch_end-<epoch>.json` | root | `exception` (`stage_runner._close_iteration`) | none |
| `mechanism.patch` / `mechanism.sha256` | root | `build.snapshot_mechanism` | patch / plain text |
| `pre_build_tests.json` | root | `run_stage`, before `build` | none |
| `baseline_equivalence.json` | root | `run_stage` at `verify`, when `build` ran | none |
| `design_matrix.json` | `runs/iter-N/` | `artifacts.write_design_matrix` | `schemas/design_matrix.schema.json` |
| `runs.jsonl` | `runs/iter-N/` | `artifacts.append_run` | `schemas/runs_row.schema.json` |
| `effects.json` | `runs/iter-N/` | `artifacts.write_effects` | `schemas/effects.schema.json` |
| `recommendation.json` | `runs/iter-N/` | `run_stage`, fitting states | `schemas/recommendation.schema.json` |
| `fit_exclusions.json` | `runs/iter-N/` | `run_stage`, only when rows were excluded | none |
| `confirmation.json` | `runs/iter-N/` | `stage_runner._finish_confirm` | `schemas/confirmation.schema.json` |
| `shortlist.json` | `runs/iter-N/` | `stage_runner._finish_confirm` | `schemas/shortlist.schema.json` |
| `relations.json` | `runs/iter-N/` | `artifacts.write_relations` | `schemas/relations.schema.json` |
| `findings.json` / `principle_updates.json` | `runs/iter-N/` | projected from the fit — zero tokens | the shared reflective schemas |
| `build_summary.md` / `build_warning.txt` | `runs/iter-N/` | `build.run_build` | prose |
| `build_events.jsonl` | `runs/iter-N/` | `build.run_build` (the SDK runner's event log) | none |

How they chain, for one epoch:

```
campaign.yaml (optimization block)
    │  build?  → mechanism.patch, mechanism.sha256, pre_build_tests.json
    │  verify  → relations.json, baseline_equivalence.json
    ▼
policy.json + policy.sha256    compile_policy(), pure Python, ZERO tokens
    │                          ── the pre-registration: hashed before run 1
    ▼
   ┌──────────────── step(policy, state, observations) ───────────────┐
   │  each call appends one row to transitions.jsonl                  │
   │                                                                  │
   │  screen ─┬─▶ foldover ─┬─▶ refine ─▶ confirm ⟲ ─▶ report        │
   │          └─────────────┴──────────────┘   │                      │
   │   per state: design_matrix.json, runs.jsonl,                     │
   │              effects.json, recommendation.json                   │
   │              (+ fit_exclusions.json if rows were excluded)        │
   │   at confirm: confirmation.json, shortlist.json                  │
   │                                                                  │
   │  any state ─▶ exception  (semantic exception; ENDS the epoch)     │
   └──────────────────────────────────────────────────────────────────┘
    │                                    │
    ▼                                    ▼
report.json                        epoch_end-<epoch>.json
 recommendation.basis,               why it ended + next_epoch_requires
 both bounds, path                  → its presence starts epoch 2
```

### 7e. policy.json — "What was pre-registered, before any result was seen?"

**Schema:** `schemas/policy.schema.json` · **Location:** work-dir root

The **compiled epoch**: a state machine compiled from the campaign's
`optimization` block by `orchestrator.optimize.policy.compile_policy` at the
end of `verify`. Compilation is pure Python — **zero model tokens** — and
reads no measurement. `policy.sha256` beside it carries the content hash.

That hash written *before the first benchmark run* is the pre-registration:
every branch the campaign could take was fixed before any result was seen.
`stage_runner` re-checks it on every subsequent stage and hard-aborts on a
mismatch — a pre-registered policy cannot change inside an epoch. **Never
edit `policy.json`;** revise the campaign YAML and start a new epoch.

| Field | What it means |
|---|---|
| `policy_version` | `1` — the compiled-policy format version |
| `epoch` | Which execution this policy registers; `epoch_end-*.json` files on disk are what advance it |
| `compiled_from` | `campaign_hash`, `mechanism_patch_hash`, `factor_ids`, and the `pre_epoch` stages (`build` / `verify`) this was compiled behind |
| `objective` | `metric`, `direction`, `epsilon`, `delta_screen`, `delta_terminal` — the campaign's `policy` block, verbatim |
| `budget` | `max_runs` (or `null` for unbudgeted) |
| `known_valid_baseline` / `workload` | The declared baseline and seed contract, carried into the epoch |
| `initial` | The epoch's first state — `screen` (`build`/`verify` are pre-epoch) |
| `states` | Per state: `spends`, `terminal`, `ends_epoch`, `design`, `estimator`, `accounting` |
| `transitions` | Ordered rules: `from`, plus either (`when`, `to`, `accounting`) or `default` |

Every `when` guard reads only keys in `policy.OBSERVATION_KEYS` and compares
them with `policy.COMPARISON_OPS` (`>`, `>=`, `<`, `<=` — no `==`/`!=`).
`check_policy` rejects anything else, and `enumerate_paths` makes
registration checkable by enumeration rather than inspection.

### 7f. transitions.jsonl — "Why did the epoch go this way?"

**Location:** work-dir root · one object per line, append-only **across
epochs** (truncating it on an exception would destroy the record of why the
epoch ended; every row carries its `epoch`, so consumers filter).

Written by `policy.append_transition` on every `step()` call. This file, not
the log, is the audit trail: `report.json`'s `path` is read back from it, and
`current_state` resumes from it.

| Field | What it means |
|---|---|
| `epoch` / `iteration` | Which epoch and which Nous iteration this step belongs to |
| `from` / `to` | The state that just finished and the state the policy routed to |
| `observations` | The **full** observation dict `step()` saw — every key in the closed vocabulary, not just the one that fired |
| `rule` | The transition that fired, including its `accounting` string (or the `default`) |
| `policy_hash` | Which registered policy scheduled this step — what keeps the question answerable across epochs |

### 7g. recommendation.json — "What does the fitted surface say is best?"

**Schema:** `schemas/recommendation.schema.json` · **Location:**
`runs/iter-N/` · written at every fitting state (`screen`, `foldover`,
`refine`) — from one call site, so the shape is identical at all three and
`stage` is the only field that tells them apart.

`recommend()` is `argmax` over `X_valid` — enumeration for a small space,
deterministic optimization for a structured one, and **no model judgment**.
It exists because a solved stationary point may be a saddle or a minimum, and
because `choice` factors are excluded from a quadratic solve.

| Field | What it means |
|---|---|
| `stage` / `iteration` | Which fitting state produced this |
| `levels` / `coded` / `predicted` | The argmax over `X_valid`, and the surface's prediction there |
| `top_candidates` | The runners-up, which become the shortlist's seed at `confirm` |
| `stationary_point` | The solved quadratic stationary point, when there is one — reported, never blindly trusted |
| `residual_regret_model` | The **model bound** `R_δ^model(x̂)`: `value`, `challenger`, `delta`, `method`, `detail` |
| `aliases` / `alias_consequential` | The alias classes, and which of them could actually change the winner — the spec's `alias_map.json` content, recorded at every fitting state |
| `fitted_ids` / `held_fixed` | Which factors this fit covered, and what the rest were pinned at |
| `model_adequate` | Whether the lack-of-fit test rejected the registered response class — read by `confirm` to decide whether the model's pick may be seated as a finalist |

### 7h. fit_exclusions.json — "Which rows were left out of the fit, and why?"

**Location:** `runs/iter-N/`, written **only when rows were excluded.**

One infeasible row used to NaN-poison every fitted coefficient while still
producing a schema-valid `effects.json`. The fit now runs on the
complete-row subset and records the exclusions here, so information loss is
visible rather than silent.

| Field | What it means |
|---|---|
| `stage` | Which fitting state |
| `planned_rows` / `fitted_rows` | How many rows the design planned versus how many the fit used |
| `excluded_row_indices` | Which `runs.jsonl` rows were excluded |
| `reason` | Why — rows that did not reach status `complete` (infeasible, rejected, or unmeasured) |

### 7i. confirmation.json / shortlist.json — "Terminal discrimination"

**Schemas:** `schemas/confirmation.schema.json` and
`schemas/shortlist.schema.json` · **Location:** `runs/iter-N/` · written by
`stage_runner._finish_confirm`.

`confirm` is this branch's name for the paper's **`discriminate`** stage
(design spec §3.3's naming note). It is **terminal discrimination**, not
replication: it measures a shortlist of finalists freshly and compares them
*against each other*, so the final comparison rests on measurements rather
than on the fitted surface.

`confirmation.json` is the record; `shortlist.json` is a pointer to it plus
the shortlist itself, so the finalists and their measurements have exactly
one source of truth.

| Field | What it means |
|---|---|
| `round` | Which round of terminal discrimination (capped by `confirm_max_rounds`) |
| `finalists` | Each finalist's `key`, `levels`, `samples`, `mean`, `n`, `status`, and **`why`** it made the shortlist |
| `best` | The winning finalist's key |
| `residual_regret_terminal` | The **terminal bound**'s value — model-free, from the fresh replicates only |
| `bounds` | The per-challenger bound record: `delta`, `method`, `challenger`, `detail` |
| `epsilon` | The resolved indifference width this round was judged against |
| `certified` | Whether `R_δ^term ≤ ε` |
| `best_observed` / `confirmed_is_best_observed` / `regression_vs_best_observed` | The best configuration observed anywhere against the winning finalist — "best finalist" and "best configuration found" are different claims |

### 7j. report.json — "What should we do, and how strong is the claim?"

**Schema:** `schemas/report.schema.json` · **Location:** work-dir root ·
written by `stage_runner._run_report`.

The report **always names an action.** The fallback ladder is recorded as
`recommendation.basis`, so a reader can tell a certificate from a fallback
without opening a log: `certified` → `terminal_best` → `model` → `measured`
→ `baseline`, plus `none` when no baseline was declared and there is
genuinely nothing legal to return. See the guide's table for what each rung
does and does not claim.

| Field | What it means |
|---|---|
| `recommendation` | `levels`, `basis`, and `value` where one exists |
| `residual_regret_model` | The model bound's value, at `delta_screen` — carries the registered response-class assumption |
| `residual_regret_terminal` | The terminal bound's value, at `delta_terminal` — does not depend on the fitted model at all |
| `epsilon` / `certified` | The indifference width, and whether the terminal bound cleared it |
| `delta_screen` / `delta_terminal` | The two error budgets: `Pr(wrong global decision) ≤ δ_s + δ_t` |
| `finalists` | The terminal shortlist, carried forward from `confirmation.json` |
| `known_valid_baseline` | The declared baseline, so the bottom rung is visible even when it was not used |
| `path` | The states this epoch actually visited, read back from `transitions.jsonl` |
| `epoch` / `policy_hash` / `iteration` | Which epoch, under which registered policy, closed at which iteration |
| `epoch_ended` | Present **only** when a semantic exception ended the epoch: the guard that fired |

The two bounds are **never collapsed into one number.** They rest on
different assumptions — the model bound on the registered response class, the
terminal bound on nothing but the fresh measurements — so a single "regret"
figure would advertise the assumption-light guarantee while delivering the
model-dependent one. A `null` bound means the variance was not estimable, and
an unknown is not a zero: treat it as "cannot certify."

`report.json` carries each bound's *value*; the full record (`challenger`,
`delta`, `method`, `detail`) stays in `recommendation.json` and
`confirmation.json`.

The separation is enforced, not merely documented. `report.schema.json`
requires `residual_regret_model` and `residual_regret_terminal`
**independently**, declares no `oneOf`/dependency relating them, and defines no
combined field for a collapsed number to live in — so a report that dropped or
merged either bound cannot reach disk. Enforcement is wired at
`stage_runner._write_json`, the one function every artifact write in the kind
goes through (see `GOVERNED_ARTIFACTS`), which is why a new write site cannot be
added that skips validation. A violation raises `OptimizationAborted` at the
write rather than shipping an unreadable certificate.

### 7k. epoch_end-&lt;epoch&gt;.json — "Why did the epoch end, and what would a new one need?"

**Location:** work-dir root, one per epoch · written by
`stage_runner._close_iteration` when the policy routes to `exception`.

A **semantic exception** is a measurement the compiled policy has no
registered branch for — a failed `correctness` relation, a NaN primary
metric, a stationary point outside the declared hull. No model call is made
to interpret it; the epoch ends instead. A `report.json` is still written, on
the strongest rung that does not rest on the fitted surface.

The file lives at the root, not per-iteration, because it is a fact about the
epoch: `_epoch_index` counts these files to know which epoch the next run is.
`iteration` is recorded inside it so the iteration that ended the epoch stays
identifiable.

| Field | What it means |
|---|---|
| `epoch` / `iteration` / `state` | Which epoch ended, at which iteration, in which state |
| `rule` / `observations` / `reason` | The guard that fired, the full observation dict, and a printable summary |
| `next_epoch_requires` | What a new epoch would need — a fixed lookup over the closed observation vocabulary, so it needs no model call to write |
| `policy_hash` | The registration this epoch ran under |

Its presence is also the signal that starts epoch 2: the next
`nous run --resume` sees `epoch_end-1.json`, **recompiles** from the revised
campaign, and runs a fresh pre-registration. That is not an escape from the
hash check — the check refuses a policy edited *inside* an epoch; recompiling
*across* an epoch boundary is the opposite operation.

### 7l. pre_build_tests.json / baseline_equivalence.json / mechanism.patch — the build oracles

**Location:** work-dir root · written around the opt-in `build` stage.

| File | Oracle | What it proves |
|---|---|---|
| `mechanism.patch` + `mechanism.sha256` | 2(a) | A snapshot of the mechanism as compiled. Every later iteration re-hashes the tree (scoped by `build_checks.mechanism_paths`) and aborts on drift — the numbers must describe the system the policy was compiled for |
| `pre_build_tests.json` | 2(b) | Each declared `native_test`'s verdict **before** the build. A `correctness` test that already passed against a tree without the mechanism is green for some other reason, and stays green if the build wires the mechanism to nothing |
| `baseline_equivalence.json` | 2(c) | The `known_valid_baseline`'s replicate vectors before and after the build. A mechanism that moves the metric *at its own OFF level* changed something outside its scope and confounds every treatment effect while looking clean |

`baseline_equivalence.json` also records how the pre/post comparison was
made. When the campaign declares `optimization.workload.seed_env`, the two
halves share **workload common random numbers** (§3.8): post replicate *i*
re-runs the draw pre replicate *i* used, so the workload's own entropy cancels
out of the pre/post difference instead of being charged to the mechanism —
which is what keeps a 5% hard-abort gate meaningful on a queue, a cache, or an
autoscaler. `paired` is `true` in that case, with `workload_seeds` (the draws,
index-aligned to `pre`/`post`) and `workload_seed_env` alongside it. `paired`
is `false` when the campaign declares no workload block, and also when the
pre-build half recorded no matching seeds — a campaign that added the block
between `build` and `verify` degrades to the unpaired reading with a WARNING
rather than labelling a pairing that never happened.

### 7a. design_matrix.json — "What configurations are pre-registered?"

**Schema:** `schemas/design_matrix.schema.json`

The pre-registered design matrix, written **before** any execution. Fixing
every configuration in advance — before any result is seen — is what
makes the campaign's anti-p-hacking property stronger than sequential
one-factor-at-a-time search.

| Field | What it means |
|---|---|
| `factor_ids` | Which factors (by id) form the matrix's columns |
| `kind` | Design family (e.g. fractional factorial, central composite) |
| `resolution` | Achieved resolution (III/IV/V) for a fractional design |
| `generators` | The published generator columns used to build the fraction |
| `aliases` | Named aliased effect pairs, if any — the honest cost of resolution < V |
| `rows` | The matrix rows themselves, in coded (±1) space |
| `run_order` / `run_order_seed` | Randomized execution order plus the seed that reproduces it — immune to time-ordered drift a sequential grid can't rule out |
| `policy_hash` | The registered policy that scheduled this matrix — the same hash `transitions.jsonl` records per row |
| `run_timeout_sec` | The wall-clock ceiling **every row here was measured under** — `optimization.run_timeout_sec`, or 600 when the campaign declared none. Recorded either way, so a `failed` row reading "timed out after 600 seconds" is readable without knowing which campaign revision was on disk |
| `max_parallel` | The **effective** ceiling on simultaneous in-flight runs this matrix was measured under — `optimization.max_parallel` at a `confirm` round, and always `1` at a spending stage regardless of what the campaign declared. Read it alongside `run_order`: a permutation looks identical whether it described a sequence or a schedule, so without this field a matrix claiming a randomized run order could be asserting a guarantee concurrent execution did not provide |
| `workload_seeds` | Row index → the seed exported into that row's run, when the campaign declares `workload.seed_env` (§3.7 oracle 3) |
| `paired` | `true` on a confirm-round matrix under common random numbers — replicate *i* of every finalist ran the same draw, which is what lets the terminal bound read the paired differences |
| `held_fixed` | Factor id → the level it was pinned at, for factors declared in the campaign but not columns of *this* design |

Those last six are **resolved run parameters**, not design structure: facts
about how the rows were measured rather than which rows they are. They live on
the pre-registration because the campaign file they came from may since have
been revised for the next epoch, and a matrix that no longer describes its own
runs is not a record.

### 7b. runs.jsonl — "What did each executed configuration produce?"

**Schema:** `schemas/runs_row.schema.json` (one object per line)

One row per executed configuration: factor levels, response metrics,
manipulation/constraint/integrity verdicts, and provenance. Configs marked
infeasible by a constraint are retained here as real data about the space,
even though they're excluded from fitting.

| Field | What it means |
|---|---|
| `row_index` | Which design_matrix.json row this run executed |
| `levels` | The factor levels actually applied |
| `role` | `corner` / `center` / `axial` (design-matrix role) |
| `replicate` | Replicate index for repeated runs |
| `status` | Whether the run completed, failed, or was retried |
| `response` | The observed metrics for this run |
| `manipulation_verdict` | Did the lever actually engage? (Family A check) |
| `constraint_verdicts` | Per-constraint admissibility results |
| `integrity_verdict` | Result of `integrity_command`, if declared |
| `duration_ms` / `build_hash` | Provenance for reproducibility and build-cache validation |
| `error` | Populated on a failed/retried run |

### 7c. effects.json — "What did the fitted surface find?"

**Schema:** `schemas/effects.schema.json`

Fitted main effects and interactions, with confidence intervals, the
pure-error estimate, and the lack-of-fit test. Written once per fitting
state — `screen`, `foldover`, and `refine` each produce one. Authored
**without spending
tokens**: a fitted effect with a confidence interval already contains
everything `findings.json` requires (a claim, a direction, a magnitude,
quantitative evidence), so `findings.json` and `principle_updates.json`
are projected from this file deterministically rather than restated in
prose.

| Field | What it means |
|---|---|
| `stage` | Which fitting state produced this fit (`screen`, `foldover`, or `refine`) |
| `intercept` / `effects` | Fitted coefficients, with confidence intervals |
| `quadratic` | Curvature terms and the solved stationary point (refine only) |
| `n_runs` | How many runs the fit is based on |
| `pure_error_var` / `pure_error_df` | Pure-error estimate from center-point replicates |
| `lack_of_fit_f` / `lack_of_fit_p` | Whether the fitted model form is adequate |
| `aliases` | The **alias classes** this fit estimated one coefficient per. At resolution IV aliased columns coincide, so one column per two-factor interaction makes `XᵀX` singular; fitting per alias class is what makes a resolution-IV screen fit at all, and recording the classes is what makes the confounding auditable. Whether any class could change the winner is `recommendation.json`'s `alias_consequential` |
| `dropped_factors` | Factors whose effect CI contained zero — the campaign's null results |

### 7d. relations.json — "Did the mechanism check out?"

**Schema:** `schemas/relations.schema.json`

Per-relation verdicts from running `test_command` against the target's own
native test tree. Nous's role here is a contract check, not a test
runner: each declared relation names a `native_test` identifier, and this
file records whether it ran and passed.

| Field | What it means |
|---|---|
| `verdicts` | Per-relation pass/fail, keyed by relation id |
| `correctness_failures` | Any failed `correctness` relation — hard-fails the campaign |
| `behavioral_failures` | Any failed `behavioral` relation — recorded as a finding, campaign continues |

## Dispatch and Prompt Templates

The orchestrator invokes agents through a dispatcher. Two implementations exist:

- `StubDispatcher` (`orchestrator/dispatch.py`) — produces deterministic, schema-valid artifacts without LLM calls. Used for testing.
- `CLIDispatcher` (`orchestrator/cli_dispatch.py`) — invokes `claude -p` as a subprocess, giving agents code access and shell tools. Used for both the planner (DESIGN, Opus) and executor (EXECUTE_ANALYZE, Sonnet) roles.

`CLIDispatcher` reads `campaign.yaml` at construction time and injects domain-specific context (target system name, metrics, knobs, active principles) into prompt templates from `prompts/methodology/`. The DESIGN phase produces both `problem.md` and `bundle.yaml` in a single dispatch — the raw output is split by `_split_design_output()` in `run_iteration.py`.

