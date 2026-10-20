#!/usr/bin/env bash
set -euo pipefail

BLIS="./blis"
BASE="--model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded --seed 42"

RATES=(1 2 5 10 15 20 25 30 35 40 45 50 55 60 65 70 75 80 85 90 95 100 110 120 130 140 150)

OUTDIR="final/data"
mkdir -p "$OUTDIR"

echo "rate,mode,itl_mean_ms,ttft_mean_ms,e2e_mean_ms,itl_p99_ms,ttft_p99_ms,completed,injected" > "$OUTDIR/sweep_results.csv"

for RATE in "${RATES[@]}"; do
  for MODE in never always; do
    echo "Running rate=$RATE pd-decider=$MODE ..." >&2
    OUTPUT=$($BLIS run $BASE --pd-decider "$MODE" --rate "$RATE" 2>/dev/null)

    # Extract cluster-level metrics
    CLUSTER=$(echo "$OUTPUT" | python3 -I -c "
import sys, json
data = sys.stdin.read()
# Find the cluster block
blocks = data.split('=== Simulation Metrics ===')
for block in blocks:
    block = block.strip()
    if '\"instance_id\": \"cluster\"' in block:
        # Extract JSON from block
        start = block.index('{')
        end = block.rindex('}') + 1
        j = json.loads(block[start:end])
        print(json.dumps(j))
        break
")

    ITL=$(echo "$CLUSTER" | python3 -I -c "import sys,json; d=json.load(sys.stdin); print(d['itl_mean_ms'])")
    TTFT=$(echo "$CLUSTER" | python3 -I -c "import sys,json; d=json.load(sys.stdin); print(d['ttft_mean_ms'])")
    E2E=$(echo "$CLUSTER" | python3 -I -c "import sys,json; d=json.load(sys.stdin); print(d['e2e_mean_ms'])")
    ITL99=$(echo "$CLUSTER" | python3 -I -c "import sys,json; d=json.load(sys.stdin); print(d['itl_p99_ms'])")
    TTFT99=$(echo "$CLUSTER" | python3 -I -c "import sys,json; d=json.load(sys.stdin); print(d['ttft_p99_ms'])")
    COMPLETED=$(echo "$CLUSTER" | python3 -I -c "import sys,json; d=json.load(sys.stdin); print(d['completed_requests'])")
    INJECTED=$(echo "$CLUSTER" | python3 -I -c "import sys,json; d=json.load(sys.stdin); print(d['injected_requests'])")

    LABEL="AL"
    if [ "$MODE" = "always" ]; then LABEL="AD"; fi

    echo "$RATE,$LABEL,$ITL,$TTFT,$E2E,$ITL99,$TTFT99,$COMPLETED,$INJECTED" >> "$OUTDIR/sweep_results.csv"

    # Save full output
    echo "$OUTPUT" > "$OUTDIR/run_${LABEL}_rate${RATE}.txt"
  done
done

echo "Done. Results in $OUTDIR/sweep_results.csv" >&2
