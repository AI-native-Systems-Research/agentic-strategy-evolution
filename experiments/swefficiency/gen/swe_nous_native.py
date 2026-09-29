"""Native in-container Nous runner for SWE-fficiency.

Unlike the old host-driven docker-exec adapter (which handicapped Nous by splitting its
artifact filesystem from the run env and extracting the final /testbed state), this runs
Nous *inside* the task container in its native git-worktree mode:

  - Nous + Node + Claude CLI are installed into the container's base (py3.11) conda env.
  - The target package's editable install is removed so a worktree's source becomes the
    code-under-test via PYTHONPATH (the egg-link otherwise pins imports to /testbed).
  - repo_path=/testbed, worktree mode: each arm is a git worktree; the executor measures
    `PYTHONPATH=$PWD python /tmp/workload.py` and gates on the covering tests.
  - The container reaches the LLM via the VM's reverse SSH tunnel to the laptop
    (--network host + a loopback /etc/hosts entry for the litellm host).

Deliverable extraction is INDEPENDENT of Nous's own ranking: after the run we harvest every
candidate patch (per-arm branches + any patches/*.patch), replay each on a clean /testbed,
measure speedup + covering-test correctness ourselves, and emit the best correct patch. This
makes the score trustworthy regardless of what the agent self-reported.

Usage (on the VM, after `set -a; . ~/.nous_env; set +a`):
  python swe_nous_native.py <instance_id> --out preds/<id>.nous.jsonl --label nous \
      --nous-iters 5 --stop-speedup 1.2
"""
import argparse, json, os, re, shlex, subprocess, tempfile, time
from pathlib import Path

CONDA = "source /opt/miniconda3/etc/profile.d/conda.sh"
HERE = Path(__file__).resolve().parent


def sh(cmd, timeout=None, check=False):
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=timeout)
    if check and r.returncode != 0:
        raise SystemExit(f"cmd failed ({r.returncode}): {cmd}\n{r.stderr}")
    return r


def dref(cname, inner, env=None, timeout=None):
    """Run a bash snippet inside the container (base shell)."""
    e = "".join(f"-e {k}={shlex.quote(str(v))} " for k, v in (env or {}).items())
    return sh(f"docker exec {e}{cname} bash -lc {shlex.quote(inner)}", timeout=timeout)


def parse_mean(out):
    m = re.search(r"Mean:\s*([0-9.eE+-]+)", out or "")
    return float(m.group(1)) if m else None


def load_instance(iid, dataset="swefficiency/swefficiency", split="test"):
    import datasets
    ds = datasets.load_dataset(dataset, split=split)
    for r in ds:
        if r["instance_id"] == iid:
            return r
    raise SystemExit(f"instance {iid} not found")


def build_description(iid, inst, pkg, ct, base_mean):
    return (
        f"You are optimizing the RUNTIME PERFORMANCE of the Python library '{pkg}' "
        f"(repo {inst.get('repo')}). Your working directory is a git worktree containing the "
        f"full library source; edit only library SOURCE, never test files.\n\n"
        f"MEASURE runtime of the fixed workload with:\n"
        f"    PYTHONPATH=$PWD python /tmp/workload.py\n"
        f"It prints 'Mean:' seconds (lower is faster). The clean baseline mean is "
        f"{base_mean:.4f}s. Your speedup = {base_mean:.4f} / your_mean.\n\n"
        f"CORRECTNESS GATE (must stay green, run from your worktree):\n"
        f"    python -m pytest -q {ct}\n"
        f"Do NOT edit /tmp/workload.py or any test files. A change that speeds up the workload "
        f"but breaks any covering test is worthless (speedup nullified to 1.0).\n\n"
        f"For every experiment arm, record the measured mean and the speedup "
        f"(baseline_mean / arm_mean) in the finding's metadata under key 'speedup', and keep "
        f"the covering tests passing. Aim for the largest genuine speedup with green tests."
    )


def write_campaign(cname, iid, inst, pkg, ct, base_mean, model, nous_iters):
    import yaml
    spec = {
        "research_question": (
            f"How can we reduce the runtime of the workload for {inst.get('repo')} without "
            f"changing observable behavior, while keeping the covering tests green?"),
        "run_id": f"swe-{iid}",
        "max_iterations": nous_iters,
        "sandbox": "bypass",
        "target_system": {
            "name": f"swefficiency::{iid}",
            "description": build_description(iid, inst, pkg, ct, base_mean),
            "repo_path": "/testbed",
            "observable_metrics": ["speedup"],
            "controllable_knobs": ["source_code_edits"],
        },
        "objective": {"weights": {"speedup": 1.0}},
        "models": {"design": model, "execute_analyze": model, "report": model},
        "prompts": {"methodology_layer": "/opt/nous_repo/prompts/methodology",
                    "domain_adapter_layer": None},
    }
    p = Path(tempfile.mkdtemp()) / "campaign.yaml"
    p.write_text(yaml.safe_dump(spec, sort_keys=False))
    sh(f"docker cp {p} {cname}:/tmp/campaign.yaml", check=True)


