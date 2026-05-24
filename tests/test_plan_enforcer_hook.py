"""Behavioral tests for the PreToolUse plan-enforcer hook (issue #128).

The hook intercepts Bash tool calls during EXECUTE_ANALYZE and decides
whether the proposed command is consistent with the iteration's
``experiment_plan.yaml``. The decision protocol:

  * ``--strict`` (env: ``NOUS_PLAN_ENFORCEMENT=strict``): block (exit 2)
    if the command's head binary doesn't appear in any planned condition.
  * ``--warn`` (default): always allow (exit 0) but log violations to
    ``<iter_dir>/plan_violations.jsonl``.
  * Escape hatch: a command containing ``# nous: ad-hoc`` is allowed in
    strict mode AND logged distinctly so reviewers can audit the use.

The hook is invoked by Claude Code with JSON on stdin describing the
proposed tool call. We test the contract: given (mode, plan, proposed
command) → exit code + violations log entry.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path

import yaml


HOOK_PATH = Path(__file__).resolve().parent.parent / "bin" / "nous-plan-enforcer"


def _load_hook_main():
    loader = importlib.machinery.SourceFileLoader("nous_plan_enforcer", str(HOOK_PATH))
    spec = importlib.util.spec_from_loader("nous_plan_enforcer", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module.main


def _write_plan(iter_dir: Path, arms: list[dict]) -> None:
    iter_dir.mkdir(parents=True, exist_ok=True)
    plan = {"arms": arms}
    (iter_dir / "experiment_plan.yaml").write_text(yaml.safe_dump(plan))


def _hook_event(command: str, cwd: str) -> str:
    """Emit a Claude Code PreToolUse hook payload for a Bash call."""
    return json.dumps({
        "session_id": "test-session",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd,
    })


def _run_hook(stdin_text: str, *, env: dict, monkeypatch) -> int:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_text))
    return _load_hook_main()()


def _read_violations(iter_dir: Path) -> list[dict]:
    p = iter_dir / "plan_violations.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


# ─── Strict mode ────────────────────────────────────────────────────────────

class TestStrictMode:

    def test_allows_planned_binary(self, tmp_path, monkeypatch, capsys):
        _write_plan(tmp_path, [{
            "arm_id": "h-main",
            "conditions": [{"name": "baseline", "command": "./blis run --workload x"}],
        }])
        rc = _run_hook(
            _hook_event("./blis run --workload y", str(tmp_path)),
            env={"NOUS_ITER_DIR": str(tmp_path), "NOUS_PLAN_ENFORCEMENT": "strict"},
            monkeypatch=monkeypatch,
        )
        assert rc == 0
        assert capsys.readouterr().err == ""

    def test_blocks_unplanned_binary_with_reason(self, tmp_path, monkeypatch, capsys):
        _write_plan(tmp_path, [{
            "arm_id": "h-main",
            "conditions": [{"name": "baseline", "command": "./blis run"}],
        }])
        rc = _run_hook(
            _hook_event("rm -rf /", str(tmp_path)),
            env={"NOUS_ITER_DIR": str(tmp_path), "NOUS_PLAN_ENFORCEMENT": "strict"},
            monkeypatch=monkeypatch,
        )
        assert rc == 2
        err = capsys.readouterr().err
        assert "rm" in err
        assert "experiment_plan.yaml" in err or "planned" in err

    def test_allows_ad_hoc_escape_hatch(self, tmp_path, monkeypatch, capsys):
        _write_plan(tmp_path, [{
            "arm_id": "h-main",
            "conditions": [{"name": "baseline", "command": "./blis run"}],
        }])
        rc = _run_hook(
            _hook_event("# nous: ad-hoc\nls -la results/", str(tmp_path)),
            env={"NOUS_ITER_DIR": str(tmp_path), "NOUS_PLAN_ENFORCEMENT": "strict"},
            monkeypatch=monkeypatch,
        )
        assert rc == 0
        violations = _read_violations(tmp_path)
        # Ad-hoc escapes are still LOGGED for audit, just not blocked.
        assert len(violations) == 1
        assert violations[0]["kind"] == "ad-hoc"


# ─── Warn mode (default) ────────────────────────────────────────────────────

class TestWarnMode:

    def test_warn_allows_unplanned_and_logs(self, tmp_path, monkeypatch, capsys):
        _write_plan(tmp_path, [{
            "arm_id": "h-main",
            "conditions": [{"name": "baseline", "command": "./blis run"}],
        }])
        rc = _run_hook(
            _hook_event("curl https://example.com", str(tmp_path)),
            env={"NOUS_ITER_DIR": str(tmp_path)},  # default = warn
            monkeypatch=monkeypatch,
        )
        assert rc == 0  # warn mode never blocks
        violations = _read_violations(tmp_path)
        assert len(violations) == 1
        assert violations[0]["kind"] == "unplanned"
        assert "curl" in violations[0]["command"]
        assert violations[0]["arm"] is not None or violations[0]["arm"] == ""
        assert "timestamp" in violations[0]

    def test_warn_does_not_log_planned_commands(self, tmp_path, monkeypatch):
        _write_plan(tmp_path, [{
            "arm_id": "h-main",
            "conditions": [{"name": "baseline", "command": "./blis run"}],
        }])
        rc = _run_hook(
            _hook_event("./blis run --threads 8", str(tmp_path)),
            env={"NOUS_ITER_DIR": str(tmp_path)},
            monkeypatch=monkeypatch,
        )
        assert rc == 0
        assert _read_violations(tmp_path) == []


# ─── No false positives across plan shapes ─────────────────────────────────

class TestNoFalsePositives:
    """Exercise representative plan shapes and assert every planned command
    is recognized as planned (no false positives in strict mode)."""

    PLANS = [
        # Single arm, single condition.
        [{"arm_id": "h-main", "conditions": [
            {"name": "x", "command": "python run.py --seed 1"},
        ]}],
        # Multiple conditions per arm.
        [{"arm_id": "h-main", "conditions": [
            {"name": "a", "command": "./blis run --workload a"},
            {"name": "b", "command": "./blis run --workload b"},
        ]}],
        # Multiple arms, mixed binaries.
        [
            {"arm_id": "h-main", "conditions": [
                {"name": "x", "command": "./sim --batch=4"}]},
            {"arm_id": "h-ablation", "conditions": [
                {"name": "y", "command": "/usr/bin/perf record -g ./sim"}]},
        ],
        # Absolute paths.
        [{"arm_id": "h-main", "conditions": [
            {"name": "x", "command": "/usr/local/bin/custom-bench --duration 60"}]}],
    ]

    def test_strict_allows_every_planned_command(self, tmp_path, monkeypatch):
        for i, arms in enumerate(self.PLANS):
            iter_dir = tmp_path / f"iter-{i}"
            _write_plan(iter_dir, arms)
            for arm in arms:
                for cond in arm["conditions"]:
                    rc = _run_hook(
                        _hook_event(cond["command"], str(iter_dir)),
                        env={
                            "NOUS_ITER_DIR": str(iter_dir),
                            "NOUS_PLAN_ENFORCEMENT": "strict",
                        },
                        monkeypatch=monkeypatch,
                    )
                    assert rc == 0, (
                        f"Strict mode blocked a planned command in plan #{i}: "
                        f"{cond['command']!r}"
                    )


# ─── Edge cases ─────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_missing_iter_dir_warns_but_allows(self, tmp_path, monkeypatch):
        # If the env var isn't set, we can't enforce; allow + log nothing.
        # (The wider campaign won't have wired up the hook in this case.)
        monkeypatch.delenv("NOUS_ITER_DIR", raising=False)
        rc = _run_hook(
            _hook_event("./blis run", str(tmp_path)),
            env={},
            monkeypatch=monkeypatch,
        )
        assert rc == 0

    def test_non_bash_tool_call_is_ignored(self, tmp_path, monkeypatch):
        _write_plan(tmp_path, [{
            "arm_id": "h-main",
            "conditions": [{"name": "x", "command": "./blis run"}],
        }])
        # Read tool — not Bash; should pass through.
        payload = json.dumps({
            "session_id": "t",
            "tool_name": "Read",
            "tool_input": {"file_path": "/etc/passwd"},
            "cwd": str(tmp_path),
        })
        rc = _run_hook(
            payload,
            env={
                "NOUS_ITER_DIR": str(tmp_path),
                "NOUS_PLAN_ENFORCEMENT": "strict",
            },
            monkeypatch=monkeypatch,
        )
        assert rc == 0
        assert _read_violations(tmp_path) == []
