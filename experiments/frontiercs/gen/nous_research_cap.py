#!/usr/bin/env python3
"""Token-based $50 cap wrapper around the SANDBOXED Nous research runner (nous_research_isolated.py).

Why a separate file: nous_research_isolated.py is iteration-capped and reports the SDK's model-aware
``cost_usd``. For the iso-cost model-scaling study we need the Nous research arm to count dollars the
SAME way as the Claude research arm (claude_code_research_runner.py), which is ``tokens x fixed $15/$75`` regardless
of model. Using the SDK's cost would give Nous ~5x more Sonnet tokens than Claude for the same $50
(Sonnet lists at $3/$15, Opus at $15/$75; the fix only matters at the Sonnet tier — Opus already lands
on $15/$75, so this wrapper is a no-op there). This wrapper does NOT modify the isolated runner; it just:
  1. launches nous_research_isolated.py (which keeps full isolation: sandbox-exec deny of
     ~/frontier/{research,datasets}, out-of-sandbox judge daemon, patch-reconstruction exploit audit),
  2. polls the campaign's llm_metrics.jsonl, computes cumulative TOKEN-based cost at fixed $15/$75,
  3. kills the inner ``nous run`` when cost >= budget so the isolated runner proceeds to its (durable,
     git-patch-based) harvest + exploit audit, then
  4. stamps the token-based cost into the pred so the reported figure matches the enforced yardstick.

Research harvest is patch-based (camp_dir/runs/iter-*/patches/*.patch), which is durable, so unlike the
algorithmic worktree case we do NOT need live solution snapshotting here.

Usage:
  nous_research_cap.py grammar_fuzzing/seed/sql --slug gf_s45 --model aws/claude-sonnet-4-5 \
    --budget 50 --niters 30 --out nous_gates/preds/gf.nous.s45.json --logdir ~/frontier/gen_logs
"""
import cost_meter as C
import argparse, glob, json, os, re, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ISO = HERE / "nous_research_isolated.py"

# SAME fixed rates as claude_code_research_runner.py / claude_code_runner.py (Anthropic list, cache-aware).
R_IN, R_OUT, R_CW, R_CR = 15/1e6, 75/1e6, 18.75/1e6, 1.5/1e6


def token_cost(camp_dir):
    cost = 0.0
    for mf in set(glob.glob(str(camp_dir) + "/**/llm_metrics.jsonl", recursive=True)):
        for ln in open(mf, errors="ignore"):
            try:
                d = json.loads(ln)
            except Exception:
                continue
            cost += (d.get("input_tokens", 0) or 0) * R_IN
            cost += (d.get("output_tokens", 0) or 0) * R_OUT
            cost += (d.get("cache_creation_input_tokens", 0) or 0) * R_CW
            cost += (d.get("cache_read_input_tokens", 0) or 0) * R_CR
    return round(cost, 4)


def live_cost(logdir, slug, since):
    """Live per-reply usage from the Agent SDK transcripts (shared ruler, gen/cost_meter.py)."""
    sdk = C.transcript_cost(Path(logdir) / f"research_{slug}_ws", since=since)
    # Nous's non-SDK calls (LLMDispatcher, e.g. gate summaries) never appear in transcripts; add them from metrics
    run_slug = re.sub(r"[^A-Za-z0-9]+", "-", f"research-{slug}").strip("-")
    direct = 0.0
    for mf in glob.glob(str(Path(logdir) / "nous_runs" / run_slug / "**" / "llm_metrics.jsonl"), recursive=True):
        for ln in open(mf, errors="ignore"):
            try: d = json.loads(ln)
            except ValueError: continue
            if d.get("dispatcher") == "llm": direct += C.usage_cost(d)
    return round(sdk + direct, 4)


