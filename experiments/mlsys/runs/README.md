# Per-run artifacts (compact export)

One folder per run: `runs/<task>/<arm>/rep<N>/`, with tasks `dbg`, `pd`, `search` and arms `l2`, `nous_prompt`, `nous`.

| File | What it is |
|---|---|
| `meta.json` | Run metadata: status, iterations, cost (with model breakdown), wall time, Nous commit, CLI version |
| `oracle.json` | Every oracle check for this run (the scores in `../figures/results.json`) |
| `final/` | The arm's output contract: `answer.json` plus the evidence files it cited |
| `ws.diff` | The arm's code change against the task's base repo |
| `search.py` | The delivered search script (search task only) |
| `arm.log`, `proxy.log` | Harness log; one line per LLM request (model, status, bytes, latency) |
| `sessions.json`, `loop_status.json` | L2 / Nous-prompt: per-session result and stop decision |
| `nous/` | Nous only: `report.md`, `principles.json`, `ledger.json`, `llm_metrics.jsonl`, `state.json`, `handoff.md`, and per iteration `bundle.yaml`, `findings.json`, `gate_summary_continue.json`, `principle_updates.json`, `problem.md` |

Not included, because of size: full Claude Code transcripts (about 4.5 GB in total), BLIS build trees, and bulk raw
metric dumps. They are in `mlsys_runs_archive_20261020.tgz` (544 MB) on the original laptop.

To re-score a run, you need the task repos and keys: see `../harness/run_one.py`, `../oracle/score_run.py` and
`../keys/`. Paths there are absolute to `~/mlsys_runs`; set them up first, as described in `../REPRODUCE.md`.
