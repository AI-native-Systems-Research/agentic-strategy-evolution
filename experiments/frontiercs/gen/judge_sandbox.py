"""Run a research-task evaluator so the judged solution cannot leak anything back to the agent.

The official Frontier-CS runner scores inside Docker; we score on the host, so the solution would
otherwise run with full file access and could copy engine source / data into a place the agent can
read (e.g. /tmp). Here every evaluation runs under sandbox-exec with no network and no file writes
except a private scratch dir that is deleted afterwards. Only the score leaves.
"""
import json, os, shlex, shutil, subprocess, tempfile
from pathlib import Path


def evaluate(evalpy, problem_dir, solution_code, timeout=600):
    """Return the evaluator's JSON dict (or {} on failure)."""
    priv = Path(tempfile.mkdtemp(prefix="fcsj_"))
    # cant_be_late: evaluator resolves ../common from its real path, prints JSON to stdout, has no --out
    cbl = "cant_be_late" in str(problem_dir)
    try:
        sol = priv / "solution.py"; sol.write_text(solution_code)
        # private working copy of the problem dir: small files copied, dirs symlinked (read-only via sandbox),
        # so evaluator side files (.coverage, output_program.py, results.json) stay private and runs never collide
        work = priv / "problem"; work.mkdir()
        for e in Path(problem_dir).iterdir():
            if e.name in (".evalvenv", "__pycache__") or e.name.startswith(".coverage"): continue
            if e.is_dir() or cbl: (work / e.name).symlink_to(e.resolve())
            else: shutil.copy2(e, work / e.name)
        out = priv / "out.json"
        prof = priv / "judge.sb"
        rp = os.path.realpath(priv)
        prof.write_text("(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)\n"
                        f'(allow file-write* (subpath "{rp}"))\n'
                        '(allow file-write* (literal "/dev/null") (literal "/dev/stdout") (literal "/dev/stderr") (regex #"^/dev/tty"))\n')
        env = dict(os.environ, TMPDIR=rp, HOME=rp, PYTHONDONTWRITEBYTECODE="1", MPLCONFIGDIR=rp)
        cmd = (f"sandbox-exec -f {shlex.quote(str(prof))} {shlex.quote(str(evalpy))} "
               f"{shlex.quote(str(work/'evaluator.py'))} --solution {shlex.quote(str(sol))}")
        if not cbl: cmd += f" --out {shlex.quote(str(out))}"
        try:
            r = subprocess.run(cmd, shell=True, cwd=str(work), env=env, capture_output=True, text=True, timeout=timeout)
            if cbl:
                d = json.loads(r.stdout.strip().splitlines()[-1])
                if "error" not in d: d["runs_successfully"] = 1.0
                return d
            return json.loads(out.read_text())
        except (subprocess.TimeoutExpired, OSError, ValueError, IndexError):
            return {}
    finally:
        shutil.rmtree(priv, ignore_errors=True)


def score(evalpy, problem_dir, solution_code, timeout=600):
    d = evaluate(evalpy, problem_dir, solution_code, timeout)
    if not d or d.get("error") or d.get("runs_successfully", 0.0) != 1.0: return 0.0
    return float(d.get("score", 0.0))