def kill_inner_nous(slug):
    pat = rf"nous run .*campaign_{re.escape(slug)}\.yaml"
    subprocess.run(["pkill", "-f", pat]); time.sleep(5)
    subprocess.run(["pkill", "-9", "-f", pat])
    # SDK `claude` children survive their parent; kill any still working in this run's workspace
    pids = subprocess.run(["pgrep", "-f", "_bundled/claude"], capture_output=True, text=True).stdout.split()
    for pid in pids:
        cwd = subprocess.run(["lsof", "-p", pid, "-a", "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout
        if f"research_{slug}_ws" in cwd:
            subprocess.run(["kill", "-9", pid])


def nous_iteration(camp_dir):
    try: return int(json.loads((Path(camp_dir) / "state.json").read_text()).get("iteration", 0))
    except (OSError, ValueError): return 0


def best_at_budget(problem_id, logdir, slug, t_cap, k=5):
    """Best clean re-judged score among solutions measured before the budget was reached."""
    import nous_research_isolated as N
    arch = sorted(glob.glob(str(Path(logdir) / f"research_{slug}_measured_*")))
    if not arch or t_cap is None: return None
    files = [f for f in N._top_measured(arch[-1], 10**6) if os.path.getmtime(f) <= t_cap][:k]
    best = None
    for f in files:
        sc, hits = N.judge_clean(problem_id, Path(f).read_text(errors="ignore"))
        if not hits and (best is None or sc > best): best = sc
    return best


def watch(a, alive, logdir, camp_dir, t0):
    """Poll cost; hard mode kills at budget, finish-iteration mode lets the current iteration complete."""
    killed = False; t_cap = None; it_cap = None
    while alive():
        time.sleep(a.poll)
        mcost, lcost = token_cost(camp_dir), live_cost(logdir, a.slug, t0)
        cost = max(mcost, lcost); it = nous_iteration(camp_dir)
        print(f"[rcap {time.strftime('%H:%M:%S')}] elapsed={int(time.time()-t0)}s cost=${cost:.2f} "
              f"(metrics ${mcost:.2f}, live ${lcost:.2f}; budget ${a.budget}) iter={it}", flush=True)
        if killed: continue
        if t_cap is None and cost >= a.budget:
            t_cap, it_cap = time.time(), it
            if not a.finish_iteration:
                print(f"[rcap] cost ${cost:.2f} >= ${a.budget} -> kill inner `nous run` (runner harvests)", flush=True)
                kill_inner_nous(a.slug); killed = True; continue
            print(f"[rcap] budget reached at ${cost:.2f} in iter {it}; letting iter {it} finish (ceiling ${a.ceiling})", flush=True)
        if t_cap is not None and (it > it_cap or cost >= a.ceiling):
            why = f"iter {it_cap} finished" if it > it_cap else f"ceiling ${a.ceiling}"
            print(f"[rcap] {why} at ${cost:.2f} -> kill inner `nous run` (runner harvests)", flush=True)
            kill_inner_nous(a.slug); killed = True
    return killed, t_cap


def stamp(a, out, logdir, camp_dir, t0, killed, t_cap):
    kill_inner_nous(a.slug)  # reap any orphaned SDK children
    final_cost = max(token_cost(camp_dir), live_cost(logdir, a.slug, t0))
    print(f"[rcap] runner exited; capped={killed}; token-cost=${final_cost:.2f}", flush=True)
    try:
        pred = json.loads(out.read_text())
        pred["cost_usd_tokenbased"] = round(final_cost, 2)
        pred["cost_rates_per_mtok"] = {"in": R_IN*1e6, "out": R_OUT*1e6, "cache_write": R_CW*1e6, "cache_read": R_CR*1e6}
        pred["cost_capped"] = killed
        if a.finish_iteration:
            b = best_at_budget(a.problem_id, logdir, a.slug, t_cap)
            pred["stop_rule"] = f"finish the iteration in progress at ${a.budget} (ceiling ${a.ceiling})"
            pred["best_at_budget"] = round(b, 2) if b is not None else None
            pred["budget_reached_at"] = t_cap
        out.write_text(json.dumps(pred, indent=2))
        print(f"[rcap] stamped cost (+ best_at_budget={pred.get('best_at_budget')}) into {out}", flush=True)
    except Exception as e:
        print(f"[rcap] WARN could not stamp cost into {out}: {e}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("problem_id")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--model", default="aws/claude-opus-5")
    ap.add_argument("--budget", type=float, default=50.0)
    ap.add_argument("--niters", type=int, default=30)
    ap.add_argument("--out", required=True)
    ap.add_argument("--logdir", default=os.path.expanduser("~/frontier/gen_logs"))
    ap.add_argument("--poll", type=float, default=20.0)
    ap.add_argument("--design-profile", choices=["standard", "lightweight", "v4"], default="lightweight")
    ap.add_argument("--finish-iteration", action="store_true",
                    help="at the budget, let the iteration in progress complete before stopping")
    ap.add_argument("--ceiling", type=float, default=57.0, help="hard stop even mid-iteration")
    ap.add_argument("--attach", type=float, default=None,
                    help="attach to an already-running isolated runner (value = its start epoch)")
    a = ap.parse_args()
    logdir = Path(os.path.expanduser(a.logdir))
    run_slug = re.sub(r"[^A-Za-z0-9]+", "-", f"research-{a.slug}").strip("-")
    camp_dir = logdir / "nous_runs" / run_slug
    out = Path(a.out).resolve()
    if a.attach is not None:
        pat = f"nous_research_isolated.py {a.problem_id} --slug {a.slug} "
        alive = lambda: subprocess.run(["pgrep", "-f", pat], capture_output=True).returncode == 0
        print(f"[rcap] attached to running runner ({pat.strip()})", flush=True)
        killed, t_cap = watch(a, alive, logdir, camp_dir, a.attach)
        stamp(a, out, logdir, camp_dir, a.attach, killed, t_cap); return
    cmd = [sys.executable, "-u", str(ISO), a.problem_id, "--slug", a.slug, "--model", a.model,
           "--niters", str(a.niters), "--out", str(out), "--logdir", str(logdir),
           "--design-profile", a.design_profile]
    print(f"[rcap] launching isolated nous research: {' '.join(cmd)}", flush=True)
    print(f"[rcap] token-based budget=${a.budget} (rates ${R_IN*1e6:.0f}/${R_OUT*1e6:.0f} per M); "
          f"metrics under {camp_dir}", flush=True)
    proc = subprocess.Popen(cmd, cwd=str(HERE.parent))
    t0 = time.time()
    killed, t_cap = watch(a, lambda: proc.poll() is None, logdir, camp_dir, t0)
    proc.wait()
    stamp(a, out, logdir, camp_dir, t0, killed, t_cap)


if __name__ == "__main__":
    main()
