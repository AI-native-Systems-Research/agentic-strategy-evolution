"""SWE-fficiency patch generation (host-driven agent + docker exec).

Runs on the Linux VM. Starts the prebuilt task container, drives an agent (plain Claude
Code, or Nous) on the HOST to optimize /testbed inside the container via `docker exec`
(the agent reaches the LLM via the litellm tunnel on the host), then extracts a git diff
as model_patch -> preds.jsonl for `swefficiency eval`.

Usage (source ~/.nous_env first for ANTHROPIC_* creds):
  python swe_gen.py <instance_id> --agent claude --model claude-opus-4-6 --out preds/<id>.jsonl --label plain_claude
"""
import argparse, json, os, subprocess, tempfile, time
from pathlib import Path

CONDA = "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed"


def sh(cmd, timeout=None):
    return subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=timeout)


def dexec(cname, inner, timeout=None):
    return sh(f"docker exec {cname} bash -lc {json_q(f'cd /testbed && {CONDA} && {inner}')}", timeout=timeout)


def json_q(s):  # shell-quote via json (double quotes escaped) then wrap for bash -lc
    return "'" + s.replace("'", "'\\''") + "'"


def load_instance(iid, dataset="swefficiency/swefficiency", split="test"):
    import datasets
    ds = datasets.load_dataset(dataset, split=split)
    for r in ds:
        if r["instance_id"] == iid:
            return r
    raise SystemExit(f"instance {iid} not found")


def build_prompt(iid, inst, cname):
    covering = inst.get("covering_tests") or []
    ct = " ".join(covering[:6])
    return f"""You are optimizing the runtime performance of a Python library in a Docker container.

CONTAINER: {cname}  (target repo at /testbed, conda env 'testbed').
Run every command INSIDE the container, e.g.:
  docker exec {cname} bash -lc "cd /testbed && {CONDA} && <CMD>"

GOAL: make the workload script run faster WITHOUT changing its observable behavior.
- Measure runtime:  python /tmp/workload.py   (prints "Mean:" / "Std Dev:")
- Do NOT edit /tmp/workload.py or any test files. Edit only library SOURCE under /testbed.
- Correctness gate: these covering tests MUST still pass:
    {ct}
  Run: python -m pytest -q {ct}

METHOD: measure baseline -> find what the workload exercises -> hypothesize an optimization ->
edit source -> re-measure -> confirm the covering tests still pass. Iterate a few times.
Aim for a genuine speedup with green tests. When finished, stop; your /testbed edits are the patch."""


def run_claude(prompt, model, log_path):
    cc = subprocess.run(
        ["claude", "-p", "--model", model, "--permission-mode", "bypassPermissions",
         "--allowedTools", "Bash", "--output-format", "text"],
        input=prompt, text=True, capture_output=True, timeout=5400,
    )
    Path(log_path).write_text((cc.stdout or "") + "\n---STDERR---\n" + (cc.stderr or ""))
    return cc.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance_id")
    ap.add_argument("--agent", choices=["claude", "nous"], default="claude")
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default=None)
    ap.add_argument("--logdir", default="/home/ubuntu/nous_swe/gen_logs")
    args = ap.parse_args()
    label = args.label or args.agent
    iid = args.instance_id
    Path(args.logdir).mkdir(parents=True, exist_ok=True)

    inst = load_instance(iid)
    img = f"ghcr.io/swefficiency/swefficiency-images:{iid}"
    cname = f"swegen_{iid.replace('__', '_')}_{label}"
    meta = {"instance_id": iid, "agent": args.agent, "label": label, "model": args.model}

    sh(f"docker pull {img}", timeout=1800)
    sh(f"docker rm -f {cname}")
    r = sh(f"docker run -d --name {cname} {img} sleep infinity")
    if r.returncode != 0:
        raise SystemExit("container run failed: " + r.stderr)
    try:
        wf = Path(tempfile.mkdtemp()) / "workload.py"
        wf.write_text(inst["workload"])
        sh(f"docker cp {wf} {cname}:/tmp/workload.py")
        base = dexec(cname, "python /tmp/workload.py", timeout=1200)
        meta["baseline_out"] = (base.stdout or "")[-400:]
        print("BASELINE:", meta["baseline_out"])

        prompt = build_prompt(iid, inst, cname)
        (Path(args.logdir) / f"{cname}.prompt.txt").write_text(prompt)
        t0 = time.time()
        if args.agent == "claude":
            rc = run_claude(prompt, args.model, Path(args.logdir) / f"{cname}.agent.log")
        else:
            raise SystemExit("nous agent wired separately (see run_nous_swe)")
        meta["agent_seconds"] = round(time.time() - t0, 1)
        meta["agent_rc"] = rc

        diff = dexec(cname, "git add -A && git diff --binary --cached HEAD -- . ':(exclude)*/tests/*' ':(exclude)*test_*'", timeout=180).stdout
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w") as f:
            f.write(json.dumps({"instance_id": iid, "model_name_or_path": label, "model_patch": diff}) + "\n")
        meta["patch_bytes"] = len(diff)
        (Path(args.logdir) / f"{cname}.meta.json").write_text(json.dumps(meta, indent=2))
        print("PATCH bytes:", len(diff), "->", args.out)
        print("META:", json.dumps(meta, default=str))
    finally:
        sh(f"docker rm -f {cname}")


if __name__ == "__main__":
    main()
