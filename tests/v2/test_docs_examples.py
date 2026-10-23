"""Docs stay true to the code (R14): the worked example validates, example yamls parse
cleanly, method.md field lists match the schemas, and user docs carry no v1 terms."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.v2.config import parse_campaign_config, validator_limits
from orchestrator.v2.final_check import check_answer
from orchestrator.v2.validators import _load_schema, iter_context, validate_artifact

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "docs" / "example-campaign"
SCHEMAS = ROOT / "orchestrator" / "v2" / "schemas"
METHOD = ROOT / "prompts" / "v2" / "method.md"

# artifact file (relative to the example work dir) -> v2 artifact type
ARTIFACTS = {
    "baseline.json": "baseline",
    "answer.json": "answer",
    "runs/iter-1/problem.json": "problem",
    "runs/iter-1/bundle.json": "bundle",
    "runs/iter-1/plan.json": "plan",
    "runs/iter-1/findings.json": "findings",
    "runs/iter-1/principle_updates.json": "principle_updates",
}
NOUS_WRITTEN = {"ledger.json", "final_check.json"}


def _limits() -> dict:
    cfg = parse_campaign_config(yaml.safe_load((EXAMPLE / "campaign.yaml").read_text()))
    return validator_limits(cfg, EXAMPLE)


def _evidence_paths() -> set[Path]:
    """Every file an example artifact cites as evidence or metrics_path."""
    out = {(EXAMPLE / json.loads((EXAMPLE / "baseline.json").read_text())["metrics_path"]).resolve()}
    text = " ".join((EXAMPLE / rel).read_text() for rel in ARTIFACTS)
    for p in re.findall(r'"(?:path|evidence)":\s*"([^"]+)"', text):
        for base in (EXAMPLE / "runs" / "iter-1", EXAMPLE):
            if (base / p).is_file():
                out.add((base / p).resolve())
                break
    return out


# ── the worked example ───────────────────────────────────────────────────


class TestExampleCampaign:
    @pytest.mark.parametrize("rel", sorted(ARTIFACTS))
    def test_artifact_validates(self, rel):
        data = json.loads((EXAMPLE / rel).read_text())
        phase_dir = (EXAMPLE / rel).parent
        ctx = iter_context(EXAMPLE, phase_dir if phase_dir != EXAMPLE else None, **_limits())
        assert validate_artifact(ARTIFACTS[rel], data, ctx) == []
        assert "extra" not in data, "example must use only schema fields"

    def test_every_json_file_is_checked(self):
        """Each JSON file is a v2 artifact, a Nous-written file, or cited evidence."""
        cited = _evidence_paths()
        for path in EXAMPLE.rglob("*.json"):
            rel = path.relative_to(EXAMPLE).as_posix()
            assert rel in ARTIFACTS or rel in NOUS_WRITTEN or path.resolve() in cited, rel

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
        assert check_answer(EXAMPLE, _limits()) == expected

    def test_ledger_rows_validate(self):
        schema = json.loads((SCHEMAS / "ledger_entry.schema.json").read_text())
        for row in json.loads((EXAMPLE / "ledger.json").read_text()):
            jsonschema.validate(row, schema)

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
    assert cfg.task_type and cfg.locked_parameters and cfg.objective


# ── method.md field lists vs schemas ─────────────────────────────────────


def _schema_names(node, props: set, values: set) -> None:
    """All property names (incl. per-task_type observation keys) and enum/const values."""
    if isinstance(node, dict):
        if isinstance(node.get("properties"), dict):
            props.update(node["properties"])
        for v in node.get("enum", []):
            values.add(str(v))
        if "const" in node:
            values.add(str(node["const"]).lower())
        for v in node.values():
            _schema_names(v, props, values)
    elif isinstance(node, list):
        for v in node:
            _schema_names(v, props, values)


def _required_names(node, out: set) -> None:
    if isinstance(node, dict):
        out.update(node.get("required", []))
        for v in node.values():
            _required_names(v, out)
    elif isinstance(node, list):
        for v in node:
            _required_names(v, out)


def _method_text() -> dict[str, str]:
    """method.md text per artifact section (from "- `x.json`" to the next phase or artifact)."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in METHOD.read_text().splitlines():
        m = re.match(r"^- `(\w+)\.json`", line)
        if m:
            current = m.group(1)
        elif line.startswith(("**", "##")) or re.match(r"^- `\S+\.md`", line):
            current = None
        if current:
            sections.setdefault(current, []).append(line)
    return {name: "\n".join(lines) for name, lines in sections.items()}


