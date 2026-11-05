# Worked example: does a bigger cache lower p99?

This directory is the work dir of a finished campaign on a toy script, `toy_cache.py` (an LRU cache in front of a slow backend). The script and every number are made up. The files were produced by running Nous with a scripted agent, and `tests/lightweight/test_docs_examples.py` checks that they still match what Nous writes.

```
campaign.yaml                  the question
notebook.jsonl                 the agent's notebook: hypotheses, then results with evidence
results/                       run outputs the evidence cites (R1.json R2.jsonl R3.csv R4.txt)
answer.json                    the agent's answer, after Nous's evidence export
nous_evidence/                 evidence copies made by Nous
runs.jsonl                     one row per Bash command (hooks)
final_check.json ledger.json state.json   written by Nous
```

Paths inside these files that pointed at the real work dir or repo are shown as `<work_dir>` and `<repo>`.

## Walkthrough

**1. The task.** Nous sends one message: the research question, plus where to keep the notebook and where to write `answer.json`. The method note in the system prompt says how.

**2. The notebook.** Before each test the agent appends a hypothesis with a prediction. After it, a result with a status and the file holding the number:

```json
{"kind": "hypothesis", "id": "H1", "claim": "more hits mean fewer slow backend misses", "predict": "p99 at 256 entries is at least 10 ms below p99 at 64"}
{"kind": "result", "id": "H1", "status": "confirmed", "evidence": [{"path": "results/R1.json", "key": "/p99_ms", "value": 41.8}, ...]}
```

H1 was confirmed and H2 ("a bigger cache makes each lookup slower") was refuted.

**3. The answer.** The agent wrote `answer.json`. When it tries to stop, the Stop hook checks the answer and the notebook. Each claim's value must equal the value in the cited file, and `repro` must be one command run from the repository root.

**4. The repro.** `runs.jsonl` holds a successful run of the `repro` command, so Nous sends no repro message and `final_check.json` has `repro_recorded: true`.

**5. The challenger.** A fresh read-only session read the answer and notebook. It replied with one gap: every run used concurrency 8. Nous sent that test to the agent, which ran it (R4.txt), added H3 to the notebook and updated the answer. The challenger's reply is in `final_check.json`.

**6. Evidence export.** Nous copied each cited file to `nous_evidence/` (in the target repo and the work dir) and rewrote each claim to the output-contract form:

```json
{"id": "C1", "metric": "p99_ms", "value": 41.8, "condition": "cache_size=256",
 "evidence": "nous_evidence/results/R1.json",
 "evidence_detail": {"path": "nous_evidence/results/R1.json", "key": "/p99_ms", "value": 41.8}}
```

Claim C3 shows the bare path form: with no `evidence_detail`, the file must exist and contain the value text `62.2`.

## Evidence keys, one per format

| Format | Item | Reads |
|---|---|---|
| JSON (pointer) | `{"path": "results/R1.json", "key": "/p99_ms", "value": 41.8}` | field `p99_ms` |
| JSONL (`line@pointer`, from 0) | `{"path": "results/R2.jsonl", "key": "1@/p99_ms", "value": 63.0}` | 2nd line, field `p99_ms` |
| CSV/TSV (`column@row`, data rows from 0) | `{"path": "results/R3.csv", "key": "lookup_us@0", "value": 0.9}` | column `lookup_us`, first data row |
| Text (regex, group 1) | `{"path": "results/R4.txt", "key": "p99_ms=([0-9.]+)", "value": 44.9}` | the first match |

Relative paths resolve against the work dir, then the target repo. Numbers match within 0.1 %, and `"62.2"` equals `62.2`. Save non-JSON output as `.txt` or `.log`, not `.json`.
