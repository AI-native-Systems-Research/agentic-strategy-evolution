"""Run one cell (task x arm x rep) in isolation, then score it with the oracle.

  run_one.py <task> <arm> <rep> <slot>        slot in 0..4 (one LLM key each, see SLOTS)

Isolation, identical for every arm:
- fresh single-commit copy of the task repo (no git history: the fix / later commits cannot be found);
- macOS sandbox (harness/sandbox.py): no internet, no reads of keys/oracle/other runs/original checkouts;
- own CLAUDE_CONFIG_DIR (own transcripts, no user settings/memory) and own localhost proxy to the gateway.
Cost = one ruler over this run's transcripts (+ Nous's direct gateway calls), harness/cost_meter.py.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
NOUS = EXP.parents[1]
sys.path.insert(0, str(HERE))
import cost_meter  # noqa: E402
import sandbox  # noqa: E402

RUNS = Path.home() / "mlsys_runs" / "runs"
REPOS = Path.home() / "mlsys_runs" / "repos"
TASKS = {"pd": ("task-pd", "pd.md", 4, 75.0), "dbg": ("task-dbg", "dbg.md", 3, 60.0),
         "search": ("task-search", "search.md", 5, 140.0)}  # repo, prompt, max iterations/sessions, safety ceiling $
SLOTS = [("NOUS_LITELLM_URL", "NOUS_LITELLM_KEY1"), ("NOUS_LITELLM_URL", "NOUS_LITELLM_KEY2"),
         ("NOUS_LITELLM_URL", "NOUS_LITELLM_KEY3"), ("NOUS_VPCINT_URL", "NOUS_VPCINT_KEY1"),
         ("NOUS_VPCINT_URL", "NOUS_VPCINT_KEY2")]
PY = sys.executable
NOUS_RT = Path.home() / "mlsys_runs" / "nous"
NOUS_BIN = str(NOUS_RT / ".venv" / "bin" / "nous")
CLAUDE = str(Path.home() / "mlsys_runs/nous/.venv/lib/python3.11/site-packages/claude_agent_sdk/_bundled/claude")

PACKAGE_PROMPT = """The research campaign below is finished. Its full record is in {work} (report.md, principles.json,
ledger.json, handoff.md, and runs/iter-*/ with findings.json, results/ and patches/). Package its result:

1. Put the campaign's final deliverable into this repository (the current directory), exactly as the campaign left it:
   for code, apply the patch(es) from {work}/runs/iter-*/patches/ that implement the campaign's final answer
   (`git apply`), or copy the delivered files. Do not write new solution code and do not change the campaign's method.
2. Copy into this repository any result files you cite as evidence (for example into final/evidence/).
3. Write final/answer.json as specified below, from the campaign's own findings and numbers.
You may build and run existing commands to check that paths and the repro command work. Do not run new experiments or
investigations, and do not change any conclusion.

--- Original task ---
{task}
"""


def env_for(slot, run_dir, port):
    url_var, key_var = SLOTS[slot]
    vals = subprocess.run(["zsh", "-ic", f'printf "%s\\n%s" "${url_var}" "${key_var}"'], capture_output=True,
                          text=True).stdout.splitlines()[-2:]
    upstream, key = vals[0].strip(), vals[1].strip()
    assert upstream.startswith("https://") and key, f"slot {slot}: missing {url_var}/{key_var}"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "OPENAI_", "CLAUDE_", "NOUS_"))}
    env.update(ANTHROPIC_BASE_URL=f"http://127.0.0.1:{port}", ANTHROPIC_API_KEY=key,
               OPENAI_BASE_URL=f"http://127.0.0.1:{port}", OPENAI_API_KEY=key,
               CLAUDE_CONFIG_DIR=str(run_dir / "claude_cfg"), CLAUDE_CODE_MAX_OUTPUT_TOKENS="32000",
               DISABLE_AUTOUPDATER="1", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
               PATH="/opt/homebrew/bin:/opt/anaconda3/bin:/usr/bin:/bin:/usr/sbin:/sbin", GOTOOLCHAIN="local",
               NOUS_CAMPAIGN_PARENT=str(run_dir / "nous_work"), TMPDIR=str(run_dir / "tmp"))
    return env, upstream


def cost_now(run_dir):
    camp = run_dir / "nous_work"
    return cost_meter.run_cost(str(run_dir / "claude_cfg"), str(camp) if camp.exists() else None)


def supervise(cmd, cwd, env, run_dir, ceiling, log):
    """Run cmd in its own process group; kill it if the run's cost passes the safety ceiling."""
    with open(log, "a") as lf:
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
        hit = False
        while p.poll() is None:
            time.sleep(30)
            if cost_now(run_dir)["total"] >= ceiling:
                hit = True
                lf.write(f"\n[harness] safety ceiling ${ceiling} reached, killing\n")
                os.killpg(p.pid, signal.SIGTERM)
                time.sleep(10)
                if p.poll() is None:
                    os.killpg(p.pid, signal.SIGKILL)
        return p.wait(), hit


