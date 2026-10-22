"""Tests for wait_for polling (spec 3.2 step 4)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from orchestrator.v2.robustness import poll_wait_for


class TestWaitForPolling:
    """Spec 3.2 step 4: poll wait_for every 60s with no model calls."""

    def test_file_wait_for_succeeds_immediately(self, tmp_path):
        """wait_for file that already exists returns immediately."""
        target = tmp_path / "done.txt"
        target.write_text("done")
        result = poll_wait_for(
            str(target), poll_interval=0.01, timeout=1.0
        )
        assert result is True

    def test_file_wait_for_waits_then_succeeds(self, tmp_path):
        """wait_for file that appears after a delay."""
        target = tmp_path / "done.txt"
        call_count = [0]
        original_exists = Path.exists

        def delayed_exists(self_path):
            if str(self_path) == str(target):
                call_count[0] += 1
                if call_count[0] >= 3:
                    target.write_text("done")
                    return True
                return False
            return original_exists(self_path)

        with patch.object(Path, "exists", delayed_exists):
            result = poll_wait_for(
                str(target), poll_interval=0.01, timeout=2.0
            )
        assert result is True

    def test_file_wait_for_times_out(self, tmp_path):
        """wait_for file that never appears returns False on timeout."""
        target = tmp_path / "never.txt"
        result = poll_wait_for(
            str(target), poll_interval=0.01, timeout=0.05
        )
        assert result is False

    def test_command_wait_for_succeeds(self, tmp_path):
        """wait_for command that exits 0."""
        result = poll_wait_for(
            "cmd:true", poll_interval=0.01, timeout=1.0
        )
        assert result is True

    def test_command_wait_for_fails_then_succeeds(self, tmp_path):
        """wait_for command that fails initially then succeeds."""
        counter_file = tmp_path / "counter"
        counter_file.write_text("0")
        # Command that succeeds on 3rd call
        cmd = f"cmd:python3 -c \"p=__import__('pathlib').Path('{counter_file}'); n=int(p.read_text())+1; p.write_text(str(n)); exit(0 if n>=3 else 1)\""
        result = poll_wait_for(
            cmd, poll_interval=0.01, timeout=2.0
        )
        assert result is True

    def test_command_wait_for_times_out(self, tmp_path):
        """wait_for command that never succeeds."""
        result = poll_wait_for(
            "cmd:false", poll_interval=0.01, timeout=0.05
        )
        assert result is False

    def test_no_model_calls_during_polling(self, tmp_path):
        """Polling must not invoke any SDK/LLM calls."""
        # This is structural by design: poll_wait_for is a pure function
        # that does file/subprocess checks only. Verify it doesn't import
        # or call any SDK module.
        target = tmp_path / "done.txt"
        target.write_text("done")
        # If poll_wait_for tried to use SDK, conftest guards would catch it
        result = poll_wait_for(
            str(target), poll_interval=0.01, timeout=1.0
        )
        assert result is True

    def test_pending_wait_for_not_validation_failure(self, tmp_path):
        """A plan entry with wait_for that hasn't completed is not a validation error."""
        # This tests the integration: the stop hook should not block
        # when a run has a pending wait_for
        plan = {
            "runs": [
                {
                    "id": "r1",
                    "hypothesis_id": "h1",
                    "role": "treatment",
                    "command": "long_job.sh",
                    "parameters": {},
                    "seeds": [1],
                    "wait_for": str(tmp_path / "not_yet.txt"),
                },
            ],
        }
        # The plan is valid despite wait_for not being satisfied yet
        from orchestrator.v2.validators import validate_artifact, ValidatorContext
        ctx = ValidatorContext(work_dir=tmp_path)
        errors = validate_artifact("plan", plan, ctx)
        assert not any("wait_for" in e for e in errors)
