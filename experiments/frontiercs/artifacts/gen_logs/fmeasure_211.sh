#!/bin/bash
# Usage: fmeasure.sh <solution.cpp> -> prints 'SCORE: <n>' (judge score 0-100, higher is better)
cd /home/ubuntu/frontier/Frontier-CS || exit 2
export PATH="$HOME/.local/bin:$PATH"
out=$(/home/ubuntu/frontier/Frontier-CS/.venv/bin/frontier eval algorithmic 211 "$1" --json 2>/dev/null)
s=$(printf '%s' "$out" | python3 -c "import sys,re;t=sys.stdin.read();m=re.findall(r'\"score\"\s*:\s*([0-9.]+)',t);print(m[-1] if m else 'ERR')")
echo "SCORE: $s"
