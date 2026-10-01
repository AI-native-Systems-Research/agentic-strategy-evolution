#!/bin/bash
cd /home/ubuntu/frontier/Frontier-CS; export PATH="$HOME/.local/bin:$PATH"; set -a; . ~/.nous_env; set +a
R=/home/ubuntu/frontier/gen_logs/nous_runs/frontier-9-nous
sc(){ ./.venv/bin/frontier eval algorithmic 9 "$1" --json 2>/dev/null | python3 -c 'import sys,re;t=sys.stdin.read();m=re.findall(r"\"score\"\s*:\s*([0-9.]+)",t);print(m[-1] if m else "ERR")'; }
best=""; bs=-1
for f in $(find $R -name '*solution*.cpp' 2>/dev/null | grep -viE 'probe|_debug|_backup' | sort -u); do
  s1=$(sc "$f"); s2=$(sc "$f"); s3=$(sc "$f"); echo "CAND $f -> $s1 $s2 $s3"
  hi=$(python3 -c "v=[x for x in ['$s1','$s2','$s3'] if x!='ERR'];print(max([float(x) for x in v]) if v else -1)")
  python3 -c "exit(0 if $hi>$bs else 1)" && { best="$f"; bs=$hi; }
done
echo "BEST=$best SCORE=$bs"
[ -n "$best" ] && python3 -c "import json;json.dump({'problem_id':'9','agent':'nous','best_score':$bs,'solution':'$best'},open('/home/ubuntu/frontier/preds/p9.nous.json','w'))"
