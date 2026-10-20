#!/bin/bash
set -e
cd /Users/toslali/mlsys_runs/runs/pd/l2/rep4/ws

for RATE in 200 250 300 400 500; do
  for MODE in never always; do
    if [ "$MODE" = "never" ]; then LABEL="AL"; else LABEL="AD"; fi
    OUTF="final/data/${LABEL}_rate${RATE}.txt"
    echo -n "$LABEL rate=$RATE: "
    ./blis run \
      --model qwen/qwen3-14b \
      --num-instances 4 \
      --prefill-instances 2 \
      --decode-instances 2 \
      --num-requests 300 \
      --prompt-tokens 512 \
      --prompt-tokens-stdev 0 \
      --output-tokens 128 \
      --output-tokens-stdev 0 \
      --routing-policy least-loaded \
      --seed 42 \
      --log error \
      --pd-decider "$MODE" \
      --rate "$RATE" > "$OUTF" 2>&1
    # Extract cluster metrics
    python3 -I -c "
import json, sys
text = open('$OUTF').read()
depth = 0; start = -1; results = []
for i, ch in enumerate(text):
    if ch == '{':
        if depth == 0: start = i
        depth += 1
    elif ch == '}':
        depth -= 1
        if depth == 0 and start >= 0:
            try: results.append(json.loads(text[start:i+1]))
            except: pass
            start = -1
for r in results:
    if r.get('instance_id') == 'cluster':
        print(f'completed={r[\"completed_requests\"]} itl={r[\"itl_mean_ms\"]:.3f} ttft={r[\"ttft_mean_ms\"]:.3f} e2e={r[\"e2e_mean_ms\"]:.1f}')
        break
"
  done
done