def main(task, arm, rep, slot):
    repo, prompt_file, n_max, ceiling = TASKS[task]
    run_dir = RUNS / task / arm / f"rep{rep}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    for d in ("logs", "claude_cfg", "nous_work", "tmp"):
        (run_dir / d).mkdir(parents=True)
    ws = run_dir / "ws"
    shutil.copytree(REPOS / repo, ws, symlinks=True)
    task_text = (EXP / "tasks" / prompt_file).read_text() + "\n" + (EXP / "tasks" / "contract.md").read_text()
    (run_dir / "task.md").write_text(task_text)
    port = 19000 + 10 * slot + (rep % 10)
    env, upstream = env_for(slot, run_dir, port)
    proxy = subprocess.Popen([PY, str(HERE / "proxy.py"), str(port), upstream, str(run_dir / "logs" / "proxy.log")],
                             start_new_session=True)
    time.sleep(1)
    sb = run_dir / "sandbox.sb"
    sb.write_text(sandbox.profile(str(run_dir)))
    t0 = time.time()
    meta = dict(task=task, arm=arm, rep=rep, slot=slot, max_iterations=n_max, ceiling=ceiling,
                nous_commit=subprocess.run(["git", "-C", str(NOUS), "rev-parse", "HEAD"], capture_output=True,
                                           text=True).stdout.strip(),
                claude_cli=subprocess.run([CLAUDE, "--version"], capture_output=True, text=True).stdout.strip(),
                started=time.strftime("%Y-%m-%d %H:%M:%S"))
    try:
        if arm in ("l2", "nous_prompt"):
            shutil.copy(HERE / "loop_arm.py", Path.home() / "mlsys_runs" / "harness" / "loop_arm.py")
            rc, hit = supervise(["sandbox-exec", "-f", str(sb), PY, str(Path.home() / "mlsys_runs/harness/loop_arm.py"), arm,
                                 str(run_dir / "task.md"), str(ws), str(n_max), str(run_dir / "logs")],
                                ws, env, run_dir, ceiling, run_dir / "logs" / "arm.log")
            ls = json.load(open(run_dir / "logs" / "loop_status.json")) if (run_dir / "logs" / "loop_status.json").exists() \
                else dict(status="crashed", declared_done=False, iterations_used=0)
            meta.update(status="ceiling" if hit else ls["status"], declared_done=ls["declared_done"],
                        iterations_used=ls["iterations_used"], hit_ceiling=hit, returncode=rc)
        else:
            camp = dict(research_question=task_text, run_id=f"{task}-nous-rep{rep}", max_iterations=n_max,
                        target_system=dict(name="BLIS (inference-sim)",
                                           description="BLIS, a discrete-event simulator for LLM inference serving (Go).",
                                           repo_path=str(ws)),
                        prompts=dict(methodology_layer="prompts/methodology", domain_adapter_layer=None))
            import yaml
            (run_dir / "campaign.yaml").write_text(yaml.safe_dump(camp, sort_keys=False, width=120))
            rc, hit = supervise(["sandbox-exec", "-f", str(sb), NOUS_BIN, "run", str(run_dir / "campaign.yaml"),
                                 "--auto-approve", "--gate-mode", "agent"], NOUS_RT, env, run_dir, ceiling,
                                run_dir / "logs" / "arm.log")
            works = [p for p in (run_dir / "nous_work").iterdir() if p.is_dir()]
            work = works[0] if works else None
            st = json.load(open(work / "state.json")) if work and (work / "state.json").exists() else {}
            led = json.load(open(work / "ledger.json")) if work and (work / "ledger.json").exists() else {}
            iters = sum(1 for r in led.get("iterations", []) if r.get("iteration", 0) > 0)
            done = (st.get("last_entered_phase") or st.get("phase")) == "DONE"
            log = (run_dir / "logs" / "arm.log").read_text(errors="ignore")
            stopped_by_agent = "Agent gate decision: reject" in log
            meta.update(status="ceiling" if hit else ("done" if (done and stopped_by_agent) else
                                                      "max_iterations" if done else "crashed"),
                        declared_done=stopped_by_agent, iterations_used=iters, hit_ceiling=hit, returncode=rc,
                        nous_work=str(work) if work else None)
            if work and not hit:  # packaging session (counted in Nous's cost)
                (run_dir / "logs" / "package.md").write_text(PACKAGE_PROMPT.format(work=work, task=task_text))
                prc, _ = supervise(["sandbox-exec", "-f", str(sb), CLAUDE, "-p", "--model", "claude-opus-4-6",
                                    "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions",
                                    "--disallowedTools", "WebSearch,WebFetch", PACKAGE_PROMPT.format(work=work, task=task_text)],
                                   ws, env, run_dir, ceiling, run_dir / "logs" / "package.jsonl")
                meta["package_rc"] = prc
    finally:
        os.killpg(proxy.pid, signal.SIGTERM)
    c = cost_now(run_dir)
    meta.update(cost_usd=c["total"], cost=c, wall_min=round((time.time() - t0) / 60, 1),
                finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                transcripts=[str(p) for p in (run_dir / "claude_cfg").rglob("*.jsonl")] +
                [str(p) for p in (run_dir / "logs").glob("*.jsonl")])
    json.dump(meta, open(run_dir / "meta.json", "w"), indent=1)
    r = subprocess.run([PY, str(EXP / "oracle" / "score_run.py"), str(run_dir)], capture_output=True, text=True,
                       cwd=str(EXP / "oracle"))
    (run_dir / "logs" / "oracle.log").write_text(r.stdout[-20000:] + r.stderr[-20000:])
    print(json.dumps({k: meta[k] for k in ("task", "arm", "rep", "status", "cost_usd", "wall_min", "iterations_used")}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
