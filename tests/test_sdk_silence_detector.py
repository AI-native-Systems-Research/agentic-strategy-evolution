"""Behavioral tests for the SDK silence detector (#201).

After each SDK turn the dispatcher walks the streaming executor_log.jsonl,
finds the longest gap between consecutive events, and (if the gap
exceeds ``campaign.sdk_timeouts.silence_threshold_seconds``) writes a
``failure_type: "sdk_silence"`` entry to retry_log.jsonl.

Observation-only today — doesn't interrupt or fail the turn. The hard-kill
on prolonged silence is a future addition (issue body's stretch goal).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ─── summarize_silence_gaps helper ─────────────────────────────────────


# ─── End-to-end: silence triggers retry_log entry ─────────────────────


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


# ─── Schema accepts the sdk_timeouts block ────────────────────────────


class TestSdkTimeoutsSchema:
    def test_accepts_silence_threshold(self) -> None:
        import jsonschema, yaml
        SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"
        schema = yaml.safe_load((SCHEMAS_DIR / "campaign.schema.yaml").read_text())
        campaign = {
            "research_question": "q",
            "target_system": {"name": "x", "description": "d"},
            "prompts": {"methodology_layer": "p"},
            "sdk_timeouts": {"silence_threshold_seconds": 1200},
        }
        jsonschema.validate(campaign, schema)

    def test_rejects_negative_threshold(self) -> None:
        import jsonschema, yaml
        SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"
        schema = yaml.safe_load((SCHEMAS_DIR / "campaign.schema.yaml").read_text())
        campaign = {
            "research_question": "q",
            "target_system": {"name": "x", "description": "d"},
            "prompts": {"methodology_layer": "p"},
            "sdk_timeouts": {"silence_threshold_seconds": -1},
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(campaign, schema)
