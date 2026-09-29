#!/bin/bash
# SWE-fficiency batch: Phase 1 = parallel generation (both agents, capped),
# Phase 2 = SERIAL scoring (isolated CPU pinning => valid timing).
# Usage: JOBS=2 bash swe_batch.sh <iid1> <iid2> ...
set -uo pipefail
JOBS="${JOBS:-2}"
TASKS="$*"
cd ~/nous_swe/swefficiency && . .venv/bin/activate
set -a; . ~/.nous_env; set +a
mkdir -p ~/nous_swe/preds ~/nous_swe/batch_logs

sem() { while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do sleep 5; done; }

echo "=== PHASE 1: parallel generation (JOBS=$JOBS) ==="
for IID in $TASKS; do
  for AG in claude nous; do
    sem
    ( python ~/nous_swe/swe_gen.py "$IID" --agent "$AG" \
        --out ~/nous_swe/preds/$IID.$AG.jsonl --label "$AG" \
        > ~/nous_swe/batch_logs/gen_${AG}_${IID}.log 2>&1; \
      echo "[gen done] $IID $AG rc=$?" ) &
  done
done
wait
echo "=== PHASE 1 DONE ==="

echo "=== PHASE 2: serial scoring (timing isolation) ==="
for IID in $TASKS; do
  swefficiency eval --run_id g_$IID --num_workers 2 --instances_regex "$IID" \
    > ~/nous_swe/batch_logs/score_gold_$IID.log 2>&1 && echo "[gold] $IID ok"
  [ -s ~/nous_swe/preds/$IID.claude.jsonl ] && swefficiency eval --run_id c_$IID --num_workers 2 \
    --prediction_path ~/nous_swe/preds/$IID.claude.jsonl --instances_regex "$IID" \
    > ~/nous_swe/batch_logs/score_c_$IID.log 2>&1 && echo "[claude] $IID ok"
  [ -s ~/nous_swe/preds/$IID.nous.jsonl ] && swefficiency eval --run_id n_$IID --num_workers 2 \
    --prediction_path ~/nous_swe/preds/$IID.nous.jsonl --instances_regex "$IID" \
    > ~/nous_swe/batch_logs/score_n_$IID.log 2>&1 && echo "[nous] $IID ok"
  echo "[scored] $IID"
done
echo "BATCH_DONE"
