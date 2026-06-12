"""Behavioral tests for the per-campaign permission policy (issue #135).

These tests describe the contract of ``render_campaign_settings`` and
``write_campaign_settings``: given inputs (work_dir, repo_path, plan,
hook paths), the resulting on-disk ``.claude/settings.json`` has
specific, externally-visible properties — what's in ``allowOnly``,
which Bash commands are allowed, where outbound network is denied.

No assertions here about how the function organized its work, what
helpers it called, or the literal Python control flow. The contract
is the file's contents.
"""
from __future__ import annotations

import json
from pathlib import Path

from orchestrator.settings_template import (
    render_campaign_settings,
    settings_path_for,
    write_campaign_settings,
)


# ─── Generator: shape of the returned dict ──────────────────────────────────

class TestRenderCampaignSettings:

    def test_allow_only_includes_work_dir(self, tmp_path):
        work_dir = tmp_path / "campaign-A"
        work_dir.mkdir()

        settings = render_campaign_settings(work_dir=work_dir)

        assert str(work_dir.resolve()) in settings["permissions"]["allowOnly"]

    def test_allow_only_includes_repo_path_when_provided(self, tmp_path):
        work_dir = tmp_path / "campaign-A"
        repo = tmp_path / "target-repo"
        work_dir.mkdir()
        repo.mkdir()

        settings = render_campaign_settings(work_dir=work_dir, repo_path=repo)

        allow_only = settings["permissions"]["allowOnly"]
        assert str(work_dir.resolve()) in allow_only
        assert str(repo.resolve()) in allow_only

    def test_default_bin_allowlist_contains_python_and_git(self, tmp_path):
        settings = render_campaign_settings(work_dir=tmp_path)

        allow = settings["permissions"]["allow"]
        # Each Bash allow entry has shape ``Bash(<bin>:*)`` — assert a few
        # canonical ones are present without prescribing their order.
        assert any("Bash(python:*)" == entry for entry in allow)
        assert any("Bash(git:*)" == entry for entry in allow)
        assert any("Bash(grep:*)" == entry for entry in allow)

    def test_plan_binaries_added_to_allowlist(self, tmp_path):
        plan = {
            "arms": [
                {
                    "arm_id": "h-main",
                    "conditions": [
                        {"name": "baseline", "command": "./blis run --workload x"},
                        {"name": "treatment", "command": "/usr/local/bin/sim --batch=4"},
                    ],
                },
            ],
        }
        settings = render_campaign_settings(
            work_dir=tmp_path, experiment_plan=plan,
        )
        allow = settings["permissions"]["allow"]

        assert "Bash(blis:*)" in allow
        assert "Bash(sim:*)" in allow

    def test_extra_bin_allowlist_extends_defaults(self, tmp_path):
        settings = render_campaign_settings(
            work_dir=tmp_path,
            extra_bin_allowlist=["custom-bench", "trace-tool"],
        )
        allow = settings["permissions"]["allow"]

        assert "Bash(custom-bench:*)" in allow
        assert "Bash(trace-tool:*)" in allow
        # Defaults still present.
        assert "Bash(git:*)" in allow

    def test_deny_blocks_outbound_https(self, tmp_path):
        settings = render_campaign_settings(work_dir=tmp_path)

        deny = settings["permissions"]["deny"]
        assert any("https" in entry for entry in deny)

    def test_deny_blocks_plain_http_curl_and_wget(self, tmp_path):
        # Plain http:// was an obvious gap: the egress-reduction rules
        # should cover both schemes for curl and wget.
        settings = render_campaign_settings(work_dir=tmp_path)

        deny = settings["permissions"]["deny"]
        assert "Bash(curl http://*)" in deny
        assert "Bash(wget http://*)" in deny

    def test_no_hooks_section_when_no_hook_paths(self, tmp_path):
        settings = render_campaign_settings(work_dir=tmp_path)

        assert "hooks" not in settings

    def test_stop_hook_registered_when_path_provided(self, tmp_path):
        hook = tmp_path / "bin" / "nous-execute-stop"
        hook.parent.mkdir(parents=True)
        hook.write_text("#!/bin/sh\nexit 0\n")

        settings = render_campaign_settings(
            work_dir=tmp_path, stop_hook_path=hook,
        )

        assert "Stop" in settings["hooks"]
        stop_cfg = settings["hooks"]["Stop"]
        assert stop_cfg[0]["hooks"][0]["command"] == str(hook.resolve())
        assert stop_cfg[0]["hooks"][0]["type"] == "command"

    def test_pre_tool_use_hook_registered_when_path_provided(self, tmp_path):
        hook = tmp_path / "bin" / "nous-plan-enforcer"
        hook.parent.mkdir(parents=True)
        hook.write_text("#!/bin/sh\nexit 0\n")

        settings = render_campaign_settings(
            work_dir=tmp_path, pre_tool_use_hook_path=hook,
        )

        assert "PreToolUse" in settings["hooks"]
        ptu = settings["hooks"]["PreToolUse"]
        assert ptu[0]["matcher"] == "Bash"
        assert ptu[0]["hooks"][0]["command"] == str(hook.resolve())


