#!/usr/bin/env python3
import glob, json, os, subprocess, time
GL = os.path.expanduser("~/frontier/gen_logs")

def cost(slug):
    c = 0.0
    for f in glob.glob(f"{GL}/nous_runs/{slug}/**/llm_metrics.jsonl", recursive=True):
        for ln in open(f, errors="ignore"):
            try: c += json.loads(ln).get("cost_usd", 0) or 0
            except Exception: pass
    return round(c, 2)

def up(pat):
    return subprocess.run(["pgrep", "-f", pat], capture_output=True).returncode == 0

# live rerun state
p0rr = cost("frontier-0-rr"); p5rr = cost("frontier-5-rr"); ccrr = cost("research-cloudcast-rr")
running = []
if up("campaign_0.yaml"): running.append(f"p0-rerun(${p0rr})")
if up("campaign_5.yaml"): running.append(f"p5-rerun(${p5rr})")
if up("campaign_cloudcast.yaml"): running.append(f"cloudcast-rerun(${ccrr})")
loop = "resume-loop UP" if up("nous_resume_until50.py") else "no resume-loop"
print(f"=== [{time.strftime('%H:%M')}] STATUS === running: {running or 'none'} | {loop}")
print("ALGORITHMIC best-score @ <=$50 (iso-cost, our judge). Nous-rerun = live $50 attempt (p)=partial-stalled")
rows = [
 ("p0", "86", f"85.1(${p0rr},p)", "70.0", "~26"),
 ("p5", "83", f"(${p5rr})",       "49.0", "~39"),
 ("p9", "100(ceil)", "-",         "55.0", "undet(leak)"),
 ("p15","100(ceil)", "-",         "20.0", "0"),
 ("p22","100(ceil)", "-",         "0.0",  "0"),
]
print(f"{'task':4} {'Nous@<=50':10} {'Nous-rerun':16} {'Engram@<=50':12} {'Claude@<=50':12}")
for r in rows:
    print(f"{r[0]:4} {r[1]:10} {r[2]:16} {r[3]:12} {r[4]:12}")
print(f"CLOUDCAST (transfer-cost $, LOWER better): Nous-orig $626 | Nous-rerun-hinted pending(${ccrr}) | realEngram ~$624 | Claude $1107 | naive $1046")
