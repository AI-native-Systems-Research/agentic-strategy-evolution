"""Native in-container plain-Claude baseline for SWE-fficiency (fair peer of swe_nous_native).

Same container, same core-pinning, same workload/measurement, same model and wall-clock as the
Nous runner, minus the scientific loop: a single `claude -p` session edits /testbed in place and
its final git diff is the patch. The editable install stays intact, so the agent measures its own
edits directly with `PYTHONPATH=/testbed python /tmp/workload.py` (no worktrees, no uninstall).

Usage (on the VM, after `set -a; . ~/.nous_env; set +a`):
  python swe_claude_native.py <instance_id> --out preds/<id>.claude.jsonl --label claude --cpuset 0-1
"""
import argparse, json, os, re, shlex, subprocess, tempfile, time
from pathlib import Path

CONDA = "source /opt/miniconda3/etc/profile.d/conda.sh"
HERE = Path(__file__).resolve().parent
DIFF = ("cd /testbed && git add -A >/dev/null 2>&1 && "
        "git diff --binary --cached HEAD -- . ':(exclude)*/tests/*' ':(exclude)*test_*' ':(exclude)*.so'")


def sh(cmd, timeout=None, check=False):
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=timeout)
    if check and r.returncode != 0:
        raise SystemExit(f"cmd failed ({r.returncode}): {cmd}\n{r.stderr}")
    return r


def dref(cname, inner, env=None, timeout=None):
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


def prompt_text(iid, inst, pkg, base_mean):
    return f"""You are optimizing the RUNTIME PERFORMANCE of the Python library '{pkg}' (repo {inst.get('repo')}).
The source is at /testbed. Edit only library SOURCE under /testbed, never test files.

MEASURE runtime of the fixed workload (lower is faster):
    bash /tmp/measure.sh
It prints 'Mean:' seconds. The clean baseline mean is {base_mean:.4f}s; your goal is a genuine speedup.

CORRECTNESS GATE (must stay green):
    bash /tmp/test.sh
Do NOT edit /tmp/workload.py or any test files. A speedup that breaks any covering test is worthless.

METHOD: measure the baseline, find what the workload exercises, hypothesize an optimization, edit
the source, re-measure, and confirm the covering tests still pass. Iterate a few times. When done,
leave your best correct optimization in place in /testbed."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance_id")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="claude")
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--logdir", default="/home/ubuntu/nous_swe/gen_logs")
    ap.add_argument("--cpuset", default="")
    ap.add_argument("--wall", type=int, default=7200)
    args = ap.parse_args()
    iid = args.instance_id
    Path(args.logdir).mkdir(parents=True, exist_ok=True)

    inst = load_instance(iid)
    pkg = (inst.get("repo") or "").split("/")[-1] or iid.split("__")[0]
    ct = " ".join(inst.get("covering_tests") or [])
    img = f"ghcr.io/swefficiency/swefficiency-images:{iid}"
    cname = f"swec_{iid.replace('__', '_')}"
    meta = {"instance_id": iid, "label": args.label, "model": args.model, "pkg": pkg, "mode": "native", "cpuset": args.cpuset}

    sh(f"docker pull {img}", timeout=1800)
    sh(f"docker rm -f {cname}")
    cpu = f"--cpuset-cpus {args.cpuset} " if args.cpuset else ""
    thr = "-e OMP_NUM_THREADS=1 -e OPENBLAS_NUM_THREADS=1 -e MKL_NUM_THREADS=1 -e NUMEXPR_NUM_THREADS=1 "
    r = sh(f"docker run -d --network host {cpu}{thr}--name {cname} {img} sleep infinity")
    if r.returncode != 0:
        raise SystemExit("container run failed: " + r.stderr)
    try:
        wf = Path(tempfile.mkdtemp()) / "workload.py"
        wf.write_text(inst["workload"])
        sh(f"docker cp {wf} {cname}:/tmp/workload.py", check=True)
        # measure/test helper scripts (wrap conda activate so the agent's calls are one-liners)
        tmp = Path(tempfile.mkdtemp())
        (tmp / "measure.sh").write_text(f"{CONDA} && conda activate testbed && cd /testbed && PYTHONPATH=/testbed python /tmp/workload.py\n")
        (tmp / "test.sh").write_text(f"{CONDA} && conda activate testbed && cd /testbed && python -m pytest -q {ct}\n")
        sh(f"docker cp {tmp/'measure.sh'} {cname}:/tmp/measure.sh", check=True)
        sh(f"docker cp {tmp/'test.sh'} {cname}:/tmp/test.sh", check=True)
        sh(f"docker cp {HERE / 'container_setup.sh'} {cname}:/tmp/container_setup.sh", check=True)

        print("[setup] node/claude + test deps (claude mode)...")
        s = dref(cname, f"bash /tmp/container_setup.sh {shlex.quote(pkg)} claude", timeout=1800)
        (Path(args.logdir) / f"{cname}.setup.log").write_text(s.stdout + "\n---\n" + s.stderr)
        if "claude=/" not in s.stdout:
            raise SystemExit("setup did not report claude on PATH; see setup.log")

        base_mean = parse_mean(dref(cname, "bash /tmp/measure.sh", timeout=1200).stdout)
        meta["base_mean"] = base_mean
        print("BASELINE mean:", base_mean)

        prompt = prompt_text(iid, inst, pkg, base_mean)
        (Path(args.logdir) / f"{cname}.prompt.txt").write_text(prompt)
        env = {
            "IS_SANDBOX": "1",
            "ANTHROPIC_BASE_URL": os.environ.get("ANTHROPIC_BASE_URL", ""),
            "ANTHROPIC_AUTH_TOKEN": os.environ.get("ANTHROPIC_AUTH_TOKEN", os.environ.get("ANTHROPIC_API_KEY", "")),
            "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_AUTH_TOKEN", "")),
        }
        # write the prompt to a file in the container and feed via stdin (avoids arg-quoting hell)
        pf = tmp / "prompt.txt"; pf.write_text(prompt)
        sh(f"docker cp {pf} {cname}:/tmp/prompt.txt", check=True)
        claude_cmd = (
            f"{CONDA} && conda activate base && cd /testbed && "
            f"claude -p --model {args.model} --permission-mode bypassPermissions "
            f"--allowedTools Bash Read Edit Write --output-format text < /tmp/prompt.txt")
        print("[claude] launching session...")
        t0 = time.time()
        cc = dref(cname, claude_cmd, env=env, timeout=args.wall)
        meta["claude_seconds"] = round(time.time() - t0, 1)
        meta["claude_rc"] = cc.returncode
        (Path(args.logdir) / f"{cname}.agent.log").write_text((cc.stdout or "") + "\n---STDERR---\n" + (cc.stderr or ""))
        print(f"[claude] finished rc={cc.returncode} in {meta['claude_seconds']}s")

        diff = dref(cname, DIFF, timeout=180).stdout
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w") as f:
            f.write(json.dumps({"instance_id": iid, "model_name_or_path": args.label, "model_patch": diff}) + "\n")
        meta["patch_bytes"] = len(diff)
        (Path(args.logdir) / f"{cname}.meta.json").write_text(json.dumps(meta, indent=2))
        print("PATCH bytes:", len(diff), "->", args.out)
    finally:
        sh(f"docker rm -f {cname}")


if __name__ == "__main__":
    main()
