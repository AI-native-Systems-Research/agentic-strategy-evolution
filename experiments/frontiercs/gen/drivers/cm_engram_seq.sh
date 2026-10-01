#!/bin/bash
cd ~/frontier/Frontier-CS && export PATH="$HOME/.local/bin:$PATH"; set -a; . ~/.nous_env; set +a
declare -A BUD=( [0]=27.45 [5]=45.62 [15]=32.25 )
for p in 0 5 15; do
  echo "=== $(date -u +%H:%M) starting engram_cm p$p budget=${BUD[$p]} ==="
  python3 -u ~/frontier/frontier_gen.py $p --agent engram --agents 40 --cost-budget ${BUD[$p]} \
    --out ~/frontier/preds/p$p.engram_cm.json > ~/frontier/gen_logs/run_p${p}_engram_cm.log 2>&1
  echo "=== $(date -u +%H:%M) done p$p ==="
done
echo "CM_ENGRAM_SEQ_DONE"
