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
