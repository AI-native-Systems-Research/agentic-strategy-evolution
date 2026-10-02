#!/bin/bash
# Driver-agent matrix: claude + engram on tasks {8,147}, 3 seeds. Concurrency 2 (gentler on the
# shared litellm gateway to avoid 429s). Skips runs whose pred JSON already exists (resume-safe).
# claude_text retries 429/5xx with backoff. Nous is run separately. litellm DIRECT via VPN.
set -u
WT="/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/asr-frontier-mac"
FG="$WT/experiments/frontiercs/gen/frontier_gen.py"
OUT="$WT/experiments/frontiercs/artifacts/mac/preds"
LOG="$HOME/frontier/gen_logs"
export PATH="$HOME/.local/bin:$PATH"
export NOUS_REPO="$WT" NOUS_BIN="$WT/.venv/bin/nous"
mkdir -p "$OUT" "$LOG"
MODEL="claude-opus-4-6"
MAXJOBS=2

throttle(){ while [ "$(jobs -rp | wc -l)" -ge "$MAXJOBS" ]; do sleep 5; done; }

run_claude(){ pid=$1; s=$2; label="claude-s$s"; out="$OUT/p${pid}.${label}.json"
  [ -f "$out" ] && { echo "SKIP claude p$pid s$s (pred exists)"; return; }
  python3 "$FG" "$pid" --agent claude --model "$MODEL" --rounds 9 \
    --label "$label" --logdir "$LOG" --out "$out" > "$LOG/run_p${pid}_${label}.log" 2>&1
  echo "DONE claude p$pid s$s -> $(grep RESULT "$LOG/run_p${pid}_${label}.log" | tail -1)"; }

run_engram(){ pid=$1; s=$2; label="engram-s$s"; out="$OUT/p${pid}.${label}.json"
  [ -f "$out" ] && { echo "SKIP engram p$pid s$s (pred exists)"; return; }
  python3 "$FG" "$pid" --agent engram --model "$MODEL" --agents 3 --rounds-per-agent 3 \
    --label "$label" --logdir "$LOG" --out "$out" > "$LOG/run_p${pid}_${label}.log" 2>&1
  echo "DONE engram p$pid s$s -> $(grep RESULT "$LOG/run_p${pid}_${label}.log" | tail -1)"; }

for pid in 8 147; do
  for s in 1 2 3; do
    throttle; run_claude "$pid" "$s" &
    throttle; run_engram "$pid" "$s" &
  done
done
wait
echo "ALL_DRIVER_RUNS_DONE"
