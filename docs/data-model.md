# Data model (Nous v2)

The agent writes the artifacts below; Nous validates them against `orchestrator/v2/schemas/*.schema.json` plus the semantic checks in [architecture.md](architecture.md#validators-repair-and-breaker). Run `nous schema <name>` for the full schema. Unknown top-level keys are moved into an `extra` object, never rejected.

Paths: `baseline.json`, `answer.json`, `report.md` sit in the work dir; the rest sit in `runs/iter-N/`.

An **evidence item** is `{path, key, value}`: a file, a locator inside it, and the value expected there. Key formats and path roots are in [architecture.md](architecture.md#evidence). [example-campaign/](example-campaign/README.md) has a complete, valid set of artifacts.

## baseline.json (BASELINE)

Required: `task_type` (`debug|verify|optimize|policy|explain|other`), `command`, `git_sha` (7-40 hex), `observation`, `metrics_path`, `noise`. Optional: `task_type_reason`.

`observation` keys depend on `task_type`:

| task_type | observation |
|---|---|
| `debug` | `{reproduced: true, symptom, expected, actual}` |
| `verify` | `{points: [{condition, predicted, measured}]}`, at least 1 point |
| `optimize` | `{score}`, a number > 0 |
| `policy`, `other` | `{metrics: {...}}`, at least 1 key |
| `explain` | `{symptom, control}` |

`noise` is exactly one of:
- `{seeds: [int], values: [number], sd: number}` (measured),
- `{deterministic: true}`,
- `{unmeasured: true, reason: string}`.

## problem.json (DESIGN)

Required: `task_type`, `claims_needed`: list of `{id, description, test_method}` with optional `min_seeds`, `needs_ci`, `conditions` (list). These declare what must be measured to answer the question; the stop rule and the final check read them. They are append-only: from iteration 2, every earlier id must still be listed.

## bundle.json (DESIGN, locked)

Required: `hypotheses`: list of `{id, role, family, mechanism, prediction, falsified_if, claim_ids}` plus `control` or `no_control_reason`. `prediction` is `{metric, direction}` with `direction` in `increase|decrease|equal|change` and optional `magnitude_or_threshold`. Optional top level: `single_family_reason` (needed when fewer than 2 families).

Nous copies it to `.bundle.locked.json` after DESIGN and restores that copy if EXECUTE edits it.

## plan.json (DESIGN)

Required: `runs`: list of `{id, hypothesis_id, role, command, parameters, seeds}`, `role` in `treatment|control`, `seeds` at least one int. Optional per run: `wait_for` (a file path containing `/` or `.`, or `cmd:<shell>`; only for background runs), `workload_changes` (keys allowed to differ from locked values).

## findings.json (EXECUTE)

Required: `hypotheses`, `question_answered` (bool), `reason`. Optional: `best: {metric, value}`.

Each hypothesis requires `id`, `status` (`CONFIRMED|PARTIALLY_CONFIRMED|REFUTED|INCONCLUSIVE`), `error_type` (`direction|magnitude|regime|shape|none`), `evidence` (list of evidence items). Optional: `partial_note`, `effect: {value (number), note, evidence}`, `noise_sd`, `noise_condition`, `noise_unmeasured`, `noise_reason`, `claims`: list of `{claim_id, metric, condition, value}` with optional `seeds`, `ci` and `evidence`.

## principle_updates.json (EXECUTE)

Required: `updates`: list of `{id, text, finding_ref, action}`, `action` in `add|revise|remove`, `finding_ref` a hypothesis id from the bundle. `scope` (the settings the principle was tested in) is required for `add` and `revise`. Nous merges these into `principles.json` (a list of `{id, text, scope}`).

## answer.json (REPORT)

Required: `answer`, `deliverable` (string), `repro` (one command, run from the repository root, not starting with `cd`), `claims`: list of `{id, metric, value, condition, evidence}` plus optional `evidence_detail`. `report.md` is free-form.

`evidence` is either a path string or an evidence item. After REPORT, Nous rewrites every claim to the output-contract form: `evidence` is a repo-relative `nous_evidence/...` path (the file is copied into the target repo), the original item moves to `evidence_detail` with the same new path, and a numeric-string `value` becomes a number:

```json
{"id": "C1", "metric": "p99_ms", "value": 41.8, "condition": "cache_size=256",
 "evidence": "nous_evidence/runs/iter-1/results/R1.json",
 "evidence_detail": {"path": "nous_evidence/runs/iter-1/results/R1.json", "key": "/p99_ms", "value": 41.8}}
```

The validator checks `evidence_detail` when present; otherwise the path must exist and contain the value text.

## Files written by Nous

**state.json**: `phase`, `iteration`, `session_id`, `sdk_version`, `cli_version`, and `cut_offs` (output cut-offs so far) once one happens. Merged with atomic writes.

**ledger.json**: list of rows, one per iteration, written by `loop.py`. `ledger_entry.schema.json` (`nous schema ledger_entry`) is the exact row shape.

| Field | Meaning |
|---|---|
| `iteration` | iteration number |
| `bundle_hash` | sha256 of the locked bundle |
| `claims_changed` | claim set differs from the previous iteration |
| `best_changed` | `findings.best.value` improved by more than `min_improvement` |
| `principles_changed` | at least one `add` or `revise` |
| `prereg_violation` | `bundle.json` was edited after the lock |
| `status` | `ok`, or `partial` when a DESIGN or EXECUTE repair ran out |
| `stop_reason` | `null`, or `halt`, `stop_sentinel`, `answered`, `max_iterations`, `stall` |
| `cost_meter_usd` | cost meter for this iteration |
| `tokens` | `{input, output}` for this iteration |
| `note` | `--note` text, on the first iteration after a resume |
| `report_cost_usd` | last row only: cost meter for REPORT |
| `repro_recorded` | last row only: from `final_check.json` |
| `claims_matched_fraction` | last row only: from `final_check.json` |

**runs.jsonl**: one row per Bash command: `ts`, `phase`, `iter`, `tool_use_id`, `command`, `exit_code`, `output_bytes`, `cwd`, `background`, `agent_id`, `experiment`.

**final_check.json**: `answer_valid`, `evidence_errors`, `repro_recorded`, `claims_matched_fraction`, `unmeasured_noise_findings` (see [architecture.md](architecture.md#final-check-final_checkpy)).

**nous_evidence/**: copies of the files that `answer.json` claims cite, in both the target repo and the work dir.

**halt.json**: `fingerprint`, `phase`, `message` (failure breaker).

**state/digest.json**: `phase`, `iteration`, `baseline` (`task_type`, `command`, `git_sha`, `noise`), `principles`, `last_findings`, `active_hypotheses` (`id`, `mechanism`). Written by the PreCompact hook; used to prime a fresh session on resume.
