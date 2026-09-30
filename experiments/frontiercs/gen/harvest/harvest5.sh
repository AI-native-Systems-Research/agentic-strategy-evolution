#!/bin/bash
cd /home/ubuntu/frontier/Frontier-CS
export PATH="$HOME/.local/bin:$PATH"
set -a; . ~/.nous_env; set +a
R=/home/ubuntu/frontier/gen_logs/nous_runs/frontier-5
WS=/home/ubuntu/frontier/gen_logs/frontier_5_nous_ws
sc(){ ./.venv/bin/frontier eval algorithmic 5 "$1" --json 2>/dev/null \
      | python3 -c 'import sys,re;t=sys.stdin.read();m=re.findall(r"\"score\"\s*:\s*([0-9.]+)",t);print(m[-1] if m else "ERR")'; }
# candidates: finalized arm inputs + iter-3 worktree + ws solution*.cpp (exclude probes/scratch)
cands=$( { find $R -name '*.cpp'; find $WS -maxdepth 3 -name 'solution*.cpp'; } 2>/dev/null \
         | grep -viE 'probe|time_test|_debug|_backup|backup_' | sort -u )
best=""; bestscore=-1
for f in $cands; do
  s1=$(sc "$f"); s2=$(sc "$f"); s3=$(sc "$f")
  echo "CAND $f -> $s1 $s2 $s3"
  hi=$(python3 -c "v=[x for x in ['$s1','$s2','$s3'] if x!='ERR'];print(max([float(x) for x in v]) if v else -1)")
  cmp=$(python3 -c "print(1 if $hi>$bestscore else 0)")
  [ "$cmp" = "1" ] && { best="$f"; bestscore=$hi; }
done
echo "BEST=$best SCORE=$bestscore"
if [ -n "$best" ]; then
  cp "$best" $R/best_solution.cpp
  python3 -c "import json;json.dump({'problem_id':'5','agent':'nous','best_score':$bestscore,'solution':'$best'},open('/home/ubuntu/frontier/preds/p5.nous.json','w'),indent=2)"
  echo "saved -> preds/p5.nous.json + best_solution.cpp"
fi
