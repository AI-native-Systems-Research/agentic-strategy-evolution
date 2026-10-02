#!/usr/bin/env python3
"""Resume a Nous campaign repeatedly past intermittent SDK stalls until cost >= $50
(or ceiling/campaign-done). Each `nous resume` continues from the last completed iter,
so cost accumulates across re-resumes. Usage: nous_resume_until50.py SLUG CAMP LOG [MAXIT]
"""
import glob, json, os, subprocess, sys, time

SLUG, CAMP, LOG = sys.argv[1], sys.argv[2], sys.argv[3]
MAXIT = sys.argv[4] if len(sys.argv) > 4 else "14"
GL = os.path.expanduser("~/frontier/gen_logs")
NOUS = os.path.expanduser("~/nous_repo/.venv/bin/nous")
TARGET = 50.0
STALL_S = 420
env = dict(os.environ)
env.update({"ANTHROPIC_BASE_URL": os.environ["OPENAI_BASE_URL"], "ANTHROPIC_API_KEY": os.environ["OPENAI_API_KEY"],
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1",
            "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1",
            "NOUS_CAMPAIGN_PARENT": f"{GL}/nous_runs"})

def cost():
    c = 0.0
    for f in glob.glob(f"{GL}/nous_runs/{SLUG}/**/llm_metrics.jsonl", recursive=True):
        for ln in open(f, errors="ignore"):
            try: c += json.loads(ln).get("cost_usd", 0) or 0
            except Exception: pass
    return round(c, 2)

def kill_tree():
    r = subprocess.run(["pgrep", "-f", CAMP], capture_output=True, text=True)
    for n in r.stdout.split():
        kids = subprocess.run(["pgrep", "-P", n], capture_output=True, text=True).stdout.split()
        for k in kids:
            for g in subprocess.run(["pgrep", "-P", k], capture_output=True, text=True).stdout.split():
                subprocess.run(["kill", "-9", g])
            subprocess.run(["kill", "-9", k])
        subprocess.run(["kill", "-9", n])
    subprocess.run(["pkill", "-9", "-f", f"nous resume {SLUG}"])

for attempt in range(1, 25):
    c = cost()
    print(f"[{time.strftime('%H:%M')}] resume#{attempt} start cost=${c}", flush=True)
    if c >= TARGET:
        print(f"REACHED ${c} >= $50 — DONE", flush=True); break
    camp_yaml = os.path.expanduser(f"~/frontier/gen_logs/{CAMP}")
    rp = subprocess.Popen([NOUS, "resume", camp_yaml, "--auto-approve", "--agent", "sdk",
                           "--max-iterations", MAXIT, "--timeout", "2400"],
                          cwd=os.path.expanduser("~/nous_repo"), env=env,
                          stdout=open(f"{GL}/{SLUG}.resume.log", "a"), stderr=subprocess.STDOUT)
    done = False
    t_start = time.time()
    while rp.poll() is None:
        time.sleep(45)
        c = cost()
        age = int(time.time() - os.path.getmtime(LOG)) if os.path.exists(LOG) else 999
        print(f"  cost=${c} logAge={age}s", flush=True)
        if c >= TARGET:
            kill_tree(); print(f"REACHED ${c} mid-resume — DONE", flush=True); done = True; break
        if age > STALL_S:
            print(f"  STALL (idle {age}s) -> kill+re-resume", flush=True); kill_tree(); time.sleep(4); break
    if done:
        break
    # resume process ended on its own. If cost reached a true terminal (ceiling) stop; else just
    # keep re-resuming (do NOT treat a fast/stalled exit as 'done'). Guard against tight-spin.
    if cost() >= TARGET:
        break
    if time.time() - t_start < 30:
        print("  resume exited fast (likely transient) -> wait 20s + re-resume", flush=True); time.sleep(20)
print(f"FINAL cost=${cost()}", flush=True)
print("ALLDONE_RESUME", flush=True)
