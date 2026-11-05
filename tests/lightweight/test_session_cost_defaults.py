"""Session isolation, cost authority, campaign keys and defaults."""

from __future__ import annotations

from orchestrator.lightweight.config import parse_campaign_config
from orchestrator.lightweight.cost import CostMeter
from orchestrator.lightweight.session import Session
from tests.fakes.sdk_client import FakeAssistantMessage, FakeResultMessage


def _campaign_yaml() -> dict:
    return {"research_question": "q", "run_id": "r", "target_system": {"name": "t", "repo_path": "/tmp/repo"}}


# ── clean session ─────────────────────────────────────────────────────


def test_session_does_not_load_user_settings():
    opts = Session(client_factory=None, options={"model": "claude-opus-4-6"}).build_agent_options()
    assert opts.setting_sources is not None
    assert "user" not in opts.setting_sources and "project" in opts.setting_sources


# ── cost ──────────────────────────────────────────────────────────────


PRICES = {"claude-opus-4-6": {"input_tokens": 5.0, "output_tokens": 25.0}}


def _msg(mid, out=1000):
    return FakeAssistantMessage(message_id=mid, model="claude-opus-4-6",
                                usage={"input_tokens": 0, "output_tokens": out})


class TestCliCostAuthority:
    def test_cli_session_total_is_used(self):
        m = CostMeter(PRICES)
        m.record(_msg("a"))  # streamed usage undercounts: priced at $0.025
        m.record(FakeResultMessage(session_id="s1", total_cost_usd=0.10))
        assert round(m.total()["cost_usd"], 6) == 0.10
        m.record(_msg("b"))
        m.record(FakeResultMessage(session_id="s1", total_cost_usd=0.25))  # cumulative per session
        assert round(m.total()["cost_usd"], 6) == 0.25

    def test_fresh_session_adds_its_own_total(self):
        m = CostMeter(PRICES)
        m.record(FakeResultMessage(session_id="s1", total_cost_usd=0.30))
        m.record(FakeResultMessage(session_id="s2", total_cost_usd=0.05))
        assert round(m.total()["cost_usd"], 6) == 0.35

    def test_iter_delta_uses_cli_cost(self):
        m = CostMeter(PRICES)
        m.record(FakeResultMessage(session_id="s1", total_cost_usd=0.30))
        assert round(m.iter_delta()["cost_usd"], 6) == 0.30
        m.record(FakeResultMessage(session_id="s1", total_cost_usd=0.45))
        assert round(m.iter_delta()["cost_usd"], 6) == 0.15

    def test_falls_back_to_priced_usage_without_cli_cost(self):
        m = CostMeter(PRICES)
        m.record(_msg("a"))
        m.record(FakeResultMessage(session_id="s1", total_cost_usd=None))
        assert round(m.total()["cost_usd"], 6) == 0.025

    def test_total_mid_turn_includes_estimate(self):
        m = CostMeter(PRICES)
        m.record(_msg("a"))
        assert round(m.total()["cost_usd"], 6) == 0.025


def test_resume_does_not_recount_earlier_spend():
    m = CostMeter(PRICES)
    m.record(FakeResultMessage(session_id="s1", total_cost_usd=4.0))
    resumed = CostMeter(PRICES, m.session_costs)  # nous resume restores state.json session_costs
    resumed.record(FakeResultMessage(session_id="s1", total_cost_usd=5.0))
    assert round(resumed.iter_delta()["cost_usd"], 6) == 1.0


# ── model key and defaults ──────────────────────────────────────────────


def test_top_level_model_key_is_used():
    assert parse_campaign_config({**_campaign_yaml(), "model": "claude-opus-5-5"}).model == "claude-opus-5-5"
    both = {**_campaign_yaml(), "model": "a", "models": {"session": "b"}}
    assert parse_campaign_config(both).model == "b"  # models.session is the explicit one


def test_default_model_is_current():
    from orchestrator.lightweight.session import DEFAULT_MODEL, MODEL_MAX_OUTPUT
    assert DEFAULT_MODEL == "claude-opus-5-5" and MODEL_MAX_OUTPUT[DEFAULT_MODEL] == 128_000


def test_default_experiment_commands_name_no_testbed_tool():
    from orchestrator.lightweight.hooks import DEFAULT_EXPERIMENT_COMMANDS
    assert not any("blis" in p for p in DEFAULT_EXPERIMENT_COMMANDS)


def test_opus_5_5_estimate_matches_cli_pricing():
    """Live probe: the CLI charged $0.0801 for this usage (Opus 5.5 list: $4/$20, cache read $0.20, write $5)."""
    from pathlib import Path

    from orchestrator.lightweight.cost import load_prices
    prices = load_prices(Path(__file__).resolve().parents[2] / "orchestrator" / "defaults.yaml")
    m = CostMeter(prices)
    m.record(FakeAssistantMessage(message_id="a", model="claude-opus-5-5", usage={
        "input_tokens": 4163, "output_tokens": 2853, "cache_read_input_tokens": 24663,
        "cache_creation_input_tokens": 291}))
    assert round(m.total()["cost_usd"], 4) == 0.0801
