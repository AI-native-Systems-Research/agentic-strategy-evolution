"""Behavioral tests for the plugin package (#125)."""
from __future__ import annotations

import json
import re
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parent.parent / "plugin" / "nous"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class TestPluginManifest:

    def test_plugin_json_exists_with_required_fields(self):
        path = PLUGIN_ROOT / "plugin.json"
        assert path.exists()
        data = json.loads(path.read_text())
        for required in ("name", "version", "description", "skills"):
            assert required in data, f"plugin.json missing {required!r}"
        assert data["name"] == "nous"
        assert isinstance(data["skills"], list)

    def test_plugin_lists_at_least_five_skills(self):
        data = json.loads((PLUGIN_ROOT / "plugin.json").read_text())
        assert len(data["skills"]) >= 5

    def test_each_listed_skill_file_exists(self):
        data = json.loads((PLUGIN_ROOT / "plugin.json").read_text())
        for rel in data["skills"]:
            assert (PLUGIN_ROOT / rel).exists(), f"missing skill file: {rel}"


class TestSkillFrontmatter:
    """Each skill markdown must have YAML frontmatter with name + description.

    The description is what Claude Code reads to decide whether to suggest
    the skill. A vague or missing description is the difference between a
    discoverable skill and a dead one.
    """

    def _frontmatter(self, path: Path) -> dict[str, str]:
        match = _FRONTMATTER_RE.match(path.read_text())
        if not match:
            return {}
        out: dict[str, str] = {}
        for line in match.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                out[k.strip()] = v.strip()
        return out

    def test_every_skill_has_name_and_description(self):
        data = json.loads((PLUGIN_ROOT / "plugin.json").read_text())
        for rel in data["skills"]:
            fm = self._frontmatter(PLUGIN_ROOT / rel)
            assert "name" in fm and fm["name"], f"{rel}: missing name"
            assert "description" in fm and fm["description"], f"{rel}: missing description"

    def test_descriptions_describe_when_to_use(self):
        """The description should include cue words that help Claude Code
        match user intent ("when the user wants", "use when", etc.)."""
        data = json.loads((PLUGIN_ROOT / "plugin.json").read_text())
        for rel in data["skills"]:
            fm = self._frontmatter(PLUGIN_ROOT / rel)
            desc = fm.get("description", "").lower()
            assert "use when" in desc or "when the user" in desc or "use this" in desc, (
                f"{rel}: description should hint at when to use the skill"
            )

    def test_each_skill_body_references_nous_cli(self):
        """Phase A skills are CLI wrappers — each markdown body must
        reference the nous command it shells out to."""
        data = json.loads((PLUGIN_ROOT / "plugin.json").read_text())
        for rel in data["skills"]:
            body = (PLUGIN_ROOT / rel).read_text()
            assert "nous " in body or "campaign_index" in body, (
                f"{rel}: body should invoke a nous command or campaign_index"
            )


class TestSkillCoverage:
    """Acceptance criterion: at least 5 skills must be present and
    cover the documented operations."""

    EXPECTED_SKILLS = {
        "nous-run", "nous-status", "nous-resume",
        "nous-list", "nous-bisect", "nous-find-principle",
    }

    def test_all_expected_skills_present(self):
        present = {p.stem for p in (PLUGIN_ROOT / "skills").glob("*.md")}
        assert self.EXPECTED_SKILLS <= present, (
            f"missing skills: {self.EXPECTED_SKILLS - present}"
        )
