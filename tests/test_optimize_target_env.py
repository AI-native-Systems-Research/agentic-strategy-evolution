"""Every target command runs with PYTHONPYCACHEPREFIX pointed at a Nous-owned
directory (round 2, A4): a PLANTED __pycache__ entry for an unchanged module,
crafted to match the source's size and mtime, is never imported."""
from __future__ import annotations

import importlib.util
import os
import py_compile
import json
import struct
import sys
from pathlib import Path

from orchestrator.optimize import runner


def _plant(tmp_path):
    (tmp_path / "mod.py").write_text("print('SOURCE')\n")
    evil = tmp_path / "evil_src.py"
    evil.write_text("print('PLANTED')\n")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    pyc = cache / f"mod.{sys.implementation.cache_tag}.pyc"
    py_compile.compile(str(evil), cfile=str(pyc))
    evil.unlink()
    st = (tmp_path / "mod.py").stat()
    data = bytearray(pyc.read_bytes())
    # Header: magic(4) flags(4) mtime(4) size(4): make it match the real source.
    data[8:16] = struct.pack("<II", int(st.st_mtime) & 0xFFFFFFFF, st.st_size & 0xFFFFFFFF)
    pyc.write_bytes(bytes(data))
    assert bytes(data[:4]) == importlib.util.MAGIC_NUMBER


def test_a_planted_bytecode_file_is_not_imported_by_a_target_command(tmp_path):
    _plant(tmp_path)
    log = tmp_path / "out.log"
    runner.run_test_command(f"{sys.executable} -c 'import mod'", cwd=tmp_path, log_path=log)
    text = log.read_text()
    assert "SOURCE" in text and "PLANTED" not in text, text


def test_the_target_environment_redirects_bytecode_and_hides_gate_secrets(monkeypatch):
    monkeypatch.setenv("NOUS_GATE_KEY_PATH", "/secret")
    env = runner.target_env()
    assert os.path.isdir(env["PYTHONPYCACHEPREFIX"])
    assert "NOUS_GATE_KEY_PATH" not in env


def test_the_run_dir_handed_to_target_code_is_outside_the_work_dir_and_kept(tmp_path):
    """Round 4, item 1: NOUS_RUN_DIR must not put the work_dir a few `..` away;
    what the adapter wrote is still kept beside the iteration."""
    import json
    import sys

    from orchestrator.optimize.matrix import ConfigRow

    wd = tmp_path / "campaigns" / "run1"
    log_dir = wd / "runs" / "iter-2" / "failed_runs"
    log_dir.mkdir(parents=True)
    script = tmp_path / "adapter.py"
    script.write_text(
        "import json, os, pathlib\n"
        "rd = os.environ['NOUS_RUN_DIR']\n"
        "pathlib.Path(rd, 'evidence.txt').write_text('built')\n"
        "print(json.dumps({'m': 1.0, 'rd': rd}))\n")
    run = runner.make_config_runner(f"{sys.executable} {script}", cwd=tmp_path,
                                    metric_path="m", timeout=60, log_dir=log_dir)
    out = run(ConfigRow(row_index=3, levels={}, role="corner", replicate=0, apply={}))
    rd = out["rd"]
    assert str(wd.resolve()) not in str(Path(rd).resolve()), rd
    kept = wd / "runs" / "iter-2" / "run_dirs" / f"{Path(rd).name}.attempt-1" / "evidence.txt"
    assert kept.read_text() == "built"
    assert not Path(rd).exists(), "the temp run dir is removed after copying back"



def _row_runner(tmp_path, body, log=True):
    import sys

    from orchestrator.optimize.matrix import ConfigRow

    wd = tmp_path / "wd"
    log_dir = wd / "runs" / "iter-3" / "failed_runs"
    log_dir.mkdir(parents=True)
    (wd / "ledger.json").write_text('{"honest": true}\n')
    tgt = tmp_path / "target"
    tgt.mkdir()
    (tgt / "bench.py").write_text(body)
    run = runner.make_config_runner(f"{sys.executable} bench.py", cwd=tgt, metric_path="m",
                                    timeout=60, log_dir=log_dir if log else None)
    row = ConfigRow(row_index=7, levels={}, role="corner", replicate=0, apply={})
    return wd, lambda: run(row)


def test_a_symlink_planted_by_one_attempt_cannot_steer_the_next_attempts_copy(tmp_path):
    """Round 5, item 1 (repro a_copyback.py): attempt 1 plants
    out.json -> ../../../../ledger.json; attempt 2 writes a real out.json.
    The copy-back must not write through the link into the work_dir."""
    mark = tmp_path / "mark"
    body = (
        "import os, json, pathlib\n"
        "rd = pathlib.Path(os.environ['NOUS_RUN_DIR'])\n"
        f"mark = pathlib.Path({str(mark)!r})\n"
        "if not mark.exists():\n"
        "    mark.write_text('1'); os.symlink('../../../../ledger.json', rd / 'out.json')\n"
        "else:\n"
        "    (rd / 'out.json').write_text('forged')\n"
        "print(json.dumps({'m': 1.0}))\n")
    wd, run = _row_runner(tmp_path, body)
    run()
    run()
    assert (wd / "ledger.json").read_text() == '{"honest": true}\n'
    kept = wd / "runs" / "iter-3" / "run_dirs"
    a1, a2 = kept / "row-7.attempt-1", kept / "row-7.attempt-2"
    assert not (a1 / "out.json").exists() and not os.path.lexists(a1 / "out.json")
    assert json.loads((a1 / "_nous_keep.json").read_text())["skipped"][0]["why"] == "symlink"
    assert (a2 / "out.json").read_text() == "forged"
    assert not any(p.is_symlink() for p in kept.rglob("*"))


def test_the_copy_back_is_capped_and_the_truncation_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "KEEP_MAX_FILES", 2)
    body = ("import os, json, pathlib\n"
            "rd = pathlib.Path(os.environ['NOUS_RUN_DIR'])\n"
            "[ (rd / f'f{i}.txt').write_text('x') for i in range(5) ]\n"
            "print(json.dumps({'m': 1.0}))\n")
    wd, run = _row_runner(tmp_path, body)
    run()
    dest = wd / "runs" / "iter-3" / "run_dirs" / "row-7.attempt-1"
    rec = json.loads((dest / "_nous_keep.json").read_text())
    assert len(rec["truncated"]) == 3 and len(list(dest.glob("f*.txt"))) == 2


def test_with_no_log_dir_the_run_dir_is_still_removed(tmp_path):
    seen = tmp_path / "rd.txt"
    body = ("import os, json, pathlib\n"
            "rd = pathlib.Path(os.environ['NOUS_RUN_DIR'])\n"
            "(rd / 'x.txt').write_text('x')\n"
            f"pathlib.Path({str(seen)!r}).write_text(str(rd))\n"
            "print(json.dumps({'m': 1.0}))\n")
    _, run = _row_runner(tmp_path, body, log=False)
    run()
    assert not Path(seen.read_text()).exists()
