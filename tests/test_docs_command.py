"""`nous docs` serves the authoring docs from ANY install.

A pip-installed nous ships no docs/ tree, yet every scaffold and error message
pointed at docs/... -- a dead end for a user, or a Claude session, outside the
checkout (found installing system-wide). The docs ship as package data; the
repo's docs/ files stay canonical, and this guard fails if a copy drifts.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.cli import DOC_TOPICS, main

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("topic", sorted(DOC_TOPICS))
def test_packaged_doc_is_byte_identical_to_its_canonical_source(topic):
    packaged, canonical = DOC_TOPICS[topic]
    assert (ROOT / "orchestrator" / "docs" / packaged).read_bytes() == \
        (ROOT / canonical).read_bytes(), (
        f"orchestrator/docs/{packaged} drifted from {canonical}: copy it over")


def _nous(argv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["nous", *argv])
    try:
        main()
    except SystemExit as exc:
        assert exc.code in (0, None)


def test_nous_docs_prints_the_quickstart_by_default(capsys, monkeypatch):
    _nous(["docs"], monkeypatch)
    out = capsys.readouterr().out
    assert out == (ROOT / DOC_TOPICS["quickstart"][1]).read_text()


def test_nous_docs_path_points_at_an_installed_file(capsys, monkeypatch):
    _nous(["docs", "guide", "--path"], monkeypatch)
    assert Path(capsys.readouterr().out.strip()).is_file()
