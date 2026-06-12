"""Tests for per-phase SDK effort resolution + schema (#282)."""
from __future__ import annotations

from pathlib import Path

import pytest


def _effort_for(campaign: dict, phase_key: str) -> str | None:
    """Standalone equivalent of the iteration.py closure — pins the contract."""
    phase = (campaign.get("sdk_options", {}) or {}).get(phase_key) or {}
    return phase.get("effort")


class TestEffortResolution:
    def test_returns_configured_effort(self):
        campaign = {"sdk_options": {"execute_analyze": {"effort": "medium"}}}
        assert _effort_for(campaign, "execute_analyze") == "medium"

    def test_none_when_stanza_absent(self):
        assert _effort_for({}, "design") is None

    def test_none_when_phase_absent(self):
        campaign = {"sdk_options": {"design": {"effort": "high"}}}
        assert _effort_for(campaign, "execute_analyze") is None

    def test_none_when_effort_key_absent(self):
        campaign = {"sdk_options": {"design": {}}}
        assert _effort_for(campaign, "design") is None

    def test_handles_null_sdk_options(self):
        # YAML "sdk_options:" with no body parses to None.
        assert _effort_for({"sdk_options": None}, "design") is None


class TestSdkOptionsSchema:
    def _schema(self):
        import yaml
        schemas_dir = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"
        return yaml.safe_load((schemas_dir / "campaign.schema.yaml").read_text())

    def _base_campaign(self):
        return {
            "research_question": "q",
            "target_system": {"name": "x", "description": "d"},
            "prompts": {"methodology_layer": "p"},
        }

    def test_accepts_valid_effort(self):
        import jsonschema
        campaign = self._base_campaign()
        campaign["sdk_options"] = {"execute_analyze": {"effort": "medium"}}
        jsonschema.validate(campaign, self._schema())

    def test_accepts_absent_stanza(self):
        import jsonschema
        jsonschema.validate(self._base_campaign(), self._schema())

    def test_accepts_empty_phase(self):
        import jsonschema
        campaign = self._base_campaign()
        campaign["sdk_options"] = {"design": {}}
        jsonschema.validate(campaign, self._schema())

    def test_rejects_unknown_effort(self):
        import jsonschema
        campaign = self._base_campaign()
        campaign["sdk_options"] = {"execute_analyze": {"effort": "medum"}}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(campaign, self._schema())

    def test_rejects_unknown_phase_key(self):
        import jsonschema
        campaign = self._base_campaign()
        campaign["sdk_options"] = {"reporting": {"effort": "high"}}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(campaign, self._schema())
