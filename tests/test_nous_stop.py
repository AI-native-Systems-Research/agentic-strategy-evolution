"""Behavioral tests for `nous stop` (agent / human campaign halt).

User-requested in the #189 cleanup wave: agents and humans need a clean
way to ask a running campaign to wind down at the next iteration
boundary without sending SIGINT to the parent process.

Contract:
  - ``nous stop <target>`` writes a ``STOP`` sentinel at the work_dir
    root; existing sentinel is left in place (idempotent).
  - The optional ``--reason "..."`` text persists in the sentinel and
    surfaces in the halt error message.
  - ``check_stop_requested(work_dir)`` returns the sentinel path when
    present and None otherwise.
  - The campaign loop honours the sentinel before each iteration and
    raises ``CampaignStopped``.
  - Mid-iteration interruption is still SIGINT's job — ``nous stop`` is
    a between-phases handle, not a kill switch. The tests document this
    by asserting that ``check_stop_requested`` is consulted explicitly
    and the sentinel survives until cleared.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest


# ─── check_stop_requested + sentinel basics ──────────────────────────────


class TestStopSentinelHelpers:
    def test_no_sentinel_returns_none(self, tmp_path: Path) -> None:
        from orchestrator.iteration import check_stop_requested
        assert check_stop_requested(tmp_path) is None

    def test_sentinel_returns_path_when_present(self, tmp_path: Path) -> None:
        from orchestrator.iteration import (
            STOP_SENTINEL_NAME, check_stop_requested,
        )
        (tmp_path / STOP_SENTINEL_NAME).write_text("")
        result = check_stop_requested(tmp_path)
        assert result is not None
        assert result.name == STOP_SENTINEL_NAME

    def test_raise_if_stopped_no_sentinel_is_noop(self, tmp_path: Path) -> None:
        from orchestrator.iteration import _raise_if_stopped
        _raise_if_stopped(tmp_path, where="before iteration 1")

    def test_raise_if_stopped_with_sentinel_raises(self, tmp_path: Path) -> None:
        from orchestrator.iteration import (
            CampaignStopped, STOP_SENTINEL_NAME, _raise_if_stopped,
        )
        (tmp_path / STOP_SENTINEL_NAME).write_text("")
        with pytest.raises(CampaignStopped, match="before iteration 2"):
            _raise_if_stopped(tmp_path, where="before iteration 2")

    def test_reason_text_surfaces_in_error(self, tmp_path: Path) -> None:
        from orchestrator.iteration import (
            CampaignStopped, STOP_SENTINEL_NAME, _raise_if_stopped,
        )
        (tmp_path / STOP_SENTINEL_NAME).write_text(
            "out of budget; stopping early\n"
        )
        with pytest.raises(CampaignStopped) as excinfo:
            _raise_if_stopped(tmp_path, where="before iteration 1")
        assert "out of budget" in str(excinfo.value)


# ─── _cmd_stop CLI handler ───────────────────────────────────────────────


class TestCmdStop:
    """Direct invocation of the CLI handler — no subprocess, no live LLM."""

    def _argspace(self, target: str, reason: str | None = None):
        return argparse.Namespace(target=target, reason=reason)

    def test_stop_writes_sentinel_at_work_dir_root(self, tmp_path: Path) -> None:
        from orchestrator.cli import _cmd_stop
        from orchestrator.iteration import STOP_SENTINEL_NAME

        work_dir = tmp_path / ".nous" / "exp1"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps({
            "phase": "DESIGN", "iteration": 1, "run_id": "exp1",
        }))

        _cmd_stop(self._argspace(str(work_dir)))
        assert (work_dir / STOP_SENTINEL_NAME).exists()

    def test_stop_records_reason(self, tmp_path: Path) -> None:
        from orchestrator.cli import _cmd_stop
        from orchestrator.iteration import STOP_SENTINEL_NAME

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
        from orchestrator.iteration import STOP_SENTINEL_NAME

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
        from orchestrator.iteration import STOP_SENTINEL_NAME

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


# ─── Integration: campaign loop honours sentinel ────────────────────────


class TestCampaignLoopHonoursSentinel:
    """A campaign with a STOP sentinel pre-staged should bail at the
    first iteration boundary without invoking run_iteration. We patch
    run_iteration to a sentry that fails the test if reached, then
    confirm the campaign exits via the stopped_by_user path.
    """

    def test_pre_staged_sentinel_skips_run_iteration(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        from orchestrator import campaign as campaign_mod
        from orchestrator.iteration import STOP_SENTINEL_NAME

        repo = tmp_path / "repo"
        repo.mkdir()
        work_dir = repo / ".nous" / "exp1"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps({
            "phase": "INIT", "iteration": 1, "run_id": "exp1",
            "family": "test", "timestamp": "2026-01-01T00:00:00Z",
        }))
        (work_dir / "ledger.json").write_text(json.dumps({"iterations": []}))
        (work_dir / "principles.json").write_text(
            json.dumps({"principles": []}),
        )
        # Pre-stage the sentinel with a reason.
        (work_dir / STOP_SENTINEL_NAME).write_text("preempted\n")

        campaign_dict = {
            "research_question": "q",
            "run_id": "exp1",
            "max_iterations": 3,
            "target_system": {
                "name": "T", "description": "d", "repo_path": str(repo),
            },
            "prompts": {"methodology_layer": "p"},
        }

        called = {"n": 0}

        def _should_not_be_called(*a, **kw):
            called["n"] += 1
            from orchestrator.iteration import IterationOutcome
            return IterationOutcome.COMPLETED

        monkeypatch.setattr(
            campaign_mod, "run_iteration", _should_not_be_called,
        )
        # Also stub out the post-loop side effects we don't need.
        monkeypatch.setattr(campaign_mod, "_generate_report", lambda *a, **k: None)
        monkeypatch.setattr(
            campaign_mod, "_emit_meta_findings", lambda *a, **k: None,
        )
        monkeypatch.setattr(
            campaign_mod, "_write_metrics_summary", lambda *a, **k: None,
        )

        campaign_mod.run_campaign(
            campaign_dict, work_dir, max_iterations=3, agent="inline",
        )
        assert called["n"] == 0, "run_iteration must not be called once stop is requested"

        ledger = json.loads((work_dir / "ledger.json").read_text())
        rows = ledger.get("iterations", [])
        assert any(
            "stopped_by_user" in (r.get("error") or "")
            for r in rows
        ), f"ledger should record stopped_by_user; got {rows}"


# ─── Phase-boundary stop checks (#198) ───────────────────────────────────


def _seed_init_state(work_dir: Path) -> None:
    """Write a minimal INIT-phase state.json so Engine() can initialize."""
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "state.json").write_text(json.dumps({
        "phase": "INIT",
        "iteration": 0,
        "run_id": "test",
        "family": "test",
        "timestamp": "2026-01-01T00:00:00Z",
    }))


class TestEnterPhaseHonorsSentinel:
    """#198: _enter_phase honours the STOP sentinel before transitioning,
    so an in-flight iteration halts at the next phase boundary instead of
    waiting for the next iteration loop."""

    def test_enter_phase_with_no_sentinel_proceeds(self, tmp_path: Path) -> None:
        from orchestrator.engine import Engine
        from orchestrator.iteration import _enter_phase

        _seed_init_state(tmp_path)
        engine = Engine(tmp_path)
        # Fresh state: phase=INIT. Should transition to DESIGN cleanly.
        result = _enter_phase(engine, "DESIGN", tmp_path)
        assert result is True
        assert engine.phase == "DESIGN"

    def test_enter_phase_with_sentinel_raises_before_transition(
        self, tmp_path: Path,
    ) -> None:
        """Mid-iter scenario: the operator wrote a STOP sentinel while
        DESIGN was running. As we try to enter HUMAN_DESIGN_GATE the next
        phase boundary should honour the sentinel and raise CampaignStopped
        without advancing the engine."""
        from orchestrator.engine import Engine
        from orchestrator.iteration import (
            CampaignStopped, STOP_SENTINEL_NAME, _enter_phase,
        )

        _seed_init_state(tmp_path)
        engine = Engine(tmp_path)
        engine.transition("DESIGN")
        (tmp_path / STOP_SENTINEL_NAME).write_text("user halt mid-design\n")

        with pytest.raises(CampaignStopped, match="HUMAN_DESIGN_GATE"):
            _enter_phase(engine, "HUMAN_DESIGN_GATE", tmp_path)
        # Engine state preserved at the pre-transition phase.
        assert engine.phase == "DESIGN"

    def test_enter_phase_skip_path_does_not_check_sentinel(
        self, tmp_path: Path,
    ) -> None:
        """When _enter_phase is asked for a phase already passed (skip-past
        on resume), no transition happens and we should NOT honour the
        sentinel — that scenario is for the iter-loop's own stop check."""
        from orchestrator.engine import Engine
        from orchestrator.iteration import (
            STOP_SENTINEL_NAME, _enter_phase,
        )

        _seed_init_state(tmp_path)
        engine = Engine(tmp_path)
        for p in ["DESIGN", "HUMAN_DESIGN_GATE", "EXECUTE_ANALYZE",
                  "HUMAN_FINDINGS_GATE", "DONE"]:
            engine.transition(p)
        (tmp_path / STOP_SENTINEL_NAME).write_text("late stop\n")

        # Asking for DESIGN now (we're past it) returns False without raising.
        result = _enter_phase(engine, "DESIGN", tmp_path)
        assert result is False

    def test_enter_phase_requires_work_dir(self, tmp_path: Path) -> None:
        """``work_dir`` is required (post-PR-#204 review tightening).

        A default of ``None`` would silently skip the stop-sentinel check
        for any caller that forgot to pass it. Failing fast at TypeError
        is the right shape — all in-repo callers pass it.
        """
        from orchestrator.engine import Engine
        from orchestrator.iteration import _enter_phase

        _seed_init_state(tmp_path)
        engine = Engine(tmp_path)
        with pytest.raises(TypeError):
            _enter_phase(engine, "DESIGN")  # missing work_dir → TypeError