# ─── Disk write ─────────────────────────────────────────────────────────────

class TestWriteCampaignSettings:

    def test_write_creates_parent_dir_and_writes_json(self, tmp_path):
        work_dir = tmp_path / "campaign-X"
        work_dir.mkdir()
        settings = render_campaign_settings(work_dir=work_dir)

        target = settings_path_for(work_dir)
        path = write_campaign_settings(target, settings)

        assert path.exists()
        # Re-read and confirm round-trip equivalence — that's the contract:
        # whatever the renderer produced is what's on disk.
        on_disk = json.loads(path.read_text())
        assert on_disk == settings

    def test_settings_path_for_returns_dot_claude_subdir(self, tmp_path):
        path = settings_path_for(tmp_path)

        assert path.parent.name == ".claude"
        assert path.name == "settings.json"


# ─── No-`--dangerously` invariant ───────────────────────────────────────────

class TestSetupWorkDirWritesSettings:
    """Init-time wiring: ``setup_work_dir`` writes ``.claude/settings.json``
    so the dispatcher can pick it up automatically."""

    def test_init_writes_settings_in_dot_claude(self, tmp_path):
        from orchestrator.iteration import setup_work_dir

        repo = tmp_path / "target-repo"
        repo.mkdir()
        work_dir = setup_work_dir("run-123", repo_path=str(repo))

        settings_path = work_dir / ".claude" / "settings.json"
        assert settings_path.exists()

        on_disk = json.loads(settings_path.read_text())
        # work_dir and repo are both in allowOnly.
        assert str(work_dir.resolve()) in on_disk["permissions"]["allowOnly"]
        assert str(repo.resolve()) in on_disk["permissions"]["allowOnly"]

    def test_init_does_not_overwrite_existing_settings(self, tmp_path):
        from orchestrator.iteration import setup_work_dir

        repo = tmp_path / "target-repo"
        repo.mkdir()
        work_dir = Path(repo) / ".nous" / "run-456"
        work_dir.mkdir(parents=True)
        settings_dir = work_dir / ".claude"
        settings_dir.mkdir()
        custom_settings = {"permissions": {"allowOnly": ["/custom"], "allow": [], "deny": []}}
        (settings_dir / "settings.json").write_text(json.dumps(custom_settings))

        # Re-running setup must NOT clobber the user's hand edits.
        setup_work_dir("run-456", repo_path=str(repo))

        on_disk = json.loads((settings_dir / "settings.json").read_text())
        assert on_disk == custom_settings


class TestNoDangerouslyFlag:
    """Settings file is the *replacement* for ``--dangerously-skip-permissions``.

    The contract is: when the dispatcher invokes claude with ``--settings <path>``
    and this file is at <path>, the agent operates under deny-by-default rules
    rather than auto-approval. We assert the produced file imposes a non-empty
    allowOnly and at least one deny rule — the two properties that make the
    settings file *meaningfully* restrictive vs ``--dangerously``.
    """

    def test_settings_imposes_allowonly_and_deny(self, tmp_path):
        settings = render_campaign_settings(work_dir=tmp_path)

        assert settings["permissions"]["allowOnly"], (
            "allowOnly must be non-empty; otherwise everything is permitted, "
            "which is the very property --dangerously gave us."
        )
        assert settings["permissions"]["deny"], (
            "deny must be non-empty so writes/network outside the worktree "
            "are blocked."
        )
