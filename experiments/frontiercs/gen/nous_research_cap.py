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


def kill_inner_nous(slug):
    pat = rf"nous run .*campaign_{re.escape(slug)}\.yaml"
    subprocess.run(["pkill", "-f", pat]); time.sleep(5)
    subprocess.run(["pkill", "-9", "-f", pat])


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
    a = ap.parse_args()
    logdir = Path(os.path.expanduser(a.logdir))
    # mirror the isolated runner's path derivation
    run_slug = re.sub(r"[^A-Za-z0-9]+", "-", f"research-{a.slug}").strip("-")
    camp_dir = logdir / "nous_runs" / run_slug
    out = Path(a.out).resolve()

    cmd = [sys.executable, "-u", str(ISO), a.problem_id, "--slug", a.slug, "--model", a.model,
           "--niters", str(a.niters), "--out", str(out), "--logdir", str(logdir)]
    print(f"[rcap] launching isolated nous research: {' '.join(cmd)}", flush=True)
    print(f"[rcap] token-based budget=${a.budget} (rates ${R_IN*1e6:.0f}/${R_OUT*1e6:.0f} per M); "
          f"metrics under {camp_dir}", flush=True)
    proc = subprocess.Popen(cmd, cwd=str(HERE.parent))
    killed = False; t0 = time.time()
    while proc.poll() is None:
        time.sleep(a.poll)
        cost = token_cost(camp_dir)
        print(f"[rcap {time.strftime('%H:%M:%S')}] elapsed={int(time.time()-t0)}s cost=${cost:.2f} "
              f"(budget ${a.budget})", flush=True)
        if not killed and cost >= a.budget:
            print(f"[rcap] cost ${cost:.2f} >= ${a.budget} -> kill inner `nous run` (runner harvests)", flush=True)
            kill_inner_nous(a.slug); killed = True
    rc = proc.wait()
    final_cost = token_cost(camp_dir)
    print(f"[rcap] runner exited rc={rc}; capped={killed}; token-cost=${final_cost:.2f}", flush=True)
    try:
        pred = json.loads(out.read_text())
        pred["cost_usd_tokenbased"] = round(final_cost, 2)
        pred["cost_rates_per_mtok"] = {"in": R_IN*1e6, "out": R_OUT*1e6,
                                       "cache_write": R_CW*1e6, "cache_read": R_CR*1e6}
        pred["cost_capped"] = killed
        out.write_text(json.dumps(pred, indent=2))
        print(f"[rcap] stamped token-based cost into {out}", flush=True)
    except Exception as e:
        print(f"[rcap] WARN could not stamp cost into {out}: {e}", flush=True)


if __name__ == "__main__":
    main()
