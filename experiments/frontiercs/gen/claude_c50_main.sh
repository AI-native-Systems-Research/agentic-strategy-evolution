#!/bin/bash
# Claude Code baseline for the main runs: claude-opus-4-6, minimal prompt, same sandbox/judge/ruler as Nous,
# $50, CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000 (matches Nous v8). One run per call; keys from env, never inlined.
# Usage: gen/claude_c50_main.sh <pid> <url-env-var> <key-env-var> <run-tag>, e.g. gen/claude_c50_main.sh 225 NOUS_LITELLM_URL FCS_VPC_KEY r1
F=/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/agentic-strategy-evolution/experiments/frontiercs
cd $F; M=claude-opus-4-6; P=$1; T=${4:?run tag}
U=${!2:?url env var $2 unset; source ~/.zshrc}; K=${!3:?key env var $3 unset; source ~/.zshrc}
mkdir -p runs/p$P
nohup env -u ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL=$U ANTHROPIC_API_KEY=$K python3 -u gen/claude_sdk_research_runner.py $P \
  --slug p${P}_cs50m${T} --model $M --budget 50 --max-output-tokens 128000 \
  --out-dir $F/runs/p$P/claude_sdk_c50m_$T --out $F/artifacts/preds/p$P.claude_sdk.c50m_$T.json \
  > runs/p$P/claude_sdk_c50m_$T.log 2>&1 &
echo "$(date +%H:%M:%S) launched claude p$P $T pid $!"
