#!/bin/bash
# One-time setup for real Engram on Opus 4.6 (local). Reproduces our environment.
set -eo pipefail
ENGRAM=${ENGRAM_DIR:-$HOME/engram_repo}
git clone --branch engram https://github.com/mit-nms/Engram.git "$ENGRAM" 2>/dev/null || true
cd "$ENGRAM"
git checkout 5295858   # pinned commit
git apply "$(dirname "$0")/engram_opus_patch.diff" || echo "patch may already be applied"
python3 -m venv .venv && ./.venv/bin/pip install -q -r requirements.txt
# Frontier-CS submodule (for fcs_alg_*/fcs_res_*) + its package
git submodule update --init SystemBench/FrontierCS/frontier_cs_repo
./.venv/bin/pip install -q -e SystemBench/FrontierCS/frontier_cs_repo
# agent sandbox image + go-judge (algorithmic) must be running:
docker pull python:3.11
echo "NOTE: algorithmic tasks need the go-judge container on :8081 (Competitive-Programming)."
echo "Set OPENAI_BASE_URL + OPENAI_API_KEY (litellm). Then: bash run_engram.sh <problem> <max_agents> <timeout_min>"
