"""Item 2 of #321: the pre-registration is anchored OUTSIDE the work_dir.

Before: policy.json and policy.sha256 sat side by side in the work_dir, so a
writer that rewrote both consistently passed every check, and reanalyze
reported the forged policy as the registration. Now compile appends an anchor
under the state home, `nous anchor` adds a file / git-ref / pushed-ref copy, and
report.json, `nous reanalyze` and `nous anchor --verify` all report a mismatch.
Behavioral, zero LLM; git runs only against tmp repos.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest

from orchestrator.optimize import anchor as anchor_mod
from orchestrator.optimize import policy as policy_mod
from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.reanalyze import reanalyze
from orchestrator.optimize.synthetic import SURFACES


@pytest.fixture
def campaign(tmp_path):
    return run_synthetic_campaign(SURFACES["bowl"](), seed=7, parent_dir=tmp_path / "c")


def _cli(monkeypatch, *argv):
    from orchestrator import cli

    monkeypatch.setattr(sys, "argv", ["nous", "anchor", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return exc.value.code


def _forge_policy(work_dir):
    """The attack the anchor exists for: rewrite the REGISTRATION consistently --
    the campaign each epoch registered, the policy recompiled from it, its
    sidecar, and the policy hash every transition and report records. A
    policy-only edit was already caught pre-fix (reanalyze recompiles from
    campaign.epoch-1.yaml); this one leaves every in-work_dir record agreeing."""
    import yaml

    cp = work_dir / "campaign.epoch-1.yaml"
    camp = yaml.safe_load(cp.read_text())
    camp["optimization"].setdefault("policy", {})["delta_terminal"] = 0.4
    cp.write_text(yaml.safe_dump(camp, sort_keys=False))
    p = work_dir / "policy.json"
    old = json.loads(p.read_text())
    pol = json.loads(p.read_text())
    pol["objective"]["delta_terminal"] = 0.4
    import hashlib

    pol["compiled_from"]["campaign_hash"] = hashlib.sha256(
        policy_mod._canonical(camp["optimization"]).encode()).hexdigest()
    p.write_text(json.dumps(pol, indent=2, sort_keys=True))
    new_h, old_h = policy_mod.policy_hash(pol), policy_mod.policy_hash(old)
    (work_dir / "policy.sha256").write_text(new_h + "\n")
    for f in [work_dir / "transitions.jsonl", work_dir / "report.json",
              *work_dir.glob("runs/iter-*/design_matrix.json")]:
        if f.exists():
            f.write_text(f.read_text().replace(old_h, new_h))


def test_compile_anchors_the_registration_outside_the_work_dir(campaign):
    d = anchor_mod.anchor_dir(campaign.work_dir)
    assert campaign.work_dir not in d.parents
    hist = [json.loads(ln) for ln in (d / "epoch-1.jsonl").read_text().splitlines()]
    assert hist[0]["policy_sha256"] == campaign.report["policy_hash"]
    assert "policy.json" in hist[0]["registration"]
    assert "campaign.epoch-1.yaml" in hist[0]["registration"]
    assert campaign.report["provenance"]["anchor"] == {
        "present": True, "matches": True, "mismatches": [], "where": "state_home",
        "reanchored": [], "absent_because": None}
    from orchestrator.optimize.report_md import render_report_markdown

    assert "**External anchor:** matches (state_home)" in render_report_markdown(
        campaign.work_dir)


def test_a_consistently_forged_policy_is_caught_by_the_anchor(campaign, monkeypatch, capsys):
    """Pre-fix this input passed: the sidecar matches the forged policy."""
    _forge_policy(campaign.work_dir)
    assert policy_mod.verify_policy_registration(campaign.work_dir) == []  # in-dir check fooled
    v_reg = anchor_mod.verify(campaign.work_dir)["mismatches"]
    assert any("campaign.epoch-1.yaml changed" in m for m in v_reg)
    v = anchor_mod.verify(campaign.work_dir)
    assert v["matches"] is False
    assert any("policy.json now hashes" in m for m in v["mismatches"])
    res = reanalyze(campaign.work_dir)
    assert not res.identical and res.anchor["matches"] is False
    assert _cli(monkeypatch, str(campaign.work_dir), "--verify") == 1
    assert "ANCHOR MISMATCH" in capsys.readouterr().out


def _replace_with_a_consistent_forgery(campaign, tmp_path):
    """The forgery NO in-work_dir check can see: the whole work_dir replaced by
    a genuine run of a REVISED registration (delta_terminal 0.4), every
    artifact derived from it and mutually consistent. Pre-fix, `nous
    reanalyze` reports it identical; only an anchor written at the original
    compile, outside the work_dir, still remembers what was registered."""
    forged = run_synthetic_campaign(
        SURFACES["bowl"](), seed=7, parent_dir=tmp_path / "forged",
        campaign_overrides={"policy": {"delta_terminal": 0.4}})
    shutil.rmtree(campaign.work_dir)
    shutil.copytree(forged.work_dir, campaign.work_dir)


def test_a_fully_consistent_forged_work_dir_is_caught_only_by_the_anchor(campaign, tmp_path):
    _replace_with_a_consistent_forgery(campaign, tmp_path)
    res = reanalyze(campaign.work_dir)
    assert not res.differences and not res.input_changes   # every in-dir record agrees
    assert res.anchor["matches"] is False and not res.identical
    assert any("policy.json now hashes" in m for m in res.anchor["mismatches"])


def test_an_edited_pre_compile_input_is_caught(campaign):
    p = campaign.work_dir / "runs" / "iter-1" / "relations.json"
    p.write_text(p.read_text() + " ")
    v = anchor_mod.verify(campaign.work_dir)
    assert not v["matches"]
    assert any("runs/iter-1/relations.json changed" in m for m in v["mismatches"])


def test_no_anchor_is_reported_as_self_attested_not_as_a_match(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(anchor_mod, "anchor_at_compile", lambda wd: None)
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=7, parent_dir=tmp_path)
    assert r.report["provenance"]["anchor"]["present"] is False
    assert r.report["provenance"]["anchor"]["matches"] is None
    assert _cli(monkeypatch, str(r.work_dir), "--verify") == 2
    assert "self-attested" in capsys.readouterr().out


def test_a_failed_compile_anchor_names_its_reason(tmp_path, monkeypatch):
    def _boom(wd):
        raise OSError("state home is read-only")

    monkeypatch.setattr(anchor_mod, "record_local", lambda wd, a: _boom(wd))
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=7, parent_dir=tmp_path)
    a = r.report["provenance"]["anchor"]
    assert a["present"] is False and "state home is read-only" in a["absent_because"]
    from orchestrator.optimize.report_md import render_report_markdown

    assert "state home is read-only" in render_report_markdown(r.work_dir)


def test_an_export_file_verifies_and_detects(campaign, tmp_path, monkeypatch):
    out = tmp_path / "anchor.json"
    assert _cli(monkeypatch, str(campaign.work_dir), "--out", str(out)) == 0
    a = json.loads(out.read_text())
    assert a["schema"] == "nous-anchor/1" and len(a["digest"]) == 64
    assert _cli(monkeypatch, str(campaign.work_dir), "--verify", "--file", str(out)) == 0
    # An anchor edited to match a forgery fails its own digest.
    a["policy_sha256"] = "0" * 64
    out.write_text(json.dumps(a))
    v = anchor_mod.verify(campaign.work_dir, extra=[a])
    assert any("own digest" in m for m in v["mismatches"])


def test_refuses_to_anchor_a_registration_that_is_already_broken(campaign, monkeypatch):
    (campaign.work_dir / "policy.sha256").write_text("0" * 64 + "\n")
    assert _cli(monkeypatch, str(campaign.work_dir)) == 1


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_ref_anchor_and_opt_in_push(campaign, tmp_path, monkeypatch):
    repo, remote = tmp_path / "anchors", tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    assert _cli(monkeypatch, str(campaign.work_dir), "--git", str(repo),
                "--push", str(remote)) == 0
    ref = f"refs/nous/anchors/{campaign.work_dir.name}/epoch-1"
    pushed = subprocess.run(["git", "-C", str(remote), "cat-file", "-p", f"{ref}:anchor.json"],
                            capture_output=True, text=True, check=True).stdout
    assert json.loads(pushed)["policy_sha256"] == campaign.report["policy_hash"]
    assert anchor_mod.verify(campaign.work_dir, use_git=True)["where"] == f"git:{ref}, state_home"
    # A forger who also rewrites the state-home history is still caught by the ref.
    shutil.rmtree(anchor_mod.anchor_dir(campaign.work_dir))
    _forge_policy(campaign.work_dir)
    v = anchor_mod.verify(campaign.work_dir, use_git=True)
    assert v["matches"] is False and v["where"] == f"git:{ref}"


def test_push_without_git_is_refused(campaign, monkeypatch):
    assert _cli(monkeypatch, str(campaign.work_dir), "--push", "origin") == 2
