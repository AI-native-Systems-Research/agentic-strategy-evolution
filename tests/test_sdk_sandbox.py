"""Behavioral tests for SDK sandbox configuration (#193).

Pre-#193: the SDK sandbox blocked BLIS subprocess writes outside cwd.
The friction-test workaround hardcoded ``permission_mode="bypassPermissions"``.
After #193 the bypass is configurable via ``campaign.sandbox`` (default
``bypass``, with ``default`` as the explicit opt-out) and overridable
via ``nous run --sandbox``.

These tests don't spawn the real SDK — they inject a fake sdk_runner
that captures the kwargs it received, including ``permission_mode``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.sdk_dispatch import SDKDispatcher, SDKResult


class _CapturingRunner:
    def __init__(self):
        self.kwargs: dict | None = None

    def __call__(self, **kwargs) -> SDKResult:
        self.kwargs = kwargs
        return SDKResult(text="ok")


def _campaign(repo_path: Path, **extra) -> dict:
    return {
        "research_question": "?",
        "target_system": {
            "name": "t",
            "description": "d",
            "repo_path": str(repo_path),
        },
        **extra,
    }


class TestSandboxDefault:
    def test_default_passes_bypass_permissions(self, tmp_path: Path) -> None:
        """#193: campaigns get bypassPermissions by default — without it,
        BLIS subprocess writes outside cwd silently fail."""
        runner = _CapturingRunner()
        d = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_campaign(tmp_path),
            sdk_runner=runner,
        )
        d.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-1" / "design_log.md",
            iteration=1,
        )
        assert runner.kwargs is not None
        assert runner.kwargs.get("permission_mode") == "bypassPermissions"


class TestSandboxOptOut:
    def test_campaign_sandbox_default_disables_bypass(self, tmp_path: Path) -> None:
        """campaign.sandbox='default' means: don't bypass; let the SDK
        apply its default permission gating. permission_mode passed to
        the runner is None."""
        runner = _CapturingRunner()
        d = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_campaign(tmp_path, sandbox="default"),
            sdk_runner=runner,
        )
        d.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-1" / "design_log.md",
            iteration=1,
        )
        assert runner.kwargs is not None
        assert runner.kwargs.get("permission_mode") is None

    def test_explicit_bypass_round_trips(self, tmp_path: Path) -> None:
        """campaign.sandbox='bypass' is the same as the default, just
        explicit — useful for documentation."""
        runner = _CapturingRunner()
        d = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_campaign(tmp_path, sandbox="bypass"),
            sdk_runner=runner,
        )
        d.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-1" / "design_log.md",
            iteration=1,
        )
        assert runner.kwargs is not None
        assert runner.kwargs.get("permission_mode") == "bypassPermissions"


class TestSandboxKwargOverride:
    def test_explicit_sandbox_kwarg_wins_over_campaign(self, tmp_path: Path) -> None:
        """The CLI flag --sandbox flows through to the SDKDispatcher
        constructor's ``sandbox`` kwarg, which overrides campaign.sandbox."""
        runner = _CapturingRunner()
        d = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_campaign(tmp_path, sandbox="default"),
            sandbox="bypass",  # explicit kwarg beats campaign value
            sdk_runner=runner,
        )
        d.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-1" / "design_log.md",
            iteration=1,
        )
        assert runner.kwargs is not None
        assert runner.kwargs.get("permission_mode") == "bypassPermissions"


class TestSandboxValidation:
    def test_invalid_sandbox_value_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="must be 'bypass' or 'default'"):
            SDKDispatcher(
                work_dir=tmp_path,
                campaign=_campaign(tmp_path, sandbox="off"),
                sdk_runner=_CapturingRunner(),
            )

    def test_invalid_sandbox_kwarg_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="must be 'bypass' or 'default'"):
            SDKDispatcher(
                work_dir=tmp_path,
                campaign=_campaign(tmp_path),
                sandbox="permissive",
                sdk_runner=_CapturingRunner(),
            )


