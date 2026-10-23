# Worked example: does a bigger cache lower p99?

This directory is the work dir of a one-iteration campaign on a toy script, `toy_cache.py` (an LRU cache in front of a slow backend). The script and every number are made up, but every file here validates against the v2 schemas (`tests/v2/test_docs_examples.py` checks it). Use it to see what each artifact looks like.

```
campaign.yaml                  the question, locks and objective
baseline.json                  BASELINE (agent)
baseline_metrics.json          the baseline command's output (metrics_path)
runs/iter-1/
  problem.json bundle.json plan.json          DESIGN (agent)
  findings.json principle_updates.json        EXECUTE (agent)
  results/R1.json R2.jsonl R3.csv R4.txt      run outputs the evidence cites
answer.json                    REPORT (agent), after Nous's evidence export
nous_evidence/                 evidence copies made by Nous at REPORT
runs.jsonl                     excerpt: one row per Bash command (hooks)
ledger.json final_check.json   written by Nous
```

## Walkthrough

**1. BASELINE.** The agent runs the cache at 64 entries with 3 seeds. `task_type: optimize` means the observation is `{score}` (here p99 = 62.2 ms). The three seeds give a measured noise sd of 0.75 ms.

```json
"observation": {"score": 62.2},
"noise": {"seeds": [1, 2, 3], "values": [62.1, 63.0, 61.5], "sd": 0.75}
```

**2. DESIGN.** `problem.json` declares two claims the answer needs: C1 (p99 at 256, 3 seeds) and C2 (hit rate at 256). `bundle.json` holds two competing families: H1 "more hits, fewer slow misses" predicts a decrease; H2 "bigger cache, costlier lookups" predicts an increase. Every claim id is covered by some `claim_ids`. `plan.json` pairs each treatment run with a control on the same seeds, and keeps the locked `requests` and `concurrency`. Nous then locks the bundle (`.bundle.locked.json`, `bundle_hash` in the ledger).

**3. EXECUTE.** p99 fell from 62.2 to 41.8 ms. The effect (-20.4 ms) is well above 2 x 0.75 ms, so H1 is `CONFIRMED`. Its `error_type` is `magnitude`, since it predicted ">= 10 ms" and the drop was twice that. H2 is `REFUTED` with `error_type: direction`. `question_answered: true` and both claims are met, so the stop rule returns `answered`.

**4. REPORT.** The agent wrote `answer.json` citing `runs/iter-1/results/R1.json`. Nous then copied that file to `nous_evidence/runs/iter-1/results/R1.json` (in the target repo and the work dir) and rewrote each claim to the output-contract form:

```json
{"id": "C1", "metric": "p99_ms", "value": 41.8, "condition": "cache_size=256",
 "evidence": "nous_evidence/runs/iter-1/results/R1.json",
 "evidence_detail": {"path": "nous_evidence/runs/iter-1/results/R1.json", "key": "/p99_ms", "value": 41.8}}
```

Claim C0 shows the bare path form: with no `evidence_detail`, the file must exist and contain the value text `62.2`. The `repro` command appears in `runs.jsonl` with exit code 0, so `final_check.json` has `repro_recorded: true`.

## Evidence keys, one per format

All from `runs/iter-1/findings.json`. Relative paths resolve against the iteration dir, then the work dir, then the target repo.

| Format | Item | Reads |
|---|---|---|
| JSON (pointer) | `{"path": "results/R1.json", "key": "/p99_ms", "value": 41.8}` | field `p99_ms` |
| JSONL (`line@pointer`, from 0) | `{"path": "results/R2.jsonl", "key": "1@/p99_ms", "value": 63.0}` | 2nd line, field `p99_ms` |
| CSV/TSV (`column@row`, data rows from 0) | `{"path": "results/R3.csv", "key": "lookup_us@0", "value": 0.9}` | column `lookup_us`, first data row |
| Text (regex, group 1) | `{"path": "runs/iter-1/results/R4.txt", "key": "p99_ms=([0-9.]+)", "value": 62.2}` | resolved from the work dir |

Numbers match within 0.1 %, and `"62.2"` equals `62.2`. Save non-JSON output as `.txt` or `.log`, not `.json`.

Check any artifact yourself:

```bash
nous validate execute --dir docs/example-campaign/runs/iter-1
nous validate report --dir docs/example-campaign
```

## Troubleshooting

**Stop-hook blocks.** The agent sees a message like this when it tries to end a phase with invalid artifacts:

```
Phase EXECUTE validation failed:
  - findings: evidence value mismatch at results/R1.json#/p99_ms: expected 41.0, got 41.8
Evidence keys: .json a JSON pointer /a/b; .jsonl N@/ptr; .csv/.tsv col@row; other text a regex with one capture group. Relative paths resolve against the iteration dir, the work dir, then the repository.
```

Other common ones: `evidence path does not exist: ... (searched <roots>)`, `run 'R1': wait_for 'R1' must be a file path or cmd:<command>`, `claims_needed ids may be added, not removed`, `repro must not start with cd`, `|effect| ... <= 2 * noise_sd`. After 6 blocks in a row the stop is allowed; any Bash command resets the count. The repair pass after the phase then sends up to 2 more messages with the same errors.

**Partial iteration.** If errors remain after the repair pass, the ledger row has `"status": "partial"`. The valid content is kept and the loop goes on, but the stop rule never returns `answered` for a partial iteration. Run `nous validate execute --dir <work_dir>/runs/iter-N` to see what is still wrong.

**halt.json.** Three identical failures in a row (same type, phase and message, numbers and paths ignored) write `halt.json` with `fingerprint`, `phase`, `message`. The loop stops with `stop_reason: halt` and still writes the REPORT. Fix the cause, delete `halt.json`, then resume.

**final_check.json.** Written after REPORT, without calling the model:

| Field | Meaning when it is bad |
|---|---|
| `answer_valid: false` | `evidence_errors` lists the schema, evidence or secret problems |
| `repro_recorded: false` | no successful `runs.jsonl` row contains the `repro` command (after dropping `cd`/`export`, `VAR=` prefixes, pipes and redirections) |
| `claims_matched_fraction` < 1 | some `claims_needed` id has no claim in any iteration's findings |
| `unmeasured_noise_findings` | hypotheses that declared `noise_unmeasured: true` |

## Resume

Say the process died during iteration 2's EXECUTE. `state.json` says `{"phase": "EXECUTE", "iteration": 2, "session_id": "..."}`.

```bash
nous status <work_dir>                       # phase, iteration, ledger rows
nous resume <work_dir> --note "use 5 seeds per arm"
```

Nous reconnects to the saved session and continues at iteration 2's EXECUTE. It keeps the original `.bundle.locked.json`, so an edit made before the crash is still a `prereg_violation`. The note is appended to the EXECUTE message and saved as `"note"` in iteration 2's ledger row.

If the session cannot be resumed (no `session_id`, `session_scope: iteration`, or the resume fails before any turn succeeds), Nous starts a fresh session and first sends a priming message built from `state/digest.json` (phase, iteration, baseline summary, principles, last findings, active hypotheses) plus the note. The digest is written before every context compaction.

To stop a running campaign cleanly, `nous stop <work_dir>` writes `STOP`; the loop checks it after the current EXECUTE, then writes the REPORT.
