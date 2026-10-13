#!/bin/bash
# fmeasure: score solution.py via the out-of-sandbox judge daemon -> prints 'SCORE: <n>'
IN="/tmp/fcs_rjudge_claude/gf_e46/inbox"; OUT="/tmp/fcs_rjudge_claude/gf_e46/outbox"
tok="m$$_$RANDOM"
cp "$1" "$IN/$tok.py"
for i in $(seq 1 600); do
  if [ -f "$OUT/$tok.score" ]; then cat "$OUT/$tok.score"; rm -f "$OUT/$tok.score"; exit 0; fi
  sleep 1
done
echo "SCORE: 0.0"
