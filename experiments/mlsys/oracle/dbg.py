"""Oracle for the debugging task (BLIS bug d8271ee: TotalOutputTokens double-counted after preemption).

All checks run on the arm's final repository state, applied to a fresh copy:
- D1 root cause located: the answer names sim/simulator.go and the decode-step accounting / completion path;
- D2 the upstream fix's own test (hidden from the agent) passes on the arm's code;
- D3 the full existing test suite passes;
- D4 our hidden black-box regression checks pass (keys/dbg/hidden_check.py, 8 cases);
- D5 the arm added a test that fails on the original buggy code and passes on its fix;
- D6 the patch is minimal (non-test Go lines changed, files touched outside sim/).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

from common import KEYS

sys.path.insert(0, os.path.join(KEYS, "dbg"))
import hidden_check  # noqa: E402

BASE = "/Users/toslali/mlsys_runs/repos/task-dbg"
UPSTREAM_TEST = os.path.join(KEYS, "dbg", "upstream_test.patch")


GO_ENV = dict(os.environ, PATH="/opt/homebrew/bin:" + os.environ.get("PATH", ""), GOTOOLCHAIN="local", GOFLAGS="-count=1")


def sh(cmd, cwd, timeout=1800):
    # non-login shell + pinned toolchain: a login shell puts an old /usr/local/go first on PATH
    r = subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True, timeout=timeout, env=GO_ENV)
    return r.returncode, r.stdout + r.stderr


def arm_diff(ws):
    """The arm's change relative to the task base commit (committed or not)."""
    code, base = sh("git rev-list --max-parents=0 HEAD | tail -1", ws)
    base = base.strip().splitlines()[-1] if code == 0 and base.strip() else None
    if not base:
        return ""
    sh("git add -A -N . 2>/dev/null", ws)
    _, d = sh(f"git diff {base} -- . ':(exclude)final' ':(exclude).nous' ':(exclude).nous-experiments' ':(exclude)blis'", ws)
    return d


def file_blocks(diff):
    blocks = {}
    for blk in re.split(r"(?m)^(?=diff --git )", diff):
        m = re.match(r"diff --git a/(\S+) b/", blk)
        if m:
            blocks[m.group(1)] = blk
    return blocks


def changed_lines(blk):
    return sum(1 for l in blk.splitlines() if l.startswith(("+", "-")) and not l.startswith(("+++", "---")))


def score(ws, answer, text):
    res = {}
    diff = arm_diff(ws)
    go_files = re.findall(r"^diff --git a/(\S+) b/", diff, re.M)
    res["patch_present"] = bool(diff.strip())
    nontest = [f for f in go_files if f.endswith(".go") and not f.endswith("_test.go")]
    tests = [f for f in go_files if f.endswith("_test.go")]
    # D1: root cause location named in the answer
    res["D1_root_cause_located"] = bool(re.search(r"simulator\.go", text) and
                                       re.search(r"(executebatchstep|decode[- ]step|totaloutputtokens\s*\+\+|"
                                                 r"recordrequestcompletion|preempt)", text) and
                                       re.search(r"(progressindex|progress index|reset|re-?run|re-?prefill|recomput)", text))
    if not res["patch_present"]:
        res.update(D2_upstream_test=False, D3_suite_passes=False, D4_hidden_checks=False, D5_own_regression_test=False,
                   D6_minimal=None, O1=False, hidden_detail=None)
        return res
    work = tempfile.mkdtemp(prefix="dbg_oracle_")
    try:
        # arm's final code, fresh copy, no build artifacts
        arm = os.path.join(work, "arm")
        shutil.copytree(BASE, arm, symlinks=True)
        pf = os.path.join(work, "arm.patch")
        open(pf, "w").write(diff)
        code, out = sh(f"git apply --whitespace=nowarn {pf}", arm)
        if code != 0:
            res.update(D2_upstream_test=False, D3_suite_passes=False, D4_hidden_checks=False, D5_own_regression_test=False,
                       D6_minimal=None, O1=False, apply_error=out[-500:])
            return res
        # D3 full suite on the arm's code (before adding the hidden upstream test)
        code3, _ = sh("go test ./...", arm, timeout=2400)
        res["D3_suite_passes"] = code3 == 0
        # D2 upstream test on the arm's code
        up = os.path.join(work, "up")
        shutil.copytree(arm, up, symlinks=True)
        # The hidden test goes in its own file under a unique name, so it never collides with the arm's tests
        # (or with an arm that happened to write a test of the same name).
        body = open(UPSTREAM_TEST).read()
        fn = "\n".join(l[1:] for l in body.splitlines() if l.startswith("+") and not l.startswith("+++"))
        fn = fn[fn.find("func TestSimulator_TotalOutputTokens_NoDoubleCountAfterPreemption"):]
        fn = fn.replace("TestSimulator_TotalOutputTokens_NoDoubleCountAfterPreemption", "TestOracleHiddenUpstream", 1)
        open(os.path.join(up, "sim", "zz_oracle_hidden_test.go"), "w").write("package sim\n\nimport \"testing\"\n\nvar _ = testing.T{}\n\n" + fn)
        c, o = sh("go test ./sim/ -run '^TestOracleHiddenUpstream$' -count=1 -v", up)
        res["D2_upstream_test"] = c == 0 and "--- PASS: TestOracleHiddenUpstream" in o
        if c != 0 and "--- FAIL" not in o:
            res["D2_error"] = o[-600:]
        # D4 hidden black-box checks
        h = hidden_check.check(arm)
        res["D4_hidden_checks"] = bool(h.get("pass"))
        res["hidden_detail"] = {k: v["ok"] for k, v in h.get("cases", {}).items()}
        # D5 arm's own test: fails on buggy base + arm tests, passes on arm code
        if tests:
            own = os.path.join(work, "own")
            shutil.copytree(BASE, own, symlinks=True)
            # arm's test files on top of the buggy base
            for t in tests:
                os.makedirs(os.path.dirname(os.path.join(own, t)), exist_ok=True)
                shutil.copy(os.path.join(arm, t), os.path.join(own, t))
            names = set()
            for t in tests:
                names |= set(re.findall(r"^\+func (Test\w+)\(", file_blocks(diff).get(t, ""), re.M))
            if names:
                pat = "|".join(sorted(names))
                pkgs = " ".join(sorted({"./" + os.path.dirname(t) for t in tests}))
                cb, _ = sh(f"go test {pkgs} -run '^({pat})$' -count=1", own)
                ca, _ = sh(f"go test {pkgs} -run '^({pat})$' -count=1", arm)
                res["D5_own_regression_test"] = cb != 0 and ca == 0
            else:
                res["D5_own_regression_test"] = False
        else:
            res["D5_own_regression_test"] = False
        # D6 minimal patch
        fb = file_blocks(diff)
        nt_lines = sum(changed_lines(fb[f]) for f in nontest)
        outside = [f for f in go_files if not f.startswith("sim/") and f.endswith(".go")]
        res["D6_nontest_lines"] = nt_lines
        res["D6_minimal"] = nt_lines <= 60 and not outside
        res["O1"] = bool(res["D2_upstream_test"] and res["D3_suite_passes"] and res["D4_hidden_checks"])
        return res
    finally:
        shutil.rmtree(work, ignore_errors=True)
