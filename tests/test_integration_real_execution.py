"""Integration tests for iteration flow, resume logic, and outcomes."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Resume logic tests
# ---------------------------------------------------------------------------

from run_iteration import (
    _enter_phase, _PHASE_ORDER, _PHASE_INDEX,
    run_iteration, IterationOutcome, setup_work_dir,
)
from orchestrator.engine import Engine, Phase


class TestEnterPhase:
    """Tests for _enter_phase resume logic."""

    def test_skip_past_phase(self, tmp_path):
        """When engine is past a phase, _enter_phase returns False (skip)."""
        state = {
            "phase": "EXECUTE_ANALYZE", "iteration": 0,
            "run_id": "test", "family": None, "timestamp": "t",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        engine = Engine(tmp_path)

        assert _enter_phase(engine, "DESIGN") is False
        assert _enter_phase(engine, "HUMAN_DESIGN_GATE") is False
        assert engine.phase == "EXECUTE_ANALYZE"  # unchanged

    def test_redo_current_phase(self, tmp_path):
        """When engine is at a phase, _enter_phase returns True without transition."""
        state = {
            "phase": "EXECUTE_ANALYZE", "iteration": 0,
            "run_id": "test", "family": None, "timestamp": "t",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        engine = Engine(tmp_path)

        assert _enter_phase(engine, "EXECUTE_ANALYZE") is True
        assert engine.phase == "EXECUTE_ANALYZE"  # no transition happened

    def test_advance_to_next_phase(self, tmp_path):
        """When engine is before a phase, _enter_phase transitions and returns True."""
        state = {
            "phase": "INIT", "iteration": 0,
            "run_id": "test", "family": None, "timestamp": "t",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        engine = Engine(tmp_path)

        assert _enter_phase(engine, "DESIGN") is True
        assert engine.phase == "DESIGN"

    def test_done_skips_everything(self, tmp_path):
        """When engine is DONE, all phases are skipped."""
        state = {
            "phase": "DONE", "iteration": 0,
            "run_id": "test", "family": None, "timestamp": "t",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        engine = Engine(tmp_path)

        for phase in _PHASE_ORDER:
            assert _enter_phase(engine, phase) is (phase == "DONE")

    def test_phase_order_matches_engine_phases(self):
        """_PHASE_ORDER must contain exactly the same phases as the engine."""
        engine_phases = {p.value for p in Phase}
        order_phases = set(_PHASE_ORDER)
        assert engine_phases == order_phases, (
            f"Mismatch: engine has {engine_phases - order_phases}, "
            f"_PHASE_ORDER has {order_phases - engine_phases}"
        )

    def test_resume_from_validate(self, tmp_path):
        """Resuming at VALIDATE skips execution phases and earlier."""
        state = {
            "phase": "VALIDATE", "iteration": 0,
            "run_id": "test", "family": None, "timestamp": "t",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        engine = Engine(tmp_path)

        assert _enter_phase(engine, "EXECUTE_ANALYZE") is False
        assert _enter_phase(engine, "VALIDATE") is True
        assert engine.phase == "VALIDATE"
        # Can advance to next
        assert _enter_phase(engine, "HUMAN_FINDINGS_GATE") is True
        assert engine.phase == "HUMAN_FINDINGS_GATE"


# ---------------------------------------------------------------------------
# IterationOutcome tests
# ---------------------------------------------------------------------------

from orchestrator.dispatch import StubDispatcher
import warnings


def _setup_stub_iteration(tmp_path, monkeypatch):
    """Prepare a work_dir with stub dispatcher for testing run_iteration outcomes."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    # Copy templates
    import shutil
    templates_dir = Path(__file__).resolve().parent.parent / "templates"
    for t in ["state.json", "ledger.json", "principles.json"]:
        shutil.copy(templates_dir / t, work_dir / t)
    state = json.loads((work_dir / "state.json").read_text())
    state["run_id"] = "test"
    (work_dir / "state.json").write_text(json.dumps(state, indent=2))

    campaign = {
        "research_question": "Test question?",
        "target_system": {
            "name": "TestSystem",
            "description": "Test system.",
            "observable_metrics": ["latency_ms"],
            "controllable_knobs": ["config"],
        },
        "prompts": {
            "methodology_layer": "prompts/methodology",
            "domain_adapter_layer": None,
        },
    }

    # Monkeypatch LLMDispatcher -> StubDispatcher in run_iteration module
    import run_iteration as ri
    def stub_factory(work_dir, campaign, model=None):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return StubDispatcher(work_dir)

    monkeypatch.setattr(ri, "LLMDispatcher", stub_factory)
    return work_dir, campaign


