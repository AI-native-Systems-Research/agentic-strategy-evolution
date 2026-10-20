#!/bin/bash
set -euo pipefail

BLIS="./blis"
OUTDIR="final/data"
mkdir -p "$OUTDIR"

BASE_FLAGS="--model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded --seed 42"

RATES="1 2 5 10 15 20 25 30 35 40 45 50 55 60 65 70 75 80 85 90 95 100 110 120 130 140 150"

for mode in never always; do
    echo "=== Running pd-decider=$mode ==="
    for rate in $RATES; do
        outfile="$OUTDIR/${mode}_rate${rate}.json"
        if [ -f "$outfile" ]; then
            echo "  rate=$rate already done, skipping"
            continue
        fi
        echo -n "  rate=$rate ... "
        output=$($BLIS run $BASE_FLAGS --pd-decider "$mode" --rate "$rate" 2>/dev/null)
        cluster_json=$(echo "$output" | python3 -c "
import sys, json, re

text = sys.stdin.read()
# Find the last JSON block (cluster metrics)
blocks = re.findall(r'\{[^{}]+\}', text, re.DOTALL)
for b in blocks:
    try:
        d = json.loads(b)
        if d.get('instance_id') == 'cluster':
            print(json.dumps(d))
            break
    except:
        pass
")
        if [ -z "$cluster_json" ]; then
            echo "FAILED (no cluster output)"
            continue
        fi
        echo "$cluster_json" | python3 -c "
import sys, json
d = json.load(sys.stdin)
d['rate'] = $rate
d['pd_decider'] = '$mode'
json.dump(d, sys.stdout, indent=2)
print()
" > "$outfile"
        itl=$(python3 -c "import json; d=json.load(open('$outfile')); print(f'{d[\"itl_mean_ms\"]:.3f}')")
        ttft=$(python3 -c "import json; d=json.load(open('$outfile')); print(f'{d[\"ttft_mean_ms\"]:.3f}')")
        completed=$(python3 -c "import json; d=json.load(open('$outfile')); print(d['completed_requests'])")
        echo "done (ITL=${itl}ms, TTFT=${ttft}ms, completed=${completed})"
    done
done

echo ""
echo "=== Collecting results ==="
python3 -c "
import json, glob, os

results = []
for f in sorted(glob.glob('$OUTDIR/*.json')):
    with open(f) as fh:
        d = json.load(fh)
        results.append(d)

# Sort by mode then rate
results.sort(key=lambda x: (x['pd_decider'], x['rate']))

with open('$OUTDIR/all_results.json', 'w') as fh:
    json.dump(results, fh, indent=2)

print(f'Collected {len(results)} results into $OUTDIR/all_results.json')
"
