#!/usr/bin/env python3
"""Launch an algorithmic Nous campaign under a TOKEN-BASED $50 cap.

Why this exists (iso-cost fairness across model tiers): the Claude baseline runner
(claude_code_runner.py) counts spend as tokens x a FIXED rate ($15/$75/M, cache-aware) regardless of
model. If the Nous arm instead trusts the SDK's own ``cost_usd`` (which is model-aware: Sonnet billed
~0.6x of Opus on the IBM gateway), then at the Sonnet tier the SAME $50 would buy Nous ~1.6-5x more
tokens than Claude -> the comparison is no longer iso-cost. This launcher computes Nous's cumulative
spend with the SAME fixed rates as the Claude runner, so both agents count the $50 identically at ANY
model tier (opus, sonnet, haiku, ...). The absolute dollar figure is a consistent yardstick, not the
gateway's real billing; what matters is that both arms use the identical unit.

Mechanism: spawn frontier_gen_costbudget.py (--agent nous), poll the campaign's llm_metrics.jsonl,
and when the token-based cost crosses --budget, ``pkill`` the inner ``nous run`` process. The driver's
run_nous() then returns and harvests + re-judges the persisted candidate solutions (patch/inputs based),
writing the pred JSON. Nothing about scoring or isolation changes; only the cost yardstick.

Usage:
  nous_cap_launch.py 5 --model aws/claude-sonnet-4-5 --label sonnet45 --budget 50 \
    --nous-iters 30 --out nous_gates/preds/p5.sonnet45.json --logdir ~/frontier/gen_logs
"""
import argparse, glob, json, os, re, signal, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRIVER = HERE / "frontier_gen_costbudget.py"

# SAME fixed rates as claude_code_runner.py (Anthropic list, cache-aware). Model-INDEPENDENT on purpose:
# both arms must weigh tokens identically for the $50 to mean the same thing at every tier.
R_IN, R_OUT, R_CW, R_CR = 15/1e6, 75/1e6, 18.75/1e6, 1.5/1e6
FRONTIER = os.environ.get("FRONTIER_DIR", os.path.expanduser("~/frontier/Frontier-CS"))
FEVAL = os.environ.get("FEVAL_BIN", f"{FRONTIER}/.venv/bin/frontier")


def token_cost(camp_dir):
    """Cumulative token-based cost over every llm_metrics.jsonl row under the campaign dir."""
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


def snapshot_solutions(ws_experiments, preserve_dir, seen):
    """Copy any non-stub worktree solution.cpp into preserve_dir BEFORE #133 cleanup removes it.
    Nous runs each arm in a per-iteration git worktree that is cleaned between iterations, so the
    high-scoring intermediate solutions vanish before the end-of-run harvest. We snapshot them live
    (keyed by content hash) so the true best can be re-judged at the end."""
    import hashlib
    preserve_dir.mkdir(parents=True, exist_ok=True)
    for sol in Path(ws_experiments).glob("*/solution.cpp") if Path(ws_experiments).exists() else []:
        try:
            body = sol.read_text()
        except Exception:
            continue
        if len(body.splitlines()) < 5:
            continue  # stub
        h = hashlib.sha1(body.encode()).hexdigest()[:12]
        if h in seen:
            continue
        seen.add(h)
        (preserve_dir / f"{h}.cpp").write_text(body)


