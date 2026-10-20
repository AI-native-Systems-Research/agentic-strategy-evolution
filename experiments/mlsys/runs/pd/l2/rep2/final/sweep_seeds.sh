#!/usr/bin/env bash
set -euo pipefail

BLIS="./blis"
BASE_FLAGS="--model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded"

SEEDS=(1 2 3)
RATES=(1 10 30 60 100 150)

OUTDIR="final/data"
mkdir -p "$OUTDIR"

OUTFILE="$OUTDIR/seed_sweep.csv"
echo "seed,rate,mode,itl_mean_ms,ttft_mean_ms,e2e_mean_ms,itl_p99_ms,ttft_p99_ms,completed,injected" > "$OUTFILE"

for SEED in "${SEEDS[@]}"; do
  for RATE in "${RATES[@]}"; do
    for MODE in never always; do
      echo "Running seed=$SEED rate=$RATE pd-decider=$MODE ..." >&2
      OUTPUT=$($BLIS run $BASE_FLAGS --pd-decider "$MODE" --rate "$RATE" --seed "$SEED" 2>/dev/null)

      CLUSTER=$(echo "$OUTPUT" | python3 -I -c "
import sys, json
data = sys.stdin.read()
blocks = data.split('=== Simulation Metrics ===')
for block in blocks:
    block = block.strip()
    if '\"instance_id\": \"cluster\"' in block:
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

      echo "$SEED,$RATE,$LABEL,$ITL,$TTFT,$E2E,$ITL99,$TTFT99,$COMPLETED,$INJECTED" >> "$OUTFILE"
    done
  done
done

echo "Done. Results in $OUTFILE" >&2
