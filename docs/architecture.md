# Architecture (Nous v2)

Nous v2 wraps one Claude Code session and forces it through a fixed scientific loop. Python code (not an LLM) decides phase order, checks artifacts, records commands and decides when to stop. All runtime code lives in `orchestrator/v2/`; the CLI entry point is `orchestrator/cli.py`.

## Session (`session.py`)

`nous run` builds one `ClaudeSDKClient` for the whole campaign. `Session.build_agent_options` sets:

- `system_prompt`: the `claude_code` preset with the method prompt appended (`prompts/v2/method.md`, plus `prompts/v2/checklists/<task_type>.md` when `task_type` is set; see `prompts.py`).
- `model` (default `claude-opus-4-6`), optional `effort`, `cwd` = `target_system.repo_path`, `permission_mode="bypassPermissions"`.
- `env`: `CLAUDE_CODE_MAX_OUTPUT_TOKENS` at the model maximum and `NOUS_WORK_DIR`.
- `setting_sources=["project", "local"]`: the target repo's settings and `CLAUDE.md` load, the user's own `~/.claude` settings, plugins and global `CLAUDE.md` do not.
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

Each message names the absolute artifact paths, so the agent writes into the work dir, not the repo. Before each phase, `_set_phase` updates the hook state and `state.json` (`phase`, `iteration`) and resets the effort ladder.

After every phase (BASELINE, DESIGN, EXECUTE, REPORT) Nous re-validates that phase's artifacts and sends up to 2 repair messages listing the errors. If errors remain, the phase is `partial` (the ledger row of a partial DESIGN or EXECUTE gets `status: partial`) and the loop goes on with the valid content.

After DESIGN, Nous copies `bundle.json` to `.bundle.locked.json` and records its sha256 (`bundle_hash`). After EXECUTE, if `bundle.json` no longer matches the hash, Nous restores the locked copy and sets `prereg_violation: true` in the ledger.

`wait_for` is only for runs started in the background that outlast the turn. It is a file path (must contain `/` or `.`) or `cmd:<shell command>` that exits 0 when done; relative paths and commands resolve in the target repo. The plan validator rejects anything else (for example a bare run id `R1`). After the EXECUTE turn, if `findings.json` and `principle_updates.json` already validate, Nous does not poll. Otherwise it polls every 60 s for up to 4 hours without model calls, then sends a turn when runs finish or time out (`robustness.poll_and_resume`).

After each EXECUTE (and its repair pass), Nous merges `principle_updates.json` into `principles.json` (`add`, `revise`, `remove` by id) and appends a ledger row (see [data-model.md](data-model.md)).

### Phase commits

After BASELINE, DESIGN, EXECUTE and REPORT, Nous runs `git add -A` and `git commit` in the target checkout with message `nous: <PHASE>` or `nous: iter-N <PHASE>`. The work dir is excluded when it lives inside the target. A target without `.git` is skipped. Git failures are logged, not raised.

## Hooks (`hooks.py`)

Hooks run in-process via `ClaudeAgentOptions.hooks`; there are no shell hooks or settings files.

- **PostToolUse / PostToolUseFailure** (Bash only): append one row per command to `runs.jsonl` with `ts`, `phase`, `iter`, `tool_use_id`, `command` (secrets masked), `exit_code` (0 on success, parsed from the error on failure, `null` for background commands), `output_bytes`, `cwd`, `background`, `agent_id` and `experiment` (whether the command matches `experiment_commands`; defaults match `blis run`, `python *search|bench|run|sweep*.py`, `make bench`).
- **Stop**: validates the current phase's artifacts. It first fixes formatting in place (a numeric string where a number is required, an optional field set to `null`, `noise_unmeasured: false`), then reports every remaining schema error at once with its JSON path. On any error it returns `decision: block` with the error list (plus a one-line evidence key reminder when an error is about evidence), so the agent keeps working. A counter tracks consecutive blocks: after 6 in a row the next stop is allowed (the post-phase repair pass takes over). Any Bash command (success or failure) resets the counter, so an agent that is still working is never cut off. The stop is also allowed while a `wait_for` condition is still pending.
- **PreCompact**: writes `state/digest.json` (phase, iteration, baseline summary, principles, last findings, active hypotheses), with secrets masked.

