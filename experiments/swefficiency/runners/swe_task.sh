#!/bin/bash
# Full per-task pipeline: gold -> claude gen+score -> nous gen+score
set -uo pipefail
IID="$1"
cd ~/nous_swe/swefficiency && . .venv/bin/activate
set -a; . ~/.nous_env; set +a
echo "=== [$IID] GOLD ==="
swefficiency eval --run_id g_$IID --num_workers 2 --instances_regex "$IID" 2>&1 | grep -vE "httpx|HTTP Request|Evaluating inst" | tail -3
echo "=== [$IID] CLAUDE gen ==="
python ~/nous_swe/swe_gen.py "$IID" --agent claude --out ~/nous_swe/preds/$IID.claude.jsonl --label claude 2>&1 | grep -vE "httpx|Warning" | tail -3
swefficiency eval --run_id c_$IID --num_workers 2 --prediction_path ~/nous_swe/preds/$IID.claude.jsonl --instances_regex "$IID" 2>&1 | grep -vE "httpx|HTTP Request|Evaluating inst" | tail -2
echo "=== [$IID] NOUS gen ==="
python ~/nous_swe/swe_gen.py "$IID" --agent nous --out ~/nous_swe/preds/$IID.nous.jsonl --label nous 2>&1 | grep -vE "httpx|Warning" | tail -3
swefficiency eval --run_id n_$IID --num_workers 2 --prediction_path ~/nous_swe/preds/$IID.nous.jsonl --instances_regex "$IID" 2>&1 | grep -vE "httpx|HTTP Request|Evaluating inst" | tail -2
echo "TASK_DONE_$IID"