class TestCmdRunSandboxFlag:
    """End-to-end (#193): the --sandbox CLI flag mutates campaign["sandbox"]
    before run_campaign sees it, so SDKDispatcher reads the override.
    A regression that drops the mutation at orchestrator/cli.py would
    not be caught by the constructor-kwarg unit tests alone."""

    def test_cli_flag_overrides_campaign_sandbox(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        import argparse
        from orchestrator import cli as cli_mod
        from orchestrator import campaign as campaign_mod

        repo = tmp_path / "myrepo"
        repo.mkdir()
        campaign_file = tmp_path / "campaign.yaml"
        campaign_file.write_text(
            "run_id: demo\n"
            "max_iterations: 1\n"
            "research_question: q\n"
            f"target_system:\n  name: t\n  description: d\n  repo_path: {repo}\n"
            "prompts:\n  methodology_layer: p\n"
            "sandbox: bypass\n"  # campaign says bypass, CLI will override
        )
        captured: dict = {}
        monkeypatch.setattr(
            campaign_mod, "run_campaign",
            lambda campaign, *a, **kw: captured.update(
                campaign=campaign, **kw,
            ),
        )

        args = argparse.Namespace(
            campaign=str(campaign_file), max_iterations=1, model=None,
            run_id=None, auto_approve=True, timeout=1800,
            max_cli_retries=10, agent="sdk", sandbox="default",
            bundle=None, problem_md=None, handoff_md=None, verbose=False,
        )
        cli_mod._cmd_run(args)
        # CLI flag mutated campaign["sandbox"] from "bypass" → "default".
        assert captured["campaign"]["sandbox"] == "default"

    def test_cli_flag_absent_preserves_campaign_sandbox(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """When --sandbox is not passed, campaign.yaml's value should
        flow through unchanged."""
        import argparse
        from orchestrator import cli as cli_mod
        from orchestrator import campaign as campaign_mod

        repo = tmp_path / "myrepo"
        repo.mkdir()
        campaign_file = tmp_path / "campaign.yaml"
        campaign_file.write_text(
            "run_id: demo\n"
            "max_iterations: 1\n"
            "research_question: q\n"
            f"target_system:\n  name: t\n  description: d\n  repo_path: {repo}\n"
            "prompts:\n  methodology_layer: p\n"
            "sandbox: default\n"
        )
        captured: dict = {}
        monkeypatch.setattr(
            campaign_mod, "run_campaign",
            lambda campaign, *a, **kw: captured.update(campaign=campaign),
        )
        args = argparse.Namespace(
            campaign=str(campaign_file), max_iterations=1, model=None,
            run_id=None, auto_approve=True, timeout=1800,
            max_cli_retries=10, agent="sdk", sandbox=None,
            bundle=None, problem_md=None, handoff_md=None, verbose=False,
        )
        cli_mod._cmd_run(args)
        # No CLI flag → campaign.yaml's value preserved.
        assert captured["campaign"]["sandbox"] == "default"


class TestSandboxSchema:
    def test_campaign_yaml_accepts_sandbox_bypass(self) -> None:
        import jsonschema, yaml
        SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"
        schema = yaml.safe_load((SCHEMAS_DIR / "campaign.schema.yaml").read_text())
        campaign = {
            "research_question": "q",
            "target_system": {"name": "x", "description": "d"},
            "prompts": {"methodology_layer": "p"},
            "sandbox": "bypass",
        }
        jsonschema.validate(campaign, schema)

    def test_campaign_yaml_accepts_sandbox_default(self) -> None:
        import jsonschema, yaml
        SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"
        schema = yaml.safe_load((SCHEMAS_DIR / "campaign.schema.yaml").read_text())
        campaign = {
            "research_question": "q",
            "target_system": {"name": "x", "description": "d"},
            "prompts": {"methodology_layer": "p"},
            "sandbox": "default",
        }
        jsonschema.validate(campaign, schema)

    def test_campaign_yaml_rejects_unknown_sandbox(self) -> None:
        import jsonschema, yaml
        SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"
        schema = yaml.safe_load((SCHEMAS_DIR / "campaign.schema.yaml").read_text())
        campaign = {
            "research_question": "q",
            "target_system": {"name": "x", "description": "d"},
            "prompts": {"methodology_layer": "p"},
            "sandbox": "lockdown",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(campaign, schema)
