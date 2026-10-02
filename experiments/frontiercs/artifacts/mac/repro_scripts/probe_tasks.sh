#!/bin/bash
# Quick non-saturation probe: claude cost-budget $1.5 (~6 rounds) on candidate hard tasks.
# Keep tasks whose best score lands in a "hard" range (not ~0, not ~100).
set -u
WT="/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/asr-frontier-mac"
FG="$WT/experiments/frontiercs/gen/frontier_gen.py"
LOG="$HOME/frontier/gen_logs"; export PATH="$HOME/.local/bin:$PATH"
mkdir -p "$HOME/frontier/probe"
MAXJOBS=3
throttle(){ while [ "$(jobs -rp|wc -l)" -ge "$MAXJOBS" ]; do sleep 5; done; }
for pid in 185 192 44 46 47 181; do
  throttle
  ( python3 "$FG" "$pid" --agent claude --model claude-opus-4-6 --cost-budget-usd 1.5 \
      --label probe --logdir "$LOG" --out "$HOME/frontier/probe/p${pid}.probe.json" \
      > "$LOG/probe_p${pid}.log" 2>&1
    echo "PROBE p$pid -> $(grep RESULT "$LOG/probe_p${pid}.log"|tail -1)" ) &
done
wait
echo "ALL_PROBES_DONE"