class TestIterationOutcome:
    """Test that run_iteration returns correct IterationOutcome values."""

    def test_returns_completed_by_default(self, tmp_path, monkeypatch):
        work_dir, campaign = _setup_stub_iteration(tmp_path, monkeypatch)
        import run_iteration as ri
        monkeypatch.setattr(ri, "HumanGate", lambda: MagicMock(prompt=MagicMock(return_value=("approve", None))))

        result = run_iteration(campaign, work_dir, iteration=1)

        assert result == IterationOutcome.COMPLETED
        engine = Engine(work_dir)
        assert engine.phase == "DONE"

    def test_returns_continue_when_not_final(self, tmp_path, monkeypatch):
        work_dir, campaign = _setup_stub_iteration(tmp_path, monkeypatch)
        import run_iteration as ri
        monkeypatch.setattr(ri, "HumanGate", lambda: MagicMock(prompt=MagicMock(return_value=("approve", None))))

        result = run_iteration(campaign, work_dir, iteration=1, final=False)

        assert result == IterationOutcome.CONTINUE
        engine = Engine(work_dir)
        assert engine.phase == "HUMAN_FINDINGS_GATE"

    def test_returns_aborted_on_design_gate_abort(self, tmp_path, monkeypatch):
        work_dir, campaign = _setup_stub_iteration(tmp_path, monkeypatch)
        import run_iteration as ri
        monkeypatch.setattr(ri, "HumanGate", lambda: MagicMock(prompt=MagicMock(return_value=("abort", None))))

        result = run_iteration(campaign, work_dir, iteration=1)

        assert result == IterationOutcome.ABORTED

    def test_returns_redesign_on_design_gate_reject(self, tmp_path, monkeypatch):
        work_dir, campaign = _setup_stub_iteration(tmp_path, monkeypatch)
        import run_iteration as ri
        monkeypatch.setattr(ri, "HumanGate", lambda: MagicMock(prompt=MagicMock(return_value=("reject", None))))

        result = run_iteration(campaign, work_dir, iteration=1)

        assert result == IterationOutcome.REDESIGN


class TestExecutePlanResetCmdKwargs:
    """run_iteration.py — the reset_cmd kwarg must be 'git checkout -- .'
    when running in a worktree and None otherwise. The exact string is
    load-bearing: e.g., 'git reset --hard' would also wipe untracked patches/.
    """

    def _capture_execute_plan_kwargs(self, tmp_path, monkeypatch, *, with_repo_path):
        work_dir, campaign = _setup_stub_iteration(tmp_path, monkeypatch)
        import run_iteration as ri
        monkeypatch.setattr(
            ri, "HumanGate",
            lambda: MagicMock(prompt=MagicMock(return_value=("approve", None))),
        )

        # Also patch CLIDispatcher so it doesn't call claude -p
        from orchestrator import cli_dispatch as cli_mod
        import contextlib
        _work_dir = work_dir
        class FakeCLI:
            def __init__(self, **kw):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    self._stub = StubDispatcher(_work_dir)
            def dispatch(self, *a, **kw):
                return self._stub.dispatch(*a, **kw)
            def override_cwd(self, cwd):
                @contextlib.contextmanager
                def noop():
                    yield
                return noop()
        monkeypatch.setattr(cli_mod, "CLIDispatcher", FakeCLI)

        # Optionally point the campaign at a fake repo so run_iteration
        # creates an experiment worktree (which is what triggers reset_cmd).
        if with_repo_path:
            fake_repo = tmp_path / "fake-repo"
            fake_repo.mkdir()
            campaign["target_system"]["repo_path"] = str(fake_repo)

            # Stub out worktree create/remove so we don't need a real git repo.
            from orchestrator import worktree as wt_mod
            fake_exp_dir = tmp_path / "fake-exp-dir"
            fake_exp_dir.mkdir()
            monkeypatch.setattr(
                wt_mod, "create_experiment_worktree",
                lambda repo, iteration: (fake_exp_dir, "exp-id-1"),
            )
            monkeypatch.setattr(
                wt_mod, "remove_experiment_worktree",
                lambda repo, eid: None,
            )

        captured = {}

        def fake_execute_plan(plan, cwd, iter_dir, **kwargs):
            captured.update(kwargs)
            captured["_cwd"] = cwd
            (iter_dir / "execution_results.json").write_text(
                json.dumps({"plan_ref": "x", "setup_results": [], "arms": []})
                + "\n"
            )
            return {"plan_ref": "x", "setup_results": [], "arms": []}

        from orchestrator import executor as exec_mod
        monkeypatch.setattr(exec_mod, "execute_plan", fake_execute_plan)

        run_iteration(campaign, work_dir, iteration=1)
        return captured

    def test_reset_cmd_is_git_checkout_when_in_worktree(self, tmp_path, monkeypatch):
        captured = self._capture_execute_plan_kwargs(
            tmp_path, monkeypatch, with_repo_path=True,
        )
        assert captured["reset_cmd"] == "git checkout -- ."

    def test_reset_cmd_is_none_without_worktree(self, tmp_path, monkeypatch):
        captured = self._capture_execute_plan_kwargs(
            tmp_path, monkeypatch, with_repo_path=False,
        )
        assert captured["reset_cmd"] is None
