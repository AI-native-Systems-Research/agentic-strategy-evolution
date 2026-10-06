import glob, json, os, re, time
GL = os.path.expanduser("~/frontier/gen_logs")
SLUG = "frontier-26-nousV2"
LOG = f"{GL}/frontier_26_nousV2.nous.log"
D = f"{GL}/nous_runs/{SLUG}"
# iteration + phase from the campaign log
iters = sorted(set(int(m) for m in re.findall(r'iteration=(\d+)', open(LOG).read()))) if os.path.exists(LOG) else []
it = iters[-1] if iters else 0
trans = re.findall(r'Transition: ([A-Z_]+ -> [A-Z_]+)', open(LOG).read()) if os.path.exists(LOG) else []
phase = trans[-1] if trans else "INIT"
# cost
cost = 0.0
for f in glob.glob(f"{D}/**/llm_metrics.jsonl", recursive=True):
    for l in open(f, errors="ignore"):
        try: cost += json.loads(l).get("cost_usd", 0) or 0
        except Exception: pass
# best score (score.txt)
best = None
for f in glob.glob(f"{D}/runs/iter-*/results/*/score.txt"):
    try:
        s = float(re.search(r"[0-9.]+", open(f).read()).group())
        best = s if best is None else max(best, s)
    except Exception: pass
# live events + idle + max gap
els = glob.glob(f"{D}/runs/iter-*/inputs/executor_log.jsonl")
ev = idle = maxgap = 0
if els:
    el = max(els, key=os.path.getmtime)
    r = [json.loads(l) for l in open(el, errors="ignore")]
    ev = len(r)
    ts = [d["ts"] for d in r if d.get("ts")]
    if ts:
        idle = time.time() - ts[-1]
        gaps = [ts[i+1]-ts[i] for i in range(len(ts)-1)]
        maxgap = max(gaps) if gaps else 0
up = os.popen("pgrep -f 'frontier_gen_costbudget.py 26'").read().strip() != ""
print(f"[{time.strftime('%H:%M:%S')}] p26 {'RUNNING' if up else 'STOPPED'} | iter={it} phase={phase} | cost=${cost:.2f} | best_score={best} | events={ev} idle={idle:.0f}s maxgap={maxgap:.0f}s")
