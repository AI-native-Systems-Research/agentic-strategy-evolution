"""Tests for compact handoff: designer → executor context sharing."""
import json
from pathlib import Path

import pytest
import yaml

from orchestrator.iteration import _split_design_output


def _make_raw_design(*, include_handoff: bool = True, handoff_heading: str = "## Handoff") -> str:
    """Build a realistic raw design output string."""
    bundle = {
        "metadata": {"iteration": 1, "family": "test", "research_question": "Does X work?"},
        "arms": [
            {"type": "h-main", "prediction": "+20%", "mechanism": "cause", "diagnostic": "check"},
            {"type": "h-control-negative", "prediction": "no effect", "mechanism": "none", "diagnostic": "check"},
        ],
    }
    bundle_yaml = yaml.safe_dump(bundle, default_flow_style=False, sort_keys=False)
    parts = [
        "## Research Question\n\nDoes X work?\n\n## System Interface\n\nBuild: `make`\n",
        "---",
        f"\n```yaml\n{bundle_yaml}```\n",
    ]
    if include_handoff:
        parts.append("\n---\n\n")
        parts.append(
            f"{handoff_heading}\n\n"
            "### Goal\nTest whether X improves latency under contention.\n\n"
            "### Key Discoveries\n- Mechanism at `src/engine.go:142` toggles batch mode\n"
            "- Baseline latency: 50ms at default load\n\n"
            "### System Interface\n- **Build:** `make`\n- **Run baseline:** `./run --baseline`\n\n"
            "### Key File Paths\n- `src/engine.go:142`\n\n"
            "### What I Tried That Didn't Work\n- `--turbo` flag doesn't exist\n\n"
            "### Warnings & Constraints\nFlag --foo is deprecated.\n"
        )
    return "\n".join(parts)


class TestHandoffExtraction:
    @pytest.fixture()
    def iter_dir(self, tmp_path: Path) -> Path:
        """Create realistic directory layout: work_dir/runs/iter-1/."""
        d = tmp_path / "runs" / "iter-1"
        d.mkdir(parents=True)
        return d

    def test_handoff_md_created_when_present(self, tmp_path: Path, iter_dir: Path) -> None:
        raw = _make_raw_design(include_handoff=True)
        _split_design_output(raw, iter_dir)
        # Per-iteration snapshot
        assert (iter_dir / "handoff_snapshot.md").exists()
        content = (iter_dir / "handoff_snapshot.md").read_text()
        assert "### Goal" in content
        assert "### Key Discoveries" in content
        assert "Test whether X improves latency" in content
        assert "Flag --foo is deprecated" in content
        # Campaign-level copy
        assert (tmp_path / "handoff.md").exists()

    def test_handoff_md_not_created_when_absent(self, tmp_path: Path, iter_dir: Path) -> None:
        raw = _make_raw_design(include_handoff=False)
        _split_design_output(raw, iter_dir)
        assert not (iter_dir / "handoff_snapshot.md").exists()
        assert not (tmp_path / "handoff.md").exists()
        assert (iter_dir / "problem.md").exists()
        assert (iter_dir / "bundle.yaml").exists()

    def test_bundle_still_valid_with_handoff(self, iter_dir: Path) -> None:
        raw = _make_raw_design(include_handoff=True)
        _split_design_output(raw, iter_dir)
        bundle = yaml.safe_load((iter_dir / "bundle.yaml").read_text())
        assert bundle["metadata"]["family"] == "test"
        assert len(bundle["arms"]) == 2

    def test_problem_md_not_polluted_by_handoff(self, iter_dir: Path) -> None:
        raw = _make_raw_design(include_handoff=True)
        _split_design_output(raw, iter_dir)
        problem = (iter_dir / "problem.md").read_text()
        assert "Executor Goal" not in problem
        assert "Warnings" not in problem

    def test_yaml_fence_in_handoff_does_not_confuse_bundle(self, tmp_path: Path) -> None:
        """YAML fences inside handoff don't get picked as the bundle."""
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        bundle = {
            "metadata": {"iteration": 1, "family": "test", "research_question": "Test?"},
            "arms": [
                {"type": "h-main", "prediction": "x", "mechanism": "y", "diagnostic": "z"},
                {"type": "h-control-negative", "prediction": "a", "mechanism": "b", "diagnostic": "c"},
            ],
        }
        bundle_yaml = yaml.safe_dump(bundle, default_flow_style=False, sort_keys=False)
        raw = (
            "## Research Question\nTest?\n\n---\n\n"
            f"```yaml\n{bundle_yaml}```\n\n"
            "---\n\n## Handoff\n\n### System Interface\n"
            "```yaml\nsome_config: true\n```\n"
        )
        _split_design_output(raw, iter_dir)
        parsed_bundle = yaml.safe_load((iter_dir / "bundle.yaml").read_text())
        assert parsed_bundle["metadata"]["family"] == "test"
        handoff = (iter_dir / "handoff_snapshot.md").read_text()
        assert "some_config" in handoff


class TestHandoffRegexTolerance:
    @pytest.fixture()
    def iter_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "runs" / "iter-1"
        d.mkdir(parents=True)
        return d

    def test_heading_case_insensitive(self, iter_dir: Path) -> None:
        raw = _make_raw_design(include_handoff=True, handoff_heading="## HANDOFF")
        _split_design_output(raw, iter_dir)
        assert (iter_dir / "handoff_snapshot.md").exists()

    def test_heading_level_3(self, iter_dir: Path) -> None:
        raw = _make_raw_design(include_handoff=True, handoff_heading="### Handoff")
        _split_design_output(raw, iter_dir)
        assert (iter_dir / "handoff_snapshot.md").exists()

    def test_no_false_positive_on_handoff_notes(self, iter_dir: Path) -> None:
        """'## Handoff Notes' should NOT match — only bare '## Handoff' heading."""
        bundle = {
            "metadata": {"iteration": 1, "family": "test", "research_question": "Test?"},
            "arms": [
                {"type": "h-main", "prediction": "x", "mechanism": "y", "diagnostic": "z"},
                {"type": "h-control-negative", "prediction": "a", "mechanism": "b", "diagnostic": "c"},
            ],
        }
        bundle_yaml = yaml.safe_dump(bundle, default_flow_style=False, sort_keys=False)
        raw = (
            "## Research Question\nTest?\n\n"
            "## Handoff Notes\nThese are just domain notes.\n\n---\n\n"
            f"```yaml\n{bundle_yaml}```\n"
        )
        _split_design_output(raw, iter_dir)
        assert not (iter_dir / "handoff_snapshot.md").exists()
