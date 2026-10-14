#!/bin/bash
# Overnight Opus-5 queue: Nous v6 vs Claude SDK, $25 per task, max 3 concurrent, one key per running job.
F=/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/agentic-strategy-evolution/experiments/frontiercs
cd $F; U=${NOUS_LITELLM_URL:?source ~/.zshrc}; M=aws/claude-opus-5
KEYS=("${NOUS_LITELLM_KEY1:?source ~/.zshrc}" "${NOUS_LITELLM_KEY2:?}" "${NOUS_LITELLM_KEY3:?}")
# job = agent|pid|slug|task_dir
JOBS=(
 "nous|5|p5_v6o5|p5" "claude|5|p5_cso5|p5"
 "nous|0|p0_v6o5|p0" "claude|0|p0_cso5|p0"
 "nous|47|p47_v6o5|p47" "claude|47|p47_cso5|p47"
 "nous|grammar_fuzzing/seed/sql|gf_v6o5|gf" "claude|grammar_fuzzing/seed/sql|gf_cso5|gf"
 "nous|llm_router|router_v6o5|llm_router" "claude|llm_router|router_cso5|llm_router"
)
KEYPID=("" "" "")   # key index -> pid (bash 3: indexed array)
pred_name(){ case $2 in grammar_fuzzing*) b=gf_seed_sql;; llm_router) b=llm_router;; *) b=p$2;; esac; echo "$b.$1.o5c25.json"; }
for job in "${JOBS[@]}"; do
  IFS='|' read agent pid slug tdir <<< "$job"
  while true; do   # wait for a free slot (max 3) and a free key
    running=0; free=-1
    for k in 0 1 2; do p=${KEYPID[$k]}; if [ -n "$p" ] && kill -0 $p 2>/dev/null; then running=$((running+1)); else KEYPID[$k]=""; [ $free -lt 0 ] && free=$k; fi; done
    [ $running -lt 3 ] && [ $free -ge 0 ] && break; sleep 30
  done
  K=${KEYS[$free]}
  if [ $agent = nous ]; then
    ANTHROPIC_API_KEY=$K OPENAI_API_KEY=$K ANTHROPIC_BASE_URL=$U OPENAI_BASE_URL=$U nohup /opt/anaconda3/bin/python3 -u gen/nous_research_cap.py $pid --slug $slug --model $M --design-profile v6 --budget 25 --niters 30 --finish-iteration --ceiling 28.5 --out $F/artifacts/preds/$(pred_name nous_v6 $pid) --logdir /Users/toslali/frontier/gen_logs > runs/$tdir/nous_v6_o5c25.log 2>&1 &
  else
    nohup env -u ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL=$U ANTHROPIC_API_KEY=$K python3 -u gen/claude_sdk_research_runner.py $pid --slug $slug --model $M --budget 25 --out-dir $F/runs/$tdir/claude_sdk_o5c25 --out $F/artifacts/preds/$(pred_name claude_sdk $pid) > runs/$tdir/claude_sdk_o5c25.log 2>&1 &
  fi
  KEYPID[$free]=$!; echo "$(date +%H:%M:%S) launched $agent $slug key$free pid $!"
  sleep 20
done
wait; echo "$(date +%H:%M:%S) ALL O5 JOBS DONE"
