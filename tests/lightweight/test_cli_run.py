"""The `nous` CLI drives Lightweight campaigns.

No real client is ever built: ``orchestrator.cli._sdk_client`` is the
client-factory seam and every test replaces it with a FakeClient factory.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest
import yaml

from orchestrator import cli
from orchestrator.lightweight.config import parse_campaign_config
from orchestrator.lightweight.loop import Campaign, method_text
from orchestrator.lightweight.session import DEFAULT_MODEL
from tests.fakes.sdk_client import FakeClient, FakeResultMessage

REPO_ROOT = Path(__file__).resolve().parents[2]


def _nous(monkeypatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["nous", *argv])
    try:
        cli.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _write_campaign(tmp_path: Path, **extra) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    raw = {
        "research_question": "Is the bug fixable?",
        "run_id": "cli-run",
        "max_iterations": 1,
        "target_system": {"name": "t", "repo_path": str(repo)},
        **extra,
    }
    path = tmp_path / "campaign.yaml"
    path.write_text(yaml.safe_dump(raw))
    return path


def _answer_files(work_dir: Path) -> dict:
    return {str(work_dir / "r.json"): '{"p99": 40}',
            str(work_dir / "answer.json"): json.dumps({
                "answer": "Yes.", "deliverable": "fix.patch", "repro": "python bench.py",
                "claims": [{"id": "C1", "metric": "p99", "value": 40, "condition": "fixed",
                            "evidence": {"path": "r.json", "key": "/p99", "value": 40}}]})}


@pytest.fixture
def campaigns(tmp_path, monkeypatch) -> Path:
    parent = tmp_path / "campaigns"
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(parent))
    return parent


@pytest.fixture
def fake_factory(monkeypatch):
    """Install a FakeClient factory: the agent writes a valid answer; the reviewer finds no gap."""
    built: list = []

    def install(work_dir: Path):
        def factory(opts):
            built.append(opts)
            if opts.model == "claude-sonnet-5-5" and opts.disallowed_tools:  # the challenger
                msg = FakeResultMessage(session_id="rev")
                msg.result = '{"gap": false, "why": "settled"}'
                return FakeClient(script=[msg])
            return FakeClient(script=[FakeResultMessage(session_id="ses-1")] * 3,
                              per_turn_files=[_answer_files(work_dir)])
        monkeypatch.setattr(cli, "_sdk_client", factory)
        return built

    return install


# ── nous run ─────────────────────────────────────────────────────────────


class TestRun:
    def test_run_drives_a_campaign(self, tmp_path, campaigns, fake_factory, monkeypatch, capsys):
        path = _write_campaign(tmp_path, task_type="debug")
        work_dir = campaigns / "cli-run"
        built = fake_factory(work_dir)

        assert _nous(monkeypatch, "run", str(path), "--model", "claude-sonnet-4-5-20250514") == 0

        ledger = json.loads((work_dir / "ledger.json").read_text())
        assert ledger[0]["status"] == "ok"
        assert (work_dir / "final_check.json").exists()
        assert yaml.safe_load((work_dir / "campaign.yaml").read_text())["run_id"] == "cli-run"
        assert "answered" in capsys.readouterr().out
        opts = built[0]
        assert opts.model == "claude-sonnet-4-5-20250514"
        assert opts.system_prompt["append"] == method_text("debug")

    def test_nous_version_key_is_accepted_and_ignored(self, tmp_path, campaigns, fake_factory, monkeypatch):
        for version in (2, 3):
            path = _write_campaign(tmp_path, nous_version=version, run_id=f"v{version}")
            fake_factory(campaigns / f"v{version}")
            assert _nous(monkeypatch, "run", str(path)) == 0
            assert json.loads((campaigns / f"v{version}" / "ledger.json").read_text())[0]["status"] == "ok"

    def test_run_refuses_existing_state(self, tmp_path, campaigns, fake_factory, monkeypatch, capsys):
        path = _write_campaign(tmp_path)
        work_dir = campaigns / "cli-run"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text('{"phase": "INVESTIGATE", "iteration": 1}')
        fake_factory(work_dir)

        assert _nous(monkeypatch, "run", str(path)) == 1
        assert "nous resume" in capsys.readouterr().err
        assert not (work_dir / "campaign.yaml").exists()
        assert not (work_dir / "ledger.json").exists()

    def test_invalid_campaign_exits_cleanly_without_work_dir(
        self, tmp_path, campaigns, monkeypatch, capsys,
    ):
        path = tmp_path / "campaign.yaml"
        path.write_text(yaml.safe_dump({"run_id": "bad", "target_system": {"name": "t"}}))
        assert _nous(monkeypatch, "run", str(path)) == 1
        assert "Campaign validation error" in capsys.readouterr().err
        assert not (campaigns / "bad").exists()

    def test_model_override_saved_for_resume(self, tmp_path, campaigns, fake_factory, monkeypatch):
        path = _write_campaign(tmp_path)
        work_dir = campaigns / "cli-run"
        fake_factory(work_dir)
        assert _nous(monkeypatch, "run", str(path), "--model", "claude-sonnet-4-5-20250514") == 0
        saved = yaml.safe_load((work_dir / "campaign.yaml").read_text())
        assert saved["models"]["session"] == "claude-sonnet-4-5-20250514"

    def test_run_id_flag_and_max_iterations(self, tmp_path, campaigns, fake_factory, monkeypatch):
        path = _write_campaign(tmp_path, max_iterations=7)
        work_dir = campaigns / "other-id"
        fake_factory(work_dir)

        assert _nous(monkeypatch, "run", str(path), "--run-id", "other-id",
                     "--max-iterations", "1") == 0
        saved = yaml.safe_load((work_dir / "campaign.yaml").read_text())
        assert saved["max_iterations"] == 1
        assert saved["run_id"] == "other-id"

    def test_removed_flags_are_rejected(self, tmp_path, campaigns, monkeypatch):
        """Old flags are gone: argparse rejects them (exit 2) instead of silently ignoring them."""
        path = _write_campaign(tmp_path)
        for flag in (["--v3"], ["--agent", "sdk"], ["--auto-approve"], ["--timeout", "5"],
                     ["--max-cli-retries", "1"], ["--sandbox", "default"], ["--bundle", "b.yaml"]):
            assert _nous(monkeypatch, "run", str(path), *flag) == 2


# ── nous resume ──────────────────────────────────────────────────────────


class TestResume:
    def test_resume_without_state_errors(self, tmp_path, monkeypatch, capsys):
        work_dir = tmp_path / "wd"
        work_dir.mkdir()
        assert _nous(monkeypatch, "resume", str(work_dir)) == 1
        assert "state.json" in capsys.readouterr().err

    def test_resume_work_dir_with_note(self, tmp_path, fake_factory, monkeypatch, capsys):
        path = _write_campaign(tmp_path)
        work_dir = tmp_path / "wd"
        work_dir.mkdir()
        (work_dir / "campaign.yaml").write_text(path.read_text())
        (work_dir / "state.json").write_text(json.dumps(
            {"phase": "INVESTIGATE", "iteration": 1, "session_id": "ses-old"}))
        fake_factory(work_dir)
        queries: list = []
        factory = cli._sdk_client

        def spy(opts):
            client = factory(opts)
            original = client.query

            async def query(prompt):
                queries.append((opts.resume, prompt))
                await original(prompt)
            client.query = query
            return client
        monkeypatch.setattr(cli, "_sdk_client", spy)

        assert _nous(monkeypatch, "resume", str(work_dir), "--note", "check X") == 0
        assert queries[0][0] == "ses-old"
        assert queries[0][1].endswith("Human note: check X")
        assert json.loads((work_dir / "ledger.json").read_text())[0]["status"] == "ok"


# ── campaign.yaml keys ───────────────────────────────────────────────────


def _raw(**extra) -> dict:
    return {
        "research_question": "q",
        "target_system": {"name": "t", "repo_path": "/tmp/r"},
        **extra,
    }


class TestCampaignKeys:
    def test_unknown_and_legacy_keys_warn_and_are_ignored(self, caplog):
        with caplog.at_level(logging.WARNING):
            cfg = parse_campaign_config(_raw(
                critic=True, pre_work={}, arm_sweep=[], parallel_arms=2,
                iteration_mode="evolve", prompts={}, sandbox="bypass", made_up_key=1,
            ))
        text = " ".join(r.getMessage() for r in caplog.records)
        for key in ("critic", "pre_work", "arm_sweep", "parallel_arms",
                    "iteration_mode", "prompts", "sandbox", "made_up_key"):
            assert key in text
        assert cfg.research_question == "q"

    def test_known_keys_do_not_warn(self, caplog):
        with caplog.at_level(logging.WARNING):
            cfg = parse_campaign_config(_raw(
                run_id="r", max_iterations=2, models={"session": "m1", "design": "m2"},
                locked_parameters={"rate": 20}, locked_workload={"n": 5},
                effort="high", human_gates=False, secrets=["S"], experiment_commands=["x"],
                objective={"metric": "m", "direction": "increase"}, min_improvement=1,
                stall_iterations=3, session_scope="campaign", task_limits={"max_runs": 3},
                task_type="debug", rerun_repro=True, nous_version=3,
            ))
        assert not caplog.records
        assert cfg.model == "m1"
        assert cfg.effort == "high" and cfg.secrets == ["S"] and cfg.task_type == "debug"

    @pytest.mark.parametrize(
        "path", sorted(p for ext in ("yaml", "yml") for p in (REPO_ROOT / "examples").rglob(f"*.{ext}")),
        ids=lambda p: str(p.relative_to(REPO_ROOT)),
    )
    def test_every_example_loads_with_warnings_only(self, path):
        cfg = parse_campaign_config(yaml.safe_load(path.read_text()))
        assert cfg.research_question


# ── Session wiring (method text, model) ──────────────────────────────────


class _Captured(Exception):
    pass


async def _captured_options(tmp_path, raw: dict):
    seen: list = []

    def factory(opts):
        seen.append(opts)
        raise _Captured

    work_dir = tmp_path / "wd"
    work_dir.mkdir(exist_ok=True)
    with pytest.raises(_Captured):
        await Campaign(parse_campaign_config(raw), work_dir, client_factory=factory).run()
    return seen[0]


class TestSessionWiring:
    async def test_method_text_appended(self, tmp_path):
        opts = await _captured_options(tmp_path, _raw(task_type="optimize"))
        assert opts.system_prompt["append"] == method_text("optimize")
        assert "notebook.jsonl" in opts.system_prompt["append"]

    @pytest.mark.parametrize("models,expected", [
        ({"session": "m-session", "design": "m-design"}, "m-session"),
        ({"design": "m-design", "execute_analyze": "x"}, "m-design"),
        (None, DEFAULT_MODEL),
    ])
    async def test_model_precedence(self, tmp_path, models, expected):
        raw = _raw() if models is None else _raw(models=models)
        opts = await _captured_options(tmp_path, raw)
        assert opts.model == expected


# ── Other commands ───────────────────────────────────────────────────────


def _work_dir_with_ledger(tmp_path: Path) -> Path:
    work_dir = tmp_path / "wd"
    work_dir.mkdir()
    (work_dir / "state.json").write_text(json.dumps(
        {"phase": "DONE", "iteration": 1, "session_id": "ses-42"}))
    (work_dir / "ledger.json").write_text(json.dumps([
        {"iteration": 1, "status": "partial", "stop_reason": "partial", "cost_meter_usd": 0.85,
         "tokens": {"input": 300, "output": 30}},
    ]))
    return work_dir


class TestOtherCommands:
    def test_status(self, tmp_path, monkeypatch, capsys):
        work_dir = _work_dir_with_ledger(tmp_path)
        assert _nous(monkeypatch, "status", str(work_dir)) == 0
        out = capsys.readouterr().out
        for text in ("DONE", "ses-42", "status=partial"):
            assert text in out

    def test_cost(self, tmp_path, monkeypatch, capsys):
        work_dir = _work_dir_with_ledger(tmp_path)
        assert _nous(monkeypatch, "cost", str(work_dir)) == 0
        out = capsys.readouterr().out
        assert "$0.8500" in out
        assert "330" in out

    @pytest.mark.parametrize("command", ["schema", "validate", "stop", "report", "replay", "lineage"])
    def test_removed_commands(self, tmp_path, monkeypatch, capsys, command):
        assert _nous(monkeypatch, command, str(tmp_path)) == 2
        assert "invalid choice" in capsys.readouterr().err