HARVEST = r'''
set -uo pipefail
source /opt/miniconda3/etc/profile.d/conda.sh
BASE="$1"; shift
CT="$*"
mkdir -p /tmp/cands
cd /testbed
# candidate patches: one per non-master branch Nous created (base..branch), + any patches/*.patch
i=0
for b in $(git branch --format='%(refname:short)' | grep -v '^master$'); do
  git diff "$BASE".."$b" > /tmp/cands/br_$i.patch 2>/dev/null || true
  [ -s /tmp/cands/br_$i.patch ] && i=$((i+1)) || rm -f /tmp/cands/br_$i.patch
done
for f in $(find /tmp/nous_runs -path '*/patches/*.patch' 2>/dev/null); do
  cp "$f" /tmp/cands/pf_$i.patch 2>/dev/null && i=$((i+1)) || true
done
echo "CANDIDATES=$i"
conda activate testbed
clean() { cd /testbed && git checkout -f "$BASE" -- . >/dev/null 2>&1; git clean -fdq; }
clean
BASE_MEAN=$(PYTHONPATH=/testbed timeout 600 python /tmp/workload.py 2>/dev/null | sed -n 's/^Mean:[[:space:]]*//p')
echo "BASE_MEAN=$BASE_MEAN"
best=""; best_sp=1.0
for p in /tmp/cands/*.patch; do
  [ -s "$p" ] || continue
  clean
  if ! git apply --whitespace=nowarn "$p" >/dev/null 2>&1; then
    if ! (patch -p1 --forward --fuzz=3 < "$p" >/dev/null 2>&1); then echo "SKIP_APPLY $p"; continue; fi
  fi
  M=$(PYTHONPATH=/testbed timeout 600 python /tmp/workload.py 2>/dev/null | sed -n 's/^Mean:[[:space:]]*//p')
  [ -z "$M" ] && { echo "NOMEAS $p"; continue; }
  if python -m pytest -q $CT >/dev/null 2>&1; then ok=1; else ok=0; fi
  SP=$(python -c "b=$BASE_MEAN;m=$M;print(round(b/m,4) if m>0 else 0)")
  echo "CAND $p mean=$M speedup=${SP}x correct=$ok"
  if [ "$ok" = "1" ]; then
    win=$(python -c "print(1 if $SP>$best_sp else 0)")
    [ "$win" = "1" ] && { best="$p"; best_sp=$SP; }
  fi
done
clean
echo "BEST_PATCH=$best BEST_SPEEDUP=${best_sp}x"
[ -n "$best" ] && cp "$best" /tmp/best.patch || : > /tmp/best.patch
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance_id")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="nous")
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--logdir", default="/home/ubuntu/nous_swe/gen_logs")
    ap.add_argument("--nous-iters", type=int, default=5)
    ap.add_argument("--nous-src-tgz", default="/home/ubuntu/nous_swe/nous_src.tgz")
    ap.add_argument("--phase-timeout", type=int, default=2400)
    ap.add_argument("--wall", type=int, default=10800)
    ap.add_argument("--cpuset", default="",
                    help="dedicated CPU cores for this container (e.g. '2-3'); isolates the "
                         "timing-sensitive workload measurement so parallel tasks don't corrupt it")
    args = ap.parse_args()
    iid = args.instance_id
    Path(args.logdir).mkdir(parents=True, exist_ok=True)

    inst = load_instance(iid)
    pkg = (inst.get("repo") or "").split("/")[-1] or iid.split("__")[0]
    ct = " ".join(inst.get("covering_tests") or [])
    img = f"ghcr.io/swefficiency/swefficiency-images:{iid}"
    cname = f"swenous_{iid.replace('__', '_')}"
    meta = {"instance_id": iid, "label": args.label, "model": args.model, "pkg": pkg, "mode": "native"}

    sh(f"docker pull {img}", timeout=1800)
    sh(f"docker rm -f {cname}")
    cpu = f"--cpuset-cpus {args.cpuset} " if args.cpuset else ""
    # force single-threaded numeric libs so workload timing is deterministic and core-isolated
    thr = "-e OMP_NUM_THREADS=1 -e OPENBLAS_NUM_THREADS=1 -e MKL_NUM_THREADS=1 -e NUMEXPR_NUM_THREADS=1 "
    r = sh(f"docker run -d --network host {cpu}{thr}--name {cname} {img} sleep infinity")
    meta["cpuset"] = args.cpuset
    if r.returncode != 0:
        raise SystemExit("container run failed: " + r.stderr)
    try:
        # workload + nous source + setup script into the container
        wf = Path(tempfile.mkdtemp()) / "workload.py"
        wf.write_text(inst["workload"])
        sh(f"docker cp {wf} {cname}:/tmp/workload.py", check=True)
        sh(f"docker exec {cname} mkdir -p /opt/nous_repo", check=True)
        sh(f"docker cp {args.nous_src_tgz} {cname}:/tmp/nous_src.tgz", check=True)
        sh(f"docker exec {cname} bash -lc 'tar xzf /tmp/nous_src.tgz -C /opt/nous_repo'", check=True)
        sh(f"docker cp {HERE / 'container_setup.sh'} {cname}:/tmp/container_setup.sh", check=True)

        print("[setup] installing node/claude/nous + prepping env (few min)...")
        s = dref(cname, f"bash /tmp/container_setup.sh {shlex.quote(pkg)}", timeout=1800)
        (Path(args.logdir) / f"{cname}.setup.log").write_text(s.stdout + "\n---\n" + s.stderr)
        print("[setup]", s.stdout.strip().splitlines()[-1] if s.stdout.strip() else s.stderr[-300:])
        if "nous=" not in s.stdout or "claude=" not in s.stdout:
            raise SystemExit("setup did not report nous/claude on PATH; see setup.log")

        base = dref(cname, f"{CONDA} && conda activate testbed && cd /testbed && "
                           f"PYTHONPATH=/testbed python /tmp/workload.py", timeout=1200)
        base_mean = parse_mean(base.stdout)
        meta["base_mean"] = base_mean
        print("BASELINE mean:", base_mean)
        if not base_mean:
            raise SystemExit("could not measure baseline: " + base.stderr[-400:])

        write_campaign(cname, iid, inst, pkg, ct, base_mean, args.model, args.nous_iters)
        base_commit = dref(cname, "cd /testbed && git rev-parse HEAD").stdout.strip()
        meta["base_commit"] = base_commit

        env = {
            "NOUS_CAMPAIGN_PARENT": "/tmp/nous_runs",
            # the container runs as root; IS_SANDBOX=1 lets the Claude CLI accept
            # --dangerously-skip-permissions under root (documented Docker/CI escape).
            "IS_SANDBOX": "1",
            "ANTHROPIC_BASE_URL": os.environ.get("ANTHROPIC_BASE_URL", ""),
            "ANTHROPIC_AUTH_TOKEN": os.environ.get("ANTHROPIC_AUTH_TOKEN", os.environ.get("ANTHROPIC_API_KEY", "")),
            "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_AUTH_TOKEN", "")),
            # extractor/report phases use the OpenAI-compatible LLMDispatcher path
            "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL", ""),
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
        }
        nous_cmd = (
            f"{CONDA} && conda activate base && cd /testbed && "
            f"nous run /tmp/campaign.yaml --auto-approve --agent sdk --sandbox bypass "
            f"--max-iterations {args.nous_iters} --timeout {args.phase_timeout}")
        print("[nous] launching campaign...")
        t0 = time.time()
        run = dref(cname, nous_cmd, env=env, timeout=args.wall)
        meta["nous_seconds"] = round(time.time() - t0, 1)
        meta["nous_rc"] = run.returncode
        (Path(args.logdir) / f"{cname}.nous.log").write_text((run.stdout or "") + "\n---STDERR---\n" + (run.stderr or ""))
        print(f"[nous] finished rc={run.returncode} in {meta['nous_seconds']}s")

        # independent harvest + rescore of every candidate patch
        hs = Path(tempfile.mkdtemp()) / "harvest.sh"
        hs.write_text(HARVEST)
        sh(f"docker cp {hs} {cname}:/tmp/harvest.sh", check=True)
        h = dref(cname, f"bash /tmp/harvest.sh {base_commit} {ct}", timeout=3600)
        (Path(args.logdir) / f"{cname}.harvest.log").write_text(h.stdout + "\n---\n" + h.stderr)
        print("[harvest]\n" + h.stdout)
        m = re.search(r"BEST_SPEEDUP=([0-9.]+)x", h.stdout)
        meta["nous_best_speedup"] = float(m.group(1)) if m else None

        diff = dref(cname, "cat /tmp/best.patch 2>/dev/null").stdout
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w") as f:
            f.write(json.dumps({"instance_id": iid, "model_name_or_path": args.label, "model_patch": diff}) + "\n")
        meta["patch_bytes"] = len(diff)
        (Path(args.logdir) / f"{cname}.meta.json").write_text(json.dumps(meta, indent=2))
        print("PATCH bytes:", len(diff), "-> best_speedup", meta.get("nous_best_speedup"), "->", args.out)
    finally:
        sh(f"docker rm -f {cname}")


if __name__ == "__main__":
    main()
