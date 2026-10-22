# Nous v2: one agent session, enforced validation, a light method, unattended resume

> Audience: the Claude Code build session that delivers this (section 7), and the human reviewer.
> Every factual claim cites an entry in **Evidence** (E-numbers) at the end.
> **Target branch: `nous-v2`, not `main`.** Create `nous-v2` from `main` (`decbde7`, v0.5.0). Every PR for this issue targets `nous-v2`, and the issue closes when `nous-v2` passes the merge bar (section 10). Merging `nous-v2` into `main` is a separate, later decision, made by a human after more experiments. `main` keeps old Nous until then. On `nous-v2`, v2 **replaces** the old orchestration; there is no opt-in flag.

---

## 1. Why

Measured on Nous `main` (`decbde7`) in a 27-run controlled study, graded by script-based answer keys with no LLM judge [E1]:

| Task (3 runs each) | Claude + 4-line "be scientific" prompt (L2) | Nous `main` |
|---|---|---|
| Fix a real BLIS bug | 3/3 correct, $3.40, 13 min | 3/3, $8.39, 51 min |
| Check the paper's ITL formula | 2/3, $10.43, 40 min | 1/3, $14.66, 62 min |
| Map an 1,800-config Pareto front | search works 2/3; structure facts: oracle 2.0 of 4, hand-graded 2.7; $3.26, 18 min | search works 2/3; facts: oracle 0.67, hand-graded 1.0; $30.69, 189 min |

- Nous was never more accurate, and cost 1.4x to 9.4x more [E1].
- **Where the money went** [E2]:
  - Design (the Opus planner) cost $108.1 of the $159.3 transcript-metered total (about 68%).
  - Design sessions ran 245 `blis run`/`search.py` commands; execute sessions ran 158.
  - Of the executor's 206 individual simulator invocations, 74 (36%) repeated a design invocation with identical flags.
- **The original case studies show the same pattern** [E3]:
  - Design cost $463 of $1,135 (19 campaigns).
  - Planners ran the experiments themselves. Flow-control iteration-2 design ran about 16–18 probe runs; s390x design ran 55 experiment runs against 4 in execute.
- **Extra iterations did not pay** [E1][E2]:
  - Search rounds 2+ cost $72.45 and about 6.8 h of session time.
  - Nous's final hypervolume (0.9949–0.9968) was no better than a one-session baseline (0.9951–0.9968).
- **Fresh sessions redo work** [E3]. An iteration-3 planner re-ran the baseline and wrote: "baseline confirmed ... matching iter-2's handoff value of 803.11ms".
- **The validation hooks never ran** in any of the 9 Nous runs [E4] (section 5, bugs B1–B4).
- **What Nous did better: the trail, and exploration** [E1][E5]:
  - On the formula task, Nous's claim-evidence coverage (C1) was 0.95 vs L2's 0.75, and its repro match (R2) was 0.95 vs 0.48.
  - Its regression test failed on the buggy code 3/3 times, against 2/3 for the others.
  - On Frontier-CS, competing algorithm families gave the clearest wins: p5 57.0 vs 50.0 at $25, and p0 81.47 vs 26.43 at $50. These are single runs. 26.43 is Claude's in-run best; its re-judged final was 20.45.
  - Counter-evidence: on search, Nous's C1 was lower (0.54 vs 0.75).

**Current Anthropic guidance matches the data:**
- Model choice [E6a]: "the orchestrator model alone at lower effort" beat delegation when the work is "one dependent chain, or fits in a single context". The same page shows delegation winning in other cases, such as work larger than one context.
- Context resets [E6b]: "had become dead weight" once Opus 4.5 removed the "context anxiety" that resets worked around.
- JSON state [E6c]: JSON is less likely than Markdown to be "inappropriately" changed by the model.
- Self-grading [E6d]: "agents reliably skew positive when grading their own work."
- Hooks vs instructions [E10]: hooks are deterministic; CLAUDE.md instructions are advisory.

**Goal of v2:** deliver Nous as Claude Code plus the scientific method plus code-enforced hooks and validators, with:
- accuracy or score comparable to plain Claude Code with a short scientific prompt (L2) or better;
- cost at most 1.25× L2's;
- a clearly better trail, *guaranteed* by code: reproducible, checkable, persistent;
- a more scientific investigation: a real baseline first, locked predictions, controls, noise-aware claims, and principles that build up across iterations.

**Principle: Nous behaves like Claude Code plus a method and code-enforced checks.** No cost or money budget influences any Nous decision: no dollar caps, no budget-based stopping, no probe quotas. Nous *measures* cost and reports it in the ledger and the final answer, but never acts on it. Decisions like how many seeds to run are the agent's scientific judgment; validators enforce honesty about them (3.4), not thrift.

---

## 2. Design summary

1. **One agent session runs all N iterations** of a campaign. Opus is the default model, through Agent SDK `ClaudeSDKClient` (successive `query()` turns share one context, and SDK auto-compaction keeps that context manageable).
2. **Iteration 1 opens with BASELINE; each iteration then runs DESIGN and EXECUTE; the campaign ends with REPORT.** The orchestrator switches phases by sending the next turn's message; in-process hooks validate each phase's artifacts and record every command. Anthropic runs explore, plan and implement in one session, and kept a planning step because "Without the planner, the generator under-scoped" [E7].
3. **Hooks and validators are the core.** Every machine-read artifact is JSON, validated by code before the session may move on. A failed check goes back to the agent to repair; valid content is never thrown away.
4. **A light, task-aware method.** A short core applies to every task: pre-registered predictions; competing mechanism families when the problem allows; a control; measure before tuning; test a "noise" explanation before accepting it; the prediction-error type; principles with evidence. On top of that, the agent identifies the task type and Nous adds only that type's short checklist (3.12). The agent chooses which hypothesis arms to run for the question; there is no required arm menu. Drop the 44 KB of per-session instructions [E8].
5. **Start simple: one real observation before any hypothesis design.** Iteration 1 opens with a BASELINE phase that gets one real observation of the current system, quickly: a reproduced bug, a measured point compared with a formula, a scored valid solution, or the current policy measured on its workload. Hypotheses are then designed as predicted changes to that observation, and later iterations build on it. Plain Claude got its first real result in 1–8 minutes for $0.65–$3.25; Nous needed 5–30 minutes and $4–$16 [E17].
6. **Stop when the question is answered**, or when `stall_iterations` (default 2) iterations change no claim, best score or principle, not only at max iterations.
7. **Unattended and resumable.** The ledger is the durable record. Resume the same session by ID; if that fails, start a fresh session primed from the ledger. `nous resume` continues any stopped run.
8. **Output cut-offs are handled.** Raise Claude Code's output cap to the model maximum. If a reply is still cut, resume one effort level lower. `MAX_THINKING_TOKENS` is ignored by these models [E9].

---

## 3. Architecture

### 3.0 Code location during the transition

Until item R11a (CLI cutover), v2 lives in `orchestrator/v2/` and is reached only through tests until R11a; no CLI flag exposes it. The existing orchestration keeps working, so the full test suite stays green on every loop. R11a–R11d then cut over and delete the old code.

### 3.1 Session

