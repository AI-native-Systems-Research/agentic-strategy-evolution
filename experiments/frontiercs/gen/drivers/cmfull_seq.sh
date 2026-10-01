#!/bin/bash
cd ~/frontier/Frontier-CS && export PATH="$HOME/.local/bin:$PATH"; set -a; . ~/.nous_env; set +a
declare -A BUD=( [0]=27.45 [15]=32.25 )
for a in engram claude; do
  for p in 0 15; do
    echo "=== $(date -u +%H:%M) start $a p$p budget=${BUD[$p]} ==="
    if [ "$a" = "engram" ]; then EXTRA="--agents 40"; else EXTRA="--rounds 200"; fi
    python3 -u ~/frontier/frontier_gen.py $p --agent $a $EXTRA --cost-budget ${BUD[$p]} \
      --out ~/frontier/preds/p$p.${a}_cmfull.json > ~/frontier/gen_logs/run_p${p}_${a}_cmfull.log 2>&1
    echo "=== $(date -u +%H:%M) done $a p$p ==="
  done
done
echo CMFULL_DONE
