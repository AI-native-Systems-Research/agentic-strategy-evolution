#!/bin/bash
# SWE-fficiency batch (parallel gen / serial score, Nous early-stops at gold).
# Phase 0: gold (serial) -> per-task expert speedup (early-stop target).
# Phase 1: parallel generation (Claude + Nous; Nous --stop-speedup=gold), JOBS cap.
# Phase 2: serial scoring (CPU-pinned => valid timing).
# Usage: JOBS=2 bash swe_batch.sh <iid1> <iid2> ...
set -uo pipefail
JOBS="${JOBS:-2}"
TASKS="$*"
cd ~/nous_swe/swefficiency && . .venv/bin/activate
set -a; . ~/.nous_env; set +a
mkdir -p ~/nous_swe/preds ~/nous_swe/batch_logs
sem() { while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do sleep 5; done; }
gold_speedup() { python3 -c "import json,glob;fs=glob.glob('logs/run_evaluation/g_$1/*/validation_report_g_$1.json');d=json.load(open(fs[0]));k=list(d)[0];print((d[k].get('perf_report') or {}).get('improvement') or 0)" 2>/dev/null || echo 0; }

echo "=== PHASE 0: gold (serial) ==="
for IID in $TASKS; do
  swefficiency eval --run_id g_$IID --num_workers 2 --instances_regex "$IID" > ~/nous_swe/batch_logs/gold_$IID.log 2>&1
  echo "[gold] $IID = $(gold_speedup $IID)x"
done

echo "=== PHASE 1: parallel generation (JOBS=$JOBS) ==="
for IID in $TASKS; do
  GS=$(gold_speedup $IID)
  sem; ( python ~/nous_swe/swe_gen.py "$IID" --agent claude --out ~/nous_swe/preds/$IID.claude.jsonl --label claude \
         > ~/nous_swe/batch_logs/gen_claude_$IID.log 2>&1; echo "[gen] $IID claude rc=$?" ) &
  sem; ( python ~/nous_swe/swe_gen.py "$IID" --agent nous --nous-iters 5 --stop-speedup "$GS" \
         --out ~/nous_swe/preds/$IID.nous.jsonl --label nous \
         > ~/nous_swe/batch_logs/gen_nous_$IID.log 2>&1; echo "[gen] $IID nous rc=$?" ) &
done
wait
echo "=== PHASE 1 DONE ==="

echo "=== PHASE 2: serial scoring ==="
for IID in $TASKS; do
  [ -s ~/nous_swe/preds/$IID.claude.jsonl ] && swefficiency eval --run_id c_$IID --num_workers 2 \
    --prediction_path ~/nous_swe/preds/$IID.claude.jsonl --instances_regex "$IID" > ~/nous_swe/batch_logs/score_c_$IID.log 2>&1
  [ -s ~/nous_swe/preds/$IID.nous.jsonl ] && swefficiency eval --run_id n_$IID --num_workers 2 \
    --prediction_path ~/nous_swe/preds/$IID.nous.jsonl --instances_regex "$IID" > ~/nous_swe/batch_logs/score_n_$IID.log 2>&1
  echo "[scored] $IID"
done
echo "BATCH_DONE"
