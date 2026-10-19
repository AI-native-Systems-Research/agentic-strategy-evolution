# Design profile v8 (fixed-budget optimization against an automated judge)

`design_profile: v8` is a lightweight profile of the Nous loop for tasks with a fast, automated judge and
a fixed dollar budget (Frontier-CS). Older profiles (`standard`, `lightweight`, `v4`..`v7`) are unchanged.
History, evidence and per-run numbers: `experiments/frontiercs/NOUS_IMPROVEMENT_LOG.md` (sections 10-12).

## Activate

In the campaign YAML:

```yaml
design_profile: v8
v8:                       # all optional; defaults shown
  iteration_budget_usd: 22
  arm_budget_usd: 6
  arm_floor_usd: 4        # smallest screening budget; an arm that cannot get it is skipped, not starved
  winner_share: 0.4       # part of each iteration kept for deepening the winner
  repair_budget_usd: 1    # one repair turn for an arm that crashed or wrote no result
  hang_minutes: 15        # watchdog: no reply for this long behind >=3 API errors restarts the session
  measure_command: "..."  # official measure; else parsed from "MEASURE only with this command:" in the target
  official_log: "..."     # JSONL of official measures {ts, submitted_ts, sha256, score}
```

Frontier-CS launcher: `experiments/frontiercs/gen/nous_v8_c50.sh <pid> <URL env var> <KEY env var> [run tag]`
(keys come from the environment, never the script; `--budget 50 --wall-hours 24 --finish-iteration`).

## What v8 does, and why

| mechanism | why (evidence) |
|---|---|
| caps and spend read from Claude Code transcripts, one count per reply | the stream reported ~10x too few output tokens; v7 caps were overrun (p58 arm $15 on a $2 cap) |
| official-first evaluator: the orchestrator runs the official measure 3x for the baseline and noise | local graders disagreed with the judge (p26 compiler trap, unknown time limits) |
| results rebuilt from the official measures log; base-solution re-measures ignored | agents' own notes lagged the judge (p181 arm 49.55 officially, 12.46 in its file) |
| exploit/explore: an improving iteration deepens one arm, a plateau screens families | spend where the evidence is |
| at most one `h-alternative`; $4 arm floor; 40% winner reserve; first arm reserves its repair | arms were starved or skipped by small overshoots (p5, p26, p0, p58) |
| repair turn, hang watchdog, fallback design when a design is capped | crashed arms and gateway hangs dropped work |
| effort rule (`orchestrator/effort.py`, below) | replies ran to the 64k output limit and were lost (p58, p26) |

## Effort rule

Adaptive-thinking models (opus-4-6, opus-5, opus-5-5) ignore thinking-token budgets (`MAX_THINKING_TOKENS`);
`effort` is the control they honour ([effort docs](https://platform.claude.com/docs/en/build-with-claude/effort)).
Claude Code cuts any reply at 64k output tokens; a cut reply (`stop_reason: max_tokens`) loses its thinking,
and the CLI's own retry redoes the same reasoning. Anthropic's remedy for `max_tokens` is to raise the limit or
lower effort ([steering thinking](https://platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost)).

1. The evaluator session (setup) runs at `medium`.
2. Every other session (design, arms, winner, repair) runs at the model's default (`high`; `medium` on
   opus-5-5 and haiku-5-5), or `sdk_options.<phase>.effort` when the campaign sets one.
3. A reply cut at the output limit stops the session; it resumes one level lower (`low` as a last resort after
   repeated cuts) with a "write and submit the simplest correct solution first" prompt. Each cut also lowers
   every later session one level, never below `medium`. State: `<work_dir>/effort_state.json`.

Each `llm_metrics.jsonl` row records the `effort` used and the session's `max_reply_usd`.

Check a change before running it: `python experiments/frontiercs/gen/replay_effort_ladder.py [slug suffix]`
replays the rule over finished runs and prints each session's effort and cut-offs. On the v8 focus runs only the
evaluator changes on p0, p5, p181 (no cut-offs); p26 and p58 drop to `medium` after their first cut-off.

## Reproduce the probes

`experiments/frontiercs/gen/probe_effort.sh` compares output tokens at two effort levels for opus-4-6, opus-5
and opus-5-5 on both gateways (live calls; a few dollars; never part of the test suite).
