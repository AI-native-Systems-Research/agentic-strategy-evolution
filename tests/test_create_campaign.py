"""Behavioral tests for campaign-authoring UX (issue #89).

Closes the silent-failure gap where authors put domain context in
``domain_adapter_layer`` (which sounds right but is unimplemented and
silently warned-and-ignored). Three lines of defense:

  1. ``nous create-campaign`` CLI scaffolder produces a heavily-
     commented, schema-valid campaign.yaml. Inline comments name
     exactly which fields reach the LLM agents.
  2. Schema description for ``domain_adapter_layer`` flags it as
     "not yet implemented" — schema-as-documentation.
  3. The runtime warning in llm_dispatch when the field is set is
     loud and points at the create-campaign skill.

A campaign-authoring skill (``plugin/nous/skills/nous-create-campaign.md``)
walks the LLM through the protocol when a user asks Claude Code to
help create a campaign.

Test contract:
  - All checks are pure file/stdout assertions. No subprocess to a
    real LLM, no live network. The scaffolder is pure deterministic
    Python.
"""
from __future__ import annotations

from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.create_campaign import (
    REACHABLE_FIELDS,
    scaffold_campaign,
)


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"
SKILLS_DIR = Path(__file__).resolve().parent.parent / "plugin" / "nous" / "skills"


def _load_campaign_schema() -> dict:
    return yaml.safe_load((SCHEMAS_DIR / "campaign.schema.yaml").read_text())


# ─── Scaffolder produces schema-valid output ─────────────────────────────


