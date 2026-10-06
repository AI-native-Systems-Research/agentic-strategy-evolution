#!/usr/bin/env python3
import glob, json, os, re, subprocess, time
GL = os.path.expanduser("~/frontier/gen_logs")
TASKS = [26, 69, 79, 170]
CLASS = {26: "DP", 69: "string", 79: "math/NT", 170: "flow"}
AIDE = {26: 30, 69: 0, 79: 0, 170: 0}  # AIDE @ <=$50 on these new tasks


def cost(slug):
    c = 0.0
    for f in glob.glob(f"{GL}/nous_runs/{slug}/**/llm_metrics.jsonl", recursive=True):
        for ln in open(f, errors="ignore"):
            try:
                c += json.loads(ln).get("cost_usd", 0) or 0
            except Exception:
                pass
    return round(c, 2)


def prog(slug):
    iters = glob.glob(f"{GL}/nous_runs/{slug}/runs/iter-*/")
    mx = 0
    for d in iters:
        m = re.search(r"iter-(\d+)", d)
        if m:
            mx = max(mx, int(m.group(1)))
    best = None
    for f in glob.glob(f"{GL}/nous_runs/{slug}/runs/iter-*/results/*/score.txt"):
        try:
            s = float(re.search(r"[0-9.]+", open(f).read()).group())
            best = s if best is None else max(best, s)
        except Exception:
            pass
    return mx, best


up = subprocess.run(["pgrep", "-f", "frontier_gen_costbudget.py"], capture_output=True).returncode == 0
done = (not up) and os.path.exists("/tmp/nous_rest_all.log") and "ALLDONE_NOUS_REST" in open("/tmp/nous_rest_all.log").read()
print(f"=== [{time.strftime('%H:%M')}] NOUS new-tasks: {'RUNNING' if up else ('DONE' if done else 'STOPPED')} ===")
print(f"{'task':14} {'iter':5} {'cost':8} {'best(our judge)':16} {'| AIDE@<=50'}")
for p in TASKS:
    slug = f"frontier-{p}-nousNEWKEY"
    it, bs = prog(slug)
    els = glob.glob(f"{GL}/nous_runs/{slug}/runs/iter-*/inputs/executor_log.jsonl")
    ev = max([sum(1 for _ in open(e, errors="ignore")) for e in els], default=0)
    print(f"p{p:<3}[{CLASS[p]:7}] it{it} ev{ev} ${cost(slug)} best={bs} | AIDE {AIDE[p]}")
print("(Nous best = max score.txt on our judge; stop at $50 or ceiling 100)")
