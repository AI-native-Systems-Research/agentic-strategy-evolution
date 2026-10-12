#!/bin/bash
# Submit solution.py to the research judge; prints SCORE (higher better) and COST ($, LOWER better).
JR="/tmp/fcs_rjudge"
tok="cloudcast__$(date +%s%N)_$RANDOM"
cp "/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/agentic-strategy-evolution/experiments/frontiercs/runs/cloudcast/claude/solution.py" "$JR/inbox/$tok.py"
for i in $(seq 1 2400); do
  if [ -f "$JR/outbox/$tok.score" ]; then cat "$JR/outbox/$tok.score"; rm -f "$JR/outbox/$tok.score"; exit 0; fi
  sleep 0.5
done
echo "SCORE: ERR"; echo "COST: ERR"
