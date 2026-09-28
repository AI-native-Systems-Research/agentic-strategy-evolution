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
    ct = " ".join(covering)  # ALL covering tests — scoring runs the full set
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


def run_nous(iid, inst, cname, model, logdir, nous_bin, nous_repo):
    """Run a Nous campaign that optimizes /testbed inside the task container via docker exec."""
    import yaml
    covering = inst.get("covering_tests") or []
    ct = " ".join(covering)
    run_dir = Path(logdir) / f"nous_{cname}"
    run_dir.mkdir(parents=True, exist_ok=True)
    desc = (
        f"A prebuilt Docker container named '{cname}' holds a Python library checked out at /testbed "
        f"(conda env 'testbed'). ALL work MUST happen inside that container via:\n"
        f'  docker exec {cname} bash -lc "cd /testbed && {CONDA} && <CMD>"\n'
        f"Measure runtime with: python /tmp/workload.py (prints Mean/Std). Do NOT edit /tmp/workload.py "
        f"or any test files. Optimize only library SOURCE under /testbed. Correctness gate: these covering "
        f"tests MUST pass: {ct} (run: python -m pytest -q <files>). Your /testbed edits in the container "
        f"are collected as the patch; there is no separate submission."
    )
    spec = {
        "research_question": f"How can we reduce the runtime of the workload for {inst.get('repo')} "
                             f"without changing its behavior, while keeping the covering tests green?",
        "run_id": f"swe-{iid}",
        "max_iterations": 1,
        "target_system": {
            "name": f"swefficiency::{iid}",
            "description": desc,
            "repo_path": str(run_dir / "workspace"),
            "live_target": True,
            "observable_metrics": ["workload_mean_runtime", "test_pass_count"],
            "controllable_knobs": ["source_code_edits"],
        },
        "models": {"design": model, "execute_analyze": model, "report": model},
        "prompts": {"methodology_layer": f"{nous_repo}/prompts/methodology", "domain_adapter_layer": None},
    }
    (run_dir / "workspace").mkdir(exist_ok=True)
    camp = run_dir / "campaign.yaml"
    camp.write_text(yaml.safe_dump(spec, sort_keys=False))
    env = dict(os.environ)
    env["NOUS_CAMPAIGN_PARENT"] = str(run_dir / "nous_runs")
    log = run_dir / "nous.log"
    cmd = [nous_bin, "run", str(camp), "--auto-approve", "--agent", "sdk", "--sandbox", "bypass", "--max-iterations", "1"]
    with open(log, "w") as lf:
        p = subprocess.run(cmd, cwd=nous_repo, env=env, stdout=lf, stderr=subprocess.STDOUT, text=True, timeout=7200)
    return p.returncode


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
    ap.add_argument("--nous-bin", default="/home/ubuntu/nous_repo/.venv/bin/nous")
    ap.add_argument("--nous-repo", default="/home/ubuntu/nous_repo")
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

        t0 = time.time()
        if args.agent == "claude":
            prompt = build_prompt(iid, inst, cname)
            (Path(args.logdir) / f"{cname}.prompt.txt").write_text(prompt)
            rc = run_claude(prompt, args.model, Path(args.logdir) / f"{cname}.agent.log")
        else:  # nous
            rc = run_nous(iid, inst, cname, args.model, args.logdir, args.nous_bin, args.nous_repo)
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