class TestScaffolderProducesValidYaml:
    def test_default_scaffold_validates_against_schema(self, tmp_path: Path) -> None:
        path = scaffold_campaign(tmp_path / "campaign.yaml")
        loaded = yaml.safe_load(path.read_text())
        jsonschema.validate(loaded, _load_campaign_schema())

    def test_scaffold_with_overrides_validates(self, tmp_path: Path) -> None:
        path = scaffold_campaign(
            tmp_path / "campaign.yaml",
            target_name="MySystem",
            target_description="A made-up system for testing.",
            research_question="Does X reduce Y under Z?",
            run_id="my-run",
        )
        loaded = yaml.safe_load(path.read_text())
        jsonschema.validate(loaded, _load_campaign_schema())
        assert loaded["target_system"]["name"] == "MySystem"
        # YAML folded scalars (`>`) preserve a trailing newline; strip
        # before equality so the test is about content not whitespace.
        assert loaded["research_question"].strip() == "Does X reduce Y under Z?"
        assert loaded["run_id"] == "my-run"

    def test_scaffold_writes_to_specified_path(self, tmp_path: Path) -> None:
        target = tmp_path / "subdir" / "campaign.yaml"
        result = scaffold_campaign(target)
        assert result == target
        assert target.exists()

    def test_scaffold_refuses_to_overwrite_by_default(self, tmp_path: Path) -> None:
        target = tmp_path / "campaign.yaml"
        scaffold_campaign(target)
        # Second call without force= should refuse.
        with pytest.raises(FileExistsError):
            scaffold_campaign(target)

    def test_scaffold_force_overwrites(self, tmp_path: Path) -> None:
        target = tmp_path / "campaign.yaml"
        scaffold_campaign(target)
        scaffold_campaign(target, target_name="Renamed", force=True)
        loaded = yaml.safe_load(target.read_text())
        assert loaded["target_system"]["name"] == "Renamed"

    def test_scaffold_writes_explicit_repo_path(self, tmp_path: Path) -> None:
        """#184: --target-repo-path must land as a real (uncommented)
        repo_path in the scaffold so `nous run` doesn't silently wedge
        when invoked from a different CWD later."""
        repo = tmp_path / "myrepo"
        repo.mkdir()
        path = scaffold_campaign(
            tmp_path / "campaign.yaml",
            target_repo_path=repo,
        )
        loaded = yaml.safe_load(path.read_text())
        assert loaded["target_system"]["repo_path"] == str(repo.resolve())

    def test_scaffold_defaults_repo_path_to_cwd(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """#184: when --target-repo-path is omitted, the scaffolder
        captures CWD at scaffold time and writes it as a real value.
        This is almost always right because authors typically scaffold
        from inside the target repo.
        """
        repo = tmp_path / "fakerepo"
        repo.mkdir()
        monkeypatch.chdir(repo)
        path = scaffold_campaign(tmp_path / "campaign.yaml")
        loaded = yaml.safe_load(path.read_text())
        # Must be a real path (not None / null), and must equal the
        # CWD that was active when scaffold_campaign ran.
        assert loaded["target_system"]["repo_path"] == str(repo.resolve())


# ─── Scaffolder names which fields reach agents ──────────────────────────


class TestScaffolderInlineGuidance:
    def test_output_lists_reachable_fields(self, tmp_path: Path) -> None:
        """The scaffolded YAML's leading comment block must explicitly
        name which fields reach the LLM via {{template}} substitution.
        Authors must not have to read llm_dispatch.py to know."""
        path = scaffold_campaign(tmp_path / "campaign.yaml")
        text = path.read_text()
        for field in REACHABLE_FIELDS:
            assert field in text, (
                f"scaffolded campaign.yaml must mention reachable field "
                f"{field!r} in inline guidance"
            )

    def test_output_warns_about_domain_adapter_layer(
        self, tmp_path: Path,
    ) -> None:
        """The trap from #89: domain_adapter_layer LOOKS like the right
        place to put domain context but is silently warned-and-ignored.
        The scaffolded YAML must call this out clearly so authors don't
        fall in."""
        path = scaffold_campaign(tmp_path / "campaign.yaml")
        text = path.read_text().lower()
        assert "not yet implemented" in text or "not implemented" in text
        assert "domain_adapter_layer" in text
        # The recommended workaround must be explicit.
        assert "description" in text  # the field to use instead

    def test_output_includes_authoring_checklist(self, tmp_path: Path) -> None:
        """The checklist from #89: schema gotchas, statistical guardrails,
        paths, baselines. Surfacing these in the YAML keeps them in
        scope when the author edits."""
        path = scaffold_campaign(tmp_path / "campaign.yaml")
        text = path.read_text().lower()
        assert "checklist" in text or "before you run" in text
        # Each checklist item should be present in some form
        assert "baseline" in text  # pre-specified baselines
        assert "path" in text  # exact file paths
        # Statistical guardrails / sample size
        assert "seeds" in text or "sample" in text


# ─── Schema honesty about domain_adapter_layer ────────────────────────────


class TestSchemaIsHonest:
    def test_domain_adapter_layer_description_flags_not_implemented(self) -> None:
        """The schema description is documentation. Today it says
        "Path to domain-specific prompt overrides", which sounds active.
        After #89 it should explicitly say it's not implemented."""
        schema = _load_campaign_schema()
        dal_desc = (
            schema["properties"]["prompts"]["properties"]
                  ["domain_adapter_layer"]["description"]
        )
        assert "not yet implemented" in dal_desc.lower() or \
               "not implemented" in dal_desc.lower(), (
            f"domain_adapter_layer description must flag the unimplemented "
            f"state. Current: {dal_desc!r}"
        )


# ─── Runtime warning is loud and points at the skill ──────────────────────


class TestRuntimeWarningIsDirective:
    def test_warning_message_mentions_create_campaign(self) -> None:
        """When campaign.prompts.domain_adapter_layer is set, the warning
        in llm_dispatch must point the author at the create-campaign
        skill so they can fix the config."""
        text = (Path(__file__).resolve().parent.parent
                / "orchestrator" / "llm_dispatch.py").read_text()
        # Find the warning block.
        assert "domain_adapter_layer" in text
        # The warning must reference the recommended workaround.
        assert "description" in text  # "put it in description"
        assert ("create-campaign" in text or
                "create_campaign" in text or
                "issue #89" in text), (
            "warning should reference the create-campaign skill or "
            "the recommended migration path"
        )


# ─── Skill file exists with required sections ────────────────────────────


class TestSkillFileExists:
    def test_skill_file_present(self) -> None:
        skill = SKILLS_DIR / "nous-create-campaign.md"
        assert skill.exists(), f"missing skill file at {skill}"

    def test_skill_has_frontmatter(self) -> None:
        skill = SKILLS_DIR / "nous-create-campaign.md"
        text = skill.read_text()
        # All plugin skills use frontmatter with name + description.
        assert text.startswith("---"), "skill must start with frontmatter"
        assert "\nname:" in text[:200]
        assert "\ndescription:" in text[:500]

    def test_skill_describes_reachable_fields(self) -> None:
        skill = SKILLS_DIR / "nous-create-campaign.md"
        text = skill.read_text()
        for field in REACHABLE_FIELDS:
            assert field in text, (
                f"skill must enumerate reachable field {field!r}"
            )

    def test_skill_warns_about_domain_adapter_layer(self) -> None:
        skill = SKILLS_DIR / "nous-create-campaign.md"
        text = skill.read_text().lower()
        assert "domain_adapter_layer" in text
        assert "not yet implemented" in text or "not implemented" in text

    def test_skill_includes_checklist(self) -> None:
        """The skill must walk the LLM through the four-item checklist
        from #89: schema gotchas, statistical guardrails, paths, baselines."""
        skill = SKILLS_DIR / "nous-create-campaign.md"
        text = skill.read_text().lower()
        assert "checklist" in text or "before you" in text
        assert "baseline" in text
        # Statistical guardrails
        assert "seeds" in text or "sample" in text or "power" in text


# ─── REACHABLE_FIELDS matches reality ────────────────────────────────────


class TestReachableFieldsConstant:
    def test_constant_includes_documented_substitutions(self) -> None:
        """The REACHABLE_FIELDS constant in create_campaign.py must
        match the actual {{template}} substitutions in
        llm_dispatch._build_context. If the LLM dispatcher gains a new
        substitution, this constant must update too — keeps the skill
        and scaffolder honest."""
        # Per #89 issue body: research_question, target_system.description,
        # target_system.observable_metrics, target_system.controllable_knobs.
        expected_min = {
            "research_question",
            "description",  # target_system.description
            "observable_metrics",
            "controllable_knobs",
        }
        assert expected_min.issubset(set(REACHABLE_FIELDS))
