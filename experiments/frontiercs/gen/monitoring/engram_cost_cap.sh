#!/bin/bash
# Run REAL Engram (as-is) with a hard cost cap by polling Engram's own cost signal.
#
# WHY THIS EXISTS: real Engram has NO $-budget flag. It burns ~$6-9/iteration and logs cumulative
# cost only every 5 iterations ("Total cost: $X" in console_output.log + total_cost in
# *_usage_stats.json). With no cap it ran to **$347 on p47** (2026-10-06). max_agents does NOT bound
# cost (one agent did 35 iterations = $347). The ONLY safe cap is to poll its cost and kill it.
#
# Granularity caveat: cost is logged every 5 iterations (~$30), so the cap triggers at the first
# checkpoint >= budget (≈ one checkpoint of overshoot, ~$60 for a $50 budget). To get a true
# best-at-$50 score, read the per-iteration "Score progression" vs the checkpoint costs afterwards.
#
# Usage: IBM_LITELLM_KEY=sk-... OPENAI_BASE_URL=https://ete-litellm.ai-models.vpc.res.ibm.com \
#          engram_cost_cap.sh <alg_id> [budget_usd]
set -uo pipefail
ID="${1:?alg id}"; BUDGET="${2:-50}"
REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"
K="${IBM_LITELLM_KEY:?set IBM_LITELLM_KEY}"
U="${OPENAI_BASE_URL:-https://ete-litellm.ai-models.vpc.res.ibm.com}"
LOG="/tmp/engram_p${ID}.log"

OPENAI_BASE_URL="$U" OPENAI_API_KEY="$K" \
  nohup bash "$REPO/experiments/frontiercs/engram_real/run_engram.sh" "fcs_alg_${ID}" 1 120 > "$LOG" 2>&1 &
EPID=$!
echo "[engram-cap] launched pid=$EPID task=fcs_alg_${ID} budget=\$$BUDGET log=$LOG"

# discover the run's results dir from its own stdout (robust vs guessing run0/run1)
RD=""
for _ in $(seq 1 40); do
  sleep 5
  RD=$(grep -oE "Results Directory: .*" "$LOG" 2>/dev/null | tail -1 | sed 's/Results Directory: //')
  [ -n "$RD" ] && break
done
CO="$RD/FrontierCS/logs/console_output.log"
echo "[engram-cap] watching $CO"

while kill -0 "$EPID" 2>/dev/null; do
  cost=$(grep -ohE "Total cost: \\\$[0-9.]+" "$CO" "$LOG" 2>/dev/null | grep -oE "[0-9.]+" | sort -g | tail -1)
  if [ -n "$cost" ]; then
    echo "[engram-cap $(date +%H:%M)] cost=\$$cost"
    if python3 -c "import sys;sys.exit(0 if $cost>=$BUDGET else 1)"; then
      echo "[engram-cap $(date +%H:%M)] cost \$$cost >= \$$BUDGET -> KILL"
      pkill -9 -f "handoff_example_usage.py --problem_name fcs_alg_${ID}" 2>/dev/null
      kill -9 "$EPID" 2>/dev/null
      break
    fi
  fi
  sleep 20
done
echo "[engram-cap] STOPPED. final: $(grep -ohE 'Total cost: \$[0-9.]+' "$CO" "$LOG" 2>/dev/null | tail -1)"
echo "[engram-cap] score progression: $(grep -oE 'Score progression: \[[^]]*\]' "$CO" 2>/dev/null | tail -1 | cut -c1-400)"
