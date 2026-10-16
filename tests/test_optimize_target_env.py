"""Every target command runs with PYTHONPYCACHEPREFIX pointed at a Nous-owned
directory (round 2, A4): a PLANTED __pycache__ entry for an unchanged module,
crafted to match the source's size and mtime, is never imported."""
from __future__ import annotations

import importlib.util
import os
import py_compile
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
    kept = wd / "runs" / "iter-2" / "run_dirs" / Path(rd).name / "evidence.txt"
    assert kept.read_text() == "built"
    assert not Path(rd).exists(), "the temp run dir is removed after copying back"
