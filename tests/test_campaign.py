"""Tests for multi-iteration campaign loop."""
import importlib.metadata as importlib_metadata
import json
import shutil
import subprocess
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import jsonschema
import pytest
import yaml

from orchestrator.dispatch import StubDispatcher
from orchestrator.engine import Engine
from orchestrator.campaign import run_campaign
from orchestrator.iteration import (
    IterationOutcome,
    _capture_runtime_meta,
    _save_human_feedback,
    setup_work_dir,
)

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "templates"


def _load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text())
    return json.loads(path.read_text())


SAMPLE_CAMPAIGN = {
    "research_question": "Does batch size affect latency?",
    "target_system": {
        "name": "TestSystem",
        "description": "A test system.",
        "observable_metrics": ["latency_ms"],
        "controllable_knobs": ["batch_size"],
    },
    "prompts": {
        "methodology_layer": "prompts/methodology",
        "domain_adapter_layer": None,
    },
}


def _setup_work_dir(tmp_path):
    """Create an initialized work directory."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    for t in ["state.json", "ledger.json", "principles.json"]:
        shutil.copy(TEMPLATES_DIR / t, work_dir / t)
    state = json.loads((work_dir / "state.json").read_text())
    state["run_id"] = "test-campaign"
    (work_dir / "state.json").write_text(json.dumps(state, indent=2))
    return work_dir


def _patch_for_stub(monkeypatch):
    """Monkeypatch LLMDispatcher and HumanGate for stub-based testing."""
    import orchestrator.iteration as ri
    import orchestrator.campaign as rc

    def stub_factory(work_dir, campaign, model=None):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return StubDispatcher(work_dir)

    monkeypatch.setattr(ri, "LLMDispatcher", stub_factory)

    # Also patch the LLMDispatcher in run_campaign (used for summarize)
    monkeypatch.setattr(rc, "LLMDispatcher", stub_factory)


def _patch_gates_approve(monkeypatch):
    """All gates auto-approve."""
    import orchestrator.iteration as ri
    import orchestrator.campaign as rc
    gate = MagicMock(prompt=MagicMock(return_value=("approve", None)))
    monkeypatch.setattr(ri, "HumanGate", lambda: gate)
    monkeypatch.setattr(rc, "HumanGate", lambda: gate)
    return gate


class TestTwoIterationHappyPath:
    def test_two_iterations_complete(self, tmp_path, monkeypatch):
        work_dir = _setup_work_dir(tmp_path)
        _patch_for_stub(monkeypatch)
        _patch_gates_approve(monkeypatch)

        run_campaign(SAMPLE_CAMPAIGN, work_dir, max_iterations=2)

        # Engine should be DONE
        engine = Engine(work_dir)
        assert engine.phase == "DONE"

        # Ledger should have baseline + 2 iteration rows
        ledger = json.loads((work_dir / "ledger.json").read_text())
        iter_rows = [r for r in ledger["iterations"] if r["iteration"] > 0]
        assert len(iter_rows) == 2  # both iter-1 and iter-2 (final) get ledger rows
        jsonschema.validate(ledger, _load_schema("ledger.schema.json"))

        # Campaign-level handoff should exist (living document)
        assert (work_dir / "handoff.md").exists()
        # Per-iteration snapshot should also exist for audit
        assert (work_dir / "runs" / "iter-1" / "handoff_snapshot.md").exists()

        # Principles should have accumulated across iterations
        principles = json.loads((work_dir / "principles.json").read_text())
        assert len(principles["principles"]) == 2

        # Both iter dirs should exist
        assert (work_dir / "runs" / "iter-1" / "bundle.yaml").exists()
        assert (work_dir / "runs" / "iter-2" / "bundle.yaml").exists()


class TestStopsOnHumanAbort:
    def test_abort_at_continue_gate(self, tmp_path, monkeypatch):
        work_dir = _setup_work_dir(tmp_path)
        _patch_for_stub(monkeypatch)

        import orchestrator.iteration as ri
        import orchestrator.campaign as rc

        # Iteration gates approve, but continue gate aborts
        iter_gate = MagicMock(prompt=MagicMock(return_value=("approve", None)))
        continue_gate = MagicMock(prompt=MagicMock(return_value=("abort", None)))
        monkeypatch.setattr(ri, "HumanGate", lambda: iter_gate)
        monkeypatch.setattr(rc, "HumanGate", lambda: continue_gate)

        run_campaign(SAMPLE_CAMPAIGN, work_dir, max_iterations=5)

        engine = Engine(work_dir)
        assert engine.phase == "DONE"
        # Only 1 iteration completed
        assert (work_dir / "runs" / "iter-1" / "findings.json").exists()
        assert not (work_dir / "runs" / "iter-2").exists()


class TestStopsAtMaxIterations:
    def test_single_iteration_max(self, tmp_path, monkeypatch):
        work_dir = _setup_work_dir(tmp_path)
        _patch_for_stub(monkeypatch)
        _patch_gates_approve(monkeypatch)

        run_campaign(SAMPLE_CAMPAIGN, work_dir, max_iterations=1)

        engine = Engine(work_dir)
        assert engine.phase == "DONE"
        assert (work_dir / "runs" / "iter-1" / "findings.json").exists()
        # No continue gate should have been invoked (iter 1 is final)
        assert not (work_dir / "runs" / "iter-2").exists()


class TestThreeIterations:
    def test_three_iterations_accumulate_principles(self, tmp_path, monkeypatch):
        work_dir = _setup_work_dir(tmp_path)
        _patch_for_stub(monkeypatch)
        _patch_gates_approve(monkeypatch)

        run_campaign(SAMPLE_CAMPAIGN, work_dir, max_iterations=3)

        engine = Engine(work_dir)
        assert engine.phase == "DONE"

        principles = json.loads((work_dir / "principles.json").read_text())
        assert len(principles["principles"]) == 3

        # Ledger has rows for all 3 iterations (including final)
        ledger = json.loads((work_dir / "ledger.json").read_text())
        iter_rows = [r for r in ledger["iterations"] if r["iteration"] > 0]
        assert len(iter_rows) == 3

        # Campaign-level handoff should exist
        assert (work_dir / "handoff.md").exists()
        # Per-iteration snapshots for audit
        assert (work_dir / "runs" / "iter-1" / "handoff_snapshot.md").exists()
        assert (work_dir / "runs" / "iter-2" / "handoff_snapshot.md").exists()


class TestAbortDuringIteration:
    def test_abort_during_gate(self, tmp_path, monkeypatch):
        """If the human aborts during a gate, campaign stops
        and engine state is preserved for potential resume."""
        work_dir = _setup_work_dir(tmp_path)
        _patch_for_stub(monkeypatch)

        import orchestrator.iteration as ri
        import orchestrator.campaign as rc

        # Iteration gate aborts
        gate = MagicMock(prompt=MagicMock(return_value=("abort", None)))
        monkeypatch.setattr(ri, "HumanGate", lambda: gate)
        monkeypatch.setattr(rc, "HumanGate", lambda: gate)

        run_campaign(SAMPLE_CAMPAIGN, work_dir, max_iterations=5)

        engine = Engine(work_dir)
        # Engine is at the first human gate (HUMAN_DESIGN_GATE) — preserved for resume
        assert engine.phase == "HUMAN_DESIGN_GATE"


class TestResumeCompletedCampaign:
    """_resume_completed_campaign bridges a DONE campaign into a new iteration
    when the caller raises max_iterations."""

    def test_fresh_campaign_returns_iteration_1(self, tmp_path):
        """Phase INIT (fresh) returns 1, state untouched."""
        from orchestrator.campaign import _resume_completed_campaign
        work_dir = _setup_work_dir(tmp_path)
        # Default state.json phase is INIT
        assert _resume_completed_campaign(work_dir, max_iterations=5) == 1
        assert Engine(work_dir).phase == "INIT"  # untouched

    def test_mid_flight_design_resumes_at_correct_iteration(self, tmp_path):
        """Mid-flight DESIGN phase returns engine.iteration without touching state."""
        from orchestrator.campaign import _resume_completed_campaign
        work_dir = _setup_work_dir(tmp_path)
        state = json.loads((work_dir / "state.json").read_text())
        state["phase"] = "DESIGN"
        state["iteration"] = 16
        (work_dir / "state.json").write_text(json.dumps(state))

        result = _resume_completed_campaign(work_dir, max_iterations=20)
        assert result == 16
        engine = Engine(work_dir)
        assert engine.phase == "DESIGN"   # untouched
        assert engine.iteration == 16

    def test_mid_flight_execute_analyze_resumes_at_correct_iteration(self, tmp_path):
        """Mid-flight EXECUTE_ANALYZE phase returns engine.iteration without touching state."""
        from orchestrator.campaign import _resume_completed_campaign
        work_dir = _setup_work_dir(tmp_path)
        state = json.loads((work_dir / "state.json").read_text())
        state["phase"] = "EXECUTE_ANALYZE"
        state["iteration"] = 5
        (work_dir / "state.json").write_text(json.dumps(state))

        result = _resume_completed_campaign(work_dir, max_iterations=10)
        assert result == 5
        engine = Engine(work_dir)
        assert engine.phase == "EXECUTE_ANALYZE"  # untouched
        assert engine.iteration == 5

    def test_mid_flight_iteration_1_boundary(self, tmp_path):
        """Mid-flight at iteration=1 returns 1 (boundary where old and new code agree)."""
        from orchestrator.campaign import _resume_completed_campaign
        work_dir = _setup_work_dir(tmp_path)
        state = json.loads((work_dir / "state.json").read_text())
        state["phase"] = "DESIGN"
        state["iteration"] = 1
        (work_dir / "state.json").write_text(json.dumps(state))

        result = _resume_completed_campaign(work_dir, max_iterations=5)
        assert result == 1
        engine = Engine(work_dir)
        assert engine.phase == "DESIGN"  # untouched

    def test_mid_flight_corrupt_iteration_falls_back_to_1(self, tmp_path, caplog):
        """Mid-flight with iteration < 1 in state.json falls back to 1 with a warning."""
        import logging
        from orchestrator.campaign import _resume_completed_campaign
        work_dir = _setup_work_dir(tmp_path)
        state = json.loads((work_dir / "state.json").read_text())
        state["phase"] = "DESIGN"
        state["iteration"] = 0
        (work_dir / "state.json").write_text(json.dumps(state))

        with caplog.at_level(logging.WARNING):
            result = _resume_completed_campaign(work_dir, max_iterations=5)
        assert result == 1
        assert any("iteration=0" in r.message for r in caplog.records)

    def test_mid_flight_exceeds_max_iterations_warns(self, tmp_path, caplog):
        """Mid-flight iteration > max_iterations logs a warning and returns start."""
        import logging
        from orchestrator.campaign import _resume_completed_campaign
        work_dir = _setup_work_dir(tmp_path)
        state = json.loads((work_dir / "state.json").read_text())
        state["phase"] = "DESIGN"
        state["iteration"] = 16
        (work_dir / "state.json").write_text(json.dumps(state))

        with caplog.at_level(logging.WARNING):
            result = _resume_completed_campaign(work_dir, max_iterations=5)
        assert result == 16
        assert any("max_iterations" in r.message for r in caplog.records)

    def test_done_with_more_iterations_configured_resumes(self, tmp_path):
        """Phase DONE + ledger shows iter 1 + max_iterations=2 -> transition to
        DESIGN and return 2."""
        from orchestrator.campaign import _resume_completed_campaign
        work_dir = _setup_work_dir(tmp_path)

        # Simulate a completed single-iteration campaign.
        state = json.loads((work_dir / "state.json").read_text())
        state["phase"] = "DONE"
        (work_dir / "state.json").write_text(json.dumps(state))
        ledger = {"iterations": [
            {"iteration": 0, "family": "baseline"},
            {"iteration": 1, "family": "x"},
        ]}
        (work_dir / "ledger.json").write_text(json.dumps(ledger))

        assert _resume_completed_campaign(work_dir, max_iterations=2) == 2
        assert Engine(work_dir).phase == "DESIGN"

    def test_done_at_max_iterations_does_not_resume(self, tmp_path):
        """If the ledger already has max_iterations rows, stay DONE."""
        from orchestrator.campaign import _resume_completed_campaign
        work_dir = _setup_work_dir(tmp_path)
        state = json.loads((work_dir / "state.json").read_text())
        state["phase"] = "DONE"
        (work_dir / "state.json").write_text(json.dumps(state))
        ledger = {"iterations": [
            {"iteration": 0, "family": "baseline"},
            {"iteration": 1, "family": "x"},
            {"iteration": 2, "family": "y"},
        ]}
        (work_dir / "ledger.json").write_text(json.dumps(ledger))

        assert _resume_completed_campaign(work_dir, max_iterations=2) == 1
        assert Engine(work_dir).phase == "DONE"  # untouched

    def test_done_but_no_real_iterations_does_not_resume(self, tmp_path):
        """Edge case: DONE with only the synthetic iter-0 row. Nothing to
        resume from, so we don't transition."""
        from orchestrator.campaign import _resume_completed_campaign
        work_dir = _setup_work_dir(tmp_path)
        state = json.loads((work_dir / "state.json").read_text())
        state["phase"] = "DONE"
        (work_dir / "state.json").write_text(json.dumps(state))
        ledger = {"iterations": [{"iteration": 0, "family": "baseline"}]}
        (work_dir / "ledger.json").write_text(json.dumps(ledger))

        assert _resume_completed_campaign(work_dir, max_iterations=5) == 1
        assert Engine(work_dir).phase == "DONE"

    def test_corrupt_ledger_does_not_crash_resume(self, tmp_path, caplog):
        """Garbage JSON in ledger.json must not take down the campaign."""
        import logging
        from orchestrator.campaign import _resume_completed_campaign
        work_dir = _setup_work_dir(tmp_path)
        state = json.loads((work_dir / "state.json").read_text())
        state["phase"] = "DONE"
        (work_dir / "state.json").write_text(json.dumps(state))
        (work_dir / "ledger.json").write_text("{this is not valid json")

        with caplog.at_level(logging.WARNING):
            assert _resume_completed_campaign(work_dir, max_iterations=3) == 1
        assert Engine(work_dir).phase == "DONE"  # state untouched
        assert any("Could not read ledger" in r.message for r in caplog.records)

    def test_ledger_with_malformed_rows_does_not_crash_resume(self, tmp_path):
        """Rows missing 'iteration' or with wrong types get skipped, not crashed."""
        from orchestrator.campaign import _resume_completed_campaign
        work_dir = _setup_work_dir(tmp_path)
        state = json.loads((work_dir / "state.json").read_text())
        state["phase"] = "DONE"
        (work_dir / "state.json").write_text(json.dumps(state))
        ledger = {"iterations": [
            {"iteration": 0, "family": "baseline"},
            "not-a-dict",                       # garbage row
            {"family": "no-iteration-key"},     # missing key
            {"iteration": "1"},                 # wrong type
            {"iteration": 1, "family": "real"}, # valid -> counts
        ]}
        (work_dir / "ledger.json").write_text(json.dumps(ledger))

        assert _resume_completed_campaign(work_dir, max_iterations=2) == 2
        assert Engine(work_dir).phase == "DESIGN"


