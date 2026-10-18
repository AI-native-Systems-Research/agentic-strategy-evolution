import json,glob,os
from datetime import datetime
G="/Users/toslali/frontier/gen_logs"; base=os.path.expanduser("~/.claude/projects")
LV=("low","medium","high")
def ts(s): return datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
for p in ("0","5","26","58","181"):
    slug=f"p{p}-v8c50"; W=f"{G}/nous_runs/research-{slug}"
    off=[json.loads(l) for l in open(f"{G}/official_p{p}_v8c50.jsonl") if l.strip()]
    first=min((r["ts"] for r in off if r.get("score",0)>0 and not r.get("rejected")), default=None)
    # truncated replies by time
    cuts=[]
    for D in glob.glob(f"{base}/-Users-toslali-frontier-gen-logs-research-{slug}-ws*"):
        if "v8c50r" in D: continue
        for F in glob.glob(D+"/*.jsonl"):
            for l in open(F):
                try:r=json.loads(l)
                except:continue
                m=r.get("message")
                if isinstance(m,dict) and m.get("stop_reason")=="max_tokens": cuts.append(ts(r["timestamp"]))
    cuts=sorted(set(cuts))
    rows=[json.loads(l) for l in open(f"{W}/llm_metrics.jsonl") if l.strip()]
    sess=[r for r in rows if r.get("dispatcher")=="sdk"]
    out=[]
    for r in sess:
        end=ts(r["timestamp"]); start=end-(r.get("duration_ms") or 0)/1000
        sd=sum(1 for c in cuts if c<start)
        scored=first is not None and first<start
        base_l="high" if scored else "medium"
        eff=LV[max(1, LV.index(base_l)-sd)] if base_l=="high" else "medium"
        cut_in=any(start<=c<=end for c in cuts)
        out.append((r.get("session_label") or r.get("phase"), eff, "CUT" if cut_in else ""))
    med=sum(1 for _,e,_ in out if e=="medium"); n=len(out)
    print(f"p{p}: sessions {n}, would run medium {med}, high {n-med}; truncated replies {len(cuts)}; first score>0 at session #{next((i for i,(_,e,_) in enumerate(out) if e=='high'), '-')}")
    print("   ", " ".join(f"{a}:{e[0]}{'!' if c else ''}" for a,e,c in out))
