"""Behavioral tests for `nous schema` (prints a v2 artifact schema; no LLM)."""
from __future__ import annotations

import argparse
import json

import yaml


def _ns(*, artifact="bundle", format="md"):  # noqa: A002
    return argparse.Namespace(artifact=artifact, format=format)


class TestSchemaCommand:
    def test_markdown_lists_required_fields(self, capsys) -> None:
        from orchestrator.cli import _cmd_schema
        _cmd_schema(_ns())
        out = capsys.readouterr().out
        assert "Required fields" in out
        assert "hypotheses" in out

    def test_json_format_round_trips(self, capsys) -> None:
        from orchestrator.cli import _cmd_schema
        _cmd_schema(_ns(artifact="findings", format="json"))
        assert "hypotheses" in json.loads(capsys.readouterr().out)["properties"]

    def test_yaml_format_round_trips(self, capsys) -> None:
        from orchestrator.cli import _cmd_schema
        _cmd_schema(_ns(artifact="plan", format="yaml"))
        assert "runs" in yaml.safe_load(capsys.readouterr().out)["properties"]
