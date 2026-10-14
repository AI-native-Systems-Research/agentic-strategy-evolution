#!/bin/bash
# Nous v7 at $50 (claude-opus-4-6, same sandbox/judge/ruler as the Claude $50 baseline).
# Usage: gen/nous_v7_c50.sh <pid> <url-env-var> <key-env-var>, e.g. gen/nous_v7_c50.sh 5 NOUS_LITELLM_URL NOUS_LITELLM_KEY2
# Keys are read from env (see ~/.zshrc), never inlined.
F=/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/agentic-strategy-evolution/experiments/frontiercs
cd $F; M=claude-opus-4-6; P=$1
U=${!2:?url env var $2 unset; source ~/.zshrc}; K=${!3:?key env var $3 unset; source ~/.zshrc}
mkdir -p runs/p$P
nohup env -u ANTHROPIC_AUTH_TOKEN ANTHROPIC_API_KEY=$K OPENAI_API_KEY=$K ANTHROPIC_BASE_URL=$U OPENAI_BASE_URL=$U \
  /opt/anaconda3/bin/python3 -u gen/nous_research_cap.py $P --slug p${P}_v7c50 --model $M --design-profile v7 \
  --budget 50 --niters 30 --finish-iteration --ceiling 57 --out $F/artifacts/preds/p$P.nous_v7.c50.json \
  --logdir /Users/toslali/frontier/gen_logs > runs/p$P/nous_v7_c50.log 2>&1 &
echo "$(date +%H:%M:%S) launched nous v7 p$P pid $!"
