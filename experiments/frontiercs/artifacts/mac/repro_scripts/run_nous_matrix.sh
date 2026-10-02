#!/bin/bash
# Nous matrix: new tasks {8,147}, 3 seeds, full 5-iter budget, concurrency 2 (one p8 + one p147
# per wave). frontier_gen harvests the best arm across all iters (no data loss). litellm DIRECT/VPN.
set -u
WT="/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/asr-frontier-mac"
FG="$WT/experiments/frontiercs/gen/frontier_gen.py"
OUT="$WT/experiments/frontiercs/artifacts/mac/preds"
LOG="$HOME/frontier/gen_logs"
export PATH="$HOME/.local/bin:$PATH"
export NOUS_REPO="$WT" NOUS_BIN="$WT/.venv/bin/nous"
mkdir -p "$OUT" "$LOG"

run_one(){ pid=$1; s=$2; label="nous-s$s";
  python3 "$FG" "$pid" --agent nous --model claude-opus-4-6 --nous-iters 5 \
    --label "$label" --logdir "$LOG" --out "$OUT/p${pid}.${label}.json" \
    > "$LOG/run_p${pid}_${label}.log" 2>&1
  echo "DONE nous p$pid s$s -> $(grep RESULT "$LOG/run_p${pid}_${label}.log" | tail -1)"; }

for s in 1 2 3; do
  run_one 8   "$s" &
  run_one 147 "$s" &
  wait
  echo "WAVE $s done"
done
echo "ALL_NOUS_RUNS_DONE"
