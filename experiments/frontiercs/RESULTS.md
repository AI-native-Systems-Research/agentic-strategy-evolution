# Frontier-CS (algorithmic): Nous vs Engram vs plain Claude

Controlled methodology comparison for the MLSys submission. All agents use the SAME model
(`claude-opus-4-6` via litellm), the SAME problems, and the SAME judge scorer
(`frontier eval algorithmic`, continuous 0-100 partial credit, higher is better; ~±5 run-to-run
variance, so finals are re-evaluated 3×).

## Methods
- **plain Claude** — driver-controlled iterative refinement: harness runs the judge, feeds the score
  back to a pure code-gen model call, keeps the best. Strong "use the model iteratively" baseline.
- **Engram-style** — faithful reimplementation of mit-nms/Engram: sequential fresh-context agents +
  on-disk Research Journal/Knowledgebase (persist *reasoning* across handoffs) + Struggle Protocol.
- **Nous** — native scientific-experimentation campaign (hypothesis bundles → controlled experiment
  arms → analysis → compounding principles), each arm scored by the judge.
- Curie — attempted; spike hit a blocker (see the Mac-side notes). Not included yet.

## Headline results (best score achieved per method, with cost)

| Problem | Type | Nous | Engram | Claude |
|---|---|---|---|---|
| **0** — polyomino packing | hard, big headroom (human ref ~76) | **86** ($27) | 55 ($2) | 1.5 ($0.8) |
| **5** — Hamiltonian-path ratio | mid, headroom | **83** ($46) | 39 ($5) | 41 ($1.4) |
| **15** — lexicographically-smallest permutation | hard correctness gate | **100** ($32) | 0 | 0 |
| **1** — treasure/knapsack (clamped) | easy, saturates ceiling 100 | **100** ($46) | ~90 ($2) | 96.8 ($0.8) |

**Ordering on the discriminating problems: Claude ≲ Engram ≪ Nous.** Nous wins every problem with
real headroom (0, 5, 15), often by 2× or more; only Nous cracks the p15 correctness gate (100 vs 0
for both baselines). On the saturated easy problem (1) all three are near the ceiling.

## Cost-matching: is it the methodology, or just more compute?

We re-ran Claude and Engram with a **cost budget equal to Nous's per-task spend** (~$27-46) and the
same early-stop rule Nous uses (stop at ceiling, on plateau, or at budget). Result:

| Problem | Claude fixed → cost-matched | Engram fixed → cost-matched | Nous |
|---|---|---|---|
| p5 | 28 → **41** (plateau $1.4) | 36 → **39** (plateau $5.3) | **83** |
| p0 | 1.5 → stuck 0¹ | 55 → stuck 0¹ | **86** |
| p15 | 0 → 0 (gate, $5) | 0 → 0 (gate, $5.4) | **100** |

¹ Cost-matched p0 runs stalled at 0 (invalid packings) and were capped at ~$5. Root causes are
themselves findings: **score-only feedback** can't tell an agent *why* a packing is invalid, and
**Engram's journal can anchor later agents on a failing approach** (a memory-propagation weakness).
The fixed-budget numbers (Engram 55, Claude 1.5) are their real p0 capability.

**Conclusion:** extra budget bought the baselines *marginal* gains on p5 (both land ~40, still half
of Nous's 83) and **nothing** on p0 or p15. The gap to Nous is **structural — it comes from
controlled experimentation, not from spending more tokens.** Neither baseline cracks the p15 gate at
any budget; Nous does.

## Cost/time context
Nous is the most expensive by far (p0 $27/185min, p5 $46/237min, p15 $32/242min; huge output-token
counts from multi-arm reasoning). Claude ~$0.8-1.4/task, Engram ~$2-5/task. The value proposition is
not efficiency — it is **solving hard, open-ended problems the base agent (and simpler agentic
memory) cannot**, when the compute is justified.

## Caveats (pilot)
- 4 tasks; scale to ~5-6 spanning difficulty for camera-ready, with a pre-stated selection rule and
  2-3 seeds/task (single cost-matched runs showed real variance, e.g. p0).
- Nous runs used early-stop too (p0 after iter-4; p15 at ceiling; p5 hit the 4h wall at iter-3).
- All raw artifacts (per-agent solutions, journals/knowledgebases, `llm_metrics.jsonl`, per-round
  histories) persisted under `experiments/frontiercs/artifacts/`.

Runners: `gen/frontier_gen.py` (`--agent claude|nous|engram`), `gen/frontier_gen_costbudget.py`
(adds `--cost-budget` + early-stop + retry-backoff). Setup: `SETUP_NOTES.md`, `RUN_ON_MAC.md`.