def kill_inner_nous(pid):
    """Terminate the inner `nous run ... campaign_<pid>.yaml` so the driver proceeds to harvest."""
    pat = rf"nous run .*campaign_{pid}\.yaml"
    subprocess.run(["pkill", "-f", pat])
    # give it a moment, then hard-kill any stragglers
    time.sleep(5)
    subprocess.run(["pkill", "-9", "-f", pat])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pid")
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--label", required=True)
    ap.add_argument("--budget", type=float, default=50.0)
    ap.add_argument("--nous-iters", type=int, default=30)
    ap.add_argument("--out", required=True)
    ap.add_argument("--logdir", default=os.path.expanduser("~/frontier/gen_logs"))
    ap.add_argument("--poll", type=float, default=20.0, help="seconds between cost polls")
    a = ap.parse_args()
    pid = a.pid
    logdir = Path(os.path.expanduser(a.logdir))
    run_slug = re.sub(r"[^A-Za-z0-9]+", "-", f"frontier-{pid}-{a.label}").strip("-")
    camp_dir = logdir / "nous_runs" / run_slug
    out = Path(a.out).resolve()

    cmd = [sys.executable, "-u", str(DRIVER), pid, "--agent", "nous", "--model", a.model,
           "--nous-iters", str(a.nous_iters), "--label", a.label,
           "--out", str(out), "--logdir", str(logdir)]
    print(f"[cap] launching nous: {' '.join(cmd)}", flush=True)
    print(f"[cap] token-based budget=${a.budget} (rates ${R_IN*1e6:.0f}/${R_OUT*1e6:.0f} per M); "
          f"metrics under {camp_dir}", flush=True)
    ws_experiments = logdir / f"frontier_{pid}_{a.label}_ws" / ".nous-experiments"
    preserve_dir = logdir / f"nous_preserved_{a.label}"
    seen_hashes: set = set()
    proc = subprocess.Popen(cmd, cwd=str(HERE.parent))  # cwd=experiments/frontiercs
    killed = False
    t0 = time.time()
    while proc.poll() is None:
        time.sleep(a.poll)
        snapshot_solutions(ws_experiments, preserve_dir, seen_hashes)  # before #133 cleanup eats them
        cost = token_cost(camp_dir)
        print(f"[cap {time.strftime('%H:%M:%S')}] elapsed={int(time.time()-t0)}s cost=${cost:.2f} "
              f"(budget ${a.budget}) preserved={len(seen_hashes)}", flush=True)
        if not killed and cost >= a.budget:
            print(f"[cap] cost ${cost:.2f} >= budget ${a.budget} -> killing inner `nous run` "
                  f"(driver will harvest)", flush=True)
            kill_inner_nous(pid)
            killed = True
            # keep polling: the driver is now harvesting + re-judging; wait for it to finish and write out
    snapshot_solutions(ws_experiments, preserve_dir, seen_hashes)
    rc = proc.wait()
    final_cost = token_cost(camp_dir)
    print(f"[cap] driver exited rc={rc}; capped={killed}; final token-cost=${final_cost:.2f}", flush=True)
    # TRUE best: re-judge every preserved iteration solution (worktrees are cleaned by #133, so these
    # snapshots are the only durable record of each arm's actual code) via the SAME out-of-sandbox judge.
    true_best = -1.0; true_best_file = None
    for cpp in sorted(preserve_dir.glob("*.cpp")) if preserve_dir.exists() else []:
        r = subprocess.run(f"{FEVAL} eval algorithmic {pid} {cpp} --json", shell=True,
                           capture_output=True, text=True, cwd=FRONTIER, timeout=900)
        import re as _re
        ms = _re.findall(r'"score"\s*:\s*([0-9.]+)', r.stdout + r.stderr)
        sc = max((float(m) for m in ms), default=-1.0)
        if sc > true_best:
            true_best, true_best_file = sc, cpp
    print(f"[cap] TRUE best over {len(list(preserve_dir.glob('*.cpp'))) if preserve_dir.exists() else 0} "
          f"preserved solutions = {true_best} ({true_best_file})", flush=True)
    # stamp the token-based cost into the pred so the reported number matches the enforced yardstick
    try:
        pred = json.loads(out.read_text())
        pred["cost_usd_tokenbased"] = round(final_cost, 2)
        pred["cost_rates_per_mtok"] = {"in": R_IN*1e6, "out": R_OUT*1e6,
                                       "cache_write": R_CW*1e6, "cache_read": R_CR*1e6}
        pred["cost_capped"] = killed
        # Prefer the TRUE best over preserved iteration solutions (robust to #133 worktree cleanup).
        if true_best >= 0:
            pred["final_score_preserved"] = round(true_best, 2)
            pred["preserved_solutions"] = len(list(preserve_dir.glob("*.cpp")))
            if (pred.get("final_score") or -1) < true_best:
                pred["final_score_harvested"] = pred.get("final_score")
                pred["final_score"] = round(true_best, 2)
        out.write_text(json.dumps(pred, indent=2))
        print(f"[cap] stamped cost + true best ({true_best}) into {out}", flush=True)
    except Exception as e:
        print(f"[cap] WARN could not stamp cost into {out}: {e}", flush=True)


if __name__ == "__main__":
    main()
