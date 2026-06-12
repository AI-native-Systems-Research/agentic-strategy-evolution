"""Behavioral tests for the deterministic Stop hook (#129).

The hook tells Claude Code whether the executor agent's work is complete,
based on objective evidence on disk: did `nous validate execution` pass,
and is `principle_updates.json` present? No LLM judgment, no agent
self-assessment.

Hook exit-code convention (Claude Code Stop hooks):
    0 → allow stop (work complete; agent terminates cleanly).
    2 → block stop (work incomplete; structured reason on stderr; agent
        receives the stderr in its conversation and keeps going).

The tests below describe the contract: given iter_dir state X, the hook
exits with code Y and writes a useful reason to stderr. They do NOT
inspect which functions the hook called or how it organized its work.
"""
from __future__ import annotations

import importlib.util
import importlib.machinery
import json
import warnings
from pathlib import Path


HOOK_PATH = Path(__file__).resolve().parent.parent / "bin" / "nous-execute-stop"


def _load_hook_main():
    """Load the hook script as a Python module and return its main().

    The hook has no ``.py`` suffix (it's an executable on PATH), so we
    construct the spec with an explicit SourceFileLoader.
    """
    loader = importlib.machinery.SourceFileLoader("nous_execute_stop", str(HOOK_PATH))
    spec = importlib.util.spec_from_loader("nous_execute_stop", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module.main


def _populate_passing_iter_dir(work_dir: Path, iteration: int = 1) -> Path:
    """Use StubDispatcher to write a valid execution iter_dir.

    StubDispatcher produces schema-conformant artifacts. Tests here can then
    mutate the dir to simulate failure modes.
    """
    from orchestrator.dispatch import StubDispatcher

    iter_dir = work_dir / "runs" / f"iter-{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dispatcher = StubDispatcher(work_dir)

    # Stub also needs design artifacts present for full validation.
    dispatcher.dispatch(
        "planner", "design",
        output_path=iter_dir / "design_log.md", iteration=iteration,
    )
    dispatcher.dispatch(
        "executor", "execute-analyze",
        output_path=iter_dir / "executor_log.md", iteration=iteration,
    )
    return iter_dir


# ─── Pass case ──────────────────────────────────────────────────────────────

class TestStopHookPassCase:

    def test_exits_zero_when_validation_passes_and_principles_present(
        self, tmp_path, monkeypatch, capsys,
    ):
        iter_dir = _populate_passing_iter_dir(tmp_path)
        monkeypatch.setenv("NOUS_ITER_DIR", str(iter_dir))

        main = _load_hook_main()
        rc = main()

        assert rc == 0
        captured = capsys.readouterr()
        assert captured.err == ""


# ─── Block cases (exit 2) ──────────────────────────────────────────────────

class TestStopHookBlockCases:

    def test_blocks_when_principle_updates_missing(
        self, tmp_path, monkeypatch, capsys,
    ):
        iter_dir = _populate_passing_iter_dir(tmp_path)
        (iter_dir / "principle_updates.json").unlink()
        monkeypatch.setenv("NOUS_ITER_DIR", str(iter_dir))

        main = _load_hook_main()
        rc = main()

        assert rc == 2
        captured = capsys.readouterr()
        assert "principle_updates.json" in captured.err

    def test_blocks_with_validation_diff_when_findings_corrupted(
        self, tmp_path, monkeypatch, capsys,
    ):
        iter_dir = _populate_passing_iter_dir(tmp_path)

        # Drop a required field from findings.json so schema validation fails.
        findings_path = iter_dir / "findings.json"
        findings = json.loads(findings_path.read_text())
        findings.pop("arms", None)  # arms is required
        findings_path.write_text(json.dumps(findings))

        monkeypatch.setenv("NOUS_ITER_DIR", str(iter_dir))

        main = _load_hook_main()
        rc = main()

        assert rc == 2
        captured = capsys.readouterr()
        # Reason should reference the actual schema problem so the agent
        # can fix it without re-running the entire iteration.
        assert "findings.json" in captured.err
        assert "arms" in captured.err.lower() or "schema" in captured.err.lower()

    def test_blocks_when_iter_dir_missing(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("NOUS_ITER_DIR", str(tmp_path / "nonexistent"))

        main = _load_hook_main()
        rc = main()

        assert rc == 2
        captured = capsys.readouterr()
        assert "nonexistent" in captured.err or "does not exist" in captured.err

    def test_blocks_when_env_var_unset(self, monkeypatch, capsys):
        monkeypatch.delenv("NOUS_ITER_DIR", raising=False)

        main = _load_hook_main()
        rc = main()

        assert rc == 2
        captured = capsys.readouterr()
        assert "NOUS_ITER_DIR" in captured.err