- Use `claude_agent_sdk.ClaudeSDKClient`.
- **Versions.** R1's **first commit** pins the latest releases at build start: `claude-agent-sdk` (0.2.170 as of 2026-10-21; `main` locks 0.2.87) and the Claude Code CLI (2.1.306 as of 2026-10-21) [E15]. Set `cli_path` to the pinned CLI, not the SDK's bundled one. Record both exact versions in `pyproject.toml`/`uv.lock` and in `state.json` for every campaign. The full suite must be green before any other change.
- Re-check the SDK APIs this spec relies on against the pinned version: `hooks`, `HookMatcher.timeout`, `PostToolUseFailure`, `env`, `max_buffer_size`, `resume`, `effort`, `SystemPromptPreset.append`, `AssistantMessage.stop_reason`. They were verified on 0.2.163. If one changed, note it in `progress.txt` and adapt.
- `orchestrator/v2/session.py` defines `Session(client_factory=...)`. Tests inject a fake (3.11).
- **`ClaudeAgentOptions`:**
  - `model`: default `claude-opus-4-6`, configurable.
  - `effort`: `None`, meaning the model default, unless the campaign sets it.
  - `system_prompt={"type":"preset","preset":"claude_code","append": <light method>}`. Today Nous *replaces* Claude Code's system prompt with 44 KB of method text [E8]. The preset `snapshot` defaults to true, so a resumed session keeps its recorded `append` [E10].
  - `hooks=`: in-process Python callbacks (3.3), each `HookMatcher` with an explicit `timeout` (Stop 120 s, PreCompact 60 s). The SDK default is 60 s [E10].
  - `max_buffer_size=32*1024*1024`. The SDK default is 1 MB (fixes #327).
  - `env={"CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(model_max_output(model)), "NOUS_WORK_DIR": ...}`. The value is 128000 for opus-4-6 and 5.x [E9]; Claude Code clamps it to the model cap. A larger output cap leaves less context before auto-compaction [E9].
  - `cwd=<campaign worktree>`: **one git worktree for the whole campaign** (D5). Nous commits it at the end of every phase (`nous: iter-N <phase>`), so code changes carry forward to the next iteration, git records every step, and the agent can revert a worse change with git. This replaces the old per-iteration worktrees and carry-forward machinery; it is how Graph-Coloring and flow-control built on their previous best code [E18].
  - `max_turns`: unset (no turn cap).
- After every turn, persist `session_id` (from `ResultMessage`) to `state.json`.
- **`session_scope`:** `campaign` is the default. `iteration` starts a fresh session each iteration, primed from `state/digest.json` (3.7). It reuses the resume fallback path, and keeps the per-iteration vs per-campaign question testable later.

### 3.2 Phases (per iteration N)

The orchestrator sends messages in this order and runs deterministic steps between them:

0. **BASELINE message (iteration 1 only):** "BASELINE phase. Do not design hypotheses yet. Get one real observation of the current system, as defined for your task type, and write `baseline.json`." The method prompt says to aim for this within about 5 turns and to keep it simple (the simplest valid solution, the existing test or command, one or two measured points). This is guidance, not an enforced cap.
   - The Stop hook gates the end of the turn until `baseline.json` validates (3.4).
   - The agent also writes `task_type` (if the campaign did not set it) in `baseline.json`.
1. **DESIGN message:** "Iteration N, DESIGN phase. Read `state/digest.json`, `baseline.json` and the active principles below. Write `iter-N/problem.json`, `iter-N/bundle.json`, `iter-N/plan.json`. Frame each prediction as a change relative to the baseline observation."
   - Nous pastes the active principles from `principles.json` into every DESIGN message, so lessons still bind after compaction in long campaigns (one cluster campaign ran 35 iterations) [E18].
   - Iteration 2+ reuses `baseline.json` unless `git rev-parse HEAD` of the target or the baseline command changed; then the agent refreshes it in DESIGN.
   - The DESIGN validator rejects `bundle.json` while `baseline.json` is missing or invalid.
2. **The Stop hook gates the end of the turn** until those files validate.
3. **Orchestrator:**
   - Hash `bundle.json` (sha256) into the ledger, and keep a copy at `iter-N/.bundle.locked.json`.
   - Run the optional human design gate (default: auto).
   - Set the phase to EXECUTE.
4. **EXECUTE message:** "Run `plan.json`; fix anything that does not run; write `iter-N/findings.json` and `iter-N/principle_updates.json`."
   - **Long runs.** A run that outlasts one turn (a cluster job, a 30-minute benchmark) is started in the background, and its `plan.json` entry names `wait_for`: a file that must exist, or a command that must exit 0. When the agent ends its turn with runs still pending, Nous waits and polls `wait_for` every 60 s with no model calls, then sends "Runs X, Y finished; continue EXECUTE." A pending run is not a validation failure, and the repro check (3.8) counts a run as finished once its `wait_for` succeeds. The alternative, the agent re-checking every 10 minutes, would cost about 24 turns per 4-hour cluster cell [E18].
   - The agent runs and fixes experiments itself. There is no plain-code runner for `plan.json`: the project owner tried one, plans often did not run as written, and the agent's own trial-and-fix is what made them work (project owner's experience, not measured here).
5. **The Stop hook gates the end of the turn** until findings and principles validate.
6. **Orchestrator:**
   - Bundle check: if `bundle.json` no longer matches the locked hash, restore it from the locked copy and record `prereg_violation: true` in the ledger. Never block on this.
   - Merge principles.
   - Write the ledger row (3.4) and apply the stop rule (3.6).
7. **End of campaign, REPORT message:** "write `answer.json` and `report.md`."
   - The Stop hook validates `answer.json`.
   - The orchestrator runs the final check (3.8).

### 3.3 Hooks (in-process, via `ClaudeAgentOptions.hooks`)

In-process callbacks replace the shell hooks wired through `.claude/settings.json`. This removes bugs B1–B3 by construction: no settings-file loading, no env var, no PATH lookup [E4][E10].

The hooks have three jobs only: **record** every command, **check** each phase's files when the phase tries to end, and **save** a summary before compaction. They never judge or block a command before it runs. There is no `PreToolUse` hook. In a single session the agent sees its own earlier runs, so the old cause of repeated experiments (two sessions that could not see each other's work, 36% repeats [E2]) is gone. A blocking rule would also stop legitimate re-runs, such as repeat seeds for noise, and could misjudge uncommitted code changes. The locked `bundle.json` is protected by the hash check at the end of EXECUTE (3.2 step 6), not by blocking edits.

| Hook | When | Rule |
|---|---|---|
| `PostToolUse` (Bash) | always | Mask secrets first (3.14), then append to `runs.jsonl`: `{ts, phase, iter, tool_use_id, command, exit_code: 0, output_bytes, cwd, background, agent_id}`. Background calls record `exit_code: null, background: true`. Durations are not recorded by the hook; the cost meter derives them from tool-use and tool-result timestamps in the session transcript when needed. |
| `PostToolUseFailure` (Bash) | always | Same row, with `exit_code` parsed from `error` (regex `Exit code (\d+)`), or -1 if absent [E10]. |
| `Stop` | BASELINE, DESIGN, EXECUTE, REPORT | Run the phase validator. On failure, return a block with the rendered error list. Keep a counter of consecutive blocks, reset by any tool call. At 6, allow the stop and let the orchestrator handle repair (3.5). Claude Code itself overrides a Stop hook after 8 blocks in a row with no tool call in between [E10]. |
| `PreCompact` | always | Write `state/digest.json`: phase, baseline, active hypotheses, active principles, the last findings summary, open questions. Compaction can drop details [E11]. |

