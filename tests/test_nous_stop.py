"""Behavioral tests for `nous stop` (agent / human campaign halt).

User-requested in the #189 cleanup wave: agents and humans need a clean
way to ask a running campaign to wind down at the next iteration
boundary without sending SIGINT to the parent process.

Contract:
  - ``nous stop <target>`` writes a ``STOP`` sentinel at the work_dir
    root; existing sentinel is left in place (idempotent).
  - The optional ``--reason "..."`` text persists in the sentinel and
    surfaces in the halt error message.
  - The v2 loop honours the sentinel at the next turn boundary
    (tested in tests/v2/).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

STOP_SENTINEL_NAME = "STOP"


# ─── _cmd_stop CLI handler ───────────────────────────────────────────────


class TestCmdStop:
    """Direct invocation of the CLI handler — no subprocess, no live LLM."""

    def _argspace(self, target: str, reason: str | None = None):
        return argparse.Namespace(target=target, reason=reason)

    def test_stop_writes_sentinel_at_work_dir_root(self, tmp_path: Path) -> None:
        from orchestrator.cli import _cmd_stop

        work_dir = tmp_path / ".nous" / "exp1"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps({
            "phase": "DESIGN", "iteration": 1, "run_id": "exp1",
        }))

        _cmd_stop(self._argspace(str(work_dir)))
        assert (work_dir / STOP_SENTINEL_NAME).exists()

    def test_stop_records_reason(self, tmp_path: Path) -> None:
        from orchestrator.cli import _cmd_stop

        work_dir = tmp_path / ".nous" / "exp1"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps({
            "phase": "DESIGN", "iteration": 1, "run_id": "exp1",
        }))

        _cmd_stop(self._argspace(str(work_dir), reason="user requested halt"))
        text = (work_dir / STOP_SENTINEL_NAME).read_text().strip()
        assert text == "user requested halt"

    def test_stop_is_idempotent(self, tmp_path: Path, capsys) -> None:
        """Second invocation when sentinel already exists prints a
        message and exits 0 instead of overwriting."""
        from orchestrator.cli import _cmd_stop

        work_dir = tmp_path / ".nous" / "exp1"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps({
            "phase": "DESIGN", "iteration": 1, "run_id": "exp1",
        }))
        (work_dir / STOP_SENTINEL_NAME).write_text("first reason\n")

        with pytest.raises(SystemExit) as excinfo:
            _cmd_stop(self._argspace(str(work_dir), reason="second reason"))
        # Idempotent: returns success exit code.
        assert excinfo.value.code in (0, None)
        # First reason wins.
        assert (work_dir / STOP_SENTINEL_NAME).read_text().strip() == "first reason"
        captured = capsys.readouterr()
        assert "already present" in captured.out

    def test_stop_message_announces_phase_boundary(
        self, tmp_path: Path, capsys,
    ) -> None:
        """#208: the CLI's user-facing message must say 'phase boundary',
        not 'iteration boundary' — STOP is honoured at every phase
        transition post-#198, not only at iteration boundaries."""
        from orchestrator.cli import _cmd_stop

        work_dir = tmp_path / ".nous" / "exp1"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps({
            "phase": "DESIGN", "iteration": 1, "run_id": "exp1",
        }))

        _cmd_stop(self._argspace(str(work_dir)))
        captured = capsys.readouterr()
        assert "phase boundary" in captured.out, (
            f"#208: stop message should announce phase boundary; got: {captured.out!r}"
        )
        # The legacy 'iteration boundary' phrasing should be gone.
        assert "iteration boundary" not in captured.out, (
            f"#208: legacy 'iteration boundary' phrasing leaked: {captured.out!r}"
        )

    def test_stop_errors_on_missing_work_dir(
        self, tmp_path: Path, capsys,
    ) -> None:
        from orchestrator.cli import _cmd_stop
        with pytest.raises(SystemExit):
            _cmd_stop(self._argspace(str(tmp_path / "ghost")))


# ─── Documentation parity (#198) ─────────────────────────────────────────
#
# The behavior of `nous stop` is honoured at every phase boundary
# post-#198. User-facing
# documentation must reflect that — the legacy "iteration boundary"
# wording lags the post-#198 reality and misleads operators.


class TestStopDocumentationReflectsPhaseAwareness:
    """#198: every user-facing surface must describe `nous stop` as
    halting at a phase boundary, not an iteration boundary."""

    def test_argparse_help_says_phase_boundary(
        self, monkeypatch, capsys,
    ) -> None:
        """`nous stop --help` (the argparse text) must announce phase
        boundary, not iteration boundary."""
        import sys
        from orchestrator.cli import main

        monkeypatch.setattr(sys, "argv", ["nous", "stop", "--help"])
        with pytest.raises(SystemExit):
            main()  # --help triggers SystemExit(0)
        out = capsys.readouterr().out
        # argparse line-wraps long descriptions, so normalize whitespace
        # before substring-matching.
        normalized = " ".join(out.split())
        assert "phase boundary" in normalized, (
            f"#198: nous stop help must say 'phase boundary'; got: "
            f"{normalized!r}"
        )
        assert "iteration boundary" not in normalized, (
            f"#198: legacy 'iteration boundary' phrasing leaked into "
            f"argparse help: {normalized!r}"
        )

    def test_schema_doc_render_says_phase_boundary(self, capsys) -> None:
        """`nous schema` markdown render references `nous stop` in its
        See-also section. That string must announce phase boundary too."""
        from orchestrator.cli import _cmd_schema

        ns = argparse.Namespace(artifact="campaign", format="md")
        _cmd_schema(ns)
        out = capsys.readouterr().out
        stop_lines = [ln for ln in out.splitlines() if "`nous stop" in ln]
        assert stop_lines, (
            "schema doc render should describe `nous stop` in See-also"
        )
        joined = "\n".join(stop_lines)
        assert "phase boundary" in joined, (
            f"#198: schema doc must say 'phase boundary'; got: {joined!r}"
        )
        assert "iteration boundary" not in joined, (
            f"#198: legacy 'iteration boundary' leaked into schema doc: "
            f"{joined!r}"
        )
