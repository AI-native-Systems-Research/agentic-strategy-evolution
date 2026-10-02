# Repro scripts (Frontier-CS Mac cost-matched study)

All driver via `experiments/frontiercs/gen/frontier_gen.py` (agents: claude, engram, nous).
litellm DIRECT via VPN; model claude-opus-4-6. Judge = local Docker (algorithmic track).

- run_driver_matrix.sh    : claude(9 rounds)+engram(3x3) x {8,147} x3 seeds (initial fixed-budget run)
- run_nous_matrix.sh      : nous 5-iter x {8,147} x3 seeds (concurrency 2)
- run_p147_nous.sh        : p147 nous 5-iter s2,s3
- run_costmatch_drivers.sh: claude/engram cost-budget $10 trajectories on 147 (cb10)
- run_newtasks_matrix.sh  : TASKS="44 47 192 185"; claude/engram cb$10 + nous 3-iter, 2 seeds
- probe_tasks.sh          : quick claude $1.5 non-saturation probe for task selection
- build_results.py        : re-eval preds 3x, group by (task,agent), emit results.csv/RESULTS.md

Results: ../RESULTS.md (147+8), ../RESULTS_newtasks.md (44/47/192/185). Preds: ../preds/. Nous metadata: ../nous_raw/.
