"""Docs stay true to the code: the worked example checks out, example yamls parse cleanly,
the method note names what Nous checks, and user docs carry no retired terms."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest
import yaml

from orchestrator.lightweight.config import parse_campaign_config
from orchestrator.lightweight.final_check import check_answer
from orchestrator.lightweight.notebook import check_notebook, summary
from orchestrator.lightweight.validators import ValidatorContext, validate_answer

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "docs" / "example-campaign"
NOUS_WRITTEN = {"ledger.json", "final_check.json", "state.json"}


# ── the worked example ───────────────────────────────────────────────────


class TestExampleCampaign:
    def test_answer_validates(self):
        data = json.loads((EXAMPLE / "answer.json").read_text())
        assert validate_answer(data, ValidatorContext(work_dir=EXAMPLE)) == []
        assert "extra" not in data, "example must use only schema fields"

    def test_notebook_checks_out(self):
        assert check_notebook(EXAMPLE) == []

    def test_every_json_file_is_checked(self):
        """Each JSON file is the answer, a Nous-written file, or cited evidence."""
        cited = set()
        text = (EXAMPLE / "answer.json").read_text() + (EXAMPLE / "notebook.jsonl").read_text()
        for p in re.findall(r'"(?:path|evidence)":\s*"([^"]+)"', text):
            cited.add((EXAMPLE / p).resolve())
        for path in EXAMPLE.rglob("*.json*"):
            rel = path.relative_to(EXAMPLE).as_posix()
            assert rel in {"answer.json", "notebook.jsonl", "runs.jsonl"} | NOUS_WRITTEN \
                or path.resolve() in cited, rel

    def test_answer_follows_output_contract(self):
        answer = json.loads((EXAMPLE / "answer.json").read_text())
        for claim in answer["claims"]:
            assert isinstance(claim["evidence"], str)
            assert claim["evidence"].startswith("nous_evidence/")
            assert (EXAMPLE / claim["evidence"]).is_file()
            assert isinstance(claim["value"], (int, float)) and not isinstance(claim["value"], bool)
            if "evidence_detail" in claim:
                assert claim["evidence_detail"]["path"] == claim["evidence"]
        assert not answer["repro"].lstrip().startswith("cd ")

    def test_final_check_matches_record(self):
        expected = json.loads((EXAMPLE / "final_check.json").read_text())
        report = check_answer(EXAMPLE)
        report.update(notebook=summary(EXAMPLE), notebook_errors=check_notebook(EXAMPLE),
                      challenger=expected["challenger"], status="ok")
        assert report == expected

    def test_ledger_row_fields(self):
        (row,) = json.loads((EXAMPLE / "ledger.json").read_text())
        assert set(row) == {"iteration", "status", "stop_reason", "cost_meter_usd", "tokens",
                            "repro_recorded", "nous_version"}
        assert row["stop_reason"] == "answered"

    def test_runs_jsonl_rows_have_hook_fields(self):
        fields = {"ts", "phase", "iter", "tool_use_id", "command", "exit_code",
                  "output_bytes", "cwd", "background", "agent_id", "experiment"}
        for line in (EXAMPLE / "runs.jsonl").read_text().splitlines():
            assert set(json.loads(line)) == fields


# ── example yamls ────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", [ROOT / "examples" / "campaign.yaml", EXAMPLE / "campaign.yaml"])
def test_example_yaml_parses_without_warnings(path, caplog):
    with caplog.at_level(logging.WARNING):
        cfg = parse_campaign_config(yaml.safe_load(path.read_text()))
    assert [r.message for r in caplog.records] == []
    assert cfg.task_type


# ── retired terms in user docs ───────────────────────────────────────────

RETIRED = re.compile(
    r"\bplanner\b|\bexecutor\b|bundle\.yaml|experiment_plan\.yaml|handoff\.md|design_profile|--agent inline"
    r"|\bv2\b|\bv3\b|--v3|nous validate|nous schema|nous stop|BASELINE phase|DESIGN phase|EXECUTE phase"
    r"|bundle\.json|plan\.json|findings\.json|principle_updates|baseline\.json",
    re.IGNORECASE,
)


def _user_doc_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "CLAUDE.md", ROOT / "tests" / "CLAUDE.md"]
    files += [p for p in (ROOT / "docs").rglob("*") if p.is_file() and p.suffix == ".md"]
    files += [p for p in (ROOT / "prompts" / "lightweight").rglob("*") if p.is_file()]
    files += [p for p in (ROOT / "plugin").rglob("*.md")]
    return files


def test_no_retired_terms_in_user_docs():
    hits = [f"{p.relative_to(ROOT)}: {m.group(0)}"
            for p in _user_doc_files() for m in RETIRED.finditer(p.read_text(errors="replace"))]
    assert hits == []
