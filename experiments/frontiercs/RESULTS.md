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

## Combined result — 7 tasks (4 seeded + 3 randomly drawn, seed=42)

All three agents, same model/judge. Scores re-evaluated (judge ±5 noise). The 3 "random" tasks
(211, 44, 9) were drawn with `random.seed(42)` from the 110 valid default-type problems, excluding
the first 4 — a pre-committed, non-cherry-picked selection.

| Task | Nous | Engram | Claude | note |
|---|---|---|---|---|
| p0  | **86**  | 55 | 1.5 | Nous |
| p1  | **100** | ~90 | 97 | ~tie (ceiling) |
| p5  | **83**  | 39 | 41 | Nous (2×) |
| p15 | **100** | 0  | 0  | Nous only cracks the gate |
| p211| **87**  | 61 | 62 | Nous |
| p44 | 71      | **78** | 31 | **Engram > Nous** (honest loss) |
| p9  | **100** | 5  | 5  | Nous (both baselines stuck at 5) |

**Tally: Nous best on 5/7, tie at ceiling on p1, loses p44 to Engram.** Nous never loses to plain
Claude. Engram beats Nous once (p44) — a problem where sequential-agent memory suffices and Nous's
extra machinery doesn't pay off. This asymmetric, non-cherry-picked result (random draw, includes a
Nous loss) is the honest controlled-comparison evidence: **the scientific loop helps most on hard,
open-ended problems, and isn't universally dominant.** Nous iters capped at 3 here (early-stop);
Engram cost-matched to Nous's per-task $; Claude run with plateau early-stop.

## Headline results (first 4 tasks; best score achieved per method, with cost)

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

