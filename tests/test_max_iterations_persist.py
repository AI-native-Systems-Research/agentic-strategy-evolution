"""Behavioral tests for max_iterations persistence across resume (#197).

Pre-#197 a kill + ``nous resume`` without --max-iterations silently
defaulted to 10, so a campaign launched with --max-iterations 1 would
quietly extend to 10 iterations on resume — major operational footgun.
After #197 the effective max_iterations is persisted into state.json
on first run and read back on resume when no CLI flag is supplied.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _state_with(max_iter: int | None = None, **extra) -> dict:
    state = {
        "phase": "INIT",
        "iteration": 0,
        "run_id": "demo",
        "family": "test",
        "timestamp": "2026-01-01T00:00:00Z",
    }
    if max_iter is not None:
        state["max_iterations"] = max_iter
    state.update(extra)
    return state


class TestPersistMaxIterations:
    def test_persists_value_when_state_exists(self, tmp_path: Path) -> None:
        from orchestrator.campaign import _persist_max_iterations
        (tmp_path / "state.json").write_text(json.dumps(_state_with()))
        _persist_max_iterations(tmp_path, 7)
        state = json.loads((tmp_path / "state.json").read_text())
        assert state["max_iterations"] == 7

    def test_silently_skips_when_state_missing(self, tmp_path: Path) -> None:
        """Best-effort: no state.json means no-op (run_campaign sets up
        state via setup_work_dir before calling this in production)."""
        from orchestrator.campaign import _persist_max_iterations
        _persist_max_iterations(tmp_path, 7)  # must not raise
        assert not (tmp_path / "state.json").exists()

    def test_idempotent_when_value_unchanged(self, tmp_path: Path) -> None:
        from orchestrator.campaign import _persist_max_iterations
        (tmp_path / "state.json").write_text(json.dumps(_state_with(max_iter=5)))
        before = (tmp_path / "state.json").stat().st_mtime_ns
        _persist_max_iterations(tmp_path, 5)
        after = (tmp_path / "state.json").stat().st_mtime_ns
        assert before == after, "no-op rewrite should not touch the file"


class TestReadPersistedMaxIterations:
    def test_returns_value_when_present(self, tmp_path: Path) -> None:
        from orchestrator.campaign import read_persisted_max_iterations
        (tmp_path / "state.json").write_text(json.dumps(_state_with(max_iter=3)))
        assert read_persisted_max_iterations(tmp_path) == 3

    def test_returns_none_when_field_absent(self, tmp_path: Path) -> None:
        from orchestrator.campaign import read_persisted_max_iterations
        (tmp_path / "state.json").write_text(json.dumps(_state_with()))
        assert read_persisted_max_iterations(tmp_path) is None

    def test_returns_none_when_state_missing(self, tmp_path: Path) -> None:
        from orchestrator.campaign import read_persisted_max_iterations
        assert read_persisted_max_iterations(tmp_path) is None

    def test_returns_none_when_state_corrupt(self, tmp_path: Path) -> None:
        from orchestrator.campaign import read_persisted_max_iterations
        (tmp_path / "state.json").write_text("not valid json{")
        assert read_persisted_max_iterations(tmp_path) is None

    def test_returns_none_for_invalid_value(self, tmp_path: Path) -> None:
        """Defensive: max_iterations < 1 or non-int doesn't propagate as
        a usable value."""
        from orchestrator.campaign import read_persisted_max_iterations
        for bad in (0, -3, "ten", None, [3]):
            (tmp_path / "state.json").write_text(
                json.dumps({**_state_with(), "max_iterations": bad})
            )
            assert read_persisted_max_iterations(tmp_path) is None, bad