## Validators, repair and breaker

`validators.py` validates each artifact against `orchestrator/v2/schemas/<name>.schema.json`. Unknown top-level keys are moved into `extra` and never fail. Semantic checks:

- **baseline**: `noise` is one of `{seeds, values, sd}`, `{deterministic: true}`, `{unmeasured: true, reason}`.
- **problem**: `claims_needed` is append-only. From iteration 2, every earlier id must still be listed; new ids may be added. A claim answered in an earlier iteration needs no hypothesis again.
- **bundle**: at least 2 distinct `family` values or a `single_family_reason`; each hypothesis has `control` or `no_control_reason`; every `claims_needed` id is covered by some hypothesis `claim_ids`.
- **plan**: treatment and control runs of a controlled hypothesis use the same seeds; `parameters` match `locked_parameters` / `locked_workload` unless the key is in `workload_changes`; `wait_for` is a path or `cmd:<command>`.
- **findings**: `PARTIALLY_CONFIRMED` needs `partial_note`. `CONFIRMED`/`REFUTED` need `noise_sd`, `noise_unmeasured: true`, or measured baseline noise; with a noise value, `|effect.value|` must exceed 2 × noise sd. Every `hypotheses[].evidence` item must resolve. `task_limits.max_runs` is checked against `runs.jsonl`.
- **principle_updates**: each `finding_ref` is a hypothesis id from the bundle.
- **answer**: `repro` must not start with `cd` (it runs from the repository root). Each claim's evidence resolves and its `value` equals the evidence value (`evidence_detail` is checked when present; for a bare path string the value text must appear in the file). No secret value appears in `answer.json` or `report.md`.

### Evidence

An evidence item is `{path, key, value}`. A relative `path` is looked up in order under the iteration dir (findings only), the work dir, then the target repo; the first root that holds the file wins. An absolute path is accepted when it lies inside one of these roots. Errors name the roots searched.

| File | `key` | Example |
|---|---|---|
| `.json` | JSON Pointer (a missing leading `/` is added) | `/p99_ms`, `/runs/0/score` |
| `.jsonl` | `line@pointer`, line numbers from 0 | `1@/p99_ms` |
| `.csv`, `.tsv` | `column@row`, data rows from 0 | `lookup_us@0` |
| other text | regex, group 1 is the value | `p99_ms=([0-9.]+)` |

Numbers and numeric strings match within a relative tolerance of 1e-3 (`"105082"` equals `105082`). A `.json` file that is not JSON gets a direct message: save it as `.txt`/`.log` and use a regex key. See [example-campaign/](example-campaign/README.md) for one of each.

`robustness.FailureBreaker` fingerprints failures (type, phase, message with numbers and paths normalised). Three identical failures in a row write `halt.json`. A successful iteration resets it.

`preflight.py` runs before the first turn: it checks validators accept known-good fixtures and reject known-bad ones, and that the Stop hook runs.

## Stop rule (`stop_rule.py`)

Checked after each iteration, in this order:

1. `halt.json` exists: `halt`.
2. `STOP` sentinel exists (`nous stop`): `stop_sentinel`.
3. `findings.question_answered` is true, at least one hypothesis is not `INCONCLUSIVE`, repair status is `ok`, and every `problem.claims_needed` entry is met (claim present, `min_seeds` distinct seeds, a `ci` when `needs_ci`): `answered`. Declared `conditions` are free text, so they do not gate the stop; each later DESIGN message lists every requirement still unmet, conditions included (a claim covers a condition when its own condition text contains it).
4. `iteration >= max_iterations`: `max_iterations`.
5. The last `stall_iterations` iterations were all quiet (no change in claims, no `best` improvement above `min_improvement`, no principle add/revise): `stall`.

