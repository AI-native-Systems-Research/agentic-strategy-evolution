"""Every target command runs with PYTHONPYCACHEPREFIX pointed at a Nous-owned
directory (round 2, A4): a PLANTED __pycache__ entry for an unchanged module,
crafted to match the source's size and mtime, is never imported."""
from __future__ import annotations

import importlib.util
import os
import py_compile
import struct
import sys

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
