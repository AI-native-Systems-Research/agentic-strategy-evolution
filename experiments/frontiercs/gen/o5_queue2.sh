#!/bin/bash
# Re-runs after the 22:49-23:08 judge outage. Global limit: 3 running agent runs; key = one not used by a running run.
F=/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/agentic-strategy-evolution/experiments/frontiercs
cd $F; U=${NOUS_LITELLM_URL:?source ~/.zshrc}; M=aws/claude-opus-5
KEYS=("${NOUS_LITELLM_KEY1:?source ~/.zshrc}" "${NOUS_LITELLM_KEY2:?}" "${NOUS_LITELLM_KEY3:?}")
JOBS=("claude|0|p0_cso5b|p0|p0.claude_sdk.o5c25.json" "nous|0|p0_v6o5b|p0|p0.nous_v6.o5c25.json" "nous|5|p5_v6o5b|p5|p5.nous_v6.o5c25.json")
running_pids(){ pgrep -f "nous_research_cap.py |claude_sdk_research_runner.py " ; }
for job in "${JOBS[@]}"; do
  IFS='|' read agent pid slug tdir pred <<< "$job"
  while true; do
    pids=$(running_pids); n=$(echo "$pids" | grep -c .)
    used=""; for p in $pids; do used="$used $(ps eww -p $p 2>/dev/null | tr ' ' '\n' | grep '^ANTHROPIC_API_KEY=' | cut -d= -f2)"; done
    free=-1; for k in 0 1 2; do echo "$used" | grep -q -- "${KEYS[$k]}" || { free=$k; break; }; done
    [ $n -lt 3 ] && [ $free -ge 0 ] && break; sleep 30
  done
  K=${KEYS[$free]}
  [ -f artifacts/preds/$pred ] && mv artifacts/preds/$pred artifacts/preds/${pred%.json}.outage_backup.json
  if [ $agent = nous ]; then
    ANTHROPIC_API_KEY=$K OPENAI_API_KEY=$K ANTHROPIC_BASE_URL=$U OPENAI_BASE_URL=$U nohup /opt/anaconda3/bin/python3 -u gen/nous_research_cap.py $pid --slug $slug --model $M --design-profile v6 --budget 25 --niters 30 --finish-iteration --ceiling 28.5 --out $F/artifacts/preds/$pred --logdir /Users/toslali/frontier/gen_logs > runs/$tdir/nous_v6_o5c25b.log 2>&1 &
  else
    nohup env -u ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL=$U ANTHROPIC_API_KEY=$K python3 -u gen/claude_sdk_research_runner.py $pid --slug $slug --model $M --budget 25 --out-dir $F/runs/$tdir/claude_sdk_o5c25b --out $F/artifacts/preds/$pred > runs/$tdir/claude_sdk_o5c25b.log 2>&1 &
  fi
  echo "$(date +%H:%M:%S) launched $agent $slug key$free pid $!"; sleep 30
done
wait; echo "$(date +%H:%M:%S) QUEUE2 DONE"
