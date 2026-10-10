#!/bin/bash
cd /home/ubuntu/frontier/Frontier-CS
export PATH="$HOME/.local/bin:$PATH"
set -a; . ~/.nous_env; set +a
R=/home/ubuntu/frontier/gen_logs/nous_runs/frontier-15
sc(){ ./.venv/bin/frontier eval algorithmic 15 "$1" --json 2>/dev/null \
      | python3 -c 'import sys,re;t=sys.stdin.read();m=re.findall(r"\"score\"\s*:\s*([0-9.]+)",t);print(m[-1] if m else "ERR")'; }
echo "iter-1 recorded score.txt:"
find $R -name score.txt -exec sh -c 'echo "  $1 = $(cat "$1")"' _ {} \;
best=""; bestscore=-1
for f in $(find $R -name '*solution.cpp' 2>/dev/null | sort -u); do
  s1=$(sc "$f"); s2=$(sc "$f"); s3=$(sc "$f")
  echo "CAND $f -> $s1 $s2 $s3"
  # track best by first eval (numeric)
  hi=$(python3 -c "v=[x for x in ['$s1','$s2','$s3'] if x!='ERR'];print(max([float(x) for x in v]) if v else -1)")
  cmp=$(python3 -c "print(1 if $hi>$bestscore else 0)")
  [ "$cmp" = "1" ] && { best="$f"; bestscore=$hi; }
done
echo "BEST=$best SCORE=$bestscore"
if [ -n "$best" ]; then
  cp "$best" $R/best_solution.cpp
  python3 -c "import json;json.dump({'problem_id':'15','agent':'nous','best_score':$bestscore,'solution':'$best'},open('/home/ubuntu/frontier/preds/p15.nous.json','w'),indent=2)"
  echo "saved -> /home/ubuntu/frontier/preds/p15.nous.json  and  $R/best_solution.cpp"
fi
