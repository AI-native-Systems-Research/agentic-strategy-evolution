"""CLI cutover to v2 (spec section 4, plan item R11a).

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
from orchestrator.v2.config import parse_campaign_config
from orchestrator.v2.loop import Campaign
from orchestrator.v2.prompts import build_system_prompt
from orchestrator.v2.session import DEFAULT_MODEL
from tests.fakes.sdk_client import FakeClient
from tests.v2.test_loop import (
    _build_per_turn_files,
    _bundle,
    _make_script,
    _plan,
    _problem,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _valid_bundle() -> dict:
    bundle = _bundle()
    for h in bundle["hypotheses"]:
        h["control"] = "unfixed code"
    return bundle


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


@pytest.fixture
def campaigns(tmp_path, monkeypatch) -> Path:
    parent = tmp_path / "campaigns"
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(parent))
    return parent


@pytest.fixture
def fake_factory(monkeypatch):
    """Install a FakeClient factory that scripts one full iteration."""
    built: list = []

    def install(work_dir: Path):
        def factory(opts):
            built.append(opts)
            return FakeClient(
                script=_make_script(4),
                per_turn_files=_build_per_turn_files(work_dir),
            )
        monkeypatch.setattr(cli, "_sdk_client", factory)
        return built

    return install


# ── nous run ─────────────────────────────────────────────────────────────


class TestRun:
    def test_run_drives_v2_campaign(self, tmp_path, campaigns, fake_factory, monkeypatch, capsys):
        path = _write_campaign(tmp_path, task_type="debug")
        work_dir = campaigns / "cli-run"
        built = fake_factory(work_dir)

        assert _nous(monkeypatch, "run", str(path), "--model", "claude-sonnet-4-5-20250514") == 0

        ledger = json.loads((work_dir / "ledger.json").read_text())
        assert ledger[0]["status"] == "ok"
        assert (work_dir / "answer.json").exists()
        assert yaml.safe_load((work_dir / "campaign.yaml").read_text())["run_id"] == "cli-run"
        assert "answered" in capsys.readouterr().out
        opts = built[0]
        assert opts.model == "claude-sonnet-4-5-20250514"
        assert opts.system_prompt["append"] == build_system_prompt("debug")

    def test_run_refuses_existing_state(self, tmp_path, campaigns, fake_factory, monkeypatch, capsys):
        path = _write_campaign(tmp_path)
        work_dir = campaigns / "cli-run"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text('{"phase": "DESIGN", "iteration": 1}')
        built = fake_factory(work_dir)

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

    def test_agent_and_legacy_flags_warn_and_are_ignored(
        self, tmp_path, campaigns, fake_factory, monkeypatch, capsys,
    ):
        path = _write_campaign(tmp_path)
        work_dir = campaigns / "cli-run"
        fake_factory(work_dir)

        code = _nous(monkeypatch, "run", str(path), "--agent", "inline", "--auto-approve",
                     "--timeout", "5", "--max-cli-retries", "1", "--sandbox", "default")
        assert code == 0
        err = capsys.readouterr().err
        for flag in ("--agent", "--auto-approve", "--timeout", "--max-cli-retries", "--sandbox"):
            assert flag in err
        assert "ignored" in err
        assert (work_dir / "answer.json").exists()

    def test_v1_bundle_flag_removed(self, tmp_path, campaigns, monkeypatch):
        path = _write_campaign(tmp_path)
        assert _nous(monkeypatch, "run", str(path), "--bundle", "b.yaml") == 2


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
            {"phase": "BASELINE", "iteration": 0, "session_id": "ses-old"}))
        built = fake_factory(work_dir)

        assert _nous(monkeypatch, "resume", str(work_dir), "--note", "check X",
                     "--agent", "sdk") == 0
        ledger = json.loads((work_dir / "ledger.json").read_text())
        assert ledger[0]["note"] == "check X"
        assert built[0].resume == "ses-old"
        assert "--agent" in capsys.readouterr().err


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
                task_type="debug", rerun_repro=True,
            ))
        assert not caplog.records
        assert cfg.rerun_repro is True
        assert cfg.locked_parameters == {"rate": 20}
        assert cfg.locked_workload == {"n": 5}
        assert cfg.model == "m1"

    def test_rerun_repro_defaults_false(self):
        assert parse_campaign_config(_raw()).rerun_repro is False

    @pytest.mark.parametrize(
        "path", sorted(p for ext in ("yaml", "yml") for p in (REPO_ROOT / "examples").rglob(f"*.{ext}")),
        ids=lambda p: str(p.relative_to(REPO_ROOT)),
    )
    def test_every_example_loads_with_warnings_only(self, path):
        cfg = parse_campaign_config(yaml.safe_load(path.read_text()))
        assert cfg.research_question


# ── Session wiring (method text, model, locked params through hooks) ─────


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
        assert opts.system_prompt["append"] == build_system_prompt("optimize")
        assert opts.system_prompt["append"]

    @pytest.mark.parametrize("models,expected", [
        ({"session": "m-session", "design": "m-design"}, "m-session"),
        ({"design": "m-design", "execute_analyze": "x"}, "m-design"),
        (None, DEFAULT_MODEL),
    ])
    async def test_model_precedence(self, tmp_path, models, expected):
        raw = _raw() if models is None else _raw(models=models)
        opts = await _captured_options(tmp_path, raw)
        assert opts.model == expected

    async def test_locked_parameters_rejected_through_stop_hook(self, tmp_path):
        """A plan deviating from campaign.locked_parameters is blocked by the
        Stop hook the Campaign wires into the session options."""
        work_dir = tmp_path / "wd"
        work_dir.mkdir()
        raw = _raw(max_iterations=1, locked_parameters={"rate": 20})
        plan = _plan()
        for run in plan["runs"]:
            run["parameters"] = {"rate": 30}
        per_turn = _build_per_turn_files(work_dir)
        idir = work_dir / "runs" / "iter-1"
        per_turn[1] = {
            str(idir / "problem.json"): json.dumps(_problem()),
            str(idir / "bundle.json"): json.dumps(_valid_bundle()),
            str(idir / "plan.json"): json.dumps(plan),
        }
        decisions: list[dict | None] = []

        class StopHookClient(FakeClient):
            async def receive_response(self):
                async for msg in super().receive_response():
                    yield msg
                decisions.append(await self._run_event_hooks("Stop", {"stop_reason": "end_turn"}))

        def factory(opts):
            return StopHookClient(script=_make_script(4), per_turn_files=per_turn, hooks=opts.hooks)

        await Campaign(parse_campaign_config(raw), work_dir, client_factory=factory).run()

        design = decisions[1]
        assert design is not None and design.get("decision") == "block"
        reason = json.dumps(design)
        assert "deviates from locked value 20" in reason
        assert "control" not in reason  # rejected for the lock, not the bundle
        assert decisions[0] is None  # BASELINE was valid


# ── Other commands ───────────────────────────────────────────────────────


def _work_dir_with_ledger(tmp_path: Path) -> Path:
    work_dir = tmp_path / "wd"
    work_dir.mkdir()
    (work_dir / "state.json").write_text(json.dumps(
        {"phase": "REPORT", "iteration": 2, "session_id": "ses-42"}))
    (work_dir / "ledger.json").write_text(json.dumps([
        {"iteration": 1, "status": "ok", "stop_reason": None, "cost_meter_usd": 0.25,
         "tokens": {"input": 100, "output": 10}},
        {"iteration": 2, "status": "partial", "stop_reason": "answered", "cost_meter_usd": 0.5,
         "report_cost_usd": 0.1,
         "tokens": {"input": 200, "output": 20}},
    ]))
    return work_dir


class TestOtherCommands:
    def test_status(self, tmp_path, monkeypatch, capsys):
        work_dir = _work_dir_with_ledger(tmp_path)
        assert _nous(monkeypatch, "status", str(work_dir)) == 0
        out = capsys.readouterr().out
        for text in ("REPORT", "ses-42", "partial", "answered"):
            assert text in out

    def test_cost(self, tmp_path, monkeypatch, capsys):
        work_dir = _work_dir_with_ledger(tmp_path)
        assert _nous(monkeypatch, "cost", str(work_dir)) == 0
        out = capsys.readouterr().out
        assert "$0.8500" in out
        assert "330" in out

    def test_validate_design_pass_and_fail(self, tmp_path, monkeypatch, capsys):
        idir = tmp_path / "wd" / "runs" / "iter-1"
        idir.mkdir(parents=True)
        (idir / "problem.json").write_text(json.dumps(_problem()))
        (idir / "bundle.json").write_text(json.dumps(_valid_bundle()))
        assert _nous(monkeypatch, "validate", "design", "--dir", str(idir)) == 1
        assert "plan" in capsys.readouterr().out
        (idir / "plan.json").write_text(json.dumps(_plan()))
        assert _nous(monkeypatch, "validate", "design", "--dir", str(idir)) == 0
        assert json.loads(capsys.readouterr().out)["status"] == "pass"

    def test_validate_applies_campaign_locks(self, tmp_path, monkeypatch, capsys):
        work_dir = tmp_path / "wd"
        idir = work_dir / "runs" / "iter-1"
        idir.mkdir(parents=True)
        (work_dir / "campaign.yaml").write_text(yaml.safe_dump(
            _raw(locked_parameters={"rate": 20})))
        plan = _plan()
        for run in plan["runs"]:
            run["parameters"] = {"rate": 30}
        (idir / "problem.json").write_text(json.dumps(_problem()))
        (idir / "bundle.json").write_text(json.dumps(_valid_bundle()))
        (idir / "plan.json").write_text(json.dumps(plan))
        assert _nous(monkeypatch, "validate", "design", "--dir", str(idir)) == 1
        assert "locked value 20" in capsys.readouterr().out

    def test_schema_serves_v2(self, monkeypatch, capsys):
        assert _nous(monkeypatch, "schema", "plan", "--format", "json") == 0
        expected = json.loads((REPO_ROOT / "orchestrator/v2/schemas/plan.schema.json").read_text())
        assert json.loads(capsys.readouterr().out) == expected
        assert _nous(monkeypatch, "schema", "bundle") == 0
        assert "hypotheses" in capsys.readouterr().out

    @pytest.mark.parametrize("command", ["report", "replay"])
    def test_v1_only_commands_deprecated(self, tmp_path, monkeypatch, capsys, command):
        argv = [command, str(tmp_path)] + (["--iter", "1"] if command == "replay" else [])
        assert _nous(monkeypatch, *argv) == 1
        assert "removed in Nous v2" in capsys.readouterr().err
