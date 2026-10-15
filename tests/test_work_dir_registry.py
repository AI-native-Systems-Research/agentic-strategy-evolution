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


def test_validate_points_an_existing_campaign_at_resume_not_a_fresh_run(tmp_path):
    """Revising a campaign for epoch 2 and re-validating said `nous run` with a
    new NOUS_CAMPAIGN_PARENT -- which would start the campaign over elsewhere."""
    import yaml

    from orchestrator.cli import _run_hint
    from orchestrator.work_dir_resolver import record_work_dir

    repo = tmp_path / "repo"
    repo.mkdir()
    camp = tmp_path / "c.yaml"
    camp.write_text(yaml.safe_dump({"run_id": "r1", "target_system": {"repo_path": str(repo)}}))
    assert "nous run" in _run_hint(camp)

    wd = tmp_path / "wd"
    wd.mkdir()
    (wd / "state.json").write_text("{}")
    record_work_dir("r1", repo, wd)
    hint = _run_hint(camp)
    assert "nous resume" in hint and str(wd) in hint and "nous run" not in hint
