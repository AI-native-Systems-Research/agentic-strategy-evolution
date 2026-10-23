"""Tests for evidence-checking rules in orchestrator.v2.validators.

Every test uses tmp_path to create fixture files on disk.  No live LLM
calls, no structural mocks — behavioral assertions only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.v2.validators import check_evidence_item


# ── Helpers ──────────────────────────────────────────────────────────────


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ── JSON evidence ────────────────────────────────────────────────────────


class TestJsonEvidence:
    def test_valid_simple(self, tmp_path: Path):
        f = tmp_path / "result.json"
        _write(f, json.dumps({"score": 42}))
        errs = check_evidence_item(
            {"path": "result.json", "key": "/score", "value": 42}, tmp_path
        )
        assert errs == []

    def test_nested_pointer(self, tmp_path: Path):
        f = tmp_path / "deep.json"
        _write(f, json.dumps({"a": {"b": [{"c": "yes"}]}}))
        errs = check_evidence_item(
            {"path": "deep.json", "key": "/a/b/0/c", "value": "yes"}, tmp_path
        )
        assert errs == []

    def test_root_pointer(self, tmp_path: Path):
        """Empty pointer returns the whole document."""
        f = tmp_path / "root.json"
        _write(f, json.dumps({"x": 1}))
        errs = check_evidence_item(
            {"path": "root.json", "key": "", "value": {"x": 1}}, tmp_path
        )
        assert errs == []

    def test_value_mismatch(self, tmp_path: Path):
        f = tmp_path / "result.json"
        _write(f, json.dumps({"score": 42}))
        errs = check_evidence_item(
            {"path": "result.json", "key": "/score", "value": 99}, tmp_path
        )
        assert len(errs) == 1
        assert "mismatch" in errs[0]

    def test_bad_pointer_key_not_found(self, tmp_path: Path):
        f = tmp_path / "result.json"
        _write(f, json.dumps({"score": 42}))
        errs = check_evidence_item(
            {"path": "result.json", "key": "/missing", "value": 0}, tmp_path
        )
        assert len(errs) == 1
        assert "lookup failed" in errs[0]

    def test_numeric_tolerance_within(self, tmp_path: Path):
        """1.0001 vs 1.0 — within rel_tol=1e-3."""
        f = tmp_path / "num.json"
        _write(f, json.dumps({"v": 1.0001}))
        errs = check_evidence_item(
            {"path": "num.json", "key": "/v", "value": 1.0}, tmp_path
        )
        assert errs == []

    def test_numeric_tolerance_beyond(self, tmp_path: Path):
        """1.01 vs 1.0 — beyond rel_tol=1e-3."""
        f = tmp_path / "num.json"
        _write(f, json.dumps({"v": 1.01}))
        errs = check_evidence_item(
            {"path": "num.json", "key": "/v", "value": 1.0}, tmp_path
        )
        assert len(errs) == 1
        assert "mismatch" in errs[0]

    def test_string_exact_match(self, tmp_path: Path):
        f = tmp_path / "s.json"
        _write(f, json.dumps({"tag": "beta"}))
        errs = check_evidence_item(
            {"path": "s.json", "key": "/tag", "value": "beta"}, tmp_path
        )
        assert errs == []

    def test_string_exact_mismatch(self, tmp_path: Path):
        f = tmp_path / "s.json"
        _write(f, json.dumps({"tag": "beta"}))
        errs = check_evidence_item(
            {"path": "s.json", "key": "/tag", "value": "alpha"}, tmp_path
        )
        assert len(errs) == 1
        assert "mismatch" in errs[0]

    def test_array_index_pointer(self, tmp_path: Path):
        f = tmp_path / "arr.json"
        _write(f, json.dumps({"items": ["a", "b", "c"]}))
        errs = check_evidence_item(
            {"path": "arr.json", "key": "/items/1", "value": "b"}, tmp_path
        )
        assert errs == []


# ── JSONL evidence ───────────────────────────────────────────────────────


class TestJsonlEvidence:
    def test_valid_line_and_pointer(self, tmp_path: Path):
        f = tmp_path / "log.jsonl"
        lines = [
            json.dumps({"metric": 0.5}),
            json.dumps({"metric": 0.9}),
        ]
        _write(f, "\n".join(lines))
        errs = check_evidence_item(
            {"path": "log.jsonl", "key": "1@/metric", "value": 0.9}, tmp_path
        )
        assert errs == []

    def test_line_out_of_range(self, tmp_path: Path):
        f = tmp_path / "log.jsonl"
        _write(f, json.dumps({"x": 1}))
        errs = check_evidence_item(
            {"path": "log.jsonl", "key": "5@/x", "value": 1}, tmp_path
        )
        assert len(errs) == 1
        assert "out of range" in errs[0]

    def test_invalid_key_format(self, tmp_path: Path):
        f = tmp_path / "log.jsonl"
        _write(f, json.dumps({"x": 1}))
        errs = check_evidence_item(
            {"path": "log.jsonl", "key": "/x", "value": 1}, tmp_path
        )
        assert len(errs) == 1
        assert "format" in errs[0].lower()

    def test_value_mismatch(self, tmp_path: Path):
        f = tmp_path / "log.jsonl"
        _write(f, json.dumps({"x": 1}))
        errs = check_evidence_item(
            {"path": "log.jsonl", "key": "0@/x", "value": 999}, tmp_path
        )
        assert len(errs) == 1
        assert "mismatch" in errs[0]

    def test_nested_pointer_in_jsonl(self, tmp_path: Path):
        f = tmp_path / "log.jsonl"
        _write(f, json.dumps({"a": {"b": 7}}))
        errs = check_evidence_item(
            {"path": "log.jsonl", "key": "0@/a/b", "value": 7}, tmp_path
        )
        assert errs == []


# ── CSV evidence ─────────────────────────────────────────────────────────


class TestCsvEvidence:
    def test_valid_string_cell(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        _write(f, "name,score\nalice,10\nbob,20\n")
        errs = check_evidence_item(
            {"path": "data.csv", "key": "name@0", "value": "alice"}, tmp_path
        )
        assert errs == []

    def test_numeric_cell_tolerance(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        _write(f, "metric\n3.14159\n")
        errs = check_evidence_item(
            {"path": "data.csv", "key": "metric@0", "value": 3.14159}, tmp_path
        )
        assert errs == []

    def test_numeric_cell_within_tolerance(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        _write(f, "metric\n1.0005\n")
        errs = check_evidence_item(
            {"path": "data.csv", "key": "metric@0", "value": 1.0}, tmp_path
        )
        assert errs == []

    def test_column_not_found(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        _write(f, "a,b\n1,2\n")
        errs = check_evidence_item(
            {"path": "data.csv", "key": "missing@0", "value": 1}, tmp_path
        )
        assert len(errs) == 1
        assert "column" in errs[0].lower()

    def test_row_out_of_range(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        _write(f, "a\n1\n")
        errs = check_evidence_item(
            {"path": "data.csv", "key": "a@10", "value": 1}, tmp_path
        )
        assert len(errs) == 1
        assert "out of range" in errs[0]

    def test_invalid_key_format(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        _write(f, "a\n1\n")
        errs = check_evidence_item(
            {"path": "data.csv", "key": "no-at-sign", "value": 1}, tmp_path
        )
        assert len(errs) == 1
        assert "format" in errs[0].lower()


# ── TSV evidence ─────────────────────────────────────────────────────────


class TestTsvEvidence:
    def test_valid_tsv_cell(self, tmp_path: Path):
        f = tmp_path / "data.tsv"
        _write(f, "name\tscore\nalice\t10\n")
        errs = check_evidence_item(
            {"path": "data.tsv", "key": "name@0", "value": "alice"}, tmp_path
        )
        assert errs == []

    def test_tsv_numeric_match(self, tmp_path: Path):
        f = tmp_path / "data.tsv"
        _write(f, "val\n42\n")
        errs = check_evidence_item(
            {"path": "data.tsv", "key": "val@0", "value": 42}, tmp_path
        )
        assert errs == []

    def test_tsv_row_out_of_range(self, tmp_path: Path):
        f = tmp_path / "data.tsv"
        _write(f, "x\n1\n")
        errs = check_evidence_item(
            {"path": "data.tsv", "key": "x@5", "value": 1}, tmp_path
        )
        assert len(errs) == 1
        assert "out of range" in errs[0]


# ── Plain text evidence ─────────────────────────────────────────────────


class TestPlainTextEvidence:
    def test_regex_group1_match(self, tmp_path: Path):
        f = tmp_path / "output.txt"
        _write(f, "final score: 42 points\n")
        errs = check_evidence_item(
            {"path": "output.txt", "key": r"score: (\d+)", "value": "42"},
            tmp_path,
        )
        assert errs == []

    def test_regex_not_found(self, tmp_path: Path):
        f = tmp_path / "output.txt"
        _write(f, "no match here\n")
        errs = check_evidence_item(
            {"path": "output.txt", "key": r"score: (\d+)", "value": "42"},
            tmp_path,
        )
        assert len(errs) == 1
        assert "not found" in errs[0]

    def test_regex_group1_mismatch(self, tmp_path: Path):
        f = tmp_path / "output.txt"
        _write(f, "final score: 99 points\n")
        errs = check_evidence_item(
            {"path": "output.txt", "key": r"score: (\d+)", "value": "42"},
            tmp_path,
        )
        assert len(errs) == 1
        assert "mismatch" in errs[0]


# ── File does not exist ──────────────────────────────────────────────────


class TestMissingFile:
    def test_nonexistent_path(self, tmp_path: Path):
        errs = check_evidence_item(
            {"path": "no_such_file.json", "key": "/x", "value": 1}, tmp_path
        )
        assert len(errs) == 1
        assert "does not exist" in errs[0]

    def test_nonexistent_nested_path(self, tmp_path: Path):
        errs = check_evidence_item(
            {"path": "sub/dir/missing.csv", "key": "a@0", "value": 1},
            tmp_path,
        )
        assert len(errs) == 1
        assert "does not exist" in errs[0]


# ── Malformed inputs return errors, never raise ──────────────────────────


class TestMalformedInputs:
    def test_bad_regex_key(self, tmp_path: Path):
        _write(tmp_path / "log.txt", "score=1\n")
        errs = check_evidence_item({"path": "log.txt", "key": "score=(", "value": "1"}, tmp_path)
        assert errs

    def test_non_int_pointer_into_list(self, tmp_path: Path):
        _write(tmp_path / "r.json", json.dumps({"a": [1, 2]}))
        errs = check_evidence_item({"path": "r.json", "key": "/a/x", "value": 1}, tmp_path)
        assert errs

    def test_binary_text_file(self, tmp_path: Path):
        (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00\x81")
        errs = check_evidence_item({"path": "blob.bin", "key": "(x)", "value": "x"}, tmp_path)
        assert errs


def test_non_object_evidence_item_is_an_error_not_a_crash(tmp_path):
    from orchestrator.v2.validators import check_evidence_item
    assert check_evidence_item("R1.json", tmp_path)
    assert check_evidence_item(None, tmp_path)
