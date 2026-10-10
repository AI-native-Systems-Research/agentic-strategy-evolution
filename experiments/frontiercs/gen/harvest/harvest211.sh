#!/bin/bash
cd /home/ubuntu/frontier/Frontier-CS; export PATH="$HOME/.local/bin:$PATH"; set -a; . ~/.nous_env; set +a
R=/home/ubuntu/frontier/gen_logs/nous_runs/frontier-211-nous
WS=/home/ubuntu/frontier/gen_logs/frontier_211_nous_ws
sc(){ ./.venv/bin/frontier eval algorithmic 211 "$1" --json 2>/dev/null | python3 -c 'import sys,re;t=sys.stdin.read();m=re.findall(r"\"score\"\s*:\s*([0-9.]+)",t);print(m[-1] if m else "ERR")'; }
best=""; bs=-1
for f in $(find $R $WS -name '*.cpp' 2>/dev/null | grep -viE 'probe|_debug|_backup|time_test' | sort -u); do
  s=$(sc "$f"); echo "CAND $f -> $s"
  python3 -c "exit(0 if '$s'!='ERR' and float('$s')>$bs else 1)" && { best="$f"; bs=$s; }
done
echo "BEST=$best SCORE=$bs"
[ -n "$best" ] && python3 -c "import json;json.dump({'problem_id':'211','agent':'nous','best_score':float('$bs'),'solution':'$best'},open('/home/ubuntu/frontier/preds/p211.nous.json','w'))"
