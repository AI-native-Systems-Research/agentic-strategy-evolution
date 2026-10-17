"""The guide's security claims, each pinned to the behaviour that makes it true
(round 6, item 6).

Every claim below has:
  * its FULL sentence, matched exactly (whitespace normalised), so a softened,
    widened or deleted claim fails here;
  * a behavioural check, executed IN THIS FILE, that exercises what the
    sentence promises -- not a check that some other test exists.
The guide's wrapper list is compared with ``clean_tree.WRAPPER_SPECS``, the
table the parser reads, so neither can drift from the other.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "docs" / "optimization-campaign-guide.md"


def _norm(s: str) -> str:
    return " ".join(s.split())


def _guide() -> str:
    return _norm(GUIDE_PATH.read_text())


CLAIMS = {
    "setsid": (
        "every descendant the poller saw that is still alive, whatever group it is in "
        "now. Its group is re-read at that moment, so a `setsid()` before or after the "
        "first poll does not escape, on a normal exit, a timeout or an interrupt alike. "
        "A pid whose start time no longer matches the one recorded when it was first "
        "seen has been reused by an unrelated process; it is recorded and never killed."),
    "not_probed": (
        "Any other command is not refused but is recorded in `clean_tree.probe.json` and "
        "listed in `provenance.waivers` as not probed. That covers one whose first program "
        "is not a Python interpreter: a launcher (`uv run`, `conda run`, `poetry run`, "
        "`make`, `sh -c`), a script such as `./bench.sh`, another runtime, a pyenv or "
        "asdf shim, `env -i`, `env -S`, or a shell-style `VAR=value` prefix."),
    "probe_env": (
        "The probe then runs the interpreter the command runs, resolved with the "
        "command's own `PATH` (an `env PATH=...` assignment included), with exactly the "
        "command's environment and interpreter flags; flags keep their arguments "
        "(`-W ignore`, `-X dev`)."),
    "deleted_key": (
        "Once the first seal exists, a missing key is an error everywhere, including a "
        "re-run build stage. A new key is never minted to replace a deleted one."),
    "copy_back": (
        "Each attempt's copy goes to a fresh `row-K.attempt-N` directory, regular files "
        "only, under a size and file-count cap that counts the bytes actually read. A "
        "symlink or other special file is skipped and recorded in `_nous_keep.json`, "
        "never written through; an unreadable file is recorded and the rest is still "
        "kept."),
}


@pytest.mark.parametrize("name", sorted(CLAIMS))
def test_each_claim_is_stated_verbatim(name):
    assert _norm(CLAIMS[name]) in _guide(), f"the guide's {name!r} claim changed"


def test_the_guides_wrapper_list_is_the_parsers_table():
    from orchestrator.optimize import clean_tree as ct

    assert f"Known wrappers are unwrapped first: {ct.wrapper_list_markdown()}." in _guide()


# ── behaviour behind each claim ─────────────────────────────────────────────


def _git(repo, *a):
    subprocess.run(["git", "-c", "commit.gpgsign=false", *a], cwd=repo, check=True,
                   capture_output=True)


@pytest.fixture
def repo_wd(tmp_path):
    from orchestrator.optimize import clean_tree as ct

    repo = tmp_path / "repo"
    (repo / "mech").mkdir(parents=True)
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        _git(repo, *a)
    (repo / "harness.py").write_text("print('honest')\n")
    (repo / "mech" / "m.py").write_text("X = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "i")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                          text=True).stdout.strip()
    wd = tmp_path / "wd"
    wd.mkdir()
    ct.capture({"optimization": {"build_checks": {"mechanism_paths": ["mech"]}}}, repo, wd,
               base, protected=set(), base_tree_sha=ct.base_tree(repo, base))
    return repo, wd


def _setsid_child(pidf: Path, *, late: bool, main_sleep: float) -> str:
    return ("import os, time\n"
            "if os.fork() == 0:\n"
            f"    time.sleep({0.5 if late else 0})\n"
            "    os.setsid()\n"
            "    fd = os.open(os.devnull, os.O_RDWR); [os.dup2(fd, i) for i in (0, 1, 2)]\n"
            f"    open({str(pidf)!r}, 'w').write(str(os.getpid())); time.sleep(30); os._exit(0)\n"
            f"time.sleep({main_sleep})\n")


def _assert_reaped(pidf: Path):
    from orchestrator.optimize import reaper

    left = reaper.take_survivors()
    pid = int(pidf.read_text())
    assert left and pid in left[0]["escaped_session"], left
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.parametrize("late", [False, True])
def test_setsid_claim_normal_exit(tmp_path, late):
    from orchestrator.optimize import reaper

    pidf = tmp_path / "pid"
    reaper.take_survivors()
    reaper.run_in_process_group([sys.executable, "-c", _setsid_child(pidf, late=late,
                                                                       main_sleep=1.0)],
                                timeout=30)
    _assert_reaped(pidf)


def test_setsid_claim_timeout(tmp_path):
    from orchestrator.optimize import reaper

    pidf = tmp_path / "pid"
    reaper.take_survivors()
    with pytest.raises(subprocess.TimeoutExpired):
        reaper.run_in_process_group(
            [sys.executable, "-c", _setsid_child(pidf, late=True, main_sleep=60)], timeout=1.5)
    _assert_reaped(pidf)


def test_setsid_claim_reused_pid_is_recorded_not_killed():
    from orchestrator.optimize import reaper

    victim = subprocess.Popen(["/bin/sh", "-c", "sleep 30 & sleep 30; wait"],
                              start_new_session=True)
    try:
        time.sleep(0.3)
        cmd = subprocess.Popen(["/usr/bin/true"], start_new_session=True)
        cmd.wait()
        reaper.take_survivors()
        reaper._reap_leftover_group(cmd.pid, ["bench"],
                                    ({victim.pid: cmd.pid}, [], {victim.pid: "long ago"}))
        time.sleep(0.3)
        assert victim.poll() is None
        assert reaper.take_survivors()[0]["pid_not_verified"] == [victim.pid]
    finally:
        import signal
        os.killpg(victim.pid, signal.SIGKILL)


@pytest.mark.parametrize("cmd", ["uv run python h.py", "conda run -n x python h.py",
                                 "poetry run python h.py", "make bench", "sh -c 'python h.py'",
                                 "./bench.sh", "node h.js", "env -i python h.py",
                                 "env -S 'python h.py'", "PYTHONPATH=/x python h.py"])
def test_not_probed_claim(repo_wd, cmd):
    from orchestrator.optimize import clean_tree as ct
    from orchestrator.optimize.provenance import waivers

    repo, wd = repo_wd
    ct.probe_imports(wd, repo, [cmd], work_dir=wd)
    rec = json.loads((wd / ct.PROBE_RECORD).read_text())
    assert rec["not_probed"] and not rec["probed"], rec
    (wd / "pre_build_tests.json").write_text("{}")
    assert any(w["gate"] == "clean_tree_import_probe" for w in waivers(wd, {}))


def test_not_probed_claim_covers_a_shim(repo_wd, tmp_path):
    from orchestrator.optimize import clean_tree as ct

    repo, wd = repo_wd
    shim = tmp_path / ".pyenv" / "shims" / "python"
    shim.parent.mkdir(parents=True)
    shim.write_text("#!/bin/sh\nexec python3 \"$@\"\n")
    shim.chmod(0o755)
    ct.probe_imports(wd, repo, [f"{shim} h.py"], work_dir=wd)
    assert json.loads((wd / ct.PROBE_RECORD).read_text())["not_probed"]


def test_probe_env_claim_path_flags_and_environment(repo_wd, tmp_path):
    from orchestrator.optimize import clean_tree as ct

    repo, wd = repo_wd
    venv = repo / ".venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
    (next(venv.glob("lib/python*/site-packages")) / "e.pth").write_text(str(repo) + "\n")
    with pytest.raises(ct.CleanTreeError, match="would import from"):
        ct.probe_imports(wd, repo, [f"env PATH={venv}/bin:/usr/bin:/bin python h.py"],
                         work_dir=wd)
    with pytest.raises(ct.CleanTreeError, match="would import from"):
        ct.probe_imports(wd, repo, [f"env PYTHONPATH={repo} {sys.executable} h.py"],
                         work_dir=wd)
    ct.probe_imports(wd, repo, [f"{sys.executable} -W ignore -X dev h.py"], work_dir=wd)
    assert json.loads((wd / ct.PROBE_RECORD).read_text())["probed"][0]["flags"] == \
        ["-W", "ignore", "-X", "dev"]


@pytest.mark.parametrize("cmd", ["timeout 5", "timeout -s KILL 5", "nice -n 5", "time -p",
                                 "nohup", "ionice -c 2 -n 7", "taskset -c 0", "chrt -f 10",
                                 "stdbuf -o L", "caffeinate -t 10", "gtimeout 5",
                                 "env A=1"])
def test_probe_env_claim_every_listed_wrapper_is_unwrapped(repo_wd, cmd):
    from orchestrator.optimize import clean_tree as ct

    repo, wd = repo_wd
    with pytest.raises(ct.CleanTreeError, match="would import from"):
        ct.probe_imports(wd, repo, [f"{cmd} env PYTHONPATH={repo} {sys.executable} h.py"],
                         work_dir=wd)


def test_every_wrapper_in_the_table_is_exercised_above():
    """The parametrized cases above must cover the whole table: adding a wrapper
    to WRAPPER_SPECS without exercising it fails here."""
    from orchestrator.optimize import clean_tree as ct

    exercised = {"timeout", "gtimeout", "nice", "time", "nohup", "ionice", "taskset",
                 "chrt", "stdbuf", "caffeinate"}
    assert set(ct.WRAPPER_SPECS) == exercised


def test_deleted_key_claim(repo_wd):
    from orchestrator.optimize import clean_tree as ct
    from orchestrator.optimize import gate_records as gr

    repo, wd = repo_wd
    ct.ensure(repo, wd, fresh=True)
    gr.key_path(wd).unlink()
    for call in (lambda: gr.ensure_key(wd), lambda: gr.seal(wd, ["x"])):
        with pytest.raises(gr.GateRecordError, match="missing"):
            call()
    assert not gr.key_path(wd).exists()


def test_copy_back_claim(tmp_path, monkeypatch):
    from orchestrator.optimize import runner
    from orchestrator.optimize.matrix import ConfigRow

    monkeypatch.setattr(runner, "KEEP_MAX_BYTES", 10)
    wd = tmp_path / "wd"
    log_dir = wd / "runs" / "iter-1" / "failed_runs"
    log_dir.mkdir(parents=True)
    (wd / "ledger.json").write_text("honest")
    mark = tmp_path / "mark"
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "bench.py").write_text(
        "import os, json, pathlib\n"
        "rd = pathlib.Path(os.environ['NOUS_RUN_DIR'])\n"
        f"mark = pathlib.Path({str(mark)!r})\n"
        "if not mark.exists():\n"
        "    mark.write_text('1'); os.symlink('../../../../ledger.json', rd / 'out.json')\n"
        "    p = rd / 'locked'; p.write_text('x'); os.chmod(p, 0)\n"
        "else:\n"
        "    (rd / 'out.json').write_text('y' * 100)\n"
        "print(json.dumps({'m': 1.0}))\n")
    run = runner.make_config_runner(f"{sys.executable} bench.py", cwd=tmp_path / "t",
                                    metric_path="m", timeout=60, log_dir=log_dir)
    row = ConfigRow(row_index=4, levels={}, role="corner", replicate=0, apply={})
    run(row)
    run(row)
    kept = wd / "runs" / "iter-1" / "run_dirs"
    r1 = json.loads((kept / "row-4.attempt-1" / "_nous_keep.json").read_text())
    r2 = json.loads((kept / "row-4.attempt-2" / "_nous_keep.json").read_text())
    assert (wd / "ledger.json").read_text() == "honest"            # never written through
    assert r1["skipped"][0]["why"] == "symlink"                     # skipped and recorded
    assert r1["errors"][0]["path"] == "locked"                      # unreadable: recorded
    assert (kept / "row-4.attempt-2" / "out.json").stat().st_size == 10   # cap on bytes read
    assert r2["truncated"] == ["out.json"]
    assert not any(p.is_symlink() for p in kept.rglob("*"))
