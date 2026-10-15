"""Behavioral tests for the Claude Code plugin package (#125).

The plugin is how most users drive Nous: from a Claude session. These tests
enforce Claude Code's documented layout (code.claude.com/docs/en/plugins-reference):
the manifest at `.claude-plugin/plugin.json`, one `skills/<name>/SKILL.md` per
skill (auto-discovered), and a marketplace at the repo root. The previous layout
(a root `plugin.json` listing flat `skills/*.md`) did not validate and could not
be installed -- found when installing Nous for Claude users.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO / "plugin" / "nous"
SKILLS = sorted((PLUGIN_ROOT / "skills").glob("*/SKILL.md"))

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _frontmatter(path: Path) -> dict[str, str]:
    match = _FRONTMATTER_RE.match(path.read_text())
    out: dict[str, str] = {}
    for line in (match.group(1).splitlines() if match else []):
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


class TestLayout:

    def test_manifest_lives_in_dot_claude_plugin(self):
        data = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())
        assert data["name"] == "nous"
        for field in ("version", "description", "author"):
            assert data.get(field), f"plugin.json missing {field!r}"
        assert not (PLUGIN_ROOT / "plugin.json").exists(), "stale root manifest"

    def test_skills_are_directories_with_skill_md(self):
        assert not list((PLUGIN_ROOT / "skills").glob("*.md")), (
            "flat skills/*.md are not loaded; use skills/<name>/SKILL.md")
        assert len(SKILLS) >= 6

    def test_marketplace_points_at_the_plugin(self):
        mp = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
        assert mp["name"] and mp["owner"]["name"]
        (entry,) = [p for p in mp["plugins"] if p["name"] == "nous"]
        assert (REPO / entry["source"]).resolve() == PLUGIN_ROOT.resolve()


class TestSkills:

    @pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
    def test_frontmatter_names_the_directory_and_says_when_to_use(self, skill):
        fm = _frontmatter(skill)
        assert fm.get("name") == skill.parent.name
        desc = fm.get("description", "").lower()
        assert "use when" in desc or "when the user" in desc or "use this" in desc

    @pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
    def test_body_drives_the_nous_cli(self, skill):
        body = skill.read_text()
        assert "nous " in body or "campaign_index" in body

    def test_expected_skills_present(self):
        present = {p.parent.name for p in SKILLS}
        assert {"nous-run", "nous-status", "nous-resume", "nous-list", "nous-bisect",
                "nous-find-principle", "nous-create-campaign", "nous-optimize"} <= present

    def test_optimize_skill_covers_the_whole_loop(self):
        body = (PLUGIN_ROOT / "skills" / "nous-optimize" / "SKILL.md").read_text()
        for step in ("nous create-campaign --kind optimization", "--smoke",
                     "--liveness", "nous progress", "report.md", "nous resume"):
            assert step in body, step


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not installed")
@pytest.mark.parametrize("target", [PLUGIN_ROOT, REPO])
def test_claude_plugin_validate_passes(target):
    r = subprocess.run(["claude", "plugin", "validate", str(target)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "Validation passed" in r.stdout, r.stdout + r.stderr
