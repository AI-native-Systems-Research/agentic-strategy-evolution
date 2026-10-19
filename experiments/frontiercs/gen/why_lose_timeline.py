import json,glob
from datetime import datetime
G="/Users/toslali/frontier/gen_logs"
for slug in ["p0-v8c50mr1","p44-v8c50mr1","p225-v8c50mr1","p26-v8c50s7","p5-v8c50mr1","p58-v8c50s7"]:
    d=f"{G}/nous_runs/research-{slug}"
    rows=[json.loads(l) for l in open(d+"/llm_metrics.jsonl") if l.strip()]
    ev=[]
    for r in rows:
        end=datetime.fromisoformat(r["timestamp"]).timestamp(); c=r.get("cost_usd") or 0
        ev.append((end,c,(r.get("session_label") or r["phase"])))
    pid,tag=slug.split("-"); tag=tag.replace("v8c50","")
    off=[json.loads(l) for l in open(f"{G}/official_{pid}_v8c50{tag}.jsonl") if l.strip()]
    best=-1;tl=[]
    for o in off:
        s=o["score"] or 0
        if s>best:
            best=s
            spent=sum(c for e,c,_ in ev if e<=o["ts"])
            cur=[l for e,c,l in ev if e>o["ts"]][:1]
            tl.append(f"${spent:.0f}:{s:.1f}({cur[0] if cur else '?'})")
    print(slug," ".join(tl))
    seq=[f"{l}:${c:.1f}" for e,c,l in ev if c]
    print("   sessions:", ", ".join(seq))
    for b in sorted(glob.glob(d+"/runs/iter-*/bundle.yaml"))+sorted(glob.glob(d+"/runs/iter-*/bundle.json")):
        import re
        t=open(b).read()
        hs=re.findall(r"(?:arm_type|id):\s*\"?(h-[\w-]+)\"?[\s\S]{0,400}?(?:prediction|claim|hypothesis):\s*\"?([^\n\"]{0,140})",t)
        print("   ",b.split('/')[-2], [h[0]+': '+h[1] for h in hs][:3])
