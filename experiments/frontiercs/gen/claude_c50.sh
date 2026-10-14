#!/bin/bash
# Claude SDK baseline (claude-opus-4-6, minimal prompt, same sandbox/judge/ruler as the $25 runs) at $50 on the
# held-out focus tasks. One key per job; keys come from env (NOUS_LITELLM_KEY1..3), never inlined.
F=/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/agentic-strategy-evolution/experiments/frontiercs
cd $F; M=claude-opus-4-6; U=${NOUS_LITELLM_URL:?source ~/.zshrc}
launch(){ # pid key
  mkdir -p runs/p$1
  nohup env -u ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL=$U ANTHROPIC_API_KEY=$2 python3 -u gen/claude_sdk_research_runner.py $1 \
    --slug p$1_cs50 --model $M --budget 50 --out-dir $F/runs/p$1/claude_sdk_c50 --out $F/artifacts/preds/p$1.claude_sdk.c50.json \
    > runs/p$1/claude_sdk_c50.log 2>&1 &
  echo "$(date +%H:%M:%S) launched p$1 pid $!"
}
launch 181 "${NOUS_LITELLM_KEY1:?source ~/.zshrc}"
launch 26 "${NOUS_LITELLM_KEY2:?}"
launch 58 "${NOUS_LITELLM_KEY3:?}"
wait; echo "$(date +%H:%M:%S) C50 DONE"
