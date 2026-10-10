#!/bin/bash
# Run real Engram (mit-nms/Engram @ 5295858 + engram_opus_patch.diff) locally on Opus 4.6 via litellm.
# Usage: bash run_engram.sh <problem> <max_agents> <agent_timeout_min>
#   problem: cloudcast | fcs_alg_<id> | fcs_res_<id>
set -eo pipefail
ENGRAM=${ENGRAM_DIR:-$HOME/engram_repo}
cd "$ENGRAM"; source .venv/bin/activate
export OPENAI_API_BASE="$OPENAI_BASE_URL"   # langchain-openai reads OPENAI_API_BASE
python -u examples/handoff_example_usage.py \
  --problem_name "${1:?problem}" --model claude-opus-4-6 \
  --max_agents "${2:-10}" --agent_timeout "${3:-30}" --num_runs 1
