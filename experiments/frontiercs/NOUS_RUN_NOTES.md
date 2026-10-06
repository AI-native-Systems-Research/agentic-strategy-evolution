# Nous run notes — auth fix + how to launch (so the "SDK hang" never comes back)

## The bug (root cause, 2026-10-05)

Nous `--agent sdk` DESIGN turns hung forever (CLI parked at 0% CPU) **only when launched from
inside a Claude Code session's shell**. Cause: that shell exports `ANTHROPIC_AUTH_TOKEN` (a fleet
token) and `ANTHROPIC_BASE_URL=...vpc-int...`. Any child inherits them, so the bundled `claude` CLI
sends **two conflicting auth headers** — `Authorization: Bearer <fleet token>` *and*
`x-api-key: <IBM gateway key>`. The IBM litellm gateway rejects the conflict (401), which surfaces as
an uncancellable hang on the streaming path.

Proven with a logging proxy: request was `POST /v1/messages?beta=true` carrying both headers →
upstream `401`. Runs launched from a clean terminal (no `ANTHROPIC_AUTH_TOKEN`) always worked — that's
why the original 6 campaigns succeeded and later agent-launched ones hung.

NOT the cause (ruled out): gateway SSE health (raw curl streams fine), CLI/SDK version, plugins/hooks,
the silence watchdog, turn length, effort setting. The VM is no cleaner — its gateway access is a
reverse SSH tunnel from the laptop, so it rides the same path.

## The fix — scope env to the child only, never change it globally

Other agents on this machine need `ANTHROPIC_AUTH_TOKEN`, so do NOT unset it in your shell/profile.
Strip it inline for just the Nous process tree:

```bash
cd .../agentic-strategy-evolution
env -u ANTHROPIC_AUTH_TOKEN \
  ANTHROPIC_BASE_URL=https://ete-litellm.ai-models.vpc.res.ibm.com \
  ANTHROPIC_API_KEY=$IBM_LITELLM_KEY_VPC \
  OPENAI_BASE_URL=https://ete-litellm.ai-models.vpc.res.ibm.com \
  OPENAI_API_KEY=$IBM_LITELLM_KEY_VPC \
  ./.venv/bin/python -u experiments/frontiercs/gen/frontier_gen_costbudget.py <PID> \
    --agent nous --model claude-opus-4-6 --nous-iters 20 --cost-budget 50 \
    --label <LABEL> --out experiments/frontiercs/nous_gates/preds/p<PID>.<LABEL>.json \
    --logdir ~/frontier/gen_logs
```

Sanity check before a long run (should print `OK` in seconds, not hang):
```bash
env -u ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL=https://ete-litellm.ai-models.vpc.res.ibm.com \
  ANTHROPIC_API_KEY=$IBM_LITELLM_KEY_VPC \
  ~/nous_repo/.venv/lib/python3.11/site-packages/claude_agent_sdk/_bundled/claude \
  -p "reply with the single word OK" --model claude-opus-4-6 </dev/null
```

## Gateway / key pairing

- Laptop (direct): `https://ete-litellm.ai-models.vpc.res.ibm.com` + key `$IBM_LITELLM_KEY_VPC` → 200.
- Key `$IBM_LITELLM_KEY_VPCINT` only works against `vpc-int` (reachable from the VM via the tunnel,
  not from the laptop directly).

## $50 budget — must be enforced externally for Nous

`frontier_gen_costbudget.py` enforces `--cost-budget` only for the claude/engram paths. For `--agent
nous` it just runs `--max-iterations`. To honor "$50 or max score": poll cumulative cost from
`~/frontier/gen_logs/nous_runs/<slug>/**/llm_metrics.jsonl` (sum `cost_usd`); when it crosses $50,
`pkill -f 'nous run .*campaign_<pid>.yaml'` — the driver then harvests saved solutions and scores them.

## Artifacts (persisted per iteration automatically)

Under `~/frontier/gen_logs/nous_runs/<slug>/runs/iter-*/`: `inputs/*solution.cpp`, `results/*/score.txt`,
`design_log.md`, `inputs/executor_log.jsonl`. Flushed at turn/iteration end (not mid-turn).

## OPEN ISSUE (2026-10-05 night) — the 90s silence watchdog kills every DESIGN turn

After the auth fix, p26 (high effort) and p26_b (medium effort) both ran but **neither completed a
single turn**. Evidence from `frontier_26_localFIX.nous.log`:
- `ERROR: Iteration 1 failed permanently: SDK still failing after 11 attempts: SDK turn observed >90s
  silence between events; aborting turn` → then force-restart at iteration 2 (same fate).
- `llm_metrics.jsonl` empty (0 rows) on both → no turn booked → cost stuck at $0 → the $50 cap never
  fires → runs churn to the 4h subprocess timeout for nothing.

Root cause: the runner sets `sdk_timeouts.turn_silence_threshold_seconds: 90` (line ~383). But a
logging proxy showed this litellm->Bedrock backend's **time-to-first-byte on the large (~200 KB)
subagent requests is routinely 45–120s, with one 696s gap**. So the 90s watchdog aborts turns that
would have eventually returned. Medium effort did NOT help (same failure) — the blocker is the
threshold vs. backend latency, not reasoning depth. No mid-stream silence, no backend errors.

**RESOLVED (2026-10-06):** `turn_silence_threshold_seconds` raised 90 -> **900** in
`frontier_gen_costbudget.py`, and `defaults.yaml` max_turns restored to the Oct-1 values
**80/120** (the 40/90 was a debug tweak). Combined with the auth fix (`env -u ANTHROPIC_AUTH_TOKEN`),
this matches the configuration under which the original 6 campaigns completed, but with extra silence
tolerance for the backend's 45-696s TTFB. Next action is to relaunch p26 (high, direct, auth-fixed)
and confirm a turn completes (llm_metrics gets rows, cost > $0) before resuming the queue
(p69, p170, a research task; then Engram, Claude). `NOUS_DESIGN_EFFORT` env hook remains available if
we want to revisit effort later.

Root-cause recap: the backend latency (litellm->Bedrock) was present even on Oct 1 (VM logs show
TimeoutExpired on campaign_5/211). Our two drifts turned survivable slowness fatal: the 90s watchdog,
and local runs inheriting ANTHROPIC_AUTH_TOKEN (VM/ssh runs don't, which is why they survived).

## max_turns note

`~/nous_repo/orchestrator/defaults.yaml` was lowered to design:40 / execute_analyze:90 during debugging
(backup `defaults.yaml.bak_*`). This was orthogonal to the real fix; revert to 80/120 to match the
original campaigns if you want identical conditions.
