# Data model (Nous v2)

The agent writes the artifacts below; Nous validates them against `orchestrator/v2/schemas/*.schema.json` plus the semantic checks in [architecture.md](architecture.md#validators-repair-and-breaker). Run `nous schema <name>` for the full schema. Unknown top-level keys are moved into an `extra` object, never rejected.

Paths: `baseline.json`, `answer.json`, `report.md` sit in the work dir; the rest sit in `runs/iter-N/`.

An **evidence item** is `{path, key, value}`: a file, a locator inside it, and the value expected there (see architecture.md for key formats).

## baseline.json (BASELINE)

Required: `task_type` (`debug|verify|optimize|policy|explain|other`), `command`, `git_sha`, `observation` (object), `metrics_path`, `noise`. Optional: `task_type_reason`.

`noise` is exactly one of:
- `{seeds: [int], values: [number], sd: number}` (measured),
- `{deterministic: true}`,
- `{unmeasured: true, reason: string}`.

## problem.json (DESIGN)

Required: `task_type`, `claims_needed`: list of `{id, description, test_method}` with optional `min_seeds`, `needs_ci`, `conditions` (list). These declare what must be measured to answer the question; the stop rule and the final check read them.

## bundle.json (DESIGN, locked)

Required: `hypotheses`: list of `{id, role, family, mechanism, prediction, falsified_if, claim_ids}` plus `control` or `no_control_reason`. `prediction` is `{metric, direction}` with `direction` in `increase|decrease|equal|change` and optional `magnitude_or_threshold`. Optional top level: `single_family_reason` (needed when fewer than 2 families).

Nous copies it to `.bundle.locked.json` after DESIGN and restores that copy if EXECUTE edits it.

## plan.json (DESIGN)

Required: `runs`: list of `{id, hypothesis_id, role, command, parameters, seeds}`, `role` in `treatment|control`. Optional per run: `wait_for` (path, or `cmd:<shell>`), `workload_changes` (keys allowed to differ from locked values).

## findings.json (EXECUTE)

Required: `hypotheses`, `question_answered` (bool), `reason`. Optional: `best: {metric, value}`.

Each hypothesis requires `id`, `status` (`CONFIRMED|PARTIALLY_CONFIRMED|REFUTED|INCONCLUSIVE`), `error_type` (`direction|magnitude|regime|shape|none`), `evidence` (list of evidence items). Optional: `partial_note`, `effect: {value, evidence}`, `noise_sd`, `noise_condition`, `noise_unmeasured`, `noise_reason`, `claims`: list of `{claim_id, metric, condition, value}` with optional `seeds` and `ci`.

## principle_updates.json (EXECUTE)

Required: `updates`: list of `{id, text, finding_ref, action}`, `action` in `add|revise|remove`, `finding_ref` a hypothesis id from the bundle. Nous merges these into `principles.json` (a list of `{id, text}`).

## answer.json (REPORT)

Required: `answer`, `deliverable`, `repro` (command that reproduces the result), `claims`: list of `{id, metric, value, condition, evidence}` where `evidence` is one evidence item. `report.md` is free-form.

## Files written by Nous

**state.json**: `phase`, `iteration`, `session_id`, `sdk_version`, `cli_version`. Merged with atomic writes.

**ledger.json**: list of rows, one per iteration, written by `loop.py`:

| Field | Meaning |
|---|---|
| `iteration` | iteration number |
| `bundle_hash` | sha256 of the locked bundle |
| `claims_changed` | claim set differs from the previous iteration |
| `best_changed` | `findings.best.value` improved by more than `min_improvement` |
| `principles_changed` | at least one `add` or `revise` |
| `prereg_violation` | `bundle.json` was edited after the lock |
| `status` | `ok`, or `partial` when repair ran out |
| `stop_reason` | `null`, or `halt`, `stop_sentinel`, `answered`, `max_iterations`, `stall` |
| `cost_meter_usd` | cost meter for this iteration |
| `tokens` | `{input, output}` for this iteration |
| `note` | `--note` text, when given on resume |

After REPORT the last row also gets `report_cost_usd`, `repro_recorded` and `claims_matched_fraction`. `ledger_entry.schema.json` describes the row shape loosely (no required fields).

**runs.jsonl**: one row per Bash command: `ts`, `phase`, `iter`, `tool_use_id`, `command`, `exit_code`, `output_bytes`, `cwd`, `background`, `agent_id`, `experiment`.

**final_check.json**: `answer_valid`, `evidence_errors`, `repro_recorded`, `claims_matched_fraction`, `unmeasured_noise_findings`.

**halt.json**: `fingerprint`, `phase`, `message` (failure breaker).

**state/digest.json**: `phase`, `iteration`, `baseline` (`task_type`, `command`, `git_sha`, `noise`), `principles`, `last_findings`, `active_hypotheses` (`id`, `mechanism`). Written by the PreCompact hook; used to prime a fresh session on resume.
