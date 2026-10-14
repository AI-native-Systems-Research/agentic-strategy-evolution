#!/bin/bash
# Task-selection pilot: Claude SDK (claude-opus-4-6, minimal prompt, same sandbox/judge/ruler as the $25 runs) at $5
# on the three held-out tasks. One key per job; keys are read from env (NOUS_LITELLM_KEY1..3), never inlined.
F=/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/agentic-strategy-evolution/experiments/frontiercs
cd $F; M=claude-opus-4-6
launch(){ # pid url key
  mkdir -p runs/p$1
  nohup env -u ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL=$2 ANTHROPIC_API_KEY=$3 python3 -u gen/claude_sdk_research_runner.py $1 \
    --slug p$1_cs5 --model $M --budget 5 --out-dir $F/runs/p$1/claude_sdk_c5 --out $F/artifacts/preds/p$1.claude_sdk.c5.json \
    > runs/p$1/claude_sdk_c5.log 2>&1 &
  echo "$(date +%H:%M:%S) launched p$1 pid $!"
}
launch 181 "$NOUS_LITELLM_URL" "${NOUS_LITELLM_KEY1:?source ~/.zshrc}"
launch 26 "$NOUS_LITELLM_URL" "$NOUS_LITELLM_KEY2"
launch 58 "$NOUS_LITELLM_URL" "$NOUS_LITELLM_KEY3"
wait; echo "$(date +%H:%M:%S) PILOT DONE"
