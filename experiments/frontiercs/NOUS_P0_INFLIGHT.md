# Nous p0 — in-flight tracking handoff (2026-10-08)

Context for resuming after a context-compaction. Two parallel Nous p0 campaigns are running to a
TRUE $50 (as-is, thinking ON, direct, no proxy). Keys/URLs are in the shell env (NOT here): vpc-int
pair = main key `sk-nQas…`; vpc pair = nous-dam key `sk-IDke…`.

## Claude baseline — DONE (committed/pushed, do not re-run)
Isolated, re-judged, cheat-audit CLEAN: p0=79.4 p5=50 p9=100 p15=100 p22=0 p47=94.1, cloudcast
total_cost=659. In README.md / BEST_AT_50.md.

## The two in-flight Nous p0 runs
| run | slug (work_dir under ~/frontier/gen_logs/nous_runs/) | endpoint | driver log | out pred |
|---|---|---|---|---|
| FRESH | frontier-0-freshvpc | vpc + nous-dam | /tmp/nous_p0_driver.out | nous_gates/preds/p0.freshvpc.json |
| RESUME89 | frontier-0-clean50 (resumed) | vpc-int + nQas | /tmp/nous_p0_resume_driver.out | nous_gates/preds/p0.resume89.json |

- FRESH = clean campaign (`nous run` via gen/frontier_gen_costbudget.py). iter-1 was 71.23 (different
  initial algo). The DRIVER auto-harvests+re-judges+writes p0.freshvpc.json when its `nous run` exits.
- RESUME89 = `nous resume <work_dir>/campaign.yaml`, building on iter-1=89.07. Harvest is MANUAL
  (the resume wrapper was stopped): re-judge persisted solutions yourself at the end.
- **89 FLOOR / BACKUP**: frontier-0-clean50 iter-1 = 89.07 (and `.bak_*`). Validated floor; keep it.
  (Had one failed iter-2 from an infra thinking-stall; cosmetic only.)

## Monitoring (combined, every 3 min) — Monitor task "both runs iters/scores/cost"
Per run, from ~/frontier/gen_logs/nous_runs/<slug>/: cumulative cost = dedup sum of
`**/llm_metrics.jsonl` `cost_usd` (use set() — the old wrapper double-counted the top-level file!);
best score = max `SCORE:` across runs/iter-*/results/*/score.txt; iters = count runs/iter-*.

## TRUE-$50 cap (MANUAL — wrappers removed to avoid double-count + shared-binary cross-kills)
When a run's dedup cost >= $50: kill ONLY that run's nous (`nous run` for FRESH, `nous resume` for
RESUME89) and its claude children scoped by cwd (fresh: frontier_0_freshvpc_ws; resume:
frontier_0_clean50_ws — do NOT blanket `pkill _bundled/claude`, it kills both runs). Then:
- FRESH: driver writes p0.freshvpc.json automatically → commit it.
- RESUME89: harvest manually — re-judge every `runs/iter-*/inputs/*solution*.cpp` and
  `frontier_0_clean50_ws/.nous-experiments/**/solution.cpp` on our go-judge
  (`~/frontier/Frontier-CS/.venv/bin/frontier eval algorithmic 0 <cpp> --json`), take best, write
  p0.resume89.json, commit.

## Nous watchdog
Nous's own 15-min silence watchdog handles stalls (my extra wdasst was removed per user). vpc-int
(RESUME89) is the stall-prone endpoint; expect it slow.

## caffeinate
`caffeinate -dimsu` must stay up until BOTH runs finish; kill it only when both are done.

## Decision at end (user)
Keep all three numbers (FRESH, RESUME89, 89-floor); user decides which to report for Nous p0.
