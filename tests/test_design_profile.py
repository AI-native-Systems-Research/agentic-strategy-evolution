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


MAX_TURNS_ERR = ("SDK reported is_error=True with no result text; captured context: "
                 "stop_reason=tool_use subtype=error_max_turns num_turns=31")


class _Runner:
    """Scripted SDK runner: pops canned SDKResults and records each call's kwargs."""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self._scripted.pop(0)


def _sdk_design(tmp_path, campaign, scripted, monkeypatch):
    from orchestrator.sdk_dispatch import SDKDispatcher
    monkeypatch.setattr("orchestrator.sdk_dispatch.time.sleep", lambda _s: None)
    runner = _Runner(scripted)
    campaign["target_system"]["repo_path"] = str(tmp_path)
    d = SDKDispatcher(work_dir=tmp_path, campaign=campaign, sdk_runner=runner, max_retries=3)
    out = tmp_path / "runs" / "iter-1" / "design_log.md"
    d.dispatch("planner", "design", output_path=out, iteration=1)
    return runner, out


def _retry_rows(tmp_path):
    import json
    p = tmp_path / "retry_log.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


class TestTurnLimitWrapUp:
    """Lightweight: a turn-limited session is resumed with a wrap-up prompt instead of restarted."""

    def test_lightweight_resumes_same_session(self, tmp_path, monkeypatch):
        from orchestrator.design_profile import LIGHTWEIGHT_WRAP_UP_TURNS, WRAP_UP_PROMPT
        from orchestrator.sdk_dispatch import SDKResult
        runner, out = _sdk_design(tmp_path, _campaign(design_profile="lightweight"), [
            SDKResult(text="", is_error=True, error_message=MAX_TURNS_ERR, session_id="s-1"),
            SDKResult(text="wrapped up", session_id="s-1"),
        ], monkeypatch)
        assert "wrapped up" in out.read_text()
        second = runner.calls[1]
        assert second["resume"] == "s-1"
        assert second["prompt"] == WRAP_UP_PROMPT
        assert second["max_turns"] == LIGHTWEIGHT_WRAP_UP_TURNS
        assert [r["failure_type"] for r in _retry_rows(tmp_path)] == ["max_turns_wrap_up"]

    def test_standard_restarts_fresh(self, tmp_path, monkeypatch):
        from orchestrator.sdk_dispatch import SDKResult
        runner, out = _sdk_design(tmp_path, _campaign(), [
            SDKResult(text="", is_error=True, error_message=MAX_TURNS_ERR, session_id="s-1"),
            SDKResult(text="second try"),
        ], monkeypatch)
        assert "second try" in out.read_text()
        assert "resume" not in runner.calls[1]
        assert [r["failure_type"] for r in _retry_rows(tmp_path)] == ["api_error"]

    def test_wrap_ups_are_bounded_then_fresh_retry(self, tmp_path, monkeypatch):
        from orchestrator.design_profile import LIGHTWEIGHT_MAX_WRAP_UPS
        from orchestrator.sdk_dispatch import SDKResult
        err = lambda: SDKResult(text="", is_error=True, error_message=MAX_TURNS_ERR, session_id="s-1")
        runner, out = _sdk_design(tmp_path, _campaign(design_profile="lightweight"),
                                  [err() for _ in range(LIGHTWEIGHT_MAX_WRAP_UPS + 1)] + [SDKResult(text="fresh")],
                                  monkeypatch)
        assert "fresh" in out.read_text()
        last = runner.calls[-1]
        assert "resume" not in last and last["max_turns"] == runner.calls[0]["max_turns"]
        assert last["prompt"].startswith(runner.calls[0]["prompt"])

    def test_other_errors_are_not_wrapped_up(self, tmp_path, monkeypatch):
        from orchestrator.sdk_dispatch import SDKResult
        runner, _ = _sdk_design(tmp_path, _campaign(design_profile="lightweight"), [
            SDKResult(text="", is_error=True, error_message="rate limit exceeded", session_id="s-1"),
            SDKResult(text="ok"),
        ], monkeypatch)
        assert "resume" not in runner.calls[1]


class TestExecutorUpdate:
    """Lightweight: the next design prompt carries the executor's measured update."""

    def _iter2_prompt(self, tmp_path, campaign, update=None, findings=None):
        prev = tmp_path / "runs" / "iter-1"
        prev.mkdir(parents=True)
        (tmp_path / "runs" / "iter-2").mkdir(parents=True)
        (tmp_path / "handoff.md").write_text("# Handoff\nbest 78.6 (written before execution)\n")
        (tmp_path / "best_found.json").write_text(
            '{"top_k": [{"candidate_id": "iter-1/h-main/0", "score": 84.05, "iteration": 1, "arm_id": "h-main"}]}')
        if update is not None:
            (prev / "handoff_update.md").write_text(update)
        if findings is not None:
            (prev / "findings.json").write_text(findings)
        fn = _Completion()
        LLMDispatcher(work_dir=tmp_path, campaign=campaign, completion_fn=fn).dispatch(
            "planner", "design", output_path=tmp_path / "runs" / "iter-2" / "design.md", iteration=2)
        return fn.prompts[0]

    def test_update_and_best_reach_design_prompt(self, tmp_path):
        p = self._iter2_prompt(tmp_path, _campaign(design_profile="lightweight"),
                               update="Best 84.05 via 2-statement suite; uncovered: parser.py:558-580")
        assert "Executor update from iteration 1" in p
        assert "parser.py:558-580" in p and "score 84.05" in p

    def test_findings_fallback_when_no_update(self, tmp_path):
        p = self._iter2_prompt(tmp_path, _campaign(design_profile="lightweight"),
                               findings='{"arms": [{"arm_id": "h-main", "observed": 84.05}]}')
        assert "No executor update was written" in p and '"observed": 84.05' in p

    def test_standard_prompt_has_no_update(self, tmp_path):
        p = self._iter2_prompt(tmp_path, _campaign(), update="SHOULD-NOT-APPEAR")
        assert "SHOULD-NOT-APPEAR" not in p and "Executor update" not in p

    def test_validator_accepts_update_file(self, tmp_path):
        from orchestrator.validate import _check_unexpected_files
        (tmp_path / "handoff_update.md").write_text("x")
        assert _check_unexpected_files(tmp_path) == []


class TestDesignOnlyGuidance:
    def test_design_only_rules_present(self):
        g = design_guidance(_campaign(design_profile="lightweight"), 30)
        assert "design only" in g and "Do not implement or measure" in g
        assert "by about turn 15" in g and "Executor" not in g.split("Build on")[0]
        assert "handoff_update.md" in execute_guidance(_campaign(design_profile="lightweight"))


def test_wrap_up_detects_subtype_even_with_result_text(tmp_path, monkeypatch):
    from orchestrator.sdk_dispatch import SDKResult
    runner, _ = _sdk_design(tmp_path, _campaign(design_profile="lightweight"), [
        SDKResult(text="", is_error=True, error_message="Reached max turns", subtype="error_max_turns",
                  session_id="s-9"),
        SDKResult(text="done"),
    ], monkeypatch)
    assert runner.calls[1]["resume"] == "s-9"
