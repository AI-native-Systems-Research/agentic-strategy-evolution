# Architecture (Nous v2)

Nous v2 wraps one Claude Code session and forces it through a fixed scientific loop. Python code (not an LLM) decides phase order, checks artifacts, records commands and decides when to stop. All runtime code lives in `orchestrator/v2/`; the CLI entry point is `orchestrator/cli.py`.

## Session (`session.py`)

`nous run` builds one `ClaudeSDKClient` for the whole campaign. `Session.build_agent_options` sets:

- `system_prompt`: the `claude_code` preset with the method prompt appended (`prompts/v2/method.md`, plus `prompts/v2/checklists/<task_type>.md` when `task_type` is set; see `prompts.py`).
- `model` (default `claude-opus-4-6`), optional `effort`, `cwd` = `target_system.repo_path`, `permission_mode="bypassPermissions"`.
- `env`: `CLAUDE_CODE_MAX_OUTPUT_TOKENS` at the model maximum and `NOUS_WORK_DIR`.
- `hooks` from `hooks.py`, and `resume=<session_id>` when resuming.

After each turn the session id is saved to `state.json` with the SDK and CLI versions. Transient errors (process errors, timeouts, API 5xx, "overloaded" results) are retried twice, after 5 s and 30 s, reconnecting with the saved session id (`session.is_transient`).

The client is created through a `client_factory` argument. The CLI passes `cli._sdk_client`; tests pass `tests/fakes/sdk_client.FakeClient`.

## Phases (`loop.py`)

`Campaign` sends one user message per phase into the same session:

| Phase | Message asks for | Artifacts |
|---|---|---|
| BASELINE (once) | one real observation, no hypotheses | `baseline.json` |
| DESIGN (per iteration) | predictions relative to the baseline; active principles are appended | `runs/iter-N/problem.json`, `bundle.json`, `plan.json` |
| EXECUTE (per iteration) | run `plan.json`, fix what does not run | `runs/iter-N/findings.json`, `principle_updates.json` |
| REPORT (once) | the answer | `answer.json`, `report.md` |

Before each phase, `_set_phase` updates the hook state, the cost meter and `state.json` (`phase`, `iteration`).

After DESIGN, Nous copies `bundle.json` to `.bundle.locked.json` and records its sha256 (`bundle_hash`). After EXECUTE, if `bundle.json` no longer matches the hash, Nous restores the locked copy and sets `prereg_violation: true` in the ledger.

If plan runs declare `wait_for` (a path, or `cmd:<shell command>`), Nous polls every 60 s for up to 4 hours without model calls, then sends a turn when runs finish or time out (`robustness.poll_and_resume`).

After each EXECUTE, Nous merges `principle_updates.json` into `principles.json` (`add`, `revise`, `remove` by id) and appends a ledger row (see [data-model.md](data-model.md)).

### Phase commits

After BASELINE, DESIGN, EXECUTE and REPORT, Nous runs `git add -A` and `git commit` in the target checkout with message `nous: <PHASE>` or `nous: iter-N <PHASE>`. The work dir is excluded when it lives inside the target. A target without `.git` is skipped. Git failures are logged, not raised.

## Hooks (`hooks.py`)

Hooks run in-process via `ClaudeAgentOptions.hooks`; there are no shell hooks or settings files.

- **PostToolUse / PostToolUseFailure** (Bash only): append one row per command to `runs.jsonl` with `ts`, `phase`, `iter`, `tool_use_id`, `command` (secrets masked), `exit_code` (0 on success, parsed from the error on failure, `null` for background commands), `output_bytes`, `cwd`, `background`, `agent_id` and `experiment` (whether the command matches `experiment_commands`; defaults match `blis run`, `python *search|bench|run|sweep*.py`, `make bench`).
- **Stop**: validates the current phase's artifacts. On any error it returns `decision: block` with the error list, so the agent keeps working. It allows the stop after 6 consecutive blocks, or while a `wait_for` condition is still pending.
- **PreCompact**: writes `state/digest.json` (phase, iteration, baseline summary, principles, last findings, active hypotheses), with secrets masked.

## Validators, repair and breaker

`validators.py` validates each artifact against `orchestrator/v2/schemas/<name>.schema.json`. Unknown top-level keys are moved into `extra` and never fail. Semantic checks:

