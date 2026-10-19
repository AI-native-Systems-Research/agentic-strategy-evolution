"""Main-run queue (nous-algo-v1 vs Claude Code, $50, 128k output): one run per gateway key at a time.

Tasks p0 p5 p26 p58 p181 (dev) + p225 p44 (held-out), 3 repeats per agent. Runs already done or running are
skipped (by their log file). Each key runs one job; when it ends, the key takes the next pending job. Keys and
URLs come from the environment (~/.zshrc), never this file. No LLM calls here.

Usage: python3 gen/main_queue.py [--dry-run]
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

F = Path(__file__).resolve().parent.parent
TASKS = ["225", "44", "0", "5", "26", "58", "181"]
REPEATS = ["r1", "r2", "r3"]
KEYS = [("NOUS_LITELLM_URL", "NOUS_LITELLM_KEY1"), ("NOUS_LITELLM_URL", "NOUS_LITELLM_KEY2"),
        ("NOUS_LITELLM_URL", "NOUS_LITELLM_KEY3"), ("NOUS_LITELLM_URL", "FCS_VPC_KEY"),
        ("NOUS_VPCINT_URL", "NOUS_VPCINT_KEY1"), ("NOUS_VPCINT_URL", "NOUS_VPCINT_KEY2")]
# smoke runs s7 are on the frozen commit and count as Nous repeat r1 of p58 and p26
NOUS_ALIAS = {("58", "r1"): "s7", ("26", "r1"): "s7"}
STATE = F / "artifacts" / "main_queue_state.json"


def log_of(agent, pid, rep):
    if agent == "claude":
        return F / f"runs/p{pid}/claude_sdk_c50m_{rep}.log"
    return F / f"runs/p{pid}/nous_v8_c50{NOUS_ALIAS.get((pid, rep), 'm' + rep)}.log"


def slug_of(agent, pid, rep):
    if agent == "claude":
        return f"p{pid}_cs50m{rep}"
    return f"p{pid}_v8c50{NOUS_ALIAS.get((pid, rep), 'm' + rep)}"


def jobs():
    # interleave agents and tasks so both agents progress on every task at the same rate
    out = []
    for rep in REPEATS:
        for pid in TASKS:
            for agent in ("nous", "claude"):
                out.append((agent, pid, rep))
    return out


def running(slug):
    return subprocess.run(["pgrep", "-f", f"slug {slug} "], capture_output=True).returncode == 0


def launch(agent, pid, rep, url, key):
    if agent == "claude":
        cmd = ["bash", str(F / "gen/claude_c50_main.sh"), pid, url, key, rep]
    else:
        cmd = ["bash", str(F / "gen/nous_v8_c50.sh"), pid, url, key, "m" + rep]
    env = dict(os.environ)
    return subprocess.run(cmd, cwd=F, env=env, capture_output=True, text=True).stdout.strip()


def main():
    dry = "--dry-run" in sys.argv
    state = json.loads(STATE.read_text()) if STATE.exists() else {"slots": {}}
    slots = state["slots"]  # key var -> slug currently assigned
    while True:
        pending = [j for j in jobs() if not log_of(*j).exists()]
        for url, key in KEYS:
            cur = slots.get(key)
            if cur and running(cur):
                continue
            busy_slugs = {s for s in slots.values() if s and running(s)}
            nxt = next((j for j in pending if slug_of(*j) not in busy_slugs), None)
            if nxt is None:
                continue
            agent, pid, rep = nxt
            if dry:
                print(f"would launch {agent} p{pid} {rep} on {key}")
            else:
                print(time.strftime("%H:%M:%S"), launch(agent, pid, rep, url, key), "on", key, flush=True)
                time.sleep(5)
            slots[key] = slug_of(agent, pid, rep)
            pending.remove(nxt)
        if not dry:
            STATE.write_text(json.dumps({"slots": slots}, indent=2))
        if dry or not [j for j in jobs() if not log_of(*j).exists()] and not any(running(s) for s in slots.values() if s):
            break
        time.sleep(60)
    print("queue done" if not dry else "dry run done", flush=True)


if __name__ == "__main__":
    main()
