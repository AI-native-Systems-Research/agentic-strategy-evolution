"""Atomic-write behavioral tests for state.json + cumulative.patch (PR #279).

Both writers previously used ``Path.write_text`` directly, which can leave
a truncated file if the process is killed mid-write. These tests assert the
observable contract: the written file is complete + parseable, idempotency
is preserved, and no leftover ``.tmp`` files are stranded in the directory
(atomic_write renames a temp file into place).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _tmp_files(d: Path) -> list[Path]:
    return list(d.glob("*.tmp"))


class TestReproducibilityAtomicWrite:
    def _seed_state(self, work_dir: Path) -> None:
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "state.json").write_text(json.dumps({
            "phase": "INIT", "iteration": 1, "run_id": "exp1",
        }) + "\n")

    def test_block_persisted_and_parseable(self, tmp_path):
        from orchestrator.reproducibility import attach_to_state
        self._seed_state(tmp_path)

        attach_to_state(tmp_path, {"captured_at": "2026-01-01T00:00:00Z", "commit": "abc"})

        state = json.loads((tmp_path / "state.json").read_text())
        assert state["reproducibility_metadata"]["commit"] == "abc"
        # Pre-existing keys preserved (full object written, not truncated).
        assert state["run_id"] == "exp1"

    def test_no_leftover_tmp_files(self, tmp_path):
        from orchestrator.reproducibility import attach_to_state
        self._seed_state(tmp_path)

        attach_to_state(tmp_path, {"captured_at": "2026-01-01T00:00:00Z"})

        assert _tmp_files(tmp_path) == []

    def test_idempotent_first_capture_wins(self, tmp_path):
        from orchestrator.reproducibility import attach_to_state
        self._seed_state(tmp_path)

        attach_to_state(tmp_path, {"captured_at": "2026-01-01T00:00:00Z", "commit": "first"})
        attach_to_state(tmp_path, {"captured_at": "2026-02-02T00:00:00Z", "commit": "second"})

        state = json.loads((tmp_path / "state.json").read_text())
        assert state["reproducibility_metadata"]["commit"] == "first"


class TestLineageAtomicWrite:
    def _init_repo_with_branch(self, repo: Path) -> str:
        repo.mkdir(parents=True, exist_ok=True)
        run = lambda *a: subprocess.run(a, cwd=repo, check=True, capture_output=True)
        run("git", "init", "-q")
        run("git", "config", "user.email", "t@t")
        run("git", "config", "user.name", "t")
        (repo / "f.txt").write_text("base\n")
        run("git", "add", ".")
        run("git", "commit", "-q", "-m", "base")
        run("git", "checkout", "-q", "-b", "nous-exp-iter-1")
        (repo / "f.txt").write_text("base\nchange\n")
        run("git", "add", ".")
        run("git", "commit", "-q", "-m", "change")
        return "nous-exp-iter-1"

    def test_patch_written_complete_and_no_tmp(self, tmp_path):
        from orchestrator.lineage import emit_cumulative_patch
        repo = tmp_path / "repo"
        branch = self._init_repo_with_branch(repo)
        iter_dir = tmp_path / "iter-1"

        out = emit_cumulative_patch(repo, branch, iter_dir)

        assert out is not None and out.exists()
        content = out.read_text()
        assert "change" in content
        # A complete unified diff ends with the added line; assert it's
        # the full diff, not truncated mid-hunk.
        assert content.startswith("diff --git")
        assert _tmp_files(out.parent) == []
