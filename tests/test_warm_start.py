"""Behavioral tests for warm-start campaigns (issue #83).

Each campaign on the same target repo today starts from scratch —
re-exploring, re-deriving principles a prior campaign already
established. Warm-start copies `principles.json` + `handoff.md` from
a completed prior campaign as seed knowledge, with drift detection
that marks inherited principles as TENTATIVE when the target repo
has changed since the prior campaign ran.

Test contract:
  - warm_start_from_prior(work_dir, prior_run_id, drift_check_fn=)
    accepts an injection seam for drift detection (production uses
    git; tests inject a deterministic stub).
  - Successful warm-start copies principles + handoff atomically and
    tags each inherited principle with provenance.
  - Drift detection promotes confidence to "tentative" so the next
    designer revalidates rather than blindly trusting.
  - Missing prior, incomplete prior (state.phase != DONE), or corrupt
    artifacts surface as informative errors.
  - Schema accepts campaign.warm_start.prior_run_id.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.warm_start import (
    DriftReport,
    WarmStartResult,
    warm_start_from_prior,
)


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_campaign_schema() -> dict:
    return yaml.safe_load((SCHEMAS_DIR / "campaign.schema.yaml").read_text())


def _principle(*, pid: str = "RP-1", confidence: str = "medium",
               category: str = "domain") -> dict:
    return {
        "id": pid, "statement": "x", "confidence": confidence,
        "regime": "", "evidence": [], "contradicts": [],
        "extraction_iteration": 1, "mechanism": "",
        "applicability_bounds": "", "superseded_by": None,
        "status": "active", "category": category,
    }


def _setup_prior(prior_dir: Path, *, phase: str = "DONE",
                 principles: list | None = None,
                 handoff_text: str = "## Handoff\n### Goal\nx\n") -> None:
    prior_dir.mkdir(parents=True, exist_ok=True)
    (prior_dir / "state.json").write_text(json.dumps({
        "phase": phase, "iteration": 3, "run_id": prior_dir.name,
        "family": None, "timestamp": "2026-05-25T00:00:00Z",
    }))
    (prior_dir / "principles.json").write_text(json.dumps({
        "principles": principles if principles is not None else [_principle()],
    }))
    (prior_dir / "handoff.md").write_text(handoff_text)


def _no_drift(*args, **kwargs) -> DriftReport:
    return DriftReport(detected=False, summary=None)


def _drift_detected(summary: str = "3 source files changed"):
    def _fn(prior_dir, repo_path) -> DriftReport:
        return DriftReport(detected=True, summary=summary)
    return _fn


# ─── Successful warm-start copies artifacts ───────────────────────────────


class TestWarmStartCopiesArtifacts:
    def test_principles_copied_with_provenance(self, tmp_path: Path) -> None:
        prior = tmp_path / "prior"
        new = tmp_path / "new"
        new.mkdir()
        _setup_prior(prior, principles=[
            _principle(pid="RP-1"), _principle(pid="RP-2"),
        ])

        result = warm_start_from_prior(
            new, prior_run_id="prior", prior_search_paths=[tmp_path],
            drift_check_fn=_no_drift,
        )

        assert result.principles_copied == 2
        assert result.handoff_copied is True
        assert result.drift.detected is False

        on_disk = json.loads((new / "principles.json").read_text())
        assert len(on_disk["principles"]) == 2
        for p in on_disk["principles"]:
            assert p.get("inherited_from") == "prior"
            assert p["confidence"] == "inherited"

    def test_handoff_copied_verbatim_when_no_drift(self, tmp_path: Path) -> None:
        prior = tmp_path / "prior"
        new = tmp_path / "new"
        new.mkdir()
        original = "## Handoff\n### Goal\nfind X\n"
        _setup_prior(prior, handoff_text=original)

        warm_start_from_prior(
            new, prior_run_id="prior", prior_search_paths=[tmp_path],
            drift_check_fn=_no_drift,
        )

        copied = (new / "handoff.md").read_text()
        assert copied == original

    def test_drift_promotes_principles_to_tentative(self, tmp_path: Path) -> None:
        prior = tmp_path / "prior"
        new = tmp_path / "new"
        new.mkdir()
        _setup_prior(prior, principles=[
            _principle(pid="RP-1", confidence="high"),
        ])

        result = warm_start_from_prior(
            new, prior_run_id="prior", prior_search_paths=[tmp_path],
            drift_check_fn=_drift_detected("4 files changed"),
        )

        assert result.drift.detected is True
        on_disk = json.loads((new / "principles.json").read_text())
        for p in on_disk["principles"]:
            assert p["confidence"] == "tentative"

    def test_drift_prepends_warning_to_handoff(self, tmp_path: Path) -> None:
        prior = tmp_path / "prior"
        new = tmp_path / "new"
        new.mkdir()
        _setup_prior(prior, handoff_text="## Goal\nx\n")

        warm_start_from_prior(
            new, prior_run_id="prior", prior_search_paths=[tmp_path],
            drift_check_fn=_drift_detected("changes"),
        )

        copied = (new / "handoff.md").read_text()
        assert "drift" in copied.lower() or "INHERITED" in copied
        assert "## Goal" in copied  # original content preserved


# ─── Failure modes ────────────────────────────────────────────────────────


class TestWarmStartFailures:
    def test_missing_prior_dir_raises(self, tmp_path: Path) -> None:
        new = tmp_path / "new"
        new.mkdir()
        with pytest.raises(FileNotFoundError, match="prior"):
            warm_start_from_prior(
                new, prior_run_id="ghost", prior_search_paths=[tmp_path],
                drift_check_fn=_no_drift,
            )

    def test_incomplete_prior_rejected(self, tmp_path: Path) -> None:
        prior = tmp_path / "prior"
        new = tmp_path / "new"
        new.mkdir()
        _setup_prior(prior, phase="EXECUTE_ANALYZE")  # not DONE

        with pytest.raises(RuntimeError, match="DONE|complete"):
            warm_start_from_prior(
                new, prior_run_id="prior", prior_search_paths=[tmp_path],
                drift_check_fn=_no_drift,
            )

    def test_corrupt_state_json_rejected(self, tmp_path: Path) -> None:
        prior = tmp_path / "prior"
        prior.mkdir()
        new = tmp_path / "new"
        new.mkdir()
        (prior / "state.json").write_text("not json")
        (prior / "principles.json").write_text(json.dumps({"principles": []}))
        (prior / "handoff.md").write_text("h")

        with pytest.raises((ValueError, RuntimeError)):
            warm_start_from_prior(
                new, prior_run_id="prior", prior_search_paths=[tmp_path],
                drift_check_fn=_no_drift,
            )

    def test_empty_principles_warm_start_succeeds(self, tmp_path: Path) -> None:
        """Prior campaign with zero principles is still a valid warm-start
        source (handoff alone is useful)."""
        prior = tmp_path / "prior"
        new = tmp_path / "new"
        new.mkdir()
        _setup_prior(prior, principles=[])

        result = warm_start_from_prior(
            new, prior_run_id="prior", prior_search_paths=[tmp_path],
            drift_check_fn=_no_drift,
        )
        assert result.principles_copied == 0
        assert result.handoff_copied is True


# ─── Injection seam ───────────────────────────────────────────────────────


class TestDriftCheckFnInjection:
    def test_injected_fn_replaces_default(self, tmp_path: Path) -> None:
        prior = tmp_path / "prior"
        new = tmp_path / "new"
        new.mkdir()
        _setup_prior(prior)

        invocations: list = []

        def fake(prior_dir, repo_path):
            invocations.append((prior_dir, repo_path))
            return DriftReport(detected=False, summary=None)

        warm_start_from_prior(
            new, prior_run_id="prior", prior_search_paths=[tmp_path],
            repo_path="/some/repo",
            drift_check_fn=fake,
        )
        assert len(invocations) == 1
        assert invocations[0][1] == "/some/repo"

    def test_default_drift_check_does_not_run_subprocess_when_no_repo(
        self, tmp_path: Path,
    ) -> None:
        """No repo_path ⇒ default drift check returns 'no drift detected'
        without invoking git subprocess (test-safe)."""
        prior = tmp_path / "prior"
        new = tmp_path / "new"
        new.mkdir()
        _setup_prior(prior)

        result = warm_start_from_prior(
            new, prior_run_id="prior", prior_search_paths=[tmp_path],
            repo_path=None,  # no repo → no git invocation
            drift_check_fn=None,  # use default
        )
        assert isinstance(result, WarmStartResult)
        assert result.drift.detected is False


# ─── Schema additivity ────────────────────────────────────────────────────


class TestSchemaAcceptsWarmStart:
    def _base(self) -> dict:
        return {
            "research_question": "q?",
            "run_id": "demo",
            "max_iterations": 1,
            "target_system": {"name": "x", "description": "d"},
            "prompts": {"methodology_layer": "p"},
        }

    def test_warm_start_block_validates(self) -> None:
        c = self._base()
        c["warm_start"] = {"prior_run_id": "campaign-foo"}
        jsonschema.validate(c, _load_campaign_schema())

    def test_legacy_no_warm_start_validates(self) -> None:
        jsonschema.validate(self._base(), _load_campaign_schema())

    def test_missing_prior_run_id_rejected(self) -> None:
        c = self._base()
        c["warm_start"] = {}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(c, _load_campaign_schema())