We ran two matched conditions: a light "converge" pass and a **full Nous-equal-budget** pass
(spend up to Nous's per-task $, early-stop on ceiling/plateau).

| Problem | Nous ($) | Engram (best; full-budget behavior) | Claude (best; full-budget behavior) |
|---|---|---|---|
| p5  | **83** ($46) | **39** — plateaued $5.3 (spending more didn't help) | **41** — plateaued $1.4 |
| p0  | **86** ($27) | **55** (fixed $2); full-budget run *plateaued at 22.5*, $5 | **1.5**; full-budget run *plateaued at 1.4*, $11 |
| p15 | **100** ($32) | **0 at the FULL $32 budget** (ran to cost_budget, gate never cracked) | **0** (fixed/cost-matched; Engram already proved 0 at full $32) |

Both baselines **plateau far below Nous** on p0/p5 — once they stop improving, extra budget just
regenerates the same solution (verified: p5 plateaued at $1.4-5.3, not $46). And on the p15 gate,
**Engram spent Nous's entire $32 and still scored 0.** Two failure modes surfaced as findings:
score-only feedback can't tell an agent *why* an output is invalid (p0 packing), and Engram's
journal can anchor later agents on a failing approach (p0 memory-propagation; high run-to-run
variance, e.g. p0 fixed 55 vs full-budget 22.5).

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

## New tasks (2026-10-01, local Mac): +1 algorithmic, +1 research-track

Broadens task-type coverage: a hard algorithmic problem and the first research-track problem. Same
model (`claude-opus-4-6`), same three agents, same protocol (Claude plateau-stop, Engram cost-matched
to Nous's $ spend, Nous 3 iters). Run locally (direct litellm, no VM tunnel). Research runner:
`gen/frontier_research_gen.py` (solution = `.py`, scored by the problem's own local evaluator).

### p22 — algorithmic ("A+B Problem": Halin-graph tree reconstruction, treewidth-3; score 0-100)

| Agent | score (re-eval 3x) | our $ spend | notes |
|---|---|---|---|
| **Nous** | **100** | $4.85 | solved it; 3 iters, 17.7 min |
| Engram | 0 | $4.93 | 7 fresh agents, cost-matched, all Halin tree-decomposition attempts failed |
| Claude | 0 | $0.84 | 6 rounds, never scores |

**A gate task only Nous cracks (like p15).** Claude and Engram both score 0; Engram spent Nous's full
matched budget across 7 journal-sharing agents and still got 0. Nous's deterministic 100 confirmed on
3 re-evals. Cost-matching does not close the gap.

### cloudcast — research track (multi-cloud broadcast routing; metric = total transfer-cost $, lower is better)

Score reported by the judge is `100/(1+total_cost)`, so the discriminating metric is **total_cost ($),
lower = better**. Deterministic local evaluator (no judge noise). Naive dijkstra baseline = $1046.

cloudcast is **Engram's own published benchmark**. The fair comparator is therefore the **real
Engram** (their actual code, `mit-nms/Engram`, run on the same model Opus 4.6 via litellm), not our
reimplementation. Running it changes the result:

| Agent | transfer-cost $ (lower=better) | our $ spend | notes |
|---|---|---|---|
| **Nous** | **$626** | $9.89 | directed Steiner arborescence (iter-2) |
| **real Engram** (as-is) | **~$624** | ~$52 | their code, Opus 4.6; ties Nous at SOTA |
| human SOTA (their paper) | $626 | — | reference |
| Engram paper (o3 / gpt-5.2) | $622-662 | — | their reported range |
| evolutionary baselines (OpenEvolve/FunSearch/EoH) | $640-696 | — | their paper |
| Claude (chat-loop) | $1107 | $2.0 | plateaus, worse than naive |
| naive dijkstra | $1046 | — | reference anchor |

**On cloudcast, Nous and real Engram are tied at the state of the art** ($626 vs ~$624, both at the
human-expert level), and both find the solver-backed (Steiner/MILP) design that the evolutionary
baselines miss ($640-696). This is **not** a Nous win; it is a tie between the two
experimentation-driven agents, with Nous reaching it at ~5x lower $ (~$10 vs ~$52) — a cost-efficiency
difference, not a quality one. The honest Nous advantage lives on the **algorithmic gate tasks**
(p15, p22, p9) where the baselines score ~0 and only Nous solves, not on cloudcast.

Footnote (do not headline): our earlier *reimplemented* Engram scored only $1077 here under
scalar-score feedback; that number **understated Engram** and is superseded by the real-Engram ~$624.
It stands only as evidence that memory-over-scalar-feedback (our reimpl) is far weaker than Engram's
real tool-enabled agent.

Infra note: the Nous SDK design turn froze once per campaign (p22 iter-1 on first launch, cloudcast
iter-3) — a shared-litellm connection stall. p22 was relaunched clean; cloudcast had already completed
iters 1-2 so its best solution was harvested (deterministic re-eval, no loss) and the dead iter-3
killed.

Artifacts: `artifacts/preds/{p22,cloudcast}.*.json`, `artifacts/nous_runs/{frontier-22,research-cloudcast-nous}/`
(findings, patches, best solution, `llm_metrics.jsonl`), `artifacts/gen_logs/newtasks/` (agent logs +
Engram journal/knowledgebase).

## Real Engram (as-is) vs Nous — gate/headroom subset (2026-10-01)

The Engram rows above use our *reimplementation*. The fair comparator is the **real Engram**
(`mit-nms/Engram` @5295858, run on the same model Opus 4.6 via litellm; setup + patch in
`engram_real/`). We ran it on the discriminating subset under the agreed rule (stop at ceiling /
plateau / ~$50) and **re-scored its best candidate on OUR judge** (same `frontier eval` used for Nous
and Claude), so the numbers are directly comparable.

| Task | Nous (score, $) | real Engram (score, $) | note |
|---|---|---|---|
| p0  | **86** ($27) | 74.8 ($84) | Nous higher, 3x cheaper |
| p5  | **83** ($46) | 49.0 ($69) | Nous higher |
| p9  | **100** ($38) | 55.0 (~$45*) | Nous higher |
| p15 | **100** ($32) | 20.0 (~$70*) | gate — Nous solves, Engram partial |
| p22 | **100** ($4.85) | 0.0 (~$55*) | gate — Nous solves, Engram fails |

\* p9/p15/p22 killed mid-agent (plateau/stuck), so usage was not finalized; cost estimated from agent
count at real Engram's ~$25-30/agent. p0/p5 costs are exact.

**Nous beats real Engram on every task in this subset, and at lower cost** (Engram ~$45-84/task vs
Nous ~$5-46). Two honest refinements over the reimpl story: (1) real Engram is clearly stronger than
our reimpl and than Claude — e.g. p9 55 (our judge) vs reimpl/Claude 5, p0 75 vs reimpl 56 — so it is
*not* stuck at 0 on headroom tasks; (2) but it still does not reach Nous on any of them, and on the
hardest gate (p22, Halin-graph tree decomposition) it scores 0 while Nous solves it (100). The Nous
advantage is a genuine quality gap on hard/gate tasks, now shown against the real system, not a
reimplementation artifact.

Caveats: Engram's own internal score disagreed with our judge on p9 (its log said 5, our judge says
55) — we report OUR judge uniformly across all agents. Engram's per-agent cost (~$25-30, from 5M-token
prompts) makes a strict $50 cap impractical (1-2 agents); p0/p5 overshot to $69-84. Artifacts +
per-task best solutions + logs: `engram_real/gates/`.
