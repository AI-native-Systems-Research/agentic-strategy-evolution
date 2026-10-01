#!/bin/bash
# Cost-matched matrix on new hard tasks. Per task: claude-cb10 + engram-cb10 (budget $10 trajectory,
# 2 seeds) + nous 3-iter short (2 seeds). Concurrency-capped, resume-safe. litellm DIRECT via VPN.
# Usage: TASKS="44 192 ..." bash run_newtasks_matrix.sh
set -u
WT="/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/asr-frontier-mac"
FG="$WT/experiments/frontiercs/gen/frontier_gen.py"
OUT="$WT/experiments/frontiercs/artifacts/mac/preds"
LOG="$HOME/frontier/gen_logs"
export PATH="$HOME/.local/bin:$PATH"
export NOUS_REPO="$WT" NOUS_BIN="$WT/.venv/bin/nous"
mkdir -p "$OUT" "$LOG"
MODEL="claude-opus-4-6"; MAXJOBS=3
TASKS="${TASKS:?set TASKS env}"
throttle(){ while [ "$(jobs -rp|wc -l)" -ge "$MAXJOBS" ]; do sleep 5; done; }
run(){ pid=$1; agent=$2; s=$3; label=$4; shift 4; out="$OUT/p${pid}.${label}.json"
  [ -f "$out" ] && { echo "SKIP p$pid $label"; return; }
  python3 "$FG" "$pid" --agent "$agent" --model "$MODEL" "$@" \
    --label "$label" --logdir "$LOG" --out "$out" > "$LOG/run_p${pid}_${label}.log" 2>&1
  echo "DONE p$pid $label -> $(grep RESULT "$LOG/run_p${pid}_${label}.log"|tail -1)"; }
# drivers first (fast), then nous
for pid in $TASKS; do for s in 1 2; do
  throttle; run "$pid" claude  "$s" "claude-cb10-s$s"  --cost-budget-usd 10 &
  throttle; run "$pid" engram  "$s" "engram-cb10-s$s"  --cost-budget-usd 10 --rounds-per-agent 4 &
done; done
wait
echo "DRIVERS_DONE_NEWTASKS"
for pid in $TASKS; do for s in 1 2; do
  throttle; run "$pid" nous "$s" "nous3-s$s" --nous-iters 3 &
done; done
wait
echo "ALL_NEWTASKS_DONE"