# ─── End-to-end: run_iteration honours mid-iteration sentinel (#198) ─────


class TestRunIterationHaltsAtPhaseBoundary:
    """Pin the call-site wiring (#198): run_iteration's four _enter_phase
    calls each pass work_dir, so a STOP sentinel written mid-iteration
    halts at the next phase boundary instead of waiting for the next
    iteration. A regression that drops work_dir from any of the four
    call sites would not be caught by the _enter_phase unit tests
    alone.
    """

    def test_sentinel_after_design_halts_before_design_gate(
        self, tmp_path, monkeypatch,
    ) -> None:
        """Stage state at DESIGN, write sentinel, run_iteration must
        raise CampaignStopped naming the next phase boundary."""
        from orchestrator.inline_dispatch import InlineDispatcher
        from orchestrator.iteration import (
            CampaignStopped,
            STOP_SENTINEL_NAME,
            run_iteration,
        )

        # Make InlineDispatcher.dispatch a no-op so DESIGN doesn't
        # actually try to do anything; the test focuses on the
        # phase-boundary sentinel honor on transition out of DESIGN.
        monkeypatch.setattr(
            InlineDispatcher, "dispatch", lambda self, *a, **kw: None,
        )

        repo = tmp_path / "repo"
        repo.mkdir()
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        iter_dir = work_dir / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        # Pre-stage all DESIGN artifacts so DESIGN's own "incomplete"
        # check passes and we proceed toward HUMAN_DESIGN_GATE.
        (iter_dir / "problem.md").write_text("p")
        (iter_dir / "bundle.yaml").write_text(
            "metadata:\n  iteration: 1\n  family: t\n  research_question: q\n"
            "arms:\n  - type: h-main\n"
            "    prediction: p\n    mechanism: m\n    diagnostic: d\n"
        )
        (iter_dir / "handoff_snapshot.md").write_text("h")
        (work_dir / "state.json").write_text(json.dumps({
            "phase": "DESIGN", "iteration": 1, "run_id": "exp",
            "family": "test", "timestamp": "2026-01-01T00:00:00Z",
        }))
        (work_dir / "ledger.json").write_text(json.dumps({"iterations": []}))
        (work_dir / "principles.json").write_text(
            json.dumps({"principles": []}),
        )
        # Sentinel pre-staged: as soon as run_iteration tries to
        # transition out of DESIGN into HUMAN_DESIGN_GATE, the
        # _enter_phase check at that call site must honour it.
        (work_dir / STOP_SENTINEL_NAME).write_text("test halt\n")

        campaign = {
            "research_question": "q?",
            "run_id": "exp",
            "max_iterations": 1,
            "target_system": {"name": "T", "description": "d"},
            "prompts": {"methodology_layer": "p"},
        }

        with pytest.raises(CampaignStopped, match="HUMAN_DESIGN_GATE"):
            run_iteration(
                campaign, work_dir, iteration=1, agent="inline",
                auto_approve=True,
            )
