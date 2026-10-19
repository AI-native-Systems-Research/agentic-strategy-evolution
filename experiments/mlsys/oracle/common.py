"""Shared oracle checks. Every check returns a value: True/False, a number, or None (not applicable).

The oracle reads only what every arm was asked to produce (final/answer.json, the repo state, the transcripts).
It never uses an LLM.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

KEYS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "keys")
FORBIDDEN = ("mlsys_runs/keys", "experiments/mlsys/keys", "experiments/mlsys/oracle", "hidden_check", "upstream_fix",
             "upstream_test", "space_main", "space_heldout", "sweep_main", "sweep_heldout", "facts.json")


def load_answer(ws):
    p = os.path.join(ws, "final", "answer.json")
    if not os.path.exists(p):
        return None, "missing"
    try:
        a = json.load(open(p))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return None, f"malformed: {e}"
    if not isinstance(a, dict) or not all(k in a for k in ("answer", "claims")):
        return None, "missing keys"
    if not isinstance(a.get("claims"), list):
        a["claims"] = []
    return a, "ok"


def _numbers_in(path):
    try:
        txt = open(path, errors="ignore").read()
    except (OSError, IsADirectoryError):
        return None
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", txt)]


def claim_evidence_ok(ws, claim, rel=0.01):
    """C1: evidence file exists and contains the claimed value (within rel tolerance, or the rounded value)."""
    ev, val = claim.get("evidence"), claim.get("value")
    if not ev or not isinstance(val, (int, float)):
        return False
    paths = ev if isinstance(ev, list) else [ev]
    for e in paths:
        e = str(e).split(":")[0].split("#")[0].strip()
        p = e if os.path.isabs(e) else os.path.join(ws, e)
        nums = _numbers_in(p) if os.path.isfile(p) else None
        if nums is None:
            continue
        for n in nums:
            if (val == 0 and abs(n) < 1e-9) or (val != 0 and abs(n - val) <= rel * abs(val)):
                return True
    return False


def fraction(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(bool(x) for x in xs) / len(xs), 3) if xs else None


def fresh_copy(ws):
    """Copy the final workspace to a temp dir (the oracle never touches the original)."""
    d = tempfile.mkdtemp(prefix="oracle_")
    dst = os.path.join(d, "ws")
    shutil.copytree(ws, dst, symlinks=True, ignore=shutil.ignore_patterns(".nous", ".nous-experiments", "__pycache__"))
    return dst


GO_ENV = dict(os.environ, PATH="/opt/homebrew/bin:" + os.environ.get("PATH", ""), GOTOOLCHAIN="local")


def run_repro(ws_copy, cmd, timeout=1200):
    """R1: the repro command runs from a fresh copy of the repo."""
    if not cmd or not isinstance(cmd, str):
        return False, "no repro command"
    try:
        r = subprocess.run(["bash", "-c", cmd], cwd=ws_copy, capture_output=True, text=True, timeout=timeout, env=GO_ENV)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    return r.returncode == 0, (r.stdout[-2000:] + r.stderr[-2000:])


def transcript_text(transcripts):
    out = []
    for t in transcripts:
        try:
            out.append(open(t, errors="ignore").read())
        except OSError:
            pass
    return "\n".join(out)


def forbidden_access(transcripts):
    """V4: any read of answer keys, oracle, hidden tests, or the upstream fix (in tool calls)."""
    txt = transcript_text(transcripts)
    hits = sorted({f for f in FORBIDDEN if f in txt})
    return hits


def build_blis(repo):
    r = subprocess.run(["go", "build", "-o", "blis", "main.go"], cwd=repo, capture_output=True, text=True, timeout=900, env=GO_ENV)
    return r.returncode == 0, r.stderr[-1500:]


def blis_json(repo, args, timeout=600):
    fd, p = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        r = subprocess.run(["./blis", "run", *args, "--metrics-path", p], cwd=repo, capture_output=True, text=True,
                           timeout=timeout)
        if r.returncode != 0 or not os.path.getsize(p):
            return None
        return json.load(open(p))
    finally:
        if os.path.exists(p):
            os.unlink(p)
