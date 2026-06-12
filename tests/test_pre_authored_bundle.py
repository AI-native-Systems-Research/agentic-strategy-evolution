"""Behavioral tests for `nous run --bundle <path>` (issue #188).

For paper-reproduction campaigns the experiment is fully pre-specified.
Asking the agent to re-derive the bundle each run wastes compute and
introduces a determinism gap (the agent might author a slightly different
bundle each time). #188 adds `--bundle <path>` so the user can supply
a pre-authored bundle.yaml; iter-1 skips DESIGN's claude-p turn entirely.

Test contract:
  - Given a valid bundle.yaml + research_question, the helper writes
    bundle.yaml, problem.md, handoff_snapshot.md, and bundle_manifest.json.
  - bundle_manifest.json carries bundle_source: pre_authored, the source
    path, and a sha256 hash of the bundle.
  - When --problem-md / --handoff-md are passed, the helper copies them
    verbatim instead of stubbing.
  - Schema-invalid bundles fail fast before any artifact is written.
  - validate_design accepts the iter dir produced by the pre-authored
    path (i.e. bundle_manifest.json is on the whitelist).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml


def _valid_bundle_dict() -> dict:
    return {
        "metadata": {
            "iteration": 1,
            "family": "paper-burst",
            "research_question": "Does ea-wfq dominate wfq under bursty load?",
        },
        "arms": [
            {
                "type": "h-main",
                "prediction": "P95(ea-wfq) < P95(wfq) for EARLY class.",
                "mechanism": "Early-arrival weighting reorders queue.",
                "diagnostic": "compare P95 latency by class across 10 seeds.",
            }
        ],
    }


def _campaign() -> dict:
    return {
        "research_question": "Does ea-wfq dominate wfq under bursty load?",
        "run_id": "demo",
        "max_iterations": 1,
        "target_system": {"name": "BLIS", "description": "d"},
        "prompts": {"methodology_layer": "p"},
    }


# ─── _apply_pre_authored_bundle: artifact creation ───────────────────────


class TestApplyPreAuthoredBundle:
    def test_writes_all_required_artifacts(self, tmp_path: Path) -> None:
        from orchestrator.iteration import _apply_pre_authored_bundle

        bundle_path = tmp_path / "src" / "bundle.yaml"
        bundle_path.parent.mkdir()
        bundle_path.write_text(yaml.safe_dump(_valid_bundle_dict()))

        iter_dir = tmp_path / "iter-1"
        _apply_pre_authored_bundle(
            iter_dir,
            bundle_path=bundle_path,
            problem_md_path=None,
            handoff_md_path=None,
            campaign=_campaign(),
        )
        assert (iter_dir / "bundle.yaml").exists()
        assert (iter_dir / "problem.md").exists()
        assert (iter_dir / "handoff_snapshot.md").exists()
        assert (iter_dir / "bundle_manifest.json").exists()

    def test_bundle_manifest_records_provenance(self, tmp_path: Path) -> None:
        from orchestrator.iteration import _apply_pre_authored_bundle

        bundle_path = tmp_path / "bundle.yaml"
        bundle_text = yaml.safe_dump(_valid_bundle_dict())
        bundle_path.write_text(bundle_text)

        iter_dir = tmp_path / "iter-1"
        _apply_pre_authored_bundle(
            iter_dir,
            bundle_path=bundle_path,
            problem_md_path=None,
            handoff_md_path=None,
            campaign=_campaign(),
        )
        manifest = json.loads(
            (iter_dir / "bundle_manifest.json").read_text()
        )
        assert manifest["bundle_source"] == "pre_authored"
        assert manifest["bundle_path"] == str(bundle_path)
        expected_sha = hashlib.sha256(bundle_text.encode("utf-8")).hexdigest()
        assert manifest["bundle_sha256"] == expected_sha
        # Stub markers when the user didn't supply problem_md/handoff_md.
        assert manifest["problem_md_source"] == "auto_stub"
        assert manifest["handoff_snapshot_md_source"] == "auto_stub"

    def test_bundle_yaml_copied_byte_for_byte(self, tmp_path: Path) -> None:
        """Determinism — re-runs of the same bundle must produce the
        same on-disk content. Hashing the source matters here."""
        from orchestrator.iteration import _apply_pre_authored_bundle

        bundle_path = tmp_path / "bundle.yaml"
        bundle_text = yaml.safe_dump(_valid_bundle_dict())
        bundle_path.write_text(bundle_text)

        iter_dir = tmp_path / "iter-1"
        _apply_pre_authored_bundle(
            iter_dir,
            bundle_path=bundle_path,
            problem_md_path=None,
            handoff_md_path=None,
            campaign=_campaign(),
        )
        assert (iter_dir / "bundle.yaml").read_text() == bundle_text

    def test_problem_md_copied_when_supplied(self, tmp_path: Path) -> None:
        from orchestrator.iteration import _apply_pre_authored_bundle

        bundle_path = tmp_path / "bundle.yaml"
        bundle_path.write_text(yaml.safe_dump(_valid_bundle_dict()))
        custom_problem = tmp_path / "my_problem.md"
        custom_problem.write_text("# Author-supplied problem\nVerbatim.\n")

        iter_dir = tmp_path / "iter-1"
        _apply_pre_authored_bundle(
            iter_dir,
            bundle_path=bundle_path,
            problem_md_path=custom_problem,
            handoff_md_path=None,
            campaign=_campaign(),
        )
        assert (iter_dir / "problem.md").read_text() == (
            "# Author-supplied problem\nVerbatim.\n"
        )
        manifest = json.loads(
            (iter_dir / "bundle_manifest.json").read_text()
        )
        assert manifest["problem_md_source"] == "pre_authored"

    def test_handoff_md_copied_when_supplied(self, tmp_path: Path) -> None:
        from orchestrator.iteration import _apply_pre_authored_bundle

        bundle_path = tmp_path / "bundle.yaml"
        bundle_path.write_text(yaml.safe_dump(_valid_bundle_dict()))
        custom_handoff = tmp_path / "my_handoff.md"
        custom_handoff.write_text("# Custom handoff\n")

        iter_dir = tmp_path / "iter-1"
        _apply_pre_authored_bundle(
            iter_dir,
            bundle_path=bundle_path,
            problem_md_path=None,
            handoff_md_path=custom_handoff,
            campaign=_campaign(),
        )
        assert (iter_dir / "handoff_snapshot.md").read_text() == "# Custom handoff\n"
        manifest = json.loads(
            (iter_dir / "bundle_manifest.json").read_text()
        )
        assert manifest["handoff_snapshot_md_source"] == "pre_authored"

    def test_research_question_appears_in_stub_problem(self, tmp_path: Path) -> None:
        """The auto-stubbed problem.md should reference the campaign's
        research_question so the validator + reviewer have context."""
        from orchestrator.iteration import _apply_pre_authored_bundle

        bundle_path = tmp_path / "bundle.yaml"
        bundle_path.write_text(yaml.safe_dump(_valid_bundle_dict()))

        iter_dir = tmp_path / "iter-1"
        _apply_pre_authored_bundle(
            iter_dir,
            bundle_path=bundle_path,
            problem_md_path=None,
            handoff_md_path=None,
            campaign=_campaign(),
        )
        text = (iter_dir / "problem.md").read_text()
        assert "Does ea-wfq dominate wfq under bursty load?" in text


# ─── Schema-invalid bundles fail fast ────────────────────────────────────


class TestPreAuthoredBundleValidation:
    def test_schema_invalid_bundle_raises(self, tmp_path: Path) -> None:
        from orchestrator.iteration import _apply_pre_authored_bundle

        bundle_path = tmp_path / "bundle.yaml"
        # Missing required `arms` field.
        bundle_path.write_text(yaml.safe_dump({"metadata": {}}))

        iter_dir = tmp_path / "iter-1"
        with pytest.raises(ValueError, match="schema validation"):
            _apply_pre_authored_bundle(
                iter_dir,
                bundle_path=bundle_path,
                problem_md_path=None,
                handoff_md_path=None,
                campaign=_campaign(),
            )
        # Nothing should have been written when validation fails.
        assert not (iter_dir / "bundle.yaml").exists()
        assert not (iter_dir / "bundle_manifest.json").exists()

    def test_missing_bundle_file_raises(self, tmp_path: Path) -> None:
        from orchestrator.iteration import _apply_pre_authored_bundle

        with pytest.raises(FileNotFoundError):
            _apply_pre_authored_bundle(
                tmp_path / "iter-1",
                bundle_path=tmp_path / "does-not-exist.yaml",
                problem_md_path=None,
                handoff_md_path=None,
                campaign=_campaign(),
            )

    def test_invalid_yaml_raises_with_path_in_message(self, tmp_path: Path) -> None:
        from orchestrator.iteration import _apply_pre_authored_bundle

        bundle_path = tmp_path / "bundle.yaml"
        bundle_path.write_text("not: : yaml: : :")

        with pytest.raises(ValueError) as excinfo:
            _apply_pre_authored_bundle(
                tmp_path / "iter-1",
                bundle_path=bundle_path,
                problem_md_path=None,
                handoff_md_path=None,
                campaign=_campaign(),
            )
        assert str(bundle_path) in str(excinfo.value)


# ─── validate_design accepts pre-authored output ─────────────────────────


class TestPreAuthoredOutputPassesValidator:
    def test_validate_design_accepts_pre_authored_iter_dir(
        self, tmp_path: Path,
    ) -> None:
        """End-to-end pin (#188 + #190): the iter dir produced by the
        pre-authored path passes ``nous validate design`` — including
        the bundle_manifest.json on the whitelist."""
        from orchestrator.iteration import _apply_pre_authored_bundle
        from orchestrator.validate import validate_design

        bundle_path = tmp_path / "bundle.yaml"
        bundle_path.write_text(yaml.safe_dump(_valid_bundle_dict()))

        iter_dir = tmp_path / "iter-1"
        _apply_pre_authored_bundle(
            iter_dir,
            bundle_path=bundle_path,
            problem_md_path=None,
            handoff_md_path=None,
            campaign=_campaign(),
        )
        result = validate_design(iter_dir)
        assert result["status"] == "pass", result
