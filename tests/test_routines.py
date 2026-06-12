"""Behavioral tests for Routines payload building (#134 Phase A)."""
from __future__ import annotations

import pytest

from orchestrator.routines import build_routine_payload


def _campaign(**overrides):
    base = {
        "research_question": "What drives saturation?",
        "run_id": "saturation-run",
        "target_system": {
            "name": "BLIS",
            "description": "Inference simulator.",
            "repo_path": "/path/to/blis",
        },
        "max_iterations": 5,
    }
    base.update(overrides)
    return base


class TestSchedulePayload:

    def test_includes_cron_trigger(self, tmp_path):
        out = build_routine_payload(_campaign(), schedule="0 2 * * *")
        assert out["trigger"] == {"type": "cron", "expression": "0 2 * * *"}

    def test_name_falls_back_to_run_id(self):
        out = build_routine_payload(_campaign(), schedule="0 2 * * *")
        assert out["name"] == "saturation-run"

    def test_command_includes_auto_approve_and_agent_sdk(self, tmp_path):
        path = tmp_path / "campaign.yaml"
        path.write_text("dummy")
        out = build_routine_payload(
            _campaign(), campaign_path=path, schedule="0 2 * * *",
        )
        assert "--auto-approve" in out["command"]
        assert out["command"][-2:] == ["--agent", "sdk"]

    def test_credentials_placeholder_not_real_secret(self):
        out = build_routine_payload(_campaign(), schedule="0 2 * * *")
        # The payload must NOT contain the real key — it's a placeholder
        # that the Routines runtime resolves from its secret store.
        assert out["credentials"]["ANTHROPIC_API_KEY"].startswith("${secret:")

    def test_mcp_refs_pass_through(self):
        out = build_routine_payload(
            _campaign(), schedule="0 2 * * *",
            mcp_refs=["nous://campaigns", "nous://campaigns/saturation-run/principles"],
        )
        assert out["mcp"]["resources"] == [
            "nous://campaigns",
            "nous://campaigns/saturation-run/principles",
        ]


class TestPrLabelPayload:

    def test_includes_pr_label_trigger(self):
        out = build_routine_payload(_campaign(), pr_label="nous-experiment")
        assert out["trigger"] == {"type": "pr_label", "label": "nous-experiment"}


class TestValidation:

    def test_missing_trigger_raises(self):
        with pytest.raises(ValueError, match="schedule or pr_label"):
            build_routine_payload(_campaign())

    def test_both_triggers_raises(self):
        with pytest.raises(ValueError, match="not both"):
            build_routine_payload(
                _campaign(), schedule="0 2 * * *", pr_label="nous-experiment",
            )


class TestCampaignReference:

    def test_campaign_path_yields_path_reference(self, tmp_path):
        path = tmp_path / "campaign.yaml"
        path.write_text("...")
        out = build_routine_payload(
            _campaign(), schedule="0 2 * * *", campaign_path=path,
        )
        assert out["campaign_path"] == str(path.resolve())
        assert "campaign_inline" not in out

    def test_no_path_inlines_campaign_dict(self):
        out = build_routine_payload(_campaign(), schedule="0 2 * * *")
        assert "campaign_inline" in out
        assert out["campaign_inline"]["run_id"] == "saturation-run"
        assert "campaign_path" not in out


# ─── Phase B: API submission with injected poster (no live HTTP) ───────────


class _RecordingPoster:
    def __init__(self, response: dict | None = None):
        self.calls: list[dict] = []
        self.response = response or {"routine_id": "rt_test_123"}

    def __call__(self, url, body, headers, timeout):
        import json as _json
        self.calls.append({
            "url": url,
            "body_json": _json.loads(body),
            "headers": dict(headers),
            "timeout": timeout,
        })
        return self.response


class TestSubmitRoutine:
    """submit_routine posts the payload via an injected poster (no live
    HTTP). Tests assert what was sent over the wire and what came back —
    never that internal helpers were called."""

    def test_posts_payload_with_auth_header(self):
        from orchestrator.routines import submit_routine

        payload = build_routine_payload(_campaign(), schedule="0 2 * * *")
        poster = _RecordingPoster()

        result = submit_routine(payload, api_key="sk-test", poster=poster)

        assert len(poster.calls) == 1
        call = poster.calls[0]
        assert call["headers"]["Authorization"] == "Bearer sk-test"
        assert call["headers"]["Content-Type"] == "application/json"
        assert call["body_json"]["trigger"] == {"type": "cron", "expression": "0 2 * * *"}
        assert result == {"routine_id": "rt_test_123"}

    def test_uses_custom_api_base(self):
        from orchestrator.routines import submit_routine

        poster = _RecordingPoster()
        submit_routine(
            build_routine_payload(_campaign(), schedule="0 2 * * *"),
            api_base="https://custom.example/v2/routines",
            api_key="sk-test", poster=poster,
        )
        assert poster.calls[0]["url"] == "https://custom.example/v2/routines"

    def test_returns_routine_id(self):
        from orchestrator.routines import submit_routine

        poster = _RecordingPoster(response={"routine_id": "rt_abc", "status": "active"})
        result = submit_routine(
            build_routine_payload(_campaign(), schedule="0 2 * * *"),
            api_key="sk-test", poster=poster,
        )
        assert result == {"routine_id": "rt_abc", "status": "active"}

    def test_raises_without_api_key_when_no_poster(self):
        """Real-world misconfig protection: no key + no env + no poster
        must fail loudly, not fall back to anonymous."""
        from orchestrator.routines import submit_routine

        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            submit_routine(build_routine_payload(_campaign(), schedule="0 2 * * *"))
