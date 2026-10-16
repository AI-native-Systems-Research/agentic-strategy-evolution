"""Round 3, A1/A2/B1: the clean tree shares NOTHING with the agent's repo.

Each test reproduces one bypass the round-2 review demonstrated against the
worktree-based clean tree (nous-e2e/scratch/wpc2-review/probe*.py) and asserts
it no longer works. Real git repos in tmp_path; no LLM.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from orchestrator.optimize import clean_tree as ct

CAMP = {"optimization": {"build_checks": {"mechanism_paths": ["mech"]},
                         "stages": ["build", "verify"]}}


def _git(repo, *a):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *a], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


@pytest.fixture
def setup(tmp_path):
    repo = tmp_path / "repo"
    (repo / "mech").mkdir(parents=True)
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        _git(repo, *a)
    (repo / "harness.py").write_text("print('honest')\n")
    (repo / "mech" / "m.py").write_text("X = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    base = _git(repo, "rev-parse", "HEAD").strip()
    tree = ct.base_tree(repo, base)
    (repo / "mech" / "m.py").write_text("X = 2\n")       # the build's edit
    wd = tmp_path / "wd"
    wd.mkdir()
    ct.capture(CAMP, repo, wd, base, protected={"harness.py"}, base_tree_sha=tree)
    return repo, wd


def test_a_planted_post_checkout_hook_never_runs_and_cannot_steal_the_key(setup, tmp_path):
    repo, wd = setup
    stolen = tmp_path / "stolen"
    hook = repo / ".git" / "hooks" / "post-checkout"
    hook.write_text(f"#!/bin/sh\necho pwn > harness.py\nls -la .. > {stolen}\n")
    hook.chmod(0o755)
    for h in ("post-commit", "pre-commit", "post-applypatch", "pre-applypatch"):
        (repo / ".git" / "hooks" / h).write_text(hook.read_text())
        (repo / ".git" / "hooks" / h).chmod(0o755)
    d = ct.ensure(repo, wd, fresh=True)
    assert (d / "harness.py").read_text() == "print('honest')\n"
    assert not stolen.exists(), "a hook of the agent's repo ran"
    assert (d / "mech" / "m.py").read_text() == "X = 2\n"


def test_fsmonitor_and_filters_of_the_agents_repo_never_run(setup, tmp_path):
    repo, wd = setup
    marker = tmp_path / "fsm"
    script = tmp_path / "fsm.sh"
    script.write_text(f"#!/bin/sh\necho ran >> {marker}\nexit 1\n")
    script.chmod(0o755)
    _git(repo, "config", "core.fsmonitor", str(script))
    _git(repo, "config", "filter.evil.smudge", f"sh -c 'echo ran >> {marker}; cat'")
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("* filter=evil\n")
    d = ct.ensure(repo, wd, fresh=True)
    ct.check(wd)
    assert not marker.exists(), marker.read_text() if marker.exists() else ""
    assert (d / "harness.py").read_text() == "print('honest')\n"


def test_skip_worktree_in_the_clean_tree_cannot_hide_a_forged_harness(setup):
    repo, wd = setup
    d = ct.ensure(repo, wd, fresh=True)
    (d / "harness.py").write_text("print('FORGED 999')\n")
    subprocess.run(["git", "update-index", "--skip-worktree", "harness.py"], cwd=d, check=True)
    with pytest.raises(ct.CleanTreeError, match="harness.py"):
        ct.ensure(repo, wd)


def test_an_excluded_conftest_planted_in_the_clean_tree_is_seen(setup):
    repo, wd = setup
    d = ct.ensure(repo, wd, fresh=True)
    (d / ".git" / "info").mkdir(exist_ok=True)
    (d / ".git" / "info" / "exclude").write_text("conftest.py\n")
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "exclude").write_text("conftest.py\n")
    (d / "conftest.py").write_text("raise SystemExit('planted')\n")
    with pytest.raises(ct.CleanTreeError, match="conftest.py"):
        ct.check(wd)


def test_the_clean_tree_is_a_private_repository_outside_the_work_dir(setup):
    repo, wd = setup
    d = ct.ensure(repo, wd, fresh=True)
    assert (d / ".git").is_dir(), "the clean tree must have its OWN .git, not a worktree link"
    common = _git(d, "rev-parse", "--git-common-dir").strip()
    assert Path(d, common).resolve() == (d / ".git").resolve()
    assert wd.resolve() not in d.resolve().parents
    assert len(_git(repo, "worktree", "list").strip().splitlines()) == 1


def test_rewritten_objects_in_the_agents_repo_cannot_change_the_base(setup):
    """The base is checked against the pre-build TREE hash recorded before the
    build, so replacing the commit (e.g. a `git replace`) is refused."""
    repo, wd = setup
    rec = json.loads((wd / ct.RECORD).read_text())
    (repo / "harness.py").write_text("print('replaced')\n")
    _git(repo, "add", "harness.py")
    _git(repo, "commit", "-qm", "other")
    other = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "replace", rec["base_sha"], other)
    with pytest.raises(ct.CleanTreeError, match="pre-build tree"):
        ct.ensure(repo, wd, fresh=True)


def test_the_seal_key_is_outside_the_work_dir_and_mode_checked(tmp_path):
    from orchestrator.optimize import gate_records as gr

    wd = tmp_path / "wd"
    wd.mkdir()
    gr.ensure_key(wd)
    kp = gr.key_path(wd)
    assert kp.exists() and wd.resolve() not in kp.resolve().parents
    assert not list(wd.iterdir()), "nothing key-like in the work_dir"
    os.chmod(kp, 0o644)
    with pytest.raises(gr.GateRecordError, match="readable by others"):
        gr.seal(wd, ["x.json"])


def test_target_commands_get_no_path_to_the_work_dir_or_the_key(monkeypatch):
    from orchestrator.optimize import runner

    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", "/campaigns")
    monkeypatch.setenv("NOUS_STATE_HOME", "/state")
    env = runner.target_env()
    assert "NOUS_CAMPAIGN_PARENT" not in env and "NOUS_STATE_HOME" not in env


# ─── round 3, D1/D2: editable installs refused; extras copied ────────────────


def _probe_setup(tmp_path, *, extras=None, pth_to_repo=False):
    import sys

    repo = tmp_path / "repo"
    (repo / "mech").mkdir(parents=True)
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        _git(repo, *a)
    (repo / "harness.py").write_text("print('honest')\n")
    (repo / "mech" / "m.py").write_text("X = 1\n")
    (repo / ".gitignore").write_text("data/\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    (repo / "data").mkdir()
    (repo / "data" / "corpus.txt").write_text("rows\n")
    base = _git(repo, "rev-parse", "HEAD").strip()
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
    if pth_to_repo:
        site = next(venv.glob("lib/python*/site-packages"))
        (site / "agent_editable.pth").write_text(str(repo) + "\n")
    wd = tmp_path / "wd"
    wd.mkdir()
    camp = {"optimization": {"build_checks": {"mechanism_paths": ["mech"]},
                             "run_command": f"{venv}/bin/python harness.py"},
            "target_system": {"worktree_extras": extras or []}}
    ct.capture(camp, repo, wd, base, protected=set(), base_tree_sha=ct.base_tree(repo, base))
    return repo, wd


def test_an_interpreter_that_imports_from_the_agents_repo_is_refused(tmp_path):
    repo, wd = _probe_setup(tmp_path, pth_to_repo=True)
    with pytest.raises(ct.CleanTreeError, match="would import from the build agent's repository"):
        ct.ensure(repo, wd, fresh=True)


def test_an_interpreter_with_no_path_into_the_repo_is_accepted(tmp_path):
    repo, wd = _probe_setup(tmp_path)
    ct.ensure(repo, wd, fresh=True)


def test_worktree_extras_are_copied_not_symlinked_and_recorded(tmp_path):
    repo, wd = _probe_setup(tmp_path, extras=["data"])
    d = ct.ensure(repo, wd, fresh=True)
    assert (d / "data" / "corpus.txt").read_text() == "rows\n"
    assert not (d / "data").is_symlink()
    rec = json.loads((wd / ct.EXTRAS).read_text())
    assert "data/corpus.txt" in rec
    # A later change in the agent's copy does not reach the clean tree, and a
    # rebuild from the changed copy is refused.
    (repo / "data" / "corpus.txt").write_text("forged\n")
    assert (d / "data" / "corpus.txt").read_text() == "rows\n"
    with pytest.raises(ct.CleanTreeError, match="worktree_extras"):
        ct.ensure(repo, wd, fresh=True)


# ─── round 3, D3 / E3: preconditions before any token is spent ───────────────


def _build_campaign_for(repo):
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES

    c = synthetic_campaign(SURFACES["additive"](), stages=["build", "verify", "screen", "confirm"],
                           known_valid_baseline={"A": 2, "B": 2, "C": "off"},
                           build_checks={"mechanism_paths": ["mech"]})
    c["target_system"]["repo_path"] = str(repo) if repo else None
    return c


def test_preconditions_name_a_dirty_tree_a_work_dir_inside_the_repo_and_a_missing_repo(
        setup, tmp_path, monkeypatch):
    repo, _ = setup                         # mech/m.py is modified in this fixture
    monkeypatch.delenv("NOUS_CAMPAIGN_PARENT", raising=False)
    probs = ct.build_preconditions(_build_campaign_for(repo), "r1")
    dirty = [p for p in probs if p.startswith("commit your changes first")]
    assert dirty and "mech/m.py" in dirty[0] and "1 tracked file(s)" in dirty[0], probs
    assert any(p.startswith("put the campaign's records outside the repo: `export "
                            "NOUS_CAMPAIGN_PARENT=") for p in probs), probs
    assert ct.build_preconditions(_build_campaign_for(None))[0].startswith(
        "set target_system.repo_path")
    _git(repo, "commit", "-qam", "clean")
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path / "campaigns"))
    assert ct.build_preconditions(_build_campaign_for(repo), "r1") == []


def test_nous_run_refuses_a_build_campaign_before_spending_a_token(setup, tmp_path, monkeypatch, capsys):
    import sys

    import yaml

    from orchestrator import cli

    repo, _ = setup
    monkeypatch.delenv("NOUS_CAMPAIGN_PARENT", raising=False)
    camp = tmp_path / "c.yaml"
    camp.write_text(yaml.safe_dump(_build_campaign_for(repo)))
    calls = []
    monkeypatch.setattr("orchestrator.campaign.run_campaign", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(sys, "argv", ["nous", "run", str(camp), "--auto-approve"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 1 and not calls
    assert "its build stage cannot start" in capsys.readouterr().err


def test_nous_validate_reports_the_build_preconditions(setup, tmp_path, monkeypatch, capsys):
    import sys

    import yaml

    from orchestrator import cli

    repo, _ = setup
    camp = tmp_path / "c.yaml"
    camp.write_text(yaml.safe_dump(_build_campaign_for(repo)))
    monkeypatch.setattr(sys, "argv", ["nous", "validate", "campaign", str(camp)])
    with pytest.raises(SystemExit):
        cli.main()
    assert "[build]" in capsys.readouterr().err


# ─── round 4: sealed tree records, fail-closed probe, hard links ─────────────


def _fresh(setup):
    repo, wd = setup
    d = ct.ensure(repo, wd, fresh=True)
    return repo, wd, d


def test_the_manifest_is_sealed_when_the_tree_is_created(setup):
    from orchestrator.optimize import gate_records as gr

    repo, wd, d = _fresh(setup)
    assert gr.check(wd, ct.MANIFEST) == "ok" and gr.check(wd, ct.EXTRAS) == "ok"


def test_a_forged_manifest_cannot_bless_a_tampered_tree(setup):
    """Item 2: rewrite the harness AND the manifest to match; a later check
    (here: a new process, which has no in-memory reference) still refuses."""
    import hashlib

    repo, wd, d = _fresh(setup)
    (d / "harness.py").write_text("print('FORGED')\n")
    mp = wd / ct.MANIFEST
    mf = json.loads(mp.read_text())
    mf["harness.py"] = hashlib.sha256((d / "harness.py").read_bytes()).hexdigest()
    mp.write_text(json.dumps(mf))
    ct._REFERENCE.clear()                     # as in a resumed process
    with pytest.raises(ct.CleanTreeError, match="fails its seal"):
        ct.check(wd)


def test_the_in_memory_reference_wins_over_a_rewritten_manifest(setup):
    import hashlib

    from orchestrator.optimize import gate_records as gr

    repo, wd, d = _fresh(setup)
    (d / "harness.py").write_text("print('FORGED')\n")
    mp = wd / ct.MANIFEST
    mf = json.loads(mp.read_text())
    mf["harness.py"] = hashlib.sha256((d / "harness.py").read_bytes()).hexdigest()
    mp.write_text(json.dumps(mf))
    gr.seal(wd, (ct.MANIFEST,))               # even a resealed forgery
    with pytest.raises(ct.CleanTreeError, match="harness.py"):
        ct.check(wd)


def test_a_hard_link_into_the_clean_tree_is_refused(setup, tmp_path):
    """A hard link elsewhere lets target code rewrite a measured file through a
    path the integrity check never looks at."""
    import os

    repo, wd, d = _fresh(setup)
    os.link(d / "harness.py", tmp_path / "backdoor.py")
    with pytest.raises(ct.CleanTreeError, match="hard links"):
        ct.check(wd)


@pytest.mark.parametrize("cmd,why", [
    ("uv run python harness.py", "launches another program"),
    ("make bench", "launches another program"),
    ("sh -c 'python harness.py'", "launches another program"),
    ("conda run -n x python harness.py", "launches another program"),
])
def test_a_launcher_command_is_recorded_as_not_probed(setup, cmd, why):
    from orchestrator.optimize.provenance import waivers

    repo, wd = setup
    ct.probe_imports(wd, repo, [cmd], work_dir=wd)
    rec = json.loads((wd / ct.PROBE_RECORD).read_text())
    assert rec["not_probed"] and why in rec["not_probed"][0]["reason"]
    (wd / "pre_build_tests.json").write_text("{}")
    assert any(w["gate"] == "clean_tree_import_probe" for w in waivers(wd, {}))


def test_a_version_manager_shim_is_recorded_as_not_probed(setup, tmp_path):
    repo, wd = setup
    shim = tmp_path / ".pyenv" / "shims" / "python"
    shim.parent.mkdir(parents=True)
    shim.write_text("#!/bin/sh\nexec python3 \"$@\"\n")
    shim.chmod(0o755)
    ct.probe_imports(wd, repo, [f"{shim} harness.py"], work_dir=wd)
    rec = json.loads((wd / ct.PROBE_RECORD).read_text())
    assert "shim" in rec["not_probed"][0]["reason"]


def test_a_probe_that_fails_refuses_the_tree(setup, tmp_path):
    repo, wd = setup
    bad = tmp_path / "python3"
    bad.write_text("#!/bin/sh\nexit 3\n")
    bad.chmod(0o755)
    with pytest.raises(ct.CleanTreeError, match="import probe .* failed"):
        ct.probe_imports(wd, repo, [f"{bad} harness.py"], work_dir=wd)


def test_a_probe_with_unparseable_output_refuses_the_tree(setup, tmp_path):
    repo, wd = setup
    bad = tmp_path / "python3"
    bad.write_text("#!/bin/sh\necho not-json\n")
    bad.chmod(0o755)
    with pytest.raises(ct.CleanTreeError, match="unparseable"):
        ct.probe_imports(wd, repo, [f"{bad} harness.py"], work_dir=wd)


def test_the_probe_runs_with_the_commands_own_interpreter_flags(setup, tmp_path):
    """`python -S` skips site-packages, so a .pth into the repo is NOT read by
    the command; probing without -S would refuse an honest tree."""
    import sys

    repo, wd = setup
    venv = tmp_path / "v"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
    site = next(venv.glob("lib/python*/site-packages"))
    (site / "agent.pth").write_text(str(repo) + "\n")
    with pytest.raises(ct.CleanTreeError, match="would import from"):
        ct.probe_imports(wd, repo, [f"{venv}/bin/python harness.py"], work_dir=wd)
    ct.probe_imports(wd, repo, [f"{venv}/bin/python -S harness.py"], work_dir=wd)
    rec = json.loads((wd / ct.PROBE_RECORD).read_text())
    assert rec["probed"][0]["flags"] == ["-S"]


# ─── round 4 self-probes: worktree_extras abuse, the key, the race ───────────


def _extras_setup(tmp_path, ignored, extras, *, plant_after=None):
    repo = tmp_path / "repo"
    (repo / "mech").mkdir(parents=True)
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        _git(repo, *a)
    (repo / "harness.py").write_text("print('honest')\n")
    (repo / "mech" / "m.py").write_text("X = 1\n")
    (repo / ".gitignore").write_text("data/\nassets/\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    for rel, val in ignored.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(val, tuple):
            os.symlink(val[1], p)
        else:
            p.write_text(val)
    base = _git(repo, "rev-parse", "HEAD").strip()
    pre = ct.extras_digest(repo, extras)
    for rel, val in (plant_after or {}).items():   # what the build agent does
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(val)
    wd = tmp_path / "wd"
    wd.mkdir()
    camp = {"optimization": {"build_checks": {"mechanism_paths": ["mech"]}},
            "target_system": {"worktree_extras": extras}}
    ct.capture(camp, repo, wd, base, protected=set(), base_tree_sha=ct.base_tree(repo, base),
               extras_pre=pre)
    return repo, wd


def test_code_planted_in_an_extras_directory_during_the_build_is_refused(tmp_path):
    repo, wd = _extras_setup(tmp_path, {"assets/data.csv": "1\n"}, ["assets"],
                             plant_after={"assets/conftest.py": "raise SystemExit('pwn')\n"})
    with pytest.raises(ct.CleanTreeError, match="changed during the build"):
        ct.ensure(repo, wd, fresh=True)


def test_an_author_asset_present_before_the_build_is_copied(tmp_path):
    repo, wd = _extras_setup(tmp_path, {"assets/data.csv": "1\n"}, ["assets"])
    d = ct.ensure(repo, wd, fresh=True)
    assert (d / "assets" / "data.csv").read_text() == "1\n"


@pytest.mark.parametrize("ignored", [
    {"data": ("link", "REPO/mech")},
    {"data/x.txt": "1\n", "data/back": ("link", "REPO")},
])
def test_an_extras_symlink_into_the_agents_repo_is_refused(tmp_path, ignored):
    repo = tmp_path / "repo"
    fixed = {k: (("link", v[1].replace("REPO", str(repo))) if isinstance(v, tuple) else v)
             for k, v in ignored.items()}
    repo, wd = _extras_setup(tmp_path, fixed, ["data"])
    with pytest.raises(ct.CleanTreeError, match="resolves into the build agent's repository"):
        ct.ensure(repo, wd, fresh=True)


def test_a_deleted_key_is_never_replaced_by_a_new_one(setup):
    """Deleting ~/.nous/keys/<hash> must not let a later seal mint a fresh key
    under which forged records would verify."""
    from orchestrator.optimize import gate_records as gr

    repo, wd = setup
    ct.ensure(repo, wd, fresh=True)
    gr.key_path(wd).unlink()
    assert gr.check(wd, ct.MANIFEST) == "unsealed"
    with pytest.raises(gr.GateRecordError, match="missing"):
        gr.seal(wd, [ct.MANIFEST])
    assert not gr.key_path(wd).exists()
