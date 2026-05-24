"""Behavioral tests for /goal-driven prompt builders (#124 Phase A)."""
from __future__ import annotations

from orchestrator.goal_driven import (
    build_full_goal_directive,
    build_goal_driven_session_prompt,
    build_inner_loop_goal_directive,
)


def _campaign(**overrides):
    base = {
        "research_question": "What drives saturation?",
        "target_system": {
            "name": "BLIS",
            "description": "Inference simulator.",
            "observable_metrics": ["throughput", "latency"],
            "controllable_knobs": ["batch_size", "scheduling"],
        },
    }
    base.update(overrides)
    return base


# ─── Mode A: whole-campaign /goal ──────────────────────────────────────────

class TestFullGoalDirective:

    def test_predicate_names_required_artifacts(self):
        out = build_full_goal_directive(_campaign(), iteration=2)
        assert "iter-2/findings.json" in out
        assert "iter-2/principle_updates.json" in out

    def test_predicate_includes_timeout_clause(self):
        out = build_full_goal_directive(_campaign(), iteration=2, timeout_hours=12)
        assert "12 hours" in out

    def test_uses_AND_OR_logic(self):
        out = build_full_goal_directive(_campaign(), iteration=1)
        assert " AND " in out
        assert " OR " in out


# ─── Mode B: inner-loop /goal ──────────────────────────────────────────────

class TestInnerLoopGoalDirective:

    def test_predicate_uses_schema_validation_language(self):
        out = build_inner_loop_goal_directive(iteration=3)
        assert "findings.schema.json" in out
        assert "iter-3" in out

    def test_extra_predicates_are_AND_chained(self):
        out = build_inner_loop_goal_directive(
            iteration=1, extra_predicates=["arm_status reports complete for all arms"],
        )
        # All three clauses joined by AND.
        assert out.count(" AND ") == 2


# ─── Mode A session prompt ─────────────────────────────────────────────────

class TestGoalDrivenSessionPrompt:

    def test_includes_campaign_brief(self):
        out = build_goal_driven_session_prompt(_campaign(), iteration=2)
        assert "What drives saturation?" in out
        assert "BLIS" in out
        assert "throughput" in out
        assert "batch_size" in out

    def test_iteration_number_appears_consistently(self):
        out = build_goal_driven_session_prompt(_campaign(), iteration=4)
        # Many references to iter-4 across artifact paths.
        assert out.count("iter-4") >= 5

    def test_explicit_print_to_stdout_instruction(self):
        """The Haiku /goal evaluator can only see what's been surfaced
        in the conversation. The prompt MUST tell the agent to print
        artifact paths."""
        out = build_goal_driven_session_prompt(_campaign(), iteration=1)
        assert "Print" in out and "stdout" in out

    def test_validate_execution_invocation_present(self):
        out = build_goal_driven_session_prompt(_campaign(), iteration=1)
        assert "nous validate execution" in out

    def test_goal_directive_appears_in_prompt(self):
        out = build_goal_driven_session_prompt(_campaign(), iteration=1)
        assert "/goal" in out


# ─── Phase B: end-to-end goal-driven iteration runner ──────────────────────


class _FakeDispatcher:
    def __init__(self):
        self.prompts: list[str] = []

    def _call_claude(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "design log content from the agent"


class TestRunGoalDrivenIteration:
    """Phase B contract: runner takes a campaign + dispatcher, dispatches
    the goal-driven prompt, and persists the transcript as design_log.md.
    The agent produces artifacts via tool calls inside the session; the
    orchestrator only persists the conversation log."""

    def test_dispatches_goal_prompt_and_writes_log(self, tmp_path):
        from orchestrator.goal_driven import run_goal_driven_iteration

        dispatcher = _FakeDispatcher()
        log_path = run_goal_driven_iteration(
            dispatcher=dispatcher, campaign=_campaign(), iteration=2,
            work_dir=tmp_path,
        )

        assert len(dispatcher.prompts) == 1
        prompt = dispatcher.prompts[0]
        assert "/goal" in prompt
        assert "iter-2" in prompt

        assert log_path == tmp_path / "runs" / "iter-2" / "design_log.md"
        assert log_path.read_text() == "design log content from the agent"

    def test_creates_iter_dir_if_missing(self, tmp_path):
        from orchestrator.goal_driven import run_goal_driven_iteration

        run_goal_driven_iteration(
            dispatcher=_FakeDispatcher(), campaign=_campaign(),
            iteration=5, work_dir=tmp_path,
        )

        assert (tmp_path / "runs" / "iter-5").is_dir()
        assert (tmp_path / "runs" / "iter-5" / "design_log.md").exists()