class TestCampaignFailureResilience:
    """Campaign continues after an iteration fails permanently."""

    def test_campaign_continues_after_iteration_failure(self, tmp_path, monkeypatch):
        """A RuntimeError from run_iteration does not kill the campaign."""
        work_dir = _setup_work_dir(tmp_path)

        call_count = {"n": 0}

        def failing_then_complete(campaign, work_dir, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("claude -p timed out after 10 attempts")
            return IterationOutcome.COMPLETED

        import orchestrator.campaign as rc
        monkeypatch.setattr(rc, "run_iteration", failing_then_complete)

        run_campaign(SAMPLE_CAMPAIGN, work_dir, max_iterations=2, auto_approve=True)

        assert call_count["n"] == 2
        ledger = json.loads((work_dir / "ledger.json").read_text())
        failed_rows = [r for r in ledger["iterations"] if r.get("status") == "FAILED"]
        assert len(failed_rows) == 1
        assert failed_rows[0]["iteration"] == 1
        assert "timed out" in failed_rows[0]["error"]

    def test_failed_iteration_recorded_in_ledger(self, tmp_path):
        """append_failed_row writes a FAILED row to ledger.json."""
        from orchestrator.ledger import append_failed_row
        work_dir = _setup_work_dir(tmp_path)
        append_failed_row(work_dir, 3, "timeout after 10 retries")

        ledger = json.loads((work_dir / "ledger.json").read_text())
        failed_rows = [r for r in ledger["iterations"] if r.get("status") == "FAILED"]
        assert len(failed_rows) == 1
        assert failed_rows[0]["iteration"] == 3
        assert "timeout" in failed_rows[0]["error"]

    def test_failed_row_idempotent(self, tmp_path):
        """Calling append_failed_row twice for same iteration writes only one row."""
        from orchestrator.ledger import append_failed_row
        work_dir = _setup_work_dir(tmp_path)
        append_failed_row(work_dir, 1, "first error")
        append_failed_row(work_dir, 1, "second error")

        ledger = json.loads((work_dir / "ledger.json").read_text())
        iter1_rows = [r for r in ledger["iterations"] if r.get("iteration") == 1]
        assert len(iter1_rows) == 1


class TestSaveHumanFeedback:
    """Tests for _save_human_feedback helper."""

    def test_creates_new_file_with_first_entry(self, tmp_path):
        _save_human_feedback(tmp_path, "design", "Too vague")
        fb = json.loads((tmp_path / "human_feedback.json").read_text())
        assert fb["design"][0]["reason"] == "Too vague"
        assert fb["design"][0]["attempt"] == 1
        assert "timestamp" in fb["design"][0]

    def test_appends_to_existing_entries(self, tmp_path):
        _save_human_feedback(tmp_path, "design", "First rejection")
        _save_human_feedback(tmp_path, "design", "Second rejection")
        fb = json.loads((tmp_path / "human_feedback.json").read_text())
        assert len(fb["design"]) == 2
        assert fb["design"][1]["attempt"] == 2
        assert fb["design"][1]["reason"] == "Second rejection"

    def test_corrupt_json_resets_store(self, tmp_path):
        (tmp_path / "human_feedback.json").write_text("{invalid json!!")
        _save_human_feedback(tmp_path, "findings", "After corruption")
        fb = json.loads((tmp_path / "human_feedback.json").read_text())
        assert fb["findings"][0]["reason"] == "After corruption"
        assert fb["findings"][0]["attempt"] == 1

    def test_multiple_phases_independent(self, tmp_path):
        _save_human_feedback(tmp_path, "design", "Design issue")
        _save_human_feedback(tmp_path, "findings", "Findings issue")
        fb = json.loads((tmp_path / "human_feedback.json").read_text())
        assert len(fb["design"]) == 1
        assert len(fb["findings"]) == 1


class TestMetadataEnrichment:
    """Tests for campaign metadata enrichment (runtime block in campaign.yaml copy)."""

    CAMPAIGN_WITH_META = {
        **SAMPLE_CAMPAIGN,
        "metadata": {
            "tags": ["prefix-caching", "ttft"],
            "goal": "Determine prefix ratio effect on TTFT",
        },
    }

    def test_setup_work_dir_writes_enriched_campaign_yaml(self, tmp_path):
        """setup_work_dir writes an enriched campaign.yaml with runtime block."""
        campaign_path = tmp_path / "campaign.yaml"
        campaign_path.write_text(yaml.safe_dump(self.CAMPAIGN_WITH_META))

        work_dir = setup_work_dir(
            "test-run", repo_path=None,
            campaign_path=campaign_path, campaign=self.CAMPAIGN_WITH_META,
        )

        enriched_path = work_dir / "campaign.yaml"
        assert enriched_path.exists()

        enriched = yaml.safe_load(enriched_path.read_text())
        assert "runtime" in enriched
        assert "started_at" in enriched["runtime"]
        assert "nous_version" in enriched["runtime"]
        assert "target_repo" in enriched["runtime"]
        assert "target_commit" in enriched["runtime"]

    def test_user_metadata_passes_through(self, tmp_path):
        """User-defined metadata from campaign.yaml appears in the enriched copy."""
        campaign_path = tmp_path / "campaign.yaml"
        campaign_path.write_text(yaml.safe_dump(self.CAMPAIGN_WITH_META))

        work_dir = setup_work_dir(
            "test-run", repo_path=None,
            campaign_path=campaign_path, campaign=self.CAMPAIGN_WITH_META,
        )

        enriched = yaml.safe_load((work_dir / "campaign.yaml").read_text())
        assert enriched["metadata"]["tags"] == ["prefix-caching", "ttft"]
        assert enriched["metadata"]["goal"] == "Determine prefix ratio effect on TTFT"

    def test_enriched_copy_not_overwritten_on_resume(self, tmp_path):
        """Re-calling setup_work_dir does not clobber the enriched campaign.yaml."""
        campaign_path = tmp_path / "campaign.yaml"
        campaign_path.write_text(yaml.safe_dump(self.CAMPAIGN_WITH_META))

        work_dir = setup_work_dir(
            "test-run", repo_path=None,
            campaign_path=campaign_path, campaign=self.CAMPAIGN_WITH_META,
        )

        # Modify the enriched file to prove it's not overwritten
        enriched_path = work_dir / "campaign.yaml"
        enriched = yaml.safe_load(enriched_path.read_text())
        enriched["runtime"]["marker"] = "original"
        enriched_path.write_text(yaml.safe_dump(enriched))

        # Call setup_work_dir again (simulating resume)
        setup_work_dir(
            "test-run", repo_path=None,
            campaign_path=campaign_path, campaign=self.CAMPAIGN_WITH_META,
        )

        reloaded = yaml.safe_load(enriched_path.read_text())
        assert reloaded["runtime"]["marker"] == "original"

    def test_runtime_meta_tolerates_no_git(self, tmp_path):
        """_capture_runtime_meta returns nulls gracefully when git is unavailable."""
        with patch("orchestrator.iteration.subprocess.check_output", side_effect=FileNotFoundError):
            meta = _capture_runtime_meta(str(tmp_path))

        assert meta["target_repo"] is None
        assert meta["target_commit"] is None
        # nous_version may still be set via importlib.metadata
        assert "started_at" in meta

    def test_runtime_meta_captures_target_commit_from_git_repo(self, tmp_path):
        """_capture_runtime_meta captures target_commit from a real git repo."""
        import subprocess
        repo = tmp_path / "target"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)

        meta = _capture_runtime_meta(str(repo))

        assert meta["target_commit"] is not None
        assert len(meta["target_commit"]) == 40  # full SHA
        # No remote configured, so target_repo should be None
        assert meta["target_repo"] is None

    def test_no_enriched_copy_without_campaign_path(self, tmp_path, monkeypatch):
        """If campaign_path is not provided, no enriched copy is written."""
        monkeypatch.chdir(tmp_path)
        work_dir = setup_work_dir("test-run", repo_path=None)
        assert not (work_dir / "campaign.yaml").exists()

    @pytest.mark.parametrize("remote,expected", [
        ("git@github.com:org/repo.git", "org/repo"),
        ("git@github.com:org/repo", "org/repo"),
        ("https://github.com/org/repo.git", "org/repo"),
        ("https://github.com/org/repo", "org/repo"),
        ("ssh://git@github.com/org/repo.git", "org/repo"),
        ("https://gitlab.com/org/repo.git", "https://gitlab.com/org/repo.git"),
        ("git@gitlab.com:org/repo.git", "git@gitlab.com:org/repo.git"),
    ])
    def test_remote_url_parsing(self, remote, expected, monkeypatch):
        """_capture_runtime_meta correctly parses various remote URL formats."""
        def fake_check_output(cmd, **kwargs):
            if "rev-parse" in cmd:
                return "a" * 40 + "\n"
            if "get-url" in cmd:
                return remote + "\n"
            raise subprocess.CalledProcessError(1, cmd)

        import subprocess as real_subprocess
        monkeypatch.setattr("orchestrator.iteration.subprocess.check_output", fake_check_output)
        meta = _capture_runtime_meta("/fake/repo")
        assert meta["target_repo"] == expected

    def test_nous_version_git_sha_fallback(self, monkeypatch):
        """When importlib.metadata fails, nous_version falls back to git SHA."""
        fake_sha = "b" * 40

        monkeypatch.setattr(
            "orchestrator.iteration.importlib_metadata.version",
            lambda _: (_ for _ in ()).throw(importlib_metadata.PackageNotFoundError()),
        )

        def fake_check_output(cmd, **kwargs):
            if "rev-parse" in cmd:
                return fake_sha + "\n"
            raise subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr("orchestrator.iteration.subprocess.check_output", fake_check_output)
        meta = _capture_runtime_meta(None)
        assert meta["nous_version"] == fake_sha

    def test_enrichment_with_repo_path(self, tmp_path):
        """Enriched campaign.yaml is written inside .nous/<run_id>/ when repo_path is set."""
        campaign_path = tmp_path / "campaign.yaml"
        campaign_path.write_text(yaml.safe_dump(self.CAMPAIGN_WITH_META))

        repo = tmp_path / "target_repo"
        repo.mkdir()

        work_dir = setup_work_dir(
            "test-run", repo_path=str(repo),
            campaign_path=campaign_path, campaign=self.CAMPAIGN_WITH_META,
        )

        assert work_dir == repo / ".nous" / "test-run"
        enriched_path = work_dir / "campaign.yaml"
        assert enriched_path.exists()
        enriched = yaml.safe_load(enriched_path.read_text())
        assert "runtime" in enriched
        assert enriched["metadata"]["tags"] == ["prefix-caching", "ttft"]
