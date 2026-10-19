import json, glob, os, collections
G="/Users/toslali/frontier/gen_logs"
F="/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/agentic-strategy-evolution/experiments/frontiercs"
for slug in ["p0-v8c50mr1","p44-v8c50mr1","p225-v8c50mr1","p26-v8c50s7","p5-v8c50mr1","p58-v8c50s7"]:
    d=f"{G}/nous_runs/research-{slug}"
    rows=[json.loads(l) for l in open(d+"/llm_metrics.jsonl") if l.strip()]
    by=collections.defaultdict(float); n=collections.Counter(); out=collections.defaultdict(int)
    for r in rows:
        c=r.get("cost_usd") or 0
        lab=r.get("session_label") or r.get("phase")
        k=lab.split("-iter")[0] if lab else r.get("phase")
        k=("arm:"+k) if k and k.startswith("h-") else k
        by[k]+=c; n[k]+=1; out[k]+=r.get("output_tokens") or 0
    tot=sum(by.values())
    print(f"\n=== Nous {slug} total ${tot:.2f} sessions {len(rows)}")
    for k,v in sorted(by.items(),key=lambda x:-x[1]):
        print(f"   {k:28s} ${v:6.2f} ({100*v/tot:4.1f}%) n={n[k]} out_tok={out[k]}")
    pid=slug.split("-")[0]; tag=slug.split("-")[1].replace("v8c50","")
    off=[json.loads(l) for l in open(f"{G}/official_{pid}_v8c50{tag}.jsonl") if l.strip()]
    t0=rows[0]["timestamp"]
    from datetime import datetime
    T0=datetime.fromisoformat(t0).timestamp()-rows[0]["duration_ms"]/1000
    best=-1; tl=[]
    for o in off:
        s=o["score"] or 0
        if s>best: best=s; tl.append(f"{(o['ts']-T0)/60:.0f}m:{s:.1f}")
    print(f"   official measures: {len(off)}, best-so-far timeline: {' '.join(tl)}")
    st=json.load(open(d+"/ledger.json"))["iterations"]
    for it in st:
        print("   ledger:", json.dumps(it)[:300])