- **baseline**: `noise` is one of `{seeds, values, sd}`, `{deterministic: true}`, `{unmeasured: true, reason}`.
- **bundle**: at least 2 distinct `family` values or a `single_family_reason`; each hypothesis has `control` or `no_control_reason`; every `claims_needed` id is covered by some hypothesis `claim_ids`.
- **plan**: treatment and control runs of a controlled hypothesis use the same seeds; `parameters` match `locked_parameters` / `locked_workload` unless the key is in `workload_changes`.
- **findings**: `PARTIALLY_CONFIRMED` needs `partial_note`. `CONFIRMED`/`REFUTED` need `noise_sd`, `noise_unmeasured: true`, or measured baseline noise; with a noise value, `|effect.value|` must exceed 2 × noise sd. Every `hypotheses[].evidence` item must resolve. `task_limits.max_runs` is checked against `runs.jsonl`.
- **principle_updates**: each `finding_ref` is a hypothesis id from the bundle.
- **answer**: claim evidence resolves; no secret value appears in `answer.json` or `report.md`.

Evidence items are `{path, key, value}`. The path is relative to the iteration dir (findings) or the work dir (answer) and must stay inside it. `key` is a JSON Pointer for `.json`, `line@pointer` for `.jsonl`, `column@row` for `.csv`/`.tsv`, and a regex with one capture group for other files. Numbers match with a relative tolerance of 1e-3.

After EXECUTE the loop validates findings and principle updates. On errors it sends a repair turn listing them, up to 2 repairs. If errors remain, the ledger row gets `status: partial`.

`robustness.FailureBreaker` fingerprints failures (type, phase, message with numbers and paths normalised). Three identical failures in a row write `halt.json`. A successful iteration resets it.

`preflight.py` runs before the first turn: it checks validators accept known-good fixtures and reject known-bad ones, and that the Stop hook runs.

## Stop rule (`stop_rule.py`)

Checked after each iteration, in this order:

1. `halt.json` exists: `halt`.
2. `STOP` sentinel exists (`nous stop`): `stop_sentinel`.
3. `findings.question_answered` is true, at least one hypothesis is not `INCONCLUSIVE`, repair status is `ok`, and every `problem.claims_needed` entry is met (claim present, `min_seeds` distinct seeds, a `ci` when `needs_ci`, all `conditions` covered): `answered`.
4. `iteration >= max_iterations`: `max_iterations`.
5. The last `stall_iterations` iterations were all quiet (no change in claims, no `best` improvement above `min_improvement`, no principle add/revise): `stall`.

Any stop reason leads to REPORT.

## Resume (`resume.py`)

`nous resume` reads `state.json` for phase, iteration and session id, and reloads the ledger, principles and previous findings. It resumes the saved session and continues from the saved phase. Resuming at EXECUTE keeps the original `.bundle.locked.json`. Resuming at REPORT only writes the report.

Nous uses a fresh session primed with `state/digest.json` (and the note) when there is no session id, when `session_scope: iteration` is set, or when resuming the saved session fails before any turn succeeds.

## Final check (`final_check.py`)

After REPORT, Nous checks `answer.json` against the record without calling the model or re-running anything. It writes `final_check.json` with:

- `answer_valid` and `evidence_errors` (schema, evidence, secrets),
- `repro_recorded`: some `runs.jsonl` row with exit code 0 contains the `answer.repro` command (or the baseline command) after normalising `export`/`cd` segments, `VAR=` prefixes, pipes and redirections,
- `claims_matched_fraction`: share of the last iteration's `claims_needed` ids present in findings,
- `unmeasured_noise_findings`: hypothesis ids with `noise_unmeasured: true`.

`repro_recorded` and `claims_matched_fraction` are also copied into the last ledger row.

## Cost meter (`cost.py`)

The meter counts each SDK message once by message id and costs it from the `prices` table in `orchestrator/defaults.yaml` (cache reads at 0.1 × input price, cache writes at 1.25 ×). Each ledger row records `cost_meter_usd` and `tokens` for that iteration; the last row also gets `report_cost_usd`. Cost is reported only and never drives a decision. `nous cost` sums these fields.

## Effort (`effort.py`)

`campaign.effort` is passed to the SDK as is. `effort.py` implements the step-down ladder for output cut-offs (`max > xhigh > high > medium > low`, `low` only after 2 consecutive cuts, reset per phase), but the loop does not call it yet.

## Secrets (`secrets.py`)

Values of the env vars named in `campaign.secrets` are replaced with `<secret:NAME>` in `runs.jsonl` and the digest. The answer validator fails if any value appears in `answer.json` or `report.md`.