`claims_needed` and claims are taken over all iterations so far (append-only), so a claim answered in iteration 1 still counts in iteration 3. Any stop reason leads to REPORT.

## REPORT

1. The REPORT turn writes `answer.json` and `report.md`; the message restates the output contract (answer every sub-question, claim values copied exactly, repro from the repo root without `cd`).
2. Repair pass on `answer.json`.
3. Repro check: if `runs.jsonl` has no successful run of `answer.repro`, Nous sends one message asking the agent to run it as written from the repository root, then repairs once more. No loop.
4. Evidence export: each claim's evidence file is copied to `<repo>/nous_evidence/<path relative to its root>` and to the same path under the work dir (mtimes kept). `evidence` becomes that repo-relative path string and the `{path, key, value}` item moves to `evidence_detail`, with the new path. A file already in the repo is cited in place. A numeric-string claim `value` becomes a number.
5. Commit the target checkout, then the final check.

## Resume (`resume.py`)

`nous resume` reads `state.json` for phase, iteration and session id, and reloads the ledger, principles and previous findings. It resumes the saved session and continues from the saved phase. Resuming at EXECUTE keeps the original `.bundle.locked.json`. Resuming at REPORT only writes the report.

Nous uses a fresh session primed with `state/digest.json` (and the note) when there is no session id, when `session_scope: iteration` is set, or when resuming the saved session fails before any turn succeeds.

`--note` is appended to the first EXECUTE message after the resume (or to the REPORT message when resuming at REPORT, or to the fallback priming message) and saved as `note` in that iteration's ledger row.

## Final check (`final_check.py`)

After REPORT, Nous checks `answer.json` against the record without calling the model or re-running anything. It writes `final_check.json` with:

- `answer_valid` and `evidence_errors` (schema, evidence, secrets),
- `repro_recorded`: some `runs.jsonl` row with exit code 0 contains the `answer.repro` command (or the baseline command) after normalising `export`/`cd` segments, `VAR=` prefixes, pipes and redirections,
- `claims_matched_fraction`: share of all `claims_needed` ids (union over iterations) that some iteration's findings claim,
- `unmeasured_noise_findings`: hypothesis ids with `noise_unmeasured: true`.

`repro_recorded` and `claims_matched_fraction` are also copied into the last ledger row.

## Cost meter (`cost.py`)

The authority is the CLI's own cost: each `ResultMessage.total_cost_usd` is cumulative for its session id (subagents included), so the meter adds its increase per session. Between results, or when the CLI reports no cost, it prices assistant usage instead, counting each message once by id and keeping the largest usage seen per id (a streamed reply repeats its id). Streamed usage undercounts output tokens, which made the old meter read 15–28% low. Prices for that estimate come from the `prices` table in `orchestrator/defaults.yaml`, which matches the Claude Code CLI (opus $5/$25, sonnet $3/$15, haiku $1/$5 per million input/output tokens; cache reads at 0.1 × input, cache writes at 1.25 ×). A model without a price costs $0. Each ledger row records `cost_meter_usd` and `tokens` for that iteration; the last row also gets `report_cost_usd`. Cost is reported only and never drives a decision. `nous cost` sums these fields.

## Effort (`effort.py`)

`campaign.effort` is passed to the SDK as is (unset means the model default). A turn is cut when the `ResultMessage` or the last main-agent `AssistantMessage` has `stop_reason: max_tokens`; subagent cut-offs do not count. On a cut, Nous steps one level down the ladder `max > xhigh > high > medium > low` (`low` only after 2 consecutive cuts), saves `cut_offs` in `state.json`, reconnects the same session at the lower effort and sends "Your last reply was cut at the output limit. Write and run the simplest correct step first." This is bounded to one retry per ladder step. The next phase resets the ladder and reconnects at the configured effort. Resume keeps the campaign-wide `cut_offs`.

## Secrets (`secrets.py`)

Values of the env vars named in `campaign.secrets` are replaced with `<secret:NAME>` in `runs.jsonl` and the digest. The answer validator fails if any value appears in `answer.json` or `report.md`.
