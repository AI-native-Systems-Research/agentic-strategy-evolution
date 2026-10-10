#!/bin/bash
# Cost-matched driver trajectories: claude + engram iterate until cumulative uniform cost >= $10
# (~2/3 of nous's ~$13), logging (cum_cost, best_score) per round so we can compare all agents at
# equal cost. Tasks 147 & 112, 2 seeds, concurrency 2, resume-safe. litellm DIRECT via VPN.
set -u
WT="/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/asr-frontier-mac"
FG="$WT/experiments/frontiercs/gen/frontier_gen.py"
OUT="$WT/experiments/frontiercs/artifacts/mac/preds"
LOG="$HOME/frontier/gen_logs"
export PATH="$HOME/.local/bin:$PATH"
export NOUS_REPO="$WT" NOUS_BIN="$WT/.venv/bin/nous"
mkdir -p "$OUT" "$LOG"
MODEL="claude-opus-4-6"; BUDGET=10; MAXJOBS=2

throttle(){ while [ "$(jobs -rp | wc -l)" -ge "$MAXJOBS" ]; do sleep 5; done; }

run_claude(){ pid=$1; s=$2; label="claude-cb${BUDGET}-s$s"; out="$OUT/p${pid}.${label}.json"
  [ -f "$out" ] && { echo "SKIP $label p$pid"; return; }
  python3 "$FG" "$pid" --agent claude --model "$MODEL" --cost-budget-usd "$BUDGET" \
    --label "$label" --logdir "$LOG" --out "$out" > "$LOG/run_p${pid}_${label}.log" 2>&1
  echo "DONE claude-cb p$pid s$s -> $(grep RESULT "$LOG/run_p${pid}_${label}.log" | tail -1)"; }

run_engram(){ pid=$1; s=$2; label="engram-cb${BUDGET}-s$s"; out="$OUT/p${pid}.${label}.json"
  [ -f "$out" ] && { echo "SKIP $label p$pid"; return; }
  python3 "$FG" "$pid" --agent engram --model "$MODEL" --rounds-per-agent 4 --cost-budget-usd "$BUDGET" \
    --label "$label" --logdir "$LOG" --out "$out" > "$LOG/run_p${pid}_${label}.log" 2>&1
  echo "DONE engram-cb p$pid s$s -> $(grep RESULT "$LOG/run_p${pid}_${label}.log" | tail -1)"; }

for pid in 147; do
  for s in 1 2; do
    throttle; run_claude "$pid" "$s" &
    throttle; run_engram "$pid" "$s" &
  done
done
wait
echo "ALL_COSTMATCH_DRIVERS_DONE"
