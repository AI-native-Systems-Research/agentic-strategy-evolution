#!/bin/bash
# Rate sweep for AL (never) and AD (always) modes
# Fixed config: qwen/qwen3-14b, 4 instances (2P+2D), 300 requests, 512 prompt, 128 output tokens
set -e

BLIS="./blis"
BASE_FLAGS="--model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded --seed 42 --log error"
OUTDIR="final/data"
mkdir -p "$OUTDIR"

# Rates to sweep (req/s)
RATES=(1 2 5 10 15 20 25 30 35 40 45 50 60 70 80 90 100 110 120 130 140 150)

echo "rate,mode,completed,ttft_mean_ms,ttft_p99_ms,itl_mean_ms,itl_p99_ms,e2e_mean_ms,e2e_p99_ms,throughput_rps" > "$OUTDIR/sweep_results.csv"

for MODE in never always; do
  if [ "$MODE" = "never" ]; then
    LABEL="AL"
  else
    LABEL="AD"
  fi
  for RATE in "${RATES[@]}"; do
    echo "Running $LABEL rate=$RATE ..."
    OUTPUT=$($BLIS run $BASE_FLAGS --pd-decider "$MODE" --rate "$RATE" 2>/dev/null)

    # Extract cluster-level metrics (last JSON block)
    CLUSTER_JSON=$(echo "$OUTPUT" | python3 -c "
import sys, json, re
text = sys.stdin.read()
# Find all JSON blocks
blocks = re.findall(r'\{[^{}]+\}', text, re.DOTALL)
# Last one is cluster
for b in reversed(blocks):
    d = json.loads(b)
    if d.get('instance_id') == 'cluster':
        print(json.dumps(d))
        break
")

    if [ -z "$CLUSTER_JSON" ]; then
      echo "$RATE,$MODE,0,0,0,0,0,0,0,0" >> "$OUTDIR/sweep_results.csv"
      continue
    fi

    # Extract values
    COMPLETED=$(echo "$CLUSTER_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['completed_requests'])")
    TTFT_MEAN=$(echo "$CLUSTER_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['ttft_mean_ms'])")
    TTFT_P99=$(echo "$CLUSTER_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['ttft_p99_ms'])")
    ITL_MEAN=$(echo "$CLUSTER_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['itl_mean_ms'])")
    ITL_P99=$(echo "$CLUSTER_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['itl_p99_ms'])")
    E2E_MEAN=$(echo "$CLUSTER_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['e2e_mean_ms'])")
    E2E_P99=$(echo "$CLUSTER_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['e2e_p99_ms'])")
    THROUGHPUT=$(echo "$CLUSTER_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['responses_per_sec'])")

    echo "$RATE,$MODE,$COMPLETED,$TTFT_MEAN,$TTFT_P99,$ITL_MEAN,$ITL_P99,$E2E_MEAN,$E2E_P99,$THROUGHPUT" >> "$OUTDIR/sweep_results.csv"

    # Also save full output for each run
    echo "$OUTPUT" > "$OUTDIR/${LABEL}_rate${RATE}.txt"
  done
done

echo "Sweep complete. Results in $OUTDIR/sweep_results.csv"
