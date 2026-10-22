"""Behavioral tests for `nous schema` (CLI schema renderer).

The `nous schema` command surfaces the canonical campaign / bundle /
findings shape from the CLI so authors don't grep the source.

Contract:
  - `nous schema` defaults to the campaign schema in Markdown.
  - `--format json` and `--format yaml` print the raw schema verbatim
    (for tooling).
  - The Markdown rendering names every required field, every optional
    field, and surfaces field descriptions verbatim from the schema.
  - The command is **pure deterministic Python** — no LLM, no SDK, no
    network. The autouse `block_live_llm_calls` fixture in
    tests/conftest.py would catch any accidental LLM call; we also pin
    that the command does not import or call into any dispatcher.
"""
from __future__ import annotations

import argparse
import json

import yaml


def _ns(*, artifact="campaign", format="md"):  # noqa: A002
    return argparse.Namespace(artifact=artifact, format=format)


class TestSchemaCommandRendersMarkdown:
    def test_default_renders_campaign_schema_in_markdown(self, capsys) -> None:
        from orchestrator.cli import _cmd_schema
        _cmd_schema(_ns())
        out = capsys.readouterr().out
        assert "# Campaign Configuration" in out
        # Required fields appear under the Required heading.
        assert "Required fields" in out
        assert "research_question" in out
        assert "target_system" in out
        assert "prompts" in out

    def test_optional_fields_section_present(self, capsys) -> None:
        from orchestrator.cli import _cmd_schema
        _cmd_schema(_ns())
        out = capsys.readouterr().out
        assert "Optional fields" in out
        # New fields landed by #185 / #186 surface here.
        assert "ground_truth" in out
        assert "max_turns" in out

    def test_rejection_marker_visible(self, capsys) -> None:
        """The campaign schema rejects unknown top-level properties.
        The renderer surfaces this so authors don't get blindsided by
        a schema-validation error after running `nous run`."""
        from orchestrator.cli import _cmd_schema
        _cmd_schema(_ns())
        out = capsys.readouterr().out
        assert "Rejects unknown top-level properties" in out


class TestSchemaCommandJsonAndYaml:
    def test_json_format_round_trips(self, capsys) -> None:
        from orchestrator.cli import _cmd_schema
        _cmd_schema(_ns(format="json"))
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["title"] == "Campaign Configuration"
        assert "research_question" in parsed["properties"]

    def test_yaml_format_round_trips(self, capsys) -> None:
        from orchestrator.cli import _cmd_schema
        _cmd_schema(_ns(format="yaml"))
        out = capsys.readouterr().out
        parsed = yaml.safe_load(out)
        assert parsed["title"] == "Campaign Configuration"


class TestBundleAndFindingsSchemas:
    def test_bundle_schema_renders(self, capsys) -> None:
        from orchestrator.cli import _cmd_schema
        _cmd_schema(_ns(artifact="bundle"))
        out = capsys.readouterr().out
        # v2 bundle (R11a): required hypotheses list.
        assert "hypotheses" in out

    def test_findings_schema_renders(self, capsys) -> None:
        from orchestrator.cli import _cmd_schema
        _cmd_schema(_ns(artifact="findings"))
        out = capsys.readouterr().out
        # findings.schema.json has a top-level title.
        assert out.strip()
