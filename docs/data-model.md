# Data model

The agent writes `notebook.jsonl` and `answer.json`; Nous checks both (see [architecture.md](architecture.md#checks)) and writes everything else. [example-campaign/](example-campaign/README.md) has a complete set of files.

An **evidence item** is `{path, key, value}`: a file, a locator inside it, and the value expected there. Key formats and path roots are in [architecture.md](architecture.md#evidence).

## notebook.jsonl (agent)

One JSON object per line, appended as the agent works:

- `{"kind": "hypothesis", "id": "H1", "claim": "...", "predict": "..."}`: written before the test. `id` and `predict` are required.
- `{"kind": "result", "id": "H1", "status": "confirmed|refuted|inconclusive", "evidence": [items]}`: written after it. A confirmed or refuted result needs `evidence`.
- `{"kind": "note", "text": "..."}`: anything else worth keeping.

To update a result, the agent appends a new result line; only the latest one per id is checked.

## answer.json (agent, rewritten by Nous)

Required: `answer` (prose answering every part of the question), `deliverable` (a path or short description), `repro` (one command run from the repository root, relative paths only, no `cd`), `claims`: list of `{id, metric, value, condition, evidence}` plus optional `evidence_detail`. The schema is `orchestrator/lightweight/schemas/answer.schema.json`.

`evidence` is either a path string or an evidence item. At the end, Nous rewrites every claim to the output-contract form: `evidence` is a repo-relative `nous_evidence/...` path (the file is copied into the target repo), the original item moves to `evidence_detail` with the same new path, and a numeric-string `value` becomes a number:

```json
{"id": "C1", "metric": "p99_ms", "value": 41.8, "condition": "cache_size=256",
 "evidence": "nous_evidence/results/R1.json",
 "evidence_detail": {"path": "nous_evidence/results/R1.json", "key": "/p99_ms", "value": 41.8}}
```

The check reads `evidence_detail` when present; otherwise the path must exist and contain the value text.

## Files written by Nous

**runs.jsonl**: one row per Bash command: `ts`, `phase` (`INVESTIGATE`), `iter` (0), `tool_use_id`, `command`, `exit_code`, `output_bytes`, `cwd`, `background`, `agent_id`, `experiment`.

**final_check.json**:

| Field | Meaning |
|---|---|
| `answer_valid`, `evidence_errors` | the answer check (schema, evidence, repro form, secrets) |
| `repro_recorded` | `runs.jsonl` holds a successful run of `repro` |
| `notebook` | counts: `hypotheses`, `confirmed`, `refuted`, `inconclusive`, `notes` |
| `notebook_errors` | the notebook check |
| `challenger` | the reviewer's verdict, `{gap: null, error}` when it failed, or `null` when the answer was not valid |
| `status` | `ok`, or `partial` when the answer still failed its checks after the repair messages |
| `claims_matched_fraction`, `unmeasured_noise_findings` | kept for a stable format; always 0.0 and `[]` |

**ledger.json**: a list with one row: `iteration` (1), `status`, `stop_reason` (`answered` or `partial`), `cost_meter_usd`, `tokens` (`{input, output}`), `repro_recorded`, `nous_version` (3, kept so existing readers parse it).

**state.json**: `phase` (`INVESTIGATE`, `CHALLENGE`, `DONE`), `iteration`, `session_id`, `sdk_version`, `cli_version`, `session_costs` (the CLI's cumulative cost per session id, so a resumed session's spend is not counted twice), `cut_offs` once a reply is cut, and `cost_usd` while in `CHALLENGE`. Merged with atomic writes.

**nous_evidence/**: copies of the files that `answer.json` claims cite, in both the target repo and the work dir.

**state/digest.json**: written by the PreCompact hook; used to prime a fresh session when the context is full.
