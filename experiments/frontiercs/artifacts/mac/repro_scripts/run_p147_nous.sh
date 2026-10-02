#!/bin/bash
# p147 nous seeds 2 and 3, sequential (s1 already running separately). Resume-safe. litellm DIRECT/VPN.
set -u
WT="/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/asr-frontier-mac"
FG="$WT/experiments/frontiercs/gen/frontier_gen.py"
OUT="$WT/experiments/frontiercs/artifacts/mac/preds"
LOG="$HOME/frontier/gen_logs"
export PATH="$HOME/.local/bin:$PATH"
export NOUS_REPO="$WT" NOUS_BIN="$WT/.venv/bin/nous"
run_one(){ s=$1; label="nous-s$s"; out="$OUT/p147.${label}.json"
  [ -f "$out" ] && { echo "SKIP p147 nous s$s (pred exists)"; return; }
  python3 "$FG" 147 --agent nous --model claude-opus-4-6 --nous-iters 5 \
    --label "$label" --logdir "$LOG" --out "$out" > "$LOG/run_p147_${label}.log" 2>&1
  echo "DONE p147 nous s$s -> $(grep RESULT "$LOG/run_p147_${label}.log" | tail -1)"; }
for s in 2 3; do run_one "$s"; done
echo "ALL_P147_NOUS_DONE"
