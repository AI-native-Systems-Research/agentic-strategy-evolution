# Nous stability debug — hangs / stalls / `exit 143` / slow runs

Investigation of why Nous campaigns on Frontier-CS were hanging, stalling, and taking hours.
Date: 2026-10-05/06. Isolated worktree `frontier-mac`; artifacts under `experiments/frontiercs/artifacts/mac/`.

## Symptoms

- Campaigns sat in DESIGN for 7–47 min with no output, or died with `exit code 143`.
- Earlier successful runs (Sep 30 / Oct 1) took ~15 min to ~3.8 h per campaign.

## Where the time goes (from `nous_raw/*/llm_metrics.jsonl`, 36 campaigns)

| role (phase) | calls | total | avg/call | max/call | avg turns | max turns |
|---|---|---|---|---|---|---|
| planner (DESIGN) | 36 | 612 min | 17 min | 68 min | 42 | 85 |
| executor (EXECUTE_ANALYZE) | 36 | 382 min | 10.6 min | 34 min | 40 | 121 |
| summarizer | 95 | 17 min | 10 s | — | 1 | 1 |

~98% of wall-time is planner + executor: many agentic tool-call turns (median ~38) at slow
per-turn latency. One 47-turn planner took 68 min (~87 s/turn). Judge (`fmeasure`) calls are a
real per-turn cost: 8–10 s on p47/p44, worse on p147 (~104 cases) and the 10 s-limit tasks.

## Root cause of the "hang → fail": `ProcessError` exit 143

The SDK dispatch runs each model turn through the **Claude Agent SDK**, which spawns the `claude`
CLI as a child and reads its output over a **streaming** connection to the litellm→Bedrock gateway.
When the gateway **stalls/drops the long stream**, the SDK's message-reader errors and its task
group **SIGTERMs the child** → child exits **143** (128+15) → surfaced as
`ProcessError: ... (exit code: 143)` / "Fatal error in message reader".

Nous classified this as **permanent**: `orchestrator/sdk_dispatch.py` only mapped class names
containing `ConnectionError / ReadTimeout / WriteTimeout / RemoteProtocolError /
ServerDisconnectedError / TimeoutError` to the retryable `SDKTransientError`. `ProcessError` was
not on that list, so a *transient* gateway hiccup became a *permanent* iteration failure (no retry).

Ruled out as the cause: the **silence watchdog** (`sdk_timeouts.silence_threshold_seconds`,
default 600 s; per-phase live watchdog design 600 / execute 120 / report 240). Raising it to 1800 s
did **not** help — deaths came at ~400–580 s with variable timing, consistent with a gateway
stream drop, not the watchdog.

## The fix (committed)

`orchestrator/sdk_dispatch.py` — add `ProcessError` and message-text match (`exit code 143`,
`message reader`) to the transient set so Nous **retries** the phase (up to `--max-cli-retries`,
default 10) instead of failing the iteration:

```python
transient_signals = (..., "ProcessError")
transient_msg = ("exit code 143" in msg or "exit code: 143" in msg or "message reader" in msg)
if any(sig in cls_name for sig in transient_signals) or transient_msg:
    raise SDKTransientError(f"{cls_name}: {exc}") from exc
```

### Optional exposure-reducers (tested, then reverted to keep defaults original)

Shorter turns are less likely to span a stream drop. These are campaign/`defaults.yaml` levers, not
required by the fix:
- `sdk_options.{design,execute_analyze}.effort: medium` (docs: medium is "adequate + much cheaper").
- `max_turns: design 40 / execute 60` (from 80/120) — fail fast on no-converge blowups
  (`error_max_turns`, ~11 % of planner calls, which waste 17–34 min then retry).

With both applied, a p47 SDK DESIGN completed in **267 s / 12 turns** vs the opus/high default.
`defaults.yaml` is left at the original 80/120 + effort-high in this branch; apply per-campaign if wanted.

## Dominant real-world blocker: gateway degradation (not a Nous bug)

Across one evening, **every** configuration stalled — opus/sonnet × SDK/CLI — DESIGN taking 20–47 min
where it normally takes 10–19 min, plus the 143 drops. The `/health` curl timed out and a trivial
one-word `claude -p` took 22 s. The litellm gateway (shared with other agents' runs) was
overloaded/degraded.

### Control experiment (the proof)

Re-ran the **exact-original** successful setup (p47, opus×3, `--agent sdk`, default timeouts,
`defaults.yaml` reverted) once the gateway recovered:

| metric | value |
|---|---|
| DESIGN | 13.6 min / 44 turns / $3.03 |
| EXECUTE | 9.2 min / 35 turns / $2.08 |
| iteration 1 total | ~23.5 min, **$5.11** |
| score (best arm, re-judged) | **95.37** (agent peak 95.44) |
| 143s / failures | **0** |

This lands on the historical p47 Nous baseline (seeds 95.7 / 96.6). Same code, same config that
stalled 20–47 min and 143-failed two hours earlier ran a clean normal-speed iteration. **Conclusion:
the stalls were transient gateway/load, not a Nous bug.** The 143→retry patch makes Nous resilient
when it recurs.

## v0.3.0 `claude -p` path (alternative, for reference)

`v0.3.0` (worktree `~/frontier/nous-v030`, own venv) predates the SDK: `--agent api` (default) =
`CLIDispatcher` running `claude -p --output-format json` as a blocking subprocess. It has **no
streaming reader and no silence watchdog**, so it structurally **cannot** 143 on a stream drop — it
waits (up to the per-phase `--timeout`) and `CLIDispatcher` retries on non-zero exit. But it is
**equally hostage to a slow gateway**: on the degraded evening, opus DESIGN took 47 min and sonnet
DESIGN >20 min there too. More robust failure surface, same throughput ceiling.

## How to watch progress (no built-in live view in `-p json` mode)

Four live sources:
1. **Nous log** `frontier_<pid>_*.nous.log` — `Transition:` lines = authoritative phase/iteration.
2. **Claude session transcript** `~/.claude/projects/<escaped-cwd>/<uuid>.jsonl` — the agent's
   tool calls + text, written live for SDK sessions (buffered/flushed-at-end for `-p --output-format json`).
3. **Campaign artifacts** `nous_runs/<run_id>/runs/iter-N/` — `bundle.yaml`, `findings.json`,
   `patches/`, `results/` appearing = forward progress.
4. **Process + network** — child `claude` alive with ESTABLISHED :443 connections = connected/working;
   0 % CPU there just means waiting on the model stream, not stuck locally.

A silent transcript + idle CPU + no artifact growth for >> the phase baseline = a real stall.
