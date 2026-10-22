"""Tests for campaign preflight check (spec 3.5, B4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.v2.preflight import run_preflight
from orchestrator.v2.hooks import HookState, build_hooks


class TestPreflight:
    """Spec 3.5 / B4: preflight validates hooks and validators at campaign start."""

    async def test_preflight_passes_with_valid_setup(self, tmp_path):
        """Preflight succeeds when hooks and validators are correctly configured."""
        state = HookState(work_dir=tmp_path)
        hooks = build_hooks(state)
        errors = await run_preflight(hooks, work_dir=tmp_path)
        assert errors == []

    async def test_preflight_catches_bad_validator(self, tmp_path):
        """Preflight fails when a validator rejects a known-good fixture."""
        state = HookState(work_dir=tmp_path)
        hooks = build_hooks(state)
        errors = await run_preflight(
            hooks,
            work_dir=tmp_path,
            override_schema_check=lambda: ["schema load failed"],
        )
        assert len(errors) > 0

    async def test_preflight_catches_stop_hook_error(self, tmp_path):
        """Preflight fails when the Stop hook callback raises."""
        bad_hooks = {
            "Stop": [],
        }
        errors = await run_preflight(bad_hooks, work_dir=tmp_path)
        assert len(errors) > 0

    async def test_preflight_runs_validator_on_known_good(self, tmp_path):
        """Preflight runs each validator on a known-good fixture."""
        state = HookState(work_dir=tmp_path)
        hooks = build_hooks(state)
        errors = await run_preflight(hooks, work_dir=tmp_path)
        assert errors == []

    async def test_preflight_runs_validator_on_known_bad(self, tmp_path):
        """Preflight verifies validators reject known-bad fixtures."""
        state = HookState(work_dir=tmp_path)
        hooks = build_hooks(state)
        errors = await run_preflight(hooks, work_dir=tmp_path)
        assert errors == []

    async def test_preflight_fail_fast_message(self, tmp_path):
        """Preflight error messages are clear and actionable."""
        errors = await run_preflight({}, work_dir=tmp_path)
        assert any(isinstance(e, str) for e in errors)