def _method_sections() -> dict[str, set[str]]:
    """Identifiers inside backticks, per artifact section of method.md."""
    out = {}
    for name, text in _method_text().items():
        spans = [re.sub(r"\([^)]*\)", "", s) for s in re.findall(r"`([^`]+)`", text)]
        out[name] = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", " ".join(spans)))
    return out


# words in method.md backticks that are not field names or enum values
_PROSE = {"json", "int", "number", "str", "sd", "cmd", "command", "nous_evidence", "cd"}
ARTIFACT_TYPES = ["baseline", "problem", "bundle", "plan", "findings", "principle_updates", "answer"]


class TestMethodFieldsMatchSchemas:
    def test_every_artifact_has_a_section(self):
        assert set(_method_sections()) == set(ARTIFACT_TYPES)

    @pytest.mark.parametrize("artifact", ARTIFACT_TYPES)
    def test_every_schema_field_is_listed(self, artifact):
        props: set = set()
        _schema_names(_load_schema(artifact), props, set())
        missing = props - {"extra"} - _method_sections()[artifact]
        assert not missing, f"method.md {artifact}.json omits schema fields {sorted(missing)}"

    @pytest.mark.parametrize("artifact", ARTIFACT_TYPES)
    def test_every_listed_name_is_in_schema(self, artifact):
        props: set = set()
        values: set = set()
        _schema_names(_load_schema(artifact), props, values)
        unknown = _method_sections()[artifact] - props - values - _PROSE - {artifact}
        assert not unknown, f"method.md {artifact}.json lists names not in the schema {sorted(unknown)}"

    @pytest.mark.parametrize("artifact", ARTIFACT_TYPES)
    def test_optional_marks_match_schema(self, artifact):
        """`name?` only for fields the schema leaves optional; required fields carry no `?`."""
        spans = " ".join(re.findall(r"`([^`]+)`", _method_text()[artifact]))
        marked = set(re.findall(r"([a-z_]+)\?", spans))
        optional: set = set()
        required: set = set()

        def walk(node):
            if isinstance(node, dict):
                if isinstance(node.get("properties"), dict):
                    req = set(node.get("required", []))
                    optional.update(set(node["properties"]) - req)
                    required.update(req)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(_load_schema(artifact))
        assert marked <= optional, sorted(marked - optional)
        assert not (marked & required - optional), artifact


# ── no v1 terms in user docs ─────────────────────────────────────────────

V1_TERMS = re.compile(
    r"\bplanner\b|\bexecutor\b|bundle\.yaml|experiment_plan\.yaml|handoff\.md|design_profile|--agent inline",
    re.IGNORECASE,
)


def _user_doc_files() -> list[Path]:
    files = [ROOT / "README.md"]
    files += [p for p in (ROOT / "docs").rglob("*") if p.is_file() and "plans" not in p.relative_to(ROOT / "docs").parts[:1]]
    files += [p for p in (ROOT / "prompts" / "v2").rglob("*") if p.is_file()]
    commands = ROOT / ".claude" / "commands"
    if commands.is_dir():
        files += [p for p in commands.rglob("*") if p.is_file()]
    return files


def test_no_v1_terms_in_user_docs():
    hits = [f"{p.relative_to(ROOT)}: {m.group(0)}"
            for p in _user_doc_files() for m in V1_TERMS.finditer(p.read_text(errors="replace"))]
    assert hits == []
