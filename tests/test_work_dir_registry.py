"""`nous progress|status FILE` finds a campaign from ANY shell.

The scaffold and validate's `next:` line launch campaigns as
`NOUS_CAMPAIGN_PARENT=... nous run FILE` -- the variable lives for that one
command. A later `nous progress FILE` from another shell (or another Claude
session) answered "Work directory not found". Found monitoring a real campaign.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from orchestrator.iteration import setup_work_dir


def _campaign(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    f = tmp_path / "c.yaml"
    f.write_text(yaml.safe_dump({"run_id": "reg-run", "kind": "optimization",
                                 "target_system": {"name": "t", "repo_path": str(repo)}}))
    return f


def _nous(args, env):
    return subprocess.run([sys.executable, "-m", "orchestrator.cli", *args],
                          capture_output=True, text=True, env=env)


def test_status_finds_a_campaign_launched_with_an_inline_parent(tmp_path, monkeypatch):
    import os
    f = _campaign(tmp_path)
    doc = yaml.safe_load(f.read_text())
    parent = tmp_path / "elsewhere"
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(parent))
    wd = setup_work_dir("reg-run", repo_path=doc["target_system"]["repo_path"], campaign=doc)
    assert Path(wd).is_relative_to(parent)
    env = {k: v for k, v in os.environ.items() if k != "NOUS_CAMPAIGN_PARENT"}
    for target in (str(f), "reg-run"):
        r = _nous(["status", target], env)
        assert "Work directory not found" not in r.stderr, (target, r.stderr)


def test_an_unknown_campaign_says_how_to_find_it(tmp_path):
    import os
    f = _campaign(tmp_path)
    r = _nous(["status", str(f)], {k: v for k, v in os.environ.items()
                                    if k != "NOUS_CAMPAIGN_PARENT"})
    assert "Work directory not found" in r.stderr and "inline" in r.stderr
