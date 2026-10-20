#!/bin/bash
# Reproduce headline numbers: rate sweep + transient model analysis
set -e
cd "$(dirname "$0")/.."

echo "Building BLIS..."
go build -o blis main.go

BASE="./blis run --model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded --seed 42"
mkdir -p final/data

echo "rate,mode,itl_mean_ms,ttft_mean_ms,e2e_mean_ms,completed" > final/data/sweep_results.csv
for RATE in 1 2 5 10 15 20 25 30 35 40 45 50 60 70 80 90 100 110 120 130 140 150; do
  for MODE in never always; do
    echo "rate=$RATE mode=$MODE ..."
    OUT=$($BASE --pd-decider "$MODE" --rate "$RATE" 2>/dev/null)
    python3 -I -c "
import json, sys
text = '''$OUT'''
depth=0; start=-1; results=[]
for i,ch in enumerate(text):
    if ch=='{':
        if depth==0: start=i
        depth+=1
    elif ch=='}':
        depth-=1
        if depth==0 and start>=0:
            try: results.append(json.loads(text[start:i+1]))
            except: pass
            start=-1
for r in reversed(results):
    if r.get('instance_id')=='cluster':
        print(f'$RATE,$MODE,{r[\"itl_mean_ms\"]},{r[\"ttft_mean_ms\"]},{r[\"e2e_mean_ms\"]},{r[\"completed_requests\"]}')
        break
" >> final/data/sweep_results.csv
  done
done

echo ""
echo "Running transient model analysis..."
python3 -I final/iter3_final_analysis.py
echo "Done."
