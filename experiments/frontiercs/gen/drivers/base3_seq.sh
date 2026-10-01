#!/bin/bash
cd ~/frontier/Frontier-CS && export PATH="$HOME/.local/bin:$PATH"; set -a; . ~/.nous_env; set +a
declare -A BUD=( [211]=35.70 [44]=29.42 [9]=38.19 )
# Claude plateau-stop (rounds cap 30, early-stop on plateau)
for p in 211 44 9; do
  echo "=== $(date -u +%H:%M) claude p$p (plateau) ==="
  python3 -u ~/frontier/frontier_gen.py $p --agent claude --rounds 30 --out ~/frontier/preds/p$p.claude.json \
    > ~/frontier/gen_logs/run_p${p}_claude.log 2>&1
done
# Engram cost-matched to Nous $
for p in 211 44 9; do
  echo "=== $(date -u +%H:%M) engram p$p (cost-matched \$${BUD[$p]}) ==="
  python3 -u ~/frontier/frontier_gen.py $p --agent engram --agents 40 --cost-budget ${BUD[$p]} \
    --out ~/frontier/preds/p$p.engram.json > ~/frontier/gen_logs/run_p${p}_engram.log 2>&1
done
echo BASE3_DONE