The agent never writes `runs.jsonl`. B11 (agents' own counters) is fixed by counting experiment commands from `runs.jsonl` and comparing them with any evaluation limit the *task itself* states (for example, "at most 200 evaluations" in a search task), when the campaign declares it as `task_limits`. If a limit is exceeded, the validator requires the findings to state it; nothing is blocked.

### 3.4 Artifacts

All machine-read artifacts are JSON, each with a JSON Schema in `orchestrator/schemas/`. `report.md` is the only Markdown file, and it is never parsed.

| File | Writer | Checks |
|---|---|---|
| `baseline.json` `{task_type, command, git_sha, observation{}, metrics_path, noise}` | agent, BASELINE | schema; `command` appears in `runs.jsonl` (exit code depends on type, below); every value in `observation` matches `metrics_path` (evidence rules below). `observation` depends on `task_type`:<br>• `debug`: `{reproduced: true, symptom, expected, actual}`; the command reproduces the bug (a failing test or a wrong number is acceptable, so the exit code may be non-zero).<br>• `verify`: `{points: [{condition, predicted, measured}]}`, at least 1 point.<br>• `optimize`: `{score}`, from a valid solution; a score of 0 from a stub does not count, so the agent repairs or simplifies until it is valid.<br>• `policy`: `{metrics{}}` of the current policy on the target workload.<br>• `explain`: `{symptom, control}`, the symptom measured plus one control point.<br>• `other`: `{metrics{}}`, at least one measured value.<br>`noise` is either `{seeds[], values[], sd}`, `{deterministic: true}`, or `{unmeasured: true, reason}`; it is measured on this real baseline, never on a stub. The agent chooses how many repeats to run; the validator only checks consistency with `runs.jsonl`. |
| `iter-N/problem.json` | agent | schema; includes `task_type` (one of `debug`, `verify`, `optimize`, `policy`, `explain`, `other`) and `claims_needed[]`: the exact claims the question requires, each with how it will be tested, plus any requirements such as `min_seeds` (3.6) |
| `iter-N/bundle.json` | agent | schema; see the hypothesis fields below; at least 2 distinct `family` values or a non-empty `single_family_reason`; every `claims_needed` entry is covered by at least one hypothesis |
| `iter-N/plan.json` `{runs:[{id, hypothesis_id, role (treatment/control), command, parameters{}, seeds[], wait_for?}]}`, plus optional `workload_changes[]` with a reason for each | agent | schema; every `hypothesis_id` exists; every run's `parameters{}` respects `locked_parameters` and `locked_workload` (the existing checks, now reading `parameters{}`), unless the change is declared in `workload_changes[]` [E18]; when a hypothesis has a control, its treatment and control runs use the same `seeds[]` (paired comparison) |
| `runs.jsonl` | PostToolUse hooks only | append-only |
| `iter-N/findings.json` | agent | schema, described below |
| `iter-N/principle_updates.json` | agent | schema; each principle has `finding_ref` (a hypothesis id in this iteration's findings) |
| `ledger.json` | orchestrator only | existing schema plus `bundle_hash`, per-phase `cost_meter_usd`, `cost_sdk_usd` and token counts, `claims_changed`, `best_changed`, `principles_changed`, `repro_recorded`, `claims_matched_fraction`, `note` (from `--note`), `stop_reason`, `status` (`ok`/`partial`), `prereg_violation`; written atomically |
| `answer.json` | agent, REPORT | the output contract: `answer`, `deliverable`, `repro`, `claims[]` of `{id, metric, value, condition, evidence}`; each claim's evidence checked like a findings evidence item |
| `report.md` | agent, REPORT | none |

**Hypothesis fields** (each entry in `bundle.json`): `id`, `role` (free text chosen by the agent, for example main, alternative, control, ablation, robustness, dose-response), `family`, `mechanism`, `prediction` (`{metric, direction, magnitude_or_threshold}`), `control` (or `no_control_reason`), `falsified_if`, `claim_ids[]`. The agent picks the arms the question needs. The validator never requires a particular set of roles. Evidence that a fixed menu is wrong in both directions [E16]: different arm types caught wrong predictions in different campaigns (robustness arms were refuted or only partly confirmed 50% of the time, dose-response 58%, controls 29%), super-additivity and tradeoff arms were rarely used (5 and 6 of 25 campaigns), and extra competing-family sessions on Frontier-CS v7 cost $62 without improving the best result.

**`findings.json`:**
- `hypotheses[]`, each with `id`, `status` (CONFIRMED/PARTIALLY_CONFIRMED/REFUTED/INCONCLUSIVE; PARTIALLY_CONFIRMED requires a `partial_note` saying which part held), `error_type` (direction/magnitude/regime/shape/none), and `evidence[]` of `{path, key, value}`.
- Per hypothesis, optional `noise_sd` (with `noise_condition`) or `noise_unmeasured: true` (with `noise_reason`), and `claims[]` of `{claim_id, metric, condition, value}`, where `claim_id` refers to `problem.json` `claims_needed`.
- An optional `best` = `{metric, value}`.
- `question_answered` (bool) and `reason`.

**Noise honesty rule** (validator, repair not block-forever): a CONFIRMED or REFUTED hypothesis whose prediction is about a measured metric must either show an effect larger than 2 × the relevant noise, or carry `noise_unmeasured: true`. The relevant noise is the finding's own `noise_sd` when it gives one: the seed spread of its paired control or of the same condition, which is preferred. Otherwise it is `baseline.noise.sd` (sd = 0 when `deterministic: true`). Noise depends on conditions: SELLGM measured 3.9 s at 8 GB vs 0.5 s at 4 GB, and the cluster flow-control campaign measured 2–19% by rate [E18]. Such findings are marked lower confidence in `answer.json`. Otherwise the validator asks the agent to add seeds or change the status to INCONCLUSIVE.

**Evidence rules:**
- `path` must exist.
- Evidence files must be JSON, JSONL, CSV, TSV or plain text; the agent exports anything else (e.g. SQLite, profiler binaries) to one of these first.
- `key` is a JSON Pointer (RFC 6901) for `.json`, `line_number@pointer` for `.jsonl`, `column@row_index` for CSV and TSV, or, for any other text file, a regex whose group 1 is the value.
- Numbers match within `rel_tol=1e-3, abs_tol=1e-9`; strings match exactly.

**Validator behaviour** (fixes #328 / B5):
- Before strict validation, unknown top-level keys move into `extra: {}`, and a warning is logged. Every schema declares `extra: {type: object}`.
- A missing required field or a wrong type fails, and returns a repair message that lists every error.

### 3.5 Failure handling

- **Repair.** A phase whose Stop hook let it end with failing validation gets up to 2 repair messages in the same session, carrying the error list.
  - If it still fails, the ledger gets `status: partial`, the valid content is kept and merged, and the campaign moves on.
  - The "failed permanently" path that drops the iteration (`campaign.py:435-440`) is removed (B5).
- **Failure breaker:** if 3 consecutive failures have the same fingerprint (exception type, phase, error message with numbers and paths removed), stop retrying, write `halt.json` with the fingerprint, and go to REPORT so the run still ends with an answer [E14].
- **Transient errors** are retried with backoff: `ProcessError` with exit 143 or the message "Fatal error in message reader", timeouts, and API 5xx (#315 / B9).
- **Preflight at campaign start:**
  - Construct the hooks and run each validator on a known-good and a known-bad fixture.
  - Run the Stop-hook callback on a fake input.
  - Fail fast with a clear message if any of these misbehave (B4).

### 3.6 Stop rule

Checked after each iteration:
1. **Question answered:** `question_answered` is true, every evidence check passed, at least one hypothesis is not INCONCLUSIVE, and every requirement declared in `claims_needed` is met (for example `min_seeds: 5`, `needs_ci: true`, `conditions: [two workloads]`). Nous checks only requirements someone declared; it never adds its own. epp-saturation looked answered at iteration 3 on short runs, and memorytime-vector on 1 seed when 5 were required [E18].
2. **Stalled:** from iteration 2 on, nothing changed for `stall_iterations` consecutive iterations (default **2**): `claims_changed`, `best_changed` and `principles_changed` are all false. Two real campaigns found their main result after a round that changed no hypothesis status (blis-search-algo2 iterations 4–5, SELLGM iterations 9–10), so one quiet round is not enough [E18].
3. **`max_iterations` reached.**
4. **Failure breaker** (3.5) or the `STOP` sentinel (3.7); both still go to REPORT.

Definitions:
- `claims_changed`: the set of `(claim_id, metric, condition, value)` across findings differs from the previous iteration, compared by the `claims_needed` ids (stable across iterations), not by hypothesis ids, which campaigns reuse.
- `principles_changed`: `principle_updates.json` adds or revises at least one principle.
- `best_changed`: `findings.best.value` beats the previous best by more than `campaign.min_improvement` (default 0) in `campaign.objective.direction`. False if either value is missing.

The LLM gate-summary calls are removed (#329 / B8). Decisions come deterministically from the ledger, and human gates stay optional.

### 3.7 Resume and unattended runs

- **`nous resume <work_dir>`:**
  - Read `state.json` (`session_id`, `iteration`, `phase`, `effort`, `cut_offs`).
  - Reconnect with `ClaudeAgentOptions(resume=session_id)`, re-applying the hooks and effort explicitly, because a resumed `-p` session does not restore the permission mode [E12].
  - Send a resume message naming the phase and pointing to `state/digest.json`.
- **Note to a running campaign:** `nous resume <work_dir> --note "..."` adds the text to the next phase message and logs it in the ledger. A cluster campaign received a human clarification at iteration 16 [E18].
- **Fallback:** if resume fails, start a fresh session whose first message is built from `ledger.json` and `state/digest.json`.
- `state.json` and `ledger.json` are written atomically after every turn; nothing depends on SessionEnd.
- The cumulative cost and wall time are measured campaign-wide and persisted in `state.json`, so a resume continues the totals rather than restarting them (reporting only).
- The existing `STOP` sentinel stops cleanly at the next turn boundary.
- Start the Claude CLI in its own process group (`start_new_session=True`), and kill the whole group (`killpg`) on STOP, crash or exit, so no orphaned process keeps running [E14].

### 3.8 Final answer check

At REPORT, the orchestrator:
1. validates `answer.json`;
2. checks each claim's evidence (evidence rules, 3.4);
3. checks the `repro` command **from the record, without re-running it**: the command must appear in `runs.jsonl` (written by the hook), it must have finished, and every claim's evidence file must have been written by that run or a later one (by file modification time, after the run's start time);
4. records `repro_recorded` and the fraction of claims matched in the ledger.

Re-running is off by default, because a repro command can take hours. `campaign.yaml` may set `rerun_repro: true` for cheap tasks; then the orchestrator also re-runs it once in a clean worktree and records `repro_ok`.

This replaces the extra packaging session our study harness needed to produce a gradable answer [E2].

### 3.9 Experiment commands

An *experiment command* is a Bash command matching any regex in `campaign.experiment_commands`. The default list is `[r'\bblis\s+run\b', r'\bpython3?\s+\S*(search|bench|run|sweep)\S*\.py\b', r'\bmake\s+bench']`. Campaigns should set their own list.

### 3.10 Effort, output cut-offs and cost

- **Detect a cut:** an `AssistantMessage` with `stop_reason == "max_tokens"` [E10].
- **On a cut:**
  1. Call `interrupt()`.
  2. Increment `cut_offs` in `state.json`.
  3. Reconnect with `resume=session_id` and the next effort level down. The ladder is `max > xhigh > high > medium > low`, starting from the configured level or the model default. `low` is used only after 2 consecutive cuts.

  Effort is dynamic in both directions: a lowered level applies only until the end of the current phase. Each new phase starts again at the configured level or the model default, so one hard step does not make the rest of the campaign think less. `CLAUDE_CODE_MAX_OUTPUT_TOKENS` is always set to the model maximum (3.1), so a cut means the reply needed more than the model can write at once.
  4. Send the message: "Your last reply was cut at the output limit. Write and run the simplest correct step first."

  Reconnecting is required because `ClaudeSDKClient` has no effort setter [E10]. Resuming with a different effort kept context in a live check on 2026-10-19 [E9]. Anthropic's thinking docs give the two remedies for `stop_reason: max_tokens`: raise the output limit, or lower effort [E9].
- **Context filling from tool output** is a separate failure from a cut reply: one huge command output (for example a full `go test ./...` log) can exhaust the context [E14]. The `PostToolUse` hook records the output size in `runs.jsonl`. The method prompt tells the agent to redirect long output to a file and read only what it needs. If the SDK reports the context is full, resume from `state/digest.json` in a fresh session (3.7 fallback).
- **Cost:** port the transcript meter (one count per message id, subagents included, prices from a table in `defaults.yaml`) from `experiments/frontiercs/gen/cost_meter.py` at `aiopslab` commit `09dcb1c` into `orchestrator/v2/cost.py`. Every SDK and API call is counted, which fixes B10. The ledger records both the meter's cost and the SDK's own `total_cost_usd` per phase, plus tokens; they are compared at analysis time, not during the run, and cost never drives a Nous decision. Why both: the SDK's price table was about 3× low for opus-4-6 in the Frontier-CS runs, while the meter matched the CLI's own total on 11 of 12 study runs [E18]. Tokens are always recorded, so cost can be recomputed later with corrected prices.
- The step-down-on-cut logic may be adapted from `orchestrator/effort.py` at `aiopslab` commit `09dcb1c` [E9]. Port only that, not its "medium until a first score" rule.

### 3.11 Testing (no live LLM calls, per `CLAUDE.md`)

- **`tests/fakes/sdk_client.py`** provides `FakeClient`:
  - It plays a script of SDK message objects (`AssistantMessage` with tool uses, then `ResultMessage` with `session_id` and usage).
  - For each scripted tool use, it calls the registered hook callbacks with SDK-shaped inputs, including PostToolUse, PostToolUseFailure, Stop with `stop_hook_active`, and PreCompact.
  - It writes the files the script says the agent wrote.
- **R1 extends the `block_live_llm_calls` guard in `tests/conftest.py`** so that `ClaudeSDKClient.connect` fails hard in tests.
- **Behavioural assertions only:** the files on disk, the ledger rows, and schema conformance (repo `CLAUDE.md`).

### 3.12 Light method prompt and task-type checklists

- **Size:** `len(text.encode()) <= 6144`, appended to the Claude Code preset. Phase details go in the phase messages.
- **Task-type checklists** live in `prompts/v2/checklists/<task_type>.md`, each at most about 600 bytes. `task_type` is **optional** in `campaign.yaml`. If the user sets it, Nous uses it. If not, the agent picks one in iteration 1 and writes it with a one-line `task_type_reason` in `baseline.json` during BASELINE. From then on, each DESIGN message includes only that type's checklist. A wrong type can be corrected in a later iteration's `problem.json`. `other` gets the core method only. Starting checklists:
  - `debug`: the baseline is the reproduced bug; locate the root cause; the regression test must fail on the unfixed code and pass on the fix; check related code paths with the same cause.
  - `verify` (a model, formula or claim): the baseline is one or two measured points against the prediction; calibrate where the model should hold, then test where it may break; report the size and sign of each error and the regime boundary; state the mechanism behind any breakdown.
  - `optimize`: the baseline is the simplest valid solution, scored; measure noise on it; climb with one change per measurement and revert when the score drops; when the score is flat for about 3 measurements, design competing solution families; keep the best solution so far and build on it; respect the task's evaluation limits.
  - `policy` (evolve a control policy, e.g. admission or routing): the baseline is the current policy measured on the target workload, with its noise; change one policy element per experiment; check the effect on more than one workload or load level before claiming it generalizes; report the tradeoff (what gets worse).
  - `explain` (why does the system behave this way): isolate one variable per experiment; include a control; separate measurement artifacts from real effects.
  - `other`: core method only.
- **Why baseline-first, for every type:** plain Claude reached a first real observation in 1–8 minutes in every task type we measured (debug, verify, search, three Frontier-CS puzzles), then improved by reacting to that number; old Nous designed first and measured late [E17]. On p5 at $50, Claude's climb went 27 → 37 → 48 → 57 in four rewrites by about $10, then stayed at 55–57 for its remaining $40: more spending without a new idea did not help. That is where competing families are meant to help; at $25, Nous v6's families reached 57.0 against Claude's 50.0 [E5][E17]. `policy` has no controlled data yet; its checklist follows the same rule and should be tested in the follow-up experiments.
- **Why task-aware:** every arm made the same framing error on the formula task (fitting over the whole range hides where it breaks), and Nous's generic method did not prevent it [E1]. The study's own lessons propose "a short framing checklist per task type ... rather than one 30 KB generic design prompt" [E1]. Debugging needed a failing regression test, which baselines got wrong 1 time in 3 [E1]. Exploring competing families gave the clearest Frontier-CS wins [E5].
- **Must contain** these exact field names: `family`, `prediction`, `control`, `falsified_if`, `status`, `error_type`, `evidence`, `question_answered`, `finding_ref`.
- **Must not contain** a required arm menu or the complexity-tier prose.
- **Why:** a 1,500-word loop prompt made an agent "slower and dumber", and a 103-word prompt fixed it [E13]. Bloated instruction files get ignored [E10]. The heavy method gave no correctness gain [E1].

### 3.13 Files on disk (campaign work dir)

Same top-level layout as old Nous; machine-read files are now JSON. Elsewhere in this spec, `iter-N/...` is short for `<work_dir>/runs/iter-N/...`.

```
<work_dir>/
  campaign.yaml   state.json   ledger.json   principles.json
  runs.jsonl      baseline.json   answer.json   report.md   halt.json (only after a breaker stop)
  state/digest.json            (written before each compaction)
  runs/iter-N/
    problem.json  bundle.json  .bundle.locked.json  plan.json
    findings.json  principle_updates.json
    results/  patches/
```

The campaign's single code worktree stays in the target repo under `.nous-experiments/<run_id>/`. Old names that go away: `bundle.yaml` (now `bundle.json`), `experiment_plan.yaml` (now `plan.json`), `problem.md` (now `problem.json`), `handoff.md` and `handoff_snapshot.md` (replaced by `state/digest.json` and the session itself), `gate_summary_*.json` (gate summaries removed). `state.json`, `ledger.json` and `runs.jsonl` are written only by Nous; every other JSON file is written by the agent and validated by Nous.

### 3.14 Secrets

`campaign.yaml` may list `secrets`: names of environment variables, such as `SSH_PASSWORD` or `HF_TOKEN`. Nous replaces each value with `<secret:NAME>` in every file it writes (`runs.jsonl`, `ledger.json`, `state/digest.json`), and the REPORT validator rejects `answer.json` or `report.md` if a secret value appears in them. The method prompt tells the agent to use the variables, never literal values. Every command is logged verbatim, so without this a password typed into a command lands in the log: SELLGM had a plaintext ssh password in 7 planned commands and 8,714 times across one campaign's files [E18].

---

## 4. CLI and `campaign.yaml` after cutover

| Item | Decision |
|---|---|
| `nous run`, `nous resume` | keep; v2 only |
| `nous status`, `nous cost`, `nous validate`, `nous schema` | keep; point at the v2 artifacts |
| `--agent {inline,sdk}`, `inline`/`cli` dispatch | remove (D1); passing `--agent` warns and is ignored |
| `nous replay`, `nous package`, `nous lineage`, `nous report`, `nous create` | keep if they work on v2 artifacts; otherwise mark deprecated with a warning and open a follow-up issue |
| `campaign.yaml`: `research_question`, `target_system`, `locked_parameters`, `locked_workload`, `max_iterations`, `models` | keep |
| `campaign.yaml`: new `effort` (optional; model default), `human_gates` (`off` default, or `design`/`findings`/`both`), `secrets` (env var names whose values are masked), `experiment_commands`, `objective{metric,direction}`, `min_improvement`, `stall_iterations`, `session_scope`, `task_limits`, optional `task_type`, optional `rerun_repro` (default false) | add |
| `campaign.yaml`: `critic`, `pre_work`, `arm_sweep`, `parallel_arms`, complexity tiers, `iteration_mode`, other legacy keys | accept with a warning, and ignore; files in `examples/` must still load |

---

## 5. Bugs this PR must fix

Each bug is tested as v2 behaviour. B1–B3 disappear with the in-process hooks, so their tests assert that hooks fire under `FakeClient` and that nothing depends on PATH.

| # | Bug | Where on `main` | Evidence |
|---|---|---|---|
| B1 | SDK mode never loads the hook settings: `SDKDispatcher` sets `self._settings_path = settings_path` (None) after the parent class resolved it | `sdk_dispatch.py:617`; caller `iteration.py:1202` | E4 |
| B2 | `NOUS_ITER_DIR` is never exported, so the Stop hook would block forever and the plan enforcer allows everything | only `plot_specs.py:74` sets it; read at `bin/nous-execute-stop:42` | E4 |
| B3 | Prompts call a bare `nous validate`, which resolved to another checkout and crashed in all 9 runs. One agent wrote its own lenient check and passed itself. | `execute_analyze_thin.md:37`, `design_thin.md:34` | E4 |
| B4 | Nothing checks that the hooks or the validator work | n/a | E4 |
| B5 | A `findings.json` schema failure fails the iteration permanently, dropping its results and principles | `iteration.py:1541-1546`, `campaign.py:435-440` | #328, E4 |
| B6 | The executor's validation result is ignored ("trust the agent") | `iteration.py:1496-1502` | E4 |
| B7 | The 1 MB SDK message buffer: one PDF read killed an iteration | `max_buffer_size` is never set | #327 |
| B8 | The continue gate said "fully fixed" and then "continue" | continue gate | #329 |
| B9 | A gateway stream drop (`ProcessError` exit 143) is classified as permanent | `sdk_dispatch.py:565-573` | #315 |
| B10 | Summary calls log `cost_usd: None`, so the cost log undercounts | `llm_dispatch.py:900` | E2 |
| B11 | Agents' own counters are trusted: a search used 204 evaluations against a limit of 200 | n/a | E1 |
| B12 | No handling of replies cut at the output limit | n/a | E9 |

---

## 6. Out of scope

- Migrating old campaigns, and resuming an old-Nous campaign with v2. Old campaigns stay readable and resumable with old Nous on `main`. Seeding a new v2 campaign with an old campaign's `principles.json` is a follow-up.
- The cross-campaign registry.
- The paper text.
- The Frontier-CS design profiles v2–v8 on `aiopslab`. Only the cost meter and the effort helper are ported.

---

## 7. How it gets built

One long Claude Code build session (Ralph-style, kept going by `/goal`), started with `caffeinate -i` so the machine stays awake. It follows the repo's own contributor workflow (`docs/contributing/workflow.md`), with the plan file standing in for that workflow's plan step.

### 7.1 Files on the branch

- `docs/plans/nous-v2/SPEC.md`: this issue, verbatim.
- `docs/plans/nous-v2/plan.json`: items `{id, title, depends_on[], tests[], acceptance[], passes:false}`. `tests[]` lists the new test ids. Only the build session flips `passes`. The session writes this file first, from 7.2, and a human (or a reviewer acting for one) approves it before any code is written.
- `docs/plans/nous-v2/progress.txt`: append-only, one block per item: what was done, test results before and after, review findings and how each was handled.
- `BLOCKED.md`: written only when the session cannot proceed. The session stops when this file exists.

If the session crashes or drifts, a new session continues from `plan.json`, `progress.txt` and git.

### 7.2 Items (risky first; one item at a time)

| Id | Item | Depends on |
|---|---|---|
| R1 | SDK lock bump (first commit); `orchestrator/v2/session.py` with `client_factory`; options (3.1); session id persistence; transient error classes (B9); buffer (B7); output-token env; `FakeClient` and the guard extension (3.11) | none |
| R2 | JSON schemas and validators for every artifact (3.4), secret masking (3.14), `parameters{}` and `workload_changes[]` lock checks, per-finding noise, `claims_needed` requirements, PARTIALLY_CONFIRMED: extra-field handling (B5), evidence rules, noise honesty rule, paired-seed check, `task_limits` (B11), the bundle hash lock | R1 |
| R3 | The in-process hooks (3.3): the `runs.jsonl` recorder (with `output_bytes`), experiment-command matching (3.9), the Stop gate counter, the PreCompact digest | R1, R2 |
| R4 | The v2 loop (3.2): the BASELINE phase, the campaign worktree with a commit per phase, principles in every DESIGN message, `wait_for` polling, phases as turns, ledger fields, repair and the failure breaker (3.5), the stop rule (3.6), deterministic gates (B8), preflight (B4), no ignored validation results (B6) | R1–R3 |
| R5 | Cost meter port (3.10, B10) | R1 |
| R6 | Effort ladder and cut-off handling (3.10, B12), with recorded-transcript fixtures | R1, R4 |
| R7 | Resume and fallback, `session_scope: iteration` (through the fallback path), `--note`, persisted cost/time totals, STOP sentinel, process-group cleanup (3.7) | R4 |
| R8 | Light method prompt, task-type checklists and phase messages (3.12) | R2 |
| R9 | Final answer check from the record (3.8), optional re-run | R4 |
| R10 | Live smoke (7.4) | R4–R9 |
| R11a | CLI cutover per section 4: `run`/`resume` call v2; `--agent` warns; new and legacy `campaign.yaml` keys; other commands pointed at v2 or deprecated | R10 |
| R11b | Delete the old planner/executor orchestration (`iteration.py`/`campaign.py` loop) and the inline/cli/llm dispatch code, with their tests | R11a |
| R11c | Delete the shell hooks (`bin/nous-*`), the settings-template hook wiring, and the gate-summary calls | R11a |
| R11d | Delete the critic and complexity_tier readers; migrate remaining `bundle.yaml` / `experiment_plan.yaml` readers, templates and docs to JSON | R11a |
| R12 | Docs: `README.md`, `docs/architecture.md`, `docs/data-model.md`, `CLAUDE.md`, CLI help | R11a–R11d |
| R13 | Merge-bar evaluation and up to 3 improvement rounds (section 10), then the held-out p225 run and `EVAL_REPORT.md` | R12, and a human-set-up `eval.sh` |

**Acceptance for every item:**
- Before implementing, run the item's `tests[]` and expect them to fail; after, expect them to pass. Log both outputs to `progress.txt`.
- `pytest -q` passes with zero failures.
- The live-call guard in `tests/conftest.py` stays.
- A deleted test is allowed only if its module imports a module deleted in the same commit. List the deleted tests in `progress.txt`.

### 7.3 Per-item workflow

For each item, in `plan.json` order (first item whose `depends_on` all pass):
1. **Worktree:** all work happens in the build worktree on `nous-v2-wip`; the main checkout is never touched (`/superpowers:using-git-worktrees`).
2. **Search first:** read the relevant code and reuse what exists (validators, ledger, `locked_parameters`, worktree helpers).
3. **Test first:** write the item's tests, run them and confirm they fail, then implement until they pass (`/superpowers:test-driven-development`). Tests use the fake SDK client (3.11) and never make live LLM calls.
4. **One fresh subagent per item** (`/superpowers:subagent-driven-development`), so the main session's context stays small.
5. **Review before commit:** run `/pr-review-toolkit:review-pr` on the item's diff (code bugs, silent failures, test coverage, type design, comment accuracy). Reason about every finding; fix only those that are valid and necessary, and record each decision in `progress.txt`.
6. **Commit and push:** `pytest -q` green, then commit and push to `nous-v2-wip` on `origin`. Never push to `main` or `nous-v2` directly.
7. **Bigger review** after R4, R9 and R11d: a full `/pr-review-toolkit:review-pr` and `/code-review` over the whole branch, plus a live smoke run (7.4). Fix valid findings as new plan items.

**Rules for every item:** never weaken a test for behaviour that stays; delete a test only together with the module it covers, and list it in `progress.txt`; the `tests/conftest.py` live-call guard stays.

**`/goal` condition:** "every item in `docs/plans/nous-v2/plan.json` has `passes: true` and the last `pytest -q` output in this session shows zero failures, or `BLOCKED.md` exists."

### 7.4 Live smoke (run by a human at the checkpoints)

- **Script:** `~/nous_v2_smoke/smoke.sh`, outside the repo; the build session never runs it or edits it.
- **Task:** the debugging task only (BLIS bug `d8271ee`, from the study harness on `origin/mlsys-exp`).
- **Scale:** about $6 per run and a handful of runs in total. This is a development estimate, not a Nous limit.
- **API key:** the smoke runs use their own key, which only `smoke.sh` can read.
- **Output:** a JSON report written to `docs/plans/nous-v2/smoke/<n>.json`, with mechanics only:
  - hook record count, `runs.jsonl` rows, validator passes, repair attempts, lost rounds;
  - cost, `answer.json` validity, `repro_recorded`.
- **It never shows oracle scores or answer keys.** The formula, search and Frontier-CS tasks are never run during the build, so they stay unseen until the final evaluation.
- **Exit code:** 0 only if `lost_rounds == 0`, the hook record count > 0, `answer.json` is valid, and `repro_recorded` is true.
- **R10 passes only on exit 0.** A failed smoke run becomes a new plan item describing the failure, not a blind retry.

### 7.5 Guardrails and monitoring

- **Branches on `origin`:** commits go to `nous-v2-wip`; when an item's `passes` flips to true, the session opens or updates a draft PR from `nous-v2-wip` into `nous-v2`. The session uses the normal git access of the person who starts it, so its instructions forbid pushing to any other branch.
- **The build session never sees or acts on cost.** Humans watch spend from outside (the gateway's usage page), and stop the session with Ctrl-C if needed. There is no spend pause in the session.
- **Progress reports every 15 minutes.** A small reporter (plain code, no model calls) runs beside the session. It reads `plan.json`, `progress.txt` and the git log, and **edits one status comment** on this issue in place (not a new comment each time): the current item and count done (for example "R3 · 2 of 16 done"), the last commit and whether tests passed, and whether `BLOCKED.md` exists. It keeps running if the session is stuck.
- **The session never rebases.** A human rebases `nous-v2-wip` on `main` after R4 if `main` moved. A conflict at any other time leads to `BLOCKED.md`. Long-lived loop branches have died on merge conflicts [E13].
- **Human touchpoints:**
  1. Approve `plan.json` (the workflow's human gate).
  2. Glance at the first 1–2 items.
  3. After R4: read `progress.txt`, run the first smoke test, rebase if needed.
  4. Review each draft PR into `nous-v2`.
  5. Set up `~/nous_v2_eval/eval.sh` and its sealed keys folder before R13 (section 10).
- **When the merge bar passes,** close this issue with `nous-v2` as the delivered branch. Do not open a PR into `main`.

---

## 8. Decisions to confirm before the build starts

- **D1:** SDK only; drop the `inline` and `cli` dispatch.
- **D2:** default model `claude-opus-4-6` for the merge-bar runs, so they are comparable with the recorded runs. The default can move to a newer model after merge.
- **D3:** `session_scope: campaign` as the default, with `iteration` available.
- **D4:** system prompt = Claude Code preset plus the appended method.
- **D5:** one worktree per campaign, committed at every phase end (3.1).
- **D6:** human gates are optional; the default is auto.
- **D7:** pin the latest `claude-agent-sdk` and Claude Code CLI at build start (3.1), and use the same versions for the final evaluation.

---

## 9. Follow-ups (not in this PR)

- A separate, skeptical evaluator session at campaign end [E6d]. It costs extra; measure the gain first.
- Process-quality scoring in the oracle.
- An experiment comparing per-iteration and per-campaign session scope (D3).
- A deterministic factor-sweep tool for knob-tuning tasks, from the `nousko` branch's `kind: optimization` (zero model calls per sweep). Too large for this PR [E14].

---

## 10. Merge bar (final evaluation, triggered by a human after the build)

**Setup:**
- Model `claude-opus-4-6`, the pinned latest SDK and CLI (D7). Oracle tasks use the harness and sandbox of the study on `origin/mlsys-exp`; p5 uses the Frontier-CS harness on `aiopslab`.
- Nous v2 runs 2 times each on debugging, formula and search, plus 2 times on Frontier-CS p5. The p5 harness stops a run at $25 to match the recorded Claude run; that limit is external and never passed to Nous.
- **Baseline:** the recorded Claude + 4-line prompt runs (L2), 3 per task on the 3 oracle tasks (CLI 2.1.301 [E1]), plus the recorded clean Claude p5 run (50.0 [E5]). They are reused as-is; no baseline is re-run. This is a merge gate, not a paper result, so the CLI version difference is acceptable here. The full experiments after this issue re-run every arm on one version.

**Pass if all hold** (new Nous compared with the Claude baseline only):
1. **Accuracy at least equal to the baseline:**
   - debugging: 2/2 correct;
   - formula: correct rate ≥ the baseline's (2/3);
   - search: search-works rate ≥ the baseline's, and oracle structure facts ≥ the baseline mean minus 0.5;
   - p5: mean ≥ 45.0 (the Claude run scored 50.0; the p5 judge's noise is about ±5 [E5]).
2. **Comparable cost:** mean cost per task ≤ 1.25× the baseline's mean for that task. Old Nous was 1.4–9.4× [E1].
3. **Trail at least equal to the baseline:**
   - claim-evidence coverage (C1) and repro match (R2) ≥ the baseline's;
   - the debugging regression test fails on the buggy code 2/2.
4. **Hooks really ran:** every run's transcript shows hook records, `runs.jsonl` has rows written by the hook, the validators ran at every phase end, and zero rounds were lost.
5. **The method really ran,** checked by script on every iteration of every run:
   - a valid `baseline.json` existed before the first `bundle.json`;
   - `bundle.json` was locked (its hash in the ledger) before the first experiment command of that iteration's EXECUTE in `runs.jsonl`;
   - every hypothesis in `findings.json` has a prediction, a result and at least one evidence item that passes the evidence rules;
   - at least one hypothesis has a control, or `no_control_reason` is set;
   - every claim in `answer.json` traces to a finding.

   A run that fails rule 4 or 5 fails the bar, whatever its score.

**Improvement rounds** (the build session may iterate on the bar; up to 3 rounds):
- **Results, never answers.** The session runs the evaluation through `~/nous_v2_eval/eval.sh <task>`, kept outside the repo. The script prints only the bar's numbers: pass/fail per rule, scores, cost per task, and trail checks. The answer keys, the oracle code and the hidden tests stay in a folder the session cannot read. A pre-isolation Frontier-CS run read hidden test data and scored a contaminated 89.1 on p0, so this boundary is enforced by the sandbox, not by instructions [E5].
- **Only general fixes.** The session may change the method prompt, the task-type checklists, phase messages, validators and hook behaviour. It may not add anything specific to a task: no mention of BLIS, the ITL formula, Pareto configs, Hamiltonian paths or any task's answer. Each change records, in `progress.txt`, the transcript evidence for why it should help and which bar rule it targets. Reason first, then fix only what is valid.
- **A held-out task decides the reported comparison.** The final report also runs Nous v2 2 times on Frontier-CS p225 (set merging), which the session never sees, using the same p5 harness. Its baseline is the recorded clean Claude run on p225 (`p225-claude-sdk-c50m-r1`), re-judged with the same judge. If Nous passes the bar tasks but clearly loses on p225, the report says it overfit.
- **Stop after 3 rounds.** One round is one full evaluation plus fixes. If the bar still fails after round 3, the session stops and writes `docs/plans/nous-v2/EVAL_REPORT.md`: what failed, the evidence, what it tried, and what it would try next. A human decides from there. This is a stopping rule, not a cost rule; the session never sees cost.
- **No clear loss.** With 2 runs per task against 3 recorded runs, one bad run can flip a rule. Before failing an accuracy rule on a borderline result, add up to 2 more runs on that task.

**Cost estimate:** 6 Nous v2 oracle-task runs (rule 2 keeps each near the baseline's $3–$16), plus 2 Nous v2 p5 runs at $25, is about $100 per round. The p225 held-out pair adds about $50 once. No baseline runs.

---

## Evidence

- **E1. Controlled study,** `origin/mlsys-exp`, `experiments/mlsys/`: `REPORT.md`, `figures/summary.json`, `figures/results.json`, per-run `oracle.json`. All arms used CLI 2.1.301 (`REPORT.md`, "What each arm is").
  - Formula C1 0.95 vs 0.75, and R2 0.95 vs 0.48. Debugging D5 1.0 vs 0.67. Search C1 0.54 vs 0.75.
  - Search works (`B1_main`): 2/3, 3/3 and 2/3. Oracle `T_score` means: L2 2.0, Nous-prompt 1.33, Nous 0.67.
  - Hand-graded structure facts, read on 2026-10-21 counting only explicit statements: 2.7, 1.7 and 1.0.
  - Nous search hypervolume (`B3_hv_main`): 0.9949 and 0.9968 (rep4 scored 0 for exceeding the evaluation budget). Nous-prompt: 0.9951–0.9968.
  - Rep4 used 204 evaluations. Its `ws/search.py` docstring says: "These probes do NOT count toward the search budget."
  - `experiments/mlsys/NOUS_LESSONS.md` §5.2 proposes a design step that lists "the exact claims the research question needs and how each is tested", and "a short 'framing checklist' per task type (verification, debugging, search) rather than one 30 KB generic design prompt".
- **E2. Cost analysis of the 9 Nous runs:** transcripts under `runs/*/nous/rep*/claude_cfg/projects/`, recomputed with one count per message id, matching `meta.json`. (Analysis scripts are local; they re-derive these numbers from the archived run transcripts and can be committed on request.)
  - Design $108.1, execute $41.1, packaging $10.2 (study harness, not Nous), out of a $159.3 transcript total.
  - Design ran 245 `blis run`/`search.py` commands and execute 158. Of 206 executor simulator invocations, 74 repeated designer flags exactly.
  - Search rounds 2+ cost $72.45 over about 407 min.
- **E3. Original case studies,** `_nous_paper/succesful_campaigns_jun16/`:
  - Design $463 of $1,135 across 19 campaigns with cost logs.
  - Flow-control iteration-2 design ran about 16–18 probe runs; s390x design ran 55 experiment runs vs 4 in execute.
  - Quote: `flow-control-reflective-v2/runs/iter-3/design_log.md`.
- **E4. Hook investigation of the 9 runs:**
  - No hook records in any transcript.
  - The settings file sits at `nous_work/<run>/.claude/settings.json`, outside the session cwd.
  - `nous validate` crashed in every run with `PermissionError` while importing another checkout.
  - pd rep2 lost iterations 2–4. Its ledger reads: "findings.json failed schema validation: Additional properties are not allowed ('mode', 'raw_results_summary' were unexpected)".
- **E5. Frontier-CS,** `aiopslab` branch, `experiments/frontiercs/README.md` and `NOUS_IMPROVEMENT_LOG.md`:
  - The $25 table: p5 57.0 vs 50.0. The task-selection table lists the p5 judge noise as about ±5 (step scoring).
  - The $50 focus table: p0 81.47 vs Claude 26.43 in-run, 20.45 re-judged.
  - Repeats are noisy: p181 scored 12.78 and 47.67.
- **E6. Anthropic guidance:**
  - (a) "Optimizing for cost and intelligence", https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence
  - (b) "Scaling Managed Agents" (2026-04-08), https://www.anthropic.com/engineering/managed-agents
  - (c) "Effective harnesses for long-running agents" (2025-11-26), https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
  - (d) "Harness design for long-running application development" (2026-03-24), https://www.anthropic.com/engineering/harness-design-long-running-apps
- **E7. Planning in one session:**
  - Claude Code best practices (explore, plan, implement, commit): https://code.claude.com/docs/en/best-practices
  - The planner quote is from E6d.
- **E8. Prompt size:** `prompts/methodology/design.md` is 30,704 B and `execute_analyze.md` is 13,603 B. Both are concatenated into the system prompt by `sdk_dispatch.py:54-80`.
- **E9. Output cut-offs:**
  - `aiopslab`: `NOUS_IMPROVEMENT_LOG.md` §12 and `docs/design-profile-v8.md`. Claude p58 had 4 of 5 replies at exactly 64,000 output tokens, and the CLI exited with "response exceeded the 64000 output token maximum". `MAX_THINKING_TOKENS` was ignored on opus-4-6, 5 and 5-5; only `--effort` changed output length. A resume with a different effort kept context (live check, 2026-10-19).
  - The remedies for `stop_reason: max_tokens` (raise `max_tokens` or lower effort) come from https://platform.claude.com/docs/en/build-with-claude/thinking-troubleshooting and https://platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost. The effort levels and defaults are at https://platform.claude.com/docs/en/build-with-claude/effort.
  - https://code.claude.com/docs/en/env-vars: `CLAUDE_CODE_MAX_OUTPUT_TOKENS` is clamped to the model cap, and a larger value reduces the room before auto-compaction. https://platform.claude.com/docs/en/about-claude/models/overview: opus-4-6 and 5.x allow 128K output tokens.
- **E10. Hooks and SDK:**
  - https://code.claude.com/docs/en/hooks-guide: "deterministic control"; a Stop hook is overridden after blocking "eight times in a row with no tool call from Claude in between"; check `stop_hook_active`.
  - https://code.claude.com/docs/en/agent-sdk/hooks: in-process hooks; a `Write|Edit` matcher misses writes made through Bash.
  - Best practices: CLAUDE.md is advisory, hooks are deterministic, and bloated instruction files get ignored.
  - Installed SDK 0.2.163:
    - `types.py`: `hooks`, `HookMatcher.timeout` (60 s default), `env`, `max_buffer_size` (1 MB default in `subprocess_cli.py:36`), `resume`, `effort` (set at connect), the `SystemPromptPreset` with `append` and `snapshot`, and `AssistantMessage.stop_reason`.
    - Hook events: `PreToolUse`, `PostToolUse`, `PostToolUseFailure` (has `error`), `Stop` (has `stop_hook_active`), `PreCompact`.
    - `client.py`: `query`, `receive_response`, `interrupt`, `set_permission_mode`, `set_model`. There is no effort setter.
    - The Bash `tool_response` has no exit-code field.
- **E11.** "Effective context engineering for AI agents" (2025-09-29), https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents: compaction can lose "subtle but critical context".
- **E12. Sessions:** https://code.claude.com/docs/en/agent-sdk/sessions (resume, fork, session ids) and https://code.claude.com/docs/en/sessions (a resumed `-p` session does not restore the permission mode).
- **E13. Ralph practice:**
  - Huntley, https://ghuntley.com/ralph/ (the loop and one item per loop).
  - The Ralph playbook, https://github.com/ghuntley/how-to-ralph-wiggum (the sandbox as the only security boundary).
  - RepoMirror, https://github.com/repomirrorhq/repomirror/blob/main/repomirror.md (a 1,500-word prompt made the agent "slower and dumber"; 103 words fixed it).
  - Horthy, "A Brief History of Ralph", https://www.humanlayer.dev/blog/brief-history-of-ralph (a six-hour refactor PR hit merge conflicts and was never merged; he advises re-running the loop on fresh code).
  - Pocock, "11 Tips", https://www.aihero.dev/tips-for-ai-coding-with-ralph-wiggum.
- **E14. `sriumcp/nousko` branch** (148 commits ahead of merge-base `dc240064`):
  - Failure breaker on 3 identical failure fingerprints, writing `halt.json` (`progress.py`, commit `abb2e4a`). A campaign wasted 4 iterations repeating the same crash before it existed.
  - Process-group reaper (`reaper.py`, commit `abb2e4a`). An orphaned SDK process kept running for 18 hours.
  - Paired seeds for treatment and control (commit `e6225cf`).
  - A build session ran out of context from tool-output volume, not from a cut reply (commits `bf5a4f9`, `66edde0`).
  - Its strict schemas rejected keys the code reads three times (`0fac096`, `a2ea643`, `66edde0`), the same failure as B5.
  - Its design-first mode beat build-only (−10.4% vs +3.65%, `docs/optimization-campaign-guide.md`, `plan` section), which supports DESIGN then EXECUTE in one session.
- **E15. Latest releases,** checked 2026-10-21: PyPI `claude-agent-sdk` 0.2.170 (uploaded 2026-10-21), https://pypi.org/project/claude-agent-sdk/; npm `@anthropic-ai/claude-code` `latest` 2.1.306, https://www.npmjs.com/package/@anthropic-ai/claude-code.
- **E16. Arm types in the original case studies,** `_nous_paper/succesful_campaigns_jun16/**/findings.json` (counted 2026-10-21):
  - main: 167 arms in 25 campaigns, 49% refuted or partly confirmed; robustness: 118 in 19, 50%; control: 122 in 23, 29%; ablation: 70 in 17, 42%; dose-response: 24 in 6, 58%; tradeoff: 14 in 6, 21%; super-additivity: 8 in 5, 37%.
  - Examples where a non-main arm decided the answer: the prefill-decode campaign's ablation arm corrected the formula's cost parameter, and its dose-response arm found the regime boundary (+29% at 120 req/s) (`paper_tex/experiments.tex`, RQ2).
  - Frontier-CS v7: 8 `h-alternative` sessions cost $62 and never improved the best (`aiopslab` `NOUS_IMPROVEMENT_LOG.md` §10, row 4).
- **E17. Time to first real result** (transcripts; Frontier-CS costs at the README token rates, controlled-study costs from transcript usage):
  - Plain Claude: p5 first score 27 at 6.4 min / $0.70; grammar fuzzing 68.8 at 1.9 min / $1.14; p0 18.7 at 4.0 min / $2.49 (c25); debug bug reproduced at 0.9 min / $0.65; verify first sweep at 7.6 min / $3.06; search first `search.py` at 7.4 min / $3.24.
  - Nous v6: p5 first non-zero score 31 at 6.3 min / $5.01; grammar fuzzing 70.1 at 4.8 min / $3.97 (its first measurements scored 0-score stubs). Nous v7: p5 39 at 19.4 min / $13.0.
  - Old Nous (controlled study): executor starts at 20.8 min / about $15.5 (debug), 17.6 min / $16.0 (verify), about 30 min / $7.5 (search).
  - Claude p5 at $50 (`p5-claude-sdk-c50` transcript): scores 27 → 37 → 48 → 57 by about $10, then 55–57 for the remaining $40.
  - Claude's pattern: "Score 27. Let me rewrite with a much better approach ..."; "Score dropped to 33 ... Let me revert"; "Let me submit this and see the score while I think about improvements."
- **E18. Case-study fit check** (26 campaigns in `_nous_paper/succesful_campaigns_jun16/`, read 2026-10-22):
  - Stall rule: `blis-search-algo2/ledger.json` iterations 1–2 have the same arm statuses (all REFUTED), and the main result came in iterations 4–5 (block_size fix, then 99.2% hypervolume). In SELLGM FIND-OPT-3, iterations 7–8 match, and iterations 9–10 found the drain design.
  - Long runs: `debug-flow-control/quartic-mk-2` (the real GPU-cluster campaign) ran 35 iterations over 43.6 h. Each cell was `oc apply && oc wait --timeout=4h`, and `retry_log.jsonl` has 48 `wave_in_flight` retries. onnx-mlir s390x planned runs of up to 1800 s each. The cluster campaign also received a human clarification at iteration 16 (`runs/iter-16/problem.md`).
  - Code carried forward: Graph-Coloring's iteration-2 baseline was iteration 1's DSatur file, and flow-control-reflective-v2's iteration-4 and iteration-5 `h-main.patch` are identical.
  - Noise by condition: SELLGM iteration 6 measured sd 3.9 s at 8 GB vs 0.5 s at 4 GB. quartic-mk-2's baseline noise was 2–19% by rate, and treatment variance was 5.9–7.5× baseline.
  - Early "answered": epp-saturation-detector concluded at iteration 3 from short runs; iterations 4–5 showed sustained runs lose 22%+ (RP-13). memorytime-vector had every arm CONFIRMED on 1 seed at iteration 2, while its pass condition required 5 seeds with bootstrap CIs.
  - Locked parameters: the old check reads `bundle.experiment_spec.verified_parameters` (`validate.py:216`), which v2 drops. Mirage's best result came from a declared workload rewrite.
  - PARTIALLY_CONFIRMED was 43 of 85 statuses in quartic-mk-2. Evidence formats: iter5_streaming_gnn used SQLite (60 files) and TSV (91); flink_torchserve used TSV (106) and JSONL (63).
  - Secrets: `SELLGM.../FIND-OPT-3/runs/iter-1/experiment_plan.yaml` has 7 `sshpass -p` commands, and the password appears 8,714 times in COMPARE-OPT, including `report.md`.
  - Cost sources: `aiopslab` `experiments/frontiercs/README.md` (the SDK's `cost_usd` priced opus-4-6 about 3× low), and `origin/mlsys-exp` `experiments/mlsys/REPORT.md` (the transcript meter matched the CLI's total on 11 of 12 runs, the 12th 0.9% lower).
  - Naming: `flow-control-reflective-v2` is the BLIS simulator campaign; the real-cluster campaign is `debug-flow-control/quartic-mk-2`.

