"""campaign.design_profile: standard leaves prompts/limits unchanged; lightweight trims them."""
import copy
from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.design_profile import (
    LIGHTWEIGHT_DESIGN_MAX_TURNS, design_guidance, design_max_turns_override, execute_guidance,
)
from orchestrator.llm_dispatch import LLMDispatcher

SCHEMA = yaml.safe_load((Path(__file__).parent.parent / "orchestrator" / "schemas" / "campaign.schema.yaml").read_text())

BASE = {
    "research_question": "What maximizes the score?",
    "target_system": {"name": "T", "description": "A target.", "repo_path": "/tmp/fake-repo"},
    "prompts": {"methodology_layer": "prompts/methodology", "domain_adapter_layer": None},
}


def _campaign(**extra):
    c = copy.deepcopy(BASE)
    c.update(extra)
    return c


class _Completion:
    """Canned chat.completions callable that records the prompts it was sent."""

    def __init__(self):
        self.prompts = []

    def __call__(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])

        class _Msg:
            content = "stub output"

        class _Choice:
            message = _Msg()

        class _Usage:
            prompt_tokens = 1
            completion_tokens = 1

        class _Resp:
            choices = [_Choice()]
            usage = _Usage()

        return _Resp()


@pytest.fixture
def work_dir(tmp_path):
    (tmp_path / "runs" / "iter-1").mkdir(parents=True)
    return tmp_path


def _design_prompt(work_dir, campaign):
    fn = _Completion()
    d = LLMDispatcher(work_dir=work_dir, campaign=campaign, completion_fn=fn)
    d.dispatch("planner", "design", output_path=work_dir / "runs" / "iter-1" / "design.md", iteration=1)
    return fn.prompts[0], d


class TestSchema:
    def test_lightweight_accepted(self):
        jsonschema.validate(_campaign(design_profile="lightweight"), SCHEMA)

    def test_standard_accepted(self):
        jsonschema.validate(_campaign(design_profile="standard"), SCHEMA)

    def test_unknown_profile_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(_campaign(design_profile="turbo"), SCHEMA)


class TestGuidance:
    def test_standard_and_absent_profile_render_nothing(self):
        for c in (_campaign(), _campaign(design_profile="standard")):
            assert design_guidance(c, 80) == ""
            assert execute_guidance(c) == ""
            assert design_max_turns_override(c) is None

    def test_lightweight_guidance_content(self):
        c = _campaign(design_profile="lightweight")
        g = design_guidance(c, LIGHTWEIGHT_DESIGN_MAX_TURNS)
        assert "1-3 arms" in g and f"at most {LIGHTWEIGHT_DESIGN_MAX_TURNS} turns" in g
        assert "handoff_snapshot.md" in g
        assert design_guidance(c, 30, "rehearsal") == ""
        assert "budget" not in g.lower() and "$" not in g
        assert "measure-edit cycles" in execute_guidance(c)
        assert execute_guidance(c, "rehearsal") == ""
        assert "refine_cycles" in execute_guidance(c)
        assert design_max_turns_override(c) == LIGHTWEIGHT_DESIGN_MAX_TURNS


class TestDesignPrompt:
    def test_standard_prompt_has_no_profile_text_or_placeholder(self, work_dir):
        prompt, _ = _design_prompt(work_dir, _campaign())
        assert "Lightweight profile" not in prompt
        assert "{{profile_guidance}}" not in prompt

    def test_lightweight_prompt_includes_guidance(self, work_dir):
        prompt, _ = _design_prompt(work_dir, _campaign(design_profile="lightweight"))
        assert "Lightweight profile" in prompt and "1-3 arms" in prompt

    def test_explicit_standard_prompt_identical_to_absent(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        for w in (a, b):
            (w / "runs" / "iter-1").mkdir(parents=True)
        pa, _ = _design_prompt(a, _campaign())
        pb, _ = _design_prompt(b, _campaign(design_profile="standard"))
        assert pa.replace(str(a), "<W>") == pb.replace(str(b), "<W>")

    def test_guidance_shows_overridden_turn_limit(self, work_dir):
        prompt, _ = _design_prompt(work_dir, _campaign(design_profile="lightweight", max_turns={"design": 12}))
        assert "at most 12 turns" in prompt


class TestMaxTurns:
    """resolve_max_turns is the single resolver used for the SDK limit and the prompt text."""
    DEFAULTS = {"design": 80, "execute_analyze": 120}

    def test_lightweight_caps_design_only(self):
        from orchestrator.design_profile import resolve_max_turns
        c = _campaign(design_profile="lightweight")
        assert resolve_max_turns(c, "design", self.DEFAULTS) == LIGHTWEIGHT_DESIGN_MAX_TURNS
        assert resolve_max_turns(c, "execute_analyze", self.DEFAULTS) == 120

    def test_campaign_max_turns_wins_over_profile(self):
        from orchestrator.design_profile import resolve_max_turns
        c = _campaign(design_profile="lightweight", max_turns={"design": 12})
        assert resolve_max_turns(c, "design", self.DEFAULTS) == 12

    def test_standard_uses_defaults_then_fallback(self):
        from orchestrator.design_profile import resolve_max_turns
        assert resolve_max_turns(_campaign(), "design", self.DEFAULTS) == 80
        assert resolve_max_turns(_campaign(), "report", {}) == 25


class TestExecuteContext:
    def _ctx(self, work_dir, campaign):
        it = work_dir / "runs" / "iter-1"
        (it / "bundle.yaml").write_text("metadata: {iteration: 1}\narms: []\n")
        (it / "problem.md").write_text("# Problem\n")
        d = LLMDispatcher(work_dir=work_dir, campaign=campaign, completion_fn=_Completion())
        return d._build_context("executor", "execute-analyze", 1, None)

    def test_lightweight_execute_guidance_in_mode_guidance(self, work_dir):
        ctx = self._ctx(work_dir, _campaign(design_profile="lightweight"))
        assert "measure-edit cycles" in ctx["mode_guidance"]
        assert "profile_guidance" not in ctx

    def test_standard_execute_mode_guidance_unchanged(self, work_dir):
        from orchestrator.iteration_mode import execute_mode_guidance_for
        ctx = self._ctx(work_dir, _campaign())
        assert ctx["mode_guidance"] == execute_mode_guidance_for("real")
