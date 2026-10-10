#!/bin/bash
# SWE-fficiency batch. Baselines get full budget; Nous early-stops at 1.2x the baseline.
#   Phase 0: gold (serial, skip if report exists) -> expert speedup denominator.
#   Phase 1: Claude gen (parallel) -> score (serial) -> claude speedup per task.
#   Phase 2: Nous gen (parallel, --stop-speedup=1.2*claude) -> score (serial).
# Usage: JOBS=2 bash swe_batch.sh <iid1> ...
set -uo pipefail
JOBS="${JOBS:-2}"
TASKS="$*"
cd ~/nous_swe/swefficiency && . .venv/bin/activate
set -a; . ~/.nous_env; set +a
mkdir -p ~/nous_swe/preds ~/nous_swe/batch_logs
sem() { while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do sleep 5; done; }
report_speedup() { python3 -c "import json,glob;fs=glob.glob('logs/run_evaluation/$1/*/validation_report_$1.json');d=json.load(open(fs[0]));k=list(d)[0];print((d[k].get('perf_report') or {}).get('improvement') or 0)" 2>/dev/null || echo 0; }
has_report() { ls logs/run_evaluation/$1/*/validation_report_$1.json >/dev/null 2>&1; }

echo "=== PHASE 0: gold (serial) ==="
for IID in $TASKS; do
  has_report g_$IID && { echo "[gold] $IID cached = $(report_speedup g_$IID)x"; continue; }
  swefficiency eval --run_id g_$IID --num_workers 2 --instances_regex "$IID" > ~/nous_swe/batch_logs/gold_$IID.log 2>&1
  echo "[gold] $IID = $(report_speedup g_$IID)x"
done

echo "=== PHASE 1: Claude gen (parallel) ==="
for IID in $TASKS; do
  sem; ( python ~/nous_swe/swe_gen.py "$IID" --agent claude --out ~/nous_swe/preds/$IID.claude.jsonl --label claude \
         > ~/nous_swe/batch_logs/gen_claude_$IID.log 2>&1; echo "[gen claude] $IID rc=$?" ) &
done
wait
echo "=== PHASE 1b: Claude score (serial) ==="
for IID in $TASKS; do
  [ -s ~/nous_swe/preds/$IID.claude.jsonl ] && swefficiency eval --run_id c_$IID --num_workers 2 \
    --prediction_path ~/nous_swe/preds/$IID.claude.jsonl --instances_regex "$IID" > ~/nous_swe/batch_logs/score_c_$IID.log 2>&1
  echo "[claude] $IID = $(report_speedup c_$IID)x"
done

echo "=== PHASE 2: Nous gen (parallel, early-stop at 1.2x claude) ==="
for IID in $TASKS; do
  CL=$(report_speedup c_$IID); STOP=$(python3 -c "print(round(1.2*float('$CL'),3) if float('$CL')>0 else 0)")
  sem; ( python ~/nous_swe/swe_gen.py "$IID" --agent nous --nous-iters 5 --stop-speedup "$STOP" \
         --out ~/nous_swe/preds/$IID.nous.jsonl --label nous \
         > ~/nous_swe/batch_logs/gen_nous_$IID.log 2>&1; echo "[gen nous] $IID stop=$STOP rc=$?" ) &
done
wait
echo "=== PHASE 2b: Nous score (serial) ==="
for IID in $TASKS; do
  [ -s ~/nous_swe/preds/$IID.nous.jsonl ] && swefficiency eval --run_id n_$IID --num_workers 2 \
    --prediction_path ~/nous_swe/preds/$IID.nous.jsonl --instances_regex "$IID" > ~/nous_swe/batch_logs/score_n_$IID.log 2>&1
  echo "[nous] $IID = $(report_speedup n_$IID)x"
done
echo "BATCH_DONE"
