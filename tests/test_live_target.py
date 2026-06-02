"""Tests for live-target mode — campaigns where the executor probes a running
target system instead of evolving code in a git worktree.
"""
import contextlib
import json
import shutil
import warnings
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orchestrator.dispatch import StubDispatcher
from orchestrator.engine import Engine
from orchestrator.iteration import IterationOutcome, run_iteration
from orchestrator.llm_dispatch import (
    LLMDispatcher,
    _LIVE_TARGET_DESIGN_CONSTRAINT,
    _LIVE_TARGET_EXECUTION_ENV,
    _WORKTREE_DESIGN_CONSTRAINT,
    _WORKTREE_EXECUTION_ENV,
)


class _CLIStub(StubDispatcher):
    """StubDispatcher with the CLIDispatcher surface area iteration.py
    needs (override_cwd context manager, model/max_turns attrs).
    """

    def __init__(self, work_dir, **_kw):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            super().__init__(work_dir)
        self.model = "stub"
        self.max_turns = 1

    @contextlib.contextmanager
    def override_cwd(self, _cwd):
        yield


TEMPLATES_DIR = (
    Path(__file__).resolve().parent.parent / "orchestrator" / "templates"
)


def _campaign(live_target: bool, repo_path: Path | None = None) -> dict:
    target = {
        "name": "TestSystem",
        "description": "A live target with no code to evolve.",
        "observable_metrics": ["latency_ms"],
        "controllable_knobs": ["config"],
    }
    if live_target:
        target["live_target"] = True
    if repo_path is not None:
        target["repo_path"] = str(repo_path)
    return {
        "research_question": "Does the live target behave?",
        "target_system": target,
        "prompts": {
            "methodology_layer": "prompts/methodology",
            "domain_adapter_layer": None,
        },
    }


# ---------------------------------------------------------------------------
# _validate_campaign
# ---------------------------------------------------------------------------


class TestCampaignValidation:
    def test_live_target_true_accepted(self, tmp_path):
        campaign = _campaign(live_target=True)
        # Must not raise.
        LLMDispatcher._validate_campaign(campaign)

    def test_live_target_false_accepted(self, tmp_path):
        campaign = _campaign(live_target=False)
        LLMDispatcher._validate_campaign(campaign)

    def test_live_target_omitted_accepted(self, tmp_path):
        campaign = _campaign(live_target=False)
        assert "live_target" not in campaign["target_system"]
        LLMDispatcher._validate_campaign(campaign)

    def test_live_target_non_bool_rejected(self):
        campaign = _campaign(live_target=False)
        campaign["target_system"]["live_target"] = "yes"
        with pytest.raises(ValueError, match="live_target"):
            LLMDispatcher._validate_campaign(campaign)


# ---------------------------------------------------------------------------
# _build_context — prompt fragment selection
# ---------------------------------------------------------------------------


class TestPromptFragmentSelection:
    """The execution_environment and worktree_constraint placeholders swap
    based on target_system.live_target. The prompt loader will substitute
    them into the design and execute_analyze templates.
    """

    def _dispatcher(self, tmp_path, live_target: bool) -> LLMDispatcher:
        # Seed the work_dir with the run_id only — no API key needed because
        # _build_context never calls the LLM.
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "runs" / "iter-1").mkdir(parents=True)
        return LLMDispatcher(
            work_dir=work_dir,
            campaign=_campaign(live_target=live_target),
            completion_fn=lambda **kw: None,
        )

    def test_default_is_worktree(self, tmp_path):
        d = self._dispatcher(tmp_path, live_target=False)
        ctx = d._build_context("planner", "design", iteration=1, perspective=None)
        assert ctx["execution_environment"] == _WORKTREE_EXECUTION_ENV
        assert ctx["worktree_constraint"] == _WORKTREE_DESIGN_CONSTRAINT

    def test_live_target_swaps_text(self, tmp_path):
        d = self._dispatcher(tmp_path, live_target=True)
        ctx = d._build_context("planner", "design", iteration=1, perspective=None)
        # _LIVE_TARGET_EXECUTION_ENV embeds {{iter_dir}}, so context-level
        # equality holds (substitution happens later, in the loader).
        assert ctx["execution_environment"] == _LIVE_TARGET_EXECUTION_ENV
        assert ctx["worktree_constraint"] == _LIVE_TARGET_DESIGN_CONSTRAINT

    def test_design_template_renders_with_live_target_constraint(self, tmp_path):
        """End-to-end: the real design.md picks up the live-target constraint
        and drops the worktree variant.
        """
        d = self._dispatcher(tmp_path, live_target=True)
        ctx = d._build_context("planner", "design", iteration=1, perspective=None)
        rendered = d.loader.load("design", ctx)
        assert _WORKTREE_DESIGN_CONSTRAINT not in rendered
        assert _LIVE_TARGET_DESIGN_CONSTRAINT in rendered

    def test_execute_analyze_template_renders_with_live_target_env(self, tmp_path):
        """End-to-end: execute_analyze.md picks up the live-target execution
        environment. The {{iter_dir}} embedded in the live-target text must
        be substituted by the loader's sequential pass.
        """
        d = self._dispatcher(tmp_path, live_target=True)
        # _build_context for execute-analyze needs a bundle.yaml and handoff.md
        bundle_path = d.work_dir / "runs" / "iter-1" / "bundle.yaml"
        bundle_path.write_text("metadata:\n  iteration: 1\n")
        (d.work_dir / "handoff.md").write_text("(stub handoff)")
        (d.work_dir / "runs" / "iter-1" / "problem.md").write_text("(stub problem)")
        ctx = d._build_context(
            "executor", "execute-analyze", iteration=1, perspective=None,
        )
        rendered = d.loader.load("execute_analyze", ctx)
        assert _WORKTREE_EXECUTION_ENV not in rendered
        # The live-target fragment is rendered AFTER {{iter_dir}} substitution,
        # so we assert against the post-substitution version.
        iter_dir = str((d.work_dir / "runs" / "iter-1").resolve())
        assert _LIVE_TARGET_EXECUTION_ENV.replace("{{iter_dir}}", iter_dir) in rendered
        assert "{{iter_dir}}" not in rendered  # no leftover placeholders


