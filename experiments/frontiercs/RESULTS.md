# Frontier-CS (algorithmic): Nous vs plain Claude

Controlled head-to-head for the MLSys submission. Both agents use the SAME model
(`claude-opus-4-6` via litellm), the SAME problems, and the SAME judge scorer
(`frontier eval algorithmic`, continuous 0-100 partial credit, higher is better).
The judge has ~±5 run-to-run variance, so every final solution is re-evaluated 3× and we
report the best; Nous deliverables are the best *correct* arm harvested from its persisted
per-arm solutions (not its self-report).

- **plain Claude** = driver-controlled iterative loop: the harness runs the judge and feeds the
  score back to a pure code-generating model call for N rounds, keeping the best (no tool
  orchestration). This is a strong "use the model iteratively" baseline.
- **Nous** = native scientific-experimentation campaign (5 iterations of hypothesis bundles →
  controlled experiment arms → analysis → principles), each arm scored by the same judge.

## Results

| Problem | Type | Nous | Claude | Winner |
|---|---|---|---|---|
| **0** — polyomino packing | hard, huge headroom (human ref ~76) | **86.25** | 1.49 | **Nous** (≈58×) |
| **5** — Hamiltonian-path ratio | mid, headroom | **83.0** | 28.0 | **Nous** (≈3×) |
| **15** — lexicographically-smallest permutation | hard correctness gate | **100** | 0 | **Nous** (Claude never cracked the gate) |
| **1** — treasure/knapsack (clamped) | easy, saturates at ceiling | **100** | 96.81 | Nous (narrow; both near ceiling 100) |

**Nous ≥ Claude on all four**, and wins *decisively* on the three problems with real headroom
(0, 5, 15). On the one problem that saturates the 100 ceiling (1), both are near-perfect and Nous
edges it. This matches the thesis: **the scientific loop pays off precisely when problems are hard
and open-ended; it merely ties when a strong base agent already saturates the task.**

## Cost / time (the honest tradeoff)

| Problem | Nous cost | Nous time | Nous LLM calls | Claude cost | Claude time |
|---|---|---|---|---|---|
| 0  | $27.45 | 185 min | 20 | ~$0.8¹ | ~4 min |
| 1  | $46.49 | 219 min | 28 | ~$0.8¹ | ~4 min |
| 5  | $45.62 | 237 min | 15 | $0.91 | ~4 min |
| 15 | $32.25 | 242 min | 25 | $0.79 | ~4 min |

¹ Claude p0/p1 predate token logging; estimated from p5/p15 (same round count).

Nous costs **~30-50× more** and takes **~50× longer** than plain Claude. The value proposition is
therefore *not* "cheaper/faster" — it is that Nous **solves hard problems the base agent cannot**
(p0 1.5→86, p5 28→83, p15 0→100). Use it where the problem is hard, high-value, and the compute is
justified.

## Caveats (pilot)
- **4 tasks** — a pilot to lock the pipeline and show the effect; scale to ~5-6 spanning difficulty
  for the camera-ready, with a pre-stated selection rule (avoid cherry-pick) and 2-3 seeds/task.
- Nous runs hit practical limits: p0 stopped after iter-4 (diminishing returns), p15 stopped at the
  100 ceiling (iter-2), p5 hit the 4h wall at iter-3. Best scores are from the reached iterations.
- All raw artifacts (per-arm solutions, scores, `llm_metrics.jsonl`, per-round histories) persisted
  under `experiments/frontiercs/artifacts/`.

Runners: `gen/frontier_gen.py` (`--agent claude|nous`). Setup: `SETUP_NOTES.md`, `RUN_ON_MAC.md`.
