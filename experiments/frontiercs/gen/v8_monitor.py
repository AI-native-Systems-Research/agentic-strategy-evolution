import glob, json, os, re, subprocess, sys, time
from pathlib import Path

F = Path("/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/agentic-strategy-evolution/experiments/frontiercs")
G = Path("/Users/toslali/frontier/gen_logs")
sys.path.insert(0, str(F / "gen"))
import cost_meter as C  # noqa: E402

V8 = {"5": "vpc k3"}  # task -> key; extend when more v8 runs launch (edit this file; the loop re-reads it)
CLAUDE = {"26": 0.0, "5": 57.00, "58": 0.0, "181": 56.00, "0": 26.43}
V7 = {"26": 7.09, "5": 43.0, "58": 59.71, "181": 49.55, "0": 68.24}


def alive(pat):
    return subprocess.run(["pgrep", "-f", pat], capture_output=True).returncode == 0


def claude_cc(p):
    L = F / f"runs/p{p}/claude_sdk_c50cc.log"
    t = L.read_text(errors="ignore") if L.exists() else ""
    d = re.search(r"final_clean=([0-9.]+) cost=\$([0-9.]+)", t)
    if d:
        return f"claude-cc p{p} DONE final={d.group(1)} ${d.group(2)}"
    m = (re.findall(r"cost=\$([0-9.]+) best=([-0-9.]+) measured=(\d+)", t) or [("?", "?", "?")])[-1]
    D = F / f"runs/p{p}/claude_sdk_c50cc/driver.log"
    cr = D.read_text(errors="ignore").count("crashed") if D.exists() else 0
    return f"claude-cc p{p} ${m[0]} best={m[1]} measured={m[2]} crashes={cr}" + ("" if alive(f"claude_sdk_research_runner.py {p} ") else " DEAD")


def claude_main(p, tag):
    L = F / f"runs/p{p}/claude_sdk_c50m_{tag}.log"
    t = L.read_text(errors="ignore") if L.exists() else ""
    d = re.search(r"final_clean=([0-9.]+) cost=\$([0-9.]+)", t)
    if d:
        return f"claude p{p} {tag} DONE final={d.group(1)} ${d.group(2)}"
    m = (re.findall(r"cost=\$([0-9.]+) best=([-0-9.]+) measured=(\d+)", t) or [("?", "?", "?")])[-1]
    run = F / f"runs/p{p}/claude_sdk_c50m_{tag}"
    live = C.transcript_cost(run) if run.exists() else 0.0
    return (f"claude p{p} {tag} ${m[0]} (transcripts ${live:.2f}) best={m[1]} measured={m[2]}"
            + ("" if alive(f"slug p{p}_cs50m{tag}") else " DEAD"))


def v8row(p, key):
    p, tag = re.match(r"(\d+)(.*)", p).groups()
    slug = f"p{p}_v8c50{tag}"; W = G / f"nous_runs/research-p{p}-v8c50{tag}"
    L = F / f"runs/p{p}/nous_v8_c50{tag}.log"; t = L.read_text(errors="ignore") if L.exists() else ""
    cost = (re.findall(r"cost=\$([0-9.]+)", t) or ["0"])[-1]
    md = sorted(G.glob(f"research_{slug}_measured_*"))
    judged = [float(m.group(1).rstrip(".")) for f in (md[-1].iterdir() if md else []) if (m := re.search(r"score([0-9.]+)", f.name))]
    best = max(judged) if judged else None
    phase = []
    for d in sorted((W / "runs").glob("iter-*"), key=lambda x: int(x.name.split("-")[1])):
        try:
            st = json.loads((d / "arms/state.json").read_text())
        except Exception:
            st = {}
        ss = st.get("sessions", {})
        mode = (st.get("mode") or {}).get("mode", "")
        sess = " ".join(f"{k}:{v.get('outcome') or v.get('status')}(${v.get('budget_usd')})" for k, v in ss.items())
        w = st.get("winner") or {}
        files = "".join(c for f, c in (("bundle.yaml", "B"), ("instrument.json", "I"), ("findings.json", "F")) if (d / f).exists())
        phase.append(f"{d.name}[{files}{' ' + mode if mode else ''}] {sess}" + (f" winner={w.get('key')}({w.get('status')})" if w.get("key") else ""))
    jp = W / "judge_profile.json"
    jps = ""
    if jp.exists():
        try:
            j = json.loads(jp.read_text())
            jps = f" judge_profile:limit={j.get('time_limit_s')} likely_timeouts={len(j.get('likely_timeouts') or [])} untrusted={j.get('evaluator_untrusted')}"
        except Exception:
            jps = " judge_profile:?"
    # metrics rows vs transcript truth (cap accounting sanity)
    mrows = 0.0
    mf = W / "llm_metrics.jsonl"
    if mf.exists():
        sys.path.insert(0, str(F.parents[1]))
        from orchestrator.metrics import usage_cost
        for l in mf.read_text().splitlines():
            try:
                mrows += usage_cost(json.loads(l))
            except Exception:
                pass
    effs = re.findall(r'"effort": "([a-z]+)"', mf.read_text()) if mf.exists() else []
    es = W / "effort_state.json"
    sd = json.loads(es.read_text()).get("step_down", 0) if es.exists() else 0
    jps += f" effort_last={effs[-1] if effs else None} cuts={sd}"
    tx = C.transcript_cost(G / f"research_{slug}_ws")
    retry = (W / "retry_log.jsonl").read_text() if (W / "retry_log.jsonl").exists() else ""
    kinds = sorted(set(re.findall(r'"failure_type": "([a-z_]+)"', retry)))
    clis = 0
    for pid in subprocess.run(["pgrep", "-f", "_bundled/claude"], capture_output=True, text=True).stdout.split():
        if f"research_{slug}_ws" in subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout:
            clis += 1
    flags = ("" if alive(f"nous_research_cap.py {p} ") else " ENDED") + (f" {clis}CLIs" if clis > 1 else "") + (" TRACEBACK" if "Traceback" in t else "")
    return (f"nous-v8 p{p}{tag} {key} ${float(cost):.2f} (metrics ${mrows:.2f} / transcripts ${tx:.2f}) judged_best={best} "
            f"v7={V7.get(p)} claude={CLAUDE.get(p)}{jps} retries={kinds} | " + " || ".join(phase) + flags)


while True:
    try:
        V8 = json.load(open("/tmp/v8tasks.json"))
    except Exception:
        pass
    out = [time.strftime("%H:%M") + " REPORT"]
    try:  # follow the main queue: every run with a log (or currently assigned), newest work first
        sys.path.insert(0, str(F / "gen"))
        import importlib
        import main_queue as Q
        importlib.reload(Q)
        started = [j for j in Q.jobs() if Q.log_of(*j).exists()]
        CL = [(p, r) for a, p, r in started if a == "claude"]
        V8 = {p + Q.NOUS_ALIAS.get((p, r), "m" + r): "queue" for a, p, r in started if a == "nous"}
    except Exception as e:
        out.append(f"  queue read error {e}")
        CL = []
    for p, tag in CL:
        try:
            out.append("  " + claude_main(p, tag))
        except Exception as e:
            out.append(f"  claude p{p} {tag} monitor error {e}")
    for p, key in V8.items():
        try:
            out.append("  " + v8row(p, key))
        except Exception as e:
            out.append(f"  nous-v8 p{p} monitor error {e}")
    print("\n".join(out), flush=True)
    time.sleep(180)