# ---------------------------------------------------------------------------
# Iteration loop: live-target mode skips worktree creation
# ---------------------------------------------------------------------------


def _setup_iteration(
    tmp_path: Path,
    monkeypatch,
    *,
    repo_path: Path,
    live_target: bool,
):
    """Prepare a work_dir + campaign for an iteration test. Stubs the LLM and
    CLI dispatchers and the human gate so run_iteration completes without an
    API key. Use `live_target=True` to test the live-target path,
    `live_target=False` to test the worktree path.
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    for t in ("state.json", "ledger.json", "principles.json"):
        shutil.copy(TEMPLATES_DIR / t, work_dir / t)
    state = json.loads((work_dir / "state.json").read_text())
    state["run_id"] = "test"
    (work_dir / "state.json").write_text(json.dumps(state, indent=2))

    campaign = _campaign(live_target=live_target, repo_path=repo_path)

    import orchestrator.iteration as ri

    def stub_factory(work_dir, campaign, model=None):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return StubDispatcher(work_dir)

    monkeypatch.setattr(ri, "LLMDispatcher", stub_factory)
    # When repo_path is set, iteration.py would normally instantiate a
    # CLIDispatcher. Replace it with a stub that exposes the same surface
    # iteration.py touches (override_cwd, model, max_turns).
    monkeypatch.setattr(
        "orchestrator.cli_dispatch.CLIDispatcher",
        lambda **kw: _CLIStub(kw["work_dir"]),
    )
    monkeypatch.setattr(
        ri, "HumanGate",
        lambda: MagicMock(prompt=MagicMock(return_value=("approve", None))),
    )
    return work_dir, campaign


def _setup_live_target_iteration(tmp_path: Path, monkeypatch, *, repo_path: Path):
    """Convenience wrapper for the live-target path."""
    return _setup_iteration(
        tmp_path, monkeypatch, repo_path=repo_path, live_target=True,
    )


class TestLiveTargetIterationFlow:
    def test_runs_without_git_repo(self, tmp_path, monkeypatch):
        """A non-git repo_path + live_target=true must not raise
        FileNotFoundError('Not a git repository') and must complete the
        iteration. This is the regression for the magic.yaml campaign.
        """
        repo = tmp_path / "live-target"
        repo.mkdir()  # NOT a git repo — no .git/ here.

        work_dir, campaign = _setup_live_target_iteration(
            tmp_path, monkeypatch, repo_path=repo,
        )
        result = run_iteration(campaign, work_dir, iteration=1)
        assert result == IterationOutcome.COMPLETED
        assert Engine(work_dir).phase == "DONE"

    def test_no_experiment_worktree_created(self, tmp_path, monkeypatch):
        repo = tmp_path / "live-target"
        repo.mkdir()
        work_dir, campaign = _setup_live_target_iteration(
            tmp_path, monkeypatch, repo_path=repo,
        )

        # Replace create_experiment_worktree with a sentinel that fails the
        # test if it is ever called. The iteration import is local, so patch
        # at the source module.
        called = {"n": 0}

        def must_not_call(*a, **kw):
            called["n"] += 1
            raise AssertionError(
                "create_experiment_worktree must not be called in "
                "live-target mode"
            )

        monkeypatch.setattr(
            "orchestrator.worktree.create_experiment_worktree", must_not_call,
        )

        run_iteration(campaign, work_dir, iteration=1)

        assert called["n"] == 0
        # No .experiment_id file should be written in live-target mode.
        assert not (work_dir / "runs" / "iter-1" / ".experiment_id").exists()
        # No .nous-experiments/ directory should appear in the target.
        assert not (repo / ".nous-experiments").exists()


class TestWorktreeIterationFlow:
    """Regression: with live_target=False (or omitted), repo_path must
    still trigger create_experiment_worktree. Without this test, inverting
    the gate at iteration.py would only break live-target tests.
    """

    def test_worktree_created_when_not_live_target(self, tmp_path, monkeypatch):
        repo = tmp_path / "code-target"
        repo.mkdir()
        work_dir, campaign = _setup_iteration(
            tmp_path, monkeypatch, repo_path=repo, live_target=False,
        )

        create_calls: list[tuple] = []
        remove_calls: list[tuple] = []

        def fake_create(repo_path, iteration):
            create_calls.append((Path(repo_path), iteration))
            experiment_dir = tmp_path / "fake-worktree"
            experiment_dir.mkdir(exist_ok=True)
            return experiment_dir, "fake-experiment-id"

        def fake_remove(repo_path, experiment_id):
            remove_calls.append((Path(repo_path), experiment_id))

        monkeypatch.setattr(
            "orchestrator.worktree.create_experiment_worktree", fake_create,
        )
        monkeypatch.setattr(
            "orchestrator.worktree.remove_experiment_worktree", fake_remove,
        )

        result = run_iteration(campaign, work_dir, iteration=1)

        assert result == IterationOutcome.COMPLETED
        assert create_calls == [(repo, 1)]
        assert remove_calls == [(repo, "fake-experiment-id")]
        # .experiment_id file should be written in worktree mode.
        assert (
            work_dir / "runs" / "iter-1" / ".experiment_id"
        ).read_text() == "fake-experiment-id"
