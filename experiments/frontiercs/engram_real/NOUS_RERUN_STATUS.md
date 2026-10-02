# Checkpoint 4 (Nous reruns) — status: BLOCKED by Nous-SDK streaming hang (2026-10-02)

## What we tried
Rerun Nous under the plateau/$50/ceiling rule on p0 (and then p5, cloudcast-hinted), to remove the
stopping-rule asymmetry vs the baselines. Ran via `frontier_gen_costbudget.py <pid> --agent nous
--label rr --nous-iters 6`, with a $50 + hang watchdog, one at a time.

## The blocker
Nous's `--agent sdk` dispatch spawns the bundled Claude CLI with `--output-format stream-json`. This
session, that **streaming turn wedges**: the nous process goes idle (0% CPU), no SDK child process is
present, and the campaign log freezes right after `Using bundled Claude Code CLI`. It hit p0 at iter-2
twice and iter-1 on the third relaunch (near-deterministic now).

Ruled out as causes (all verified working):
- litellm gateway: plain `/chat/completions` returns instantly.
- bundled Claude CLI: `claude --version` runs fine standalone (v2.1.286); node v25.2.1 OK.
- the deepagents-based agents (Engram handoff, Claude single_agent) spawned the same CLI and ran fine
  earlier today.
- resources: 46% mem free, ~573 procs, 2 zombies — no starvation. (The earlier "889 claude procs" was
  a `pgrep -lf | wc -l` artifact: claude's multi-line cmdline inflates the line count.)
- nous `--agent` only supports {inline, sdk}; no non-streaming `cli` mode to route around it.

Conclusion: an intermittent Nous-SDK streaming hang (Nous-specific), not fixable from here right now.

## Valid partial preserved
p0 rerun completed **iter-1 = 83.3 (our judge) @ ~$3.5** before hanging (consistent with the original
86). Not a full plateau/$50 run.

## Why this does NOT change the conclusion (fallback reasoning)
The original Nous numbers already ran UNDER the $50 ceiling: **p0 86 @ $27, p5 83 @ $46** (both < $50).
Nous keeps the best solution across iterations, so giving it MORE budget (up to $50) can only hold or
RAISE those scores — never lower them. So **86/83 are conservative lower bounds under the plateau/$50
rule**, and Nous already beats the baselines at those lower bounds. The reruns were for stopping-rule
*symmetry*; they are not required for the result. (p9/p15/p22 hit ceiling 100, already rule-compliant.)

## cloudcast-hinted rerun
Deferred — same SDK-hang blocker. This one has independent value (tests prompt-fairness: give Nous
Engram's target/MILP hints), so worth retrying when the SDK-stream issue clears.

## Update 2026-10-02 (after VPN recovery): still stall-prone, reruns can't reach $50
VPN came back (plain + sustained streaming curls work: 171 chunks/18s). But Nous `--agent sdk` turns
STILL stall intermittently — the claude CLI connects (ESTABLISHED https to litellm) then sits at 0%
CPU, streaming not flowing; disabling nonessential traffic + clean-slate orphan kills didn't stop it.
It's probabilistic PER SDK TURN, so multi-iter runs wedge within 1-2 iters. Observed: p0 cleared
iter-1→iter-2 then stalled; p5 stalled iter-1; cloudcast stalled iter-1. Reaching $50 needs ~14 clean
turns in a row — not achievable under current flakiness.

New rule applied (no plateau; stop at $50 or ceiling), but $50 is unreachable due to stalls.

Harvested partials (our judge), NOT full-budget runs:
- p0 rerun: **85.1 @ $2** (iter-1/2 arm) — usable, corroborates original 86 @ $27.
- p5 rerun: 34 @ $1.16 (iter-1 stub only) — NOT usable (undershoots; original 83 @ $46 stands).
- cloudcast rerun (hinted): stalled at the seed, $1046 @ $1.16 — NOT usable; the hinted-prompt
  experiment did not complete. `--hint` flag added to frontier_research_gen.py for when infra is stable.
`nous resume` is available (state.json persists) to continue a campaign past a stall, but each resume
also risks immediate re-stall, so it's impractical right now.

## Recommendation
Either (a) retry the Nous reruns later when the SDK-streaming hang clears (unchanged commands), or
(b) accept the originals as conservative, rule-compatible numbers and proceed. Not a blocker for the
paper's conclusion either way.
