"""--gate-mode agent: the continue gate follows the continue-gate summary's recommendation. No LLM calls."""
import json

import pytest

from orchestrator.campaign import _agent_continue_decision, run_campaign


def _summary(tmp_path, **extra):
    p = tmp_path / "gate_summary_continue.json"
    p.write_text(json.dumps({"gate_type": "continue", "summary": "s", "key_points": ["k"], **extra}))
    return p


def test_stop_recommendation_stops(tmp_path):
    assert _agent_continue_decision(_summary(tmp_path, recommendation="stop")) == "reject"


def test_continue_recommendation_continues(tmp_path):
    assert _agent_continue_decision(_summary(tmp_path, recommendation="continue")) == "approve"


def test_missing_recommendation_or_summary_continues(tmp_path):
    assert _agent_continue_decision(_summary(tmp_path)) == "approve"
    assert _agent_continue_decision(None) == "approve"
    assert _agent_continue_decision(tmp_path / "absent.json") == "approve"


def test_agent_mode_requires_auto_approve(tmp_path):
    with pytest.raises(ValueError, match="requires auto_approve"):
        run_campaign({}, tmp_path, gate_mode="agent", auto_approve=False)


def test_invalid_gate_mode_rejected(tmp_path):
    with pytest.raises(ValueError, match="gate_mode"):
        run_campaign({}, tmp_path, gate_mode="robot", auto_approve=True)


def test_schema_accepts_recommendation():
    import jsonschema
    from pathlib import Path

    schema = json.loads((Path(__file__).parents[1] / "orchestrator/schemas/gate_summary.schema.json").read_text())
    jsonschema.validate({"gate_type": "continue", "summary": "s", "key_points": ["k"], "recommendation": "stop"}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"gate_type": "continue", "summary": "s", "key_points": ["k"], "recommendation": "maybe"},
                            schema)
