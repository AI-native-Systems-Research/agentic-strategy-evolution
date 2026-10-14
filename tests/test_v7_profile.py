"""design_profile v7: competing mechanism arms screened in capped fresh sessions, then the winner deepened."""
import copy
import json
import shutil
import subprocess
import warnings
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest
import yaml

from orchestrator.design_profile import design_guidance, execute_guidance, v7_settings
from orchestrator.llm_dispatch import LLMDispatcher
from orchestrator.sdk_dispatch import SDKDispatcher, SDKResult
from orchestrator.validate import validate_design

ROOT = Path(__file__).parent.parent
SCHEMAS = ROOT / "orchestrator" / "schemas"
CAMPAIGN_SCHEMA = yaml.safe_load((SCHEMAS / "campaign.schema.yaml").read_text())
FINDINGS_SCHEMA = json.loads((SCHEMAS / "findings.schema.json").read_text())

BASE = {
    "research_question": "What maximizes the score?",
    "target_system": {"name": "T", "description": "A target.", "repo_path": "/tmp/fake-repo"},
    "prompts": {"methodology_layer": "prompts/methodology", "domain_adapter_layer": None},
}


def _campaign(**extra):
    c = copy.deepcopy(BASE)
    c.update(extra)
    return c


def _arm(t, **kw):
    a = {"type": t, "prediction": "score >= 60", "mechanism": "m", "diagnostic": "d"}
    a.update(kw)
    return a


def _bundle(*arms, **top):
    b = {"metadata": {"iteration": 1, "family": "f", "research_question": "q"}, "arms": list(arms)}
    b.update(top)
    return b


MAIN = _arm("h-main", mechanism_family="greedy packing", validity_check="feasible on a 3x3 grid")
ALT = _arm("h-alternative", mechanism_family="lookahead window search",
           differs_from_main="chooses the next piece by search, not a fixed order",
           validity_check="feasible on a 3x3 grid")


def _design_dir(tmp_path, bundle):
    d = tmp_path / "iter"
    d.mkdir(exist_ok=True)
    (d / "problem.md").write_text("# P\n")
    (d / "handoff_snapshot.md").write_text("# H\n")
    (d / "bundle.yaml").write_text(yaml.safe_dump(bundle))
    return d


class TestAlternativeArmValidation:
    def test_alternative_with_distinct_family_passes(self, tmp_path):
        r = validate_design(_design_dir(tmp_path, _bundle(MAIN, ALT)))
        assert r["status"] == "pass", r

    def test_same_family_as_main_rejected(self, tmp_path):
        alt = dict(ALT, mechanism_family="  Greedy Packing ")
        r = validate_design(_design_dir(tmp_path, _bundle(MAIN, alt)))
        assert r["status"] == "fail"
        assert any("same mechanism_family as h-main" in e for e in r["errors"])

    def test_alternative_needs_family_and_reason(self, tmp_path):
        alt = {k: v for k, v in ALT.items() if k not in ("mechanism_family", "differs_from_main")}
        r = validate_design(_design_dir(tmp_path, _bundle(MAIN, alt)))
        errs = " ".join(r["errors"])
        assert "mechanism_family" in errs and "differs_from_main" in errs

    def test_alternatives_must_differ_from_each_other(self, tmp_path):
        r = validate_design(_design_dir(tmp_path, _bundle(MAIN, ALT, dict(ALT))))
        assert any("repeats the mechanism_family" in e for e in r["errors"])

    def test_alternative_needs_main_family(self, tmp_path):
        main = {k: v for k, v in MAIN.items() if k != "mechanism_family"}
        r = validate_design(_design_dir(tmp_path, _bundle(main, ALT)))
        assert any("h-main" in e and "mechanism_family" in e for e in r["errors"])

    def test_existing_bundles_unaffected(self, tmp_path):
        r = validate_design(_design_dir(tmp_path, _bundle(_arm("h-main"), _arm("h-control-negative"))))
        assert r["status"] == "pass", r


class TestV7DesignRules:
    V7 = _campaign(design_profile="v7")

    def test_v7_bundle_passes(self, tmp_path):
        assert validate_design(_design_dir(tmp_path, _bundle(MAIN, ALT)), campaign=self.V7)["status"] == "pass"

    def test_mechanism_arm_needs_validity_check(self, tmp_path):
        alt = {k: v for k, v in ALT.items() if k != "validity_check"}
        r = validate_design(_design_dir(tmp_path, _bundle(MAIN, alt)), campaign=self.V7)
        assert any("validity_check" in e for e in r["errors"])
        # other profiles do not require it
        assert validate_design(_design_dir(tmp_path, _bundle(MAIN, alt)),
                               campaign=_campaign(design_profile="v6"))["status"] == "pass"

    def test_at_most_two_alternatives(self, tmp_path):
        alts = [dict(ALT, mechanism_family=f"family {i}") for i in range(3)]
        r = validate_design(_design_dir(tmp_path, _bundle(MAIN, *alts)), campaign=self.V7)
        assert any("at most 2 h-alternative" in e for e in r["errors"])

    def test_single_family_needs_reason(self, tmp_path):
        r = validate_design(_design_dir(tmp_path, _bundle(MAIN)), campaign=self.V7)
        assert any("single_family_reason" in e for e in r["errors"])
        ok = _bundle(MAIN, single_family_reason="only exact DP is feasible at these sizes")
        assert validate_design(_design_dir(tmp_path, ok), campaign=self.V7)["status"] == "pass"

    def test_cli_validate_reads_v7_campaign(self, tmp_path, capsys):
        import argparse
        from orchestrator.cli import _cmd_validate
        work = tmp_path / "w"
        it = work / "runs" / "iter-1"
        it.mkdir(parents=True)
        (work / "campaign.yaml").write_text(yaml.safe_dump(self.V7))
        d = _design_dir(tmp_path, _bundle(MAIN))
        for f in d.iterdir():
            shutil.copy(f, it / f.name)
        with pytest.raises(SystemExit):
            _cmd_validate(argparse.Namespace(phase="design", dir=it))
        assert "single_family_reason" in capsys.readouterr().out


class TestSchemas:
    def test_findings_accept_alternative_and_gap_analysis(self):
        f = {"iteration": 1, "bundle_ref": "b", "experiment_valid": True, "discrepancy_analysis": "x",
             "arms": [{"arm_type": "h-alternative", "predicted": "p", "observed": "o", "status": "REFUTED",
                       "error_type": "magnitude", "diagnostic_note": None}],
             "gap_analysis": [{"group": "n>=1e5", "loss": 12.5, "n_instances": 17, "max_cpu_s": 3.9,
                               "time_limit_s": 2.0, "timeouts": 4, "evidence": "evaluator run 3"}]}
        jsonschema.validate(f, FINDINGS_SCHEMA)

    def test_execute_analyze_schema_lists_alternative(self):
        s = (SCHEMAS / "execute_analyze.schema.json").read_text()
        assert '"h-alternative"' in s

    def test_campaign_schema_v7_block(self):
        jsonschema.validate(_campaign(design_profile="v7", v7={"arm_budget_usd": 3,
                                                               "iteration_budget_usd": 10}), CAMPAIGN_SCHEMA)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(_campaign(design_profile="v7", v7={"arm_budget": 3}), CAMPAIGN_SCHEMA)

    def test_ledger_records_alternatives(self, tmp_path):
        from orchestrator.ledger import _build_row
        findings = {"arms": [
            {"arm_type": "h-main", "status": "CONFIRMED", "metadata": {"candidate_id": "h-main"}},
            {"arm_type": "h-alternative", "status": "REFUTED", "metadata": {"candidate_id": "h-alternative-1"}}]}
        row = _build_row(1, findings, {"metadata": {"family": "f"}}, {"principles": []})
        assert row["alternative_results"] == {"h-alternative-1": "REFUTED"}
        ledger_schema = json.loads((SCHEMAS / "ledger.schema.json").read_text())
        jsonschema.validate({"iterations": [row]}, ledger_schema)
        plain = _build_row(1, {"arms": findings["arms"][:1]}, {"metadata": {"family": "f"}}, {"principles": []})
        assert "alternative_results" not in plain


class TestGuidance:
    def test_v7_design_guidance(self):
        g = design_guidance(_campaign(design_profile="v7"), 30)
        for s in ("h-alternative", "mechanism_family", "differs_from_main", "validity_check",
                  "single_family_reason", "h-dose-response", "h-control-negative", "h-robustness",
                  "h-ablation", "Build on the current best code"):
            assert s in g, s
        assert "Few, focused arms" not in g and "--" not in g

    def test_v7_execute_guidance(self):
        e = execute_guidance(_campaign(design_profile="v7"))
        assert "per size group" in e and "gap_analysis" in e and "h-control-negative" in e
        assert "Start from the current best" in e and "--" not in e

    def test_v7_build_and_measure_early(self):
        c = _campaign(design_profile="v7")
        assert "Design in steps" in design_guidance(c, 30)
        assert "Build and measure early" in execute_guidance(c)
        root = Path(__file__).resolve().parents[1] / "prompts" / "methodology"
        assert "Build and measure early" in (root / "execute_arm.md").read_text()
        assert "never a whole turn" in (root / "build_evaluator.md").read_text()

    def test_other_profiles_unchanged(self):
        for p in ("lightweight", "v4", "v5", "v6"):
            c = _campaign(design_profile=p)
            text = design_guidance(c, 30) + execute_guidance(c)
            assert "h-alternative" not in text and "validity_check" not in text
            assert "Build and measure early" not in text and "Design in steps" not in text
            assert "Few, focused arms" in design_guidance(c, 30)

    def test_v7_keeps_v6_machinery(self):
        from orchestrator.design_profile import carry_forward_enabled, max_wrap_ups, resolve_max_turns
        c = _campaign(design_profile="v7")
        jsonschema.validate(c, CAMPAIGN_SCHEMA)
        assert carry_forward_enabled(c) and max_wrap_ups(c) > 0
        assert resolve_max_turns(c, "execute_analyze", {"execute_analyze": 120}) == 120

    def _design_prompt(self, work_dir, iteration):
        prompts = []

        def fn(**kw):
            prompts.append(kw["messages"][0]["content"])
            r = MagicMock()
            r.choices = [MagicMock(message=MagicMock(content="x"))]
            r.usage = MagicMock(prompt_tokens=1, completion_tokens=1)
            return r
        (work_dir / "runs" / f"iter-{iteration}").mkdir(parents=True, exist_ok=True)
        LLMDispatcher(work_dir=work_dir, campaign=_campaign(design_profile="v7"), completion_fn=fn).dispatch(
            "planner", "design", output_path=work_dir / "runs" / f"iter-{iteration}" / "d.md",
            iteration=iteration)
        return prompts[0]

    def test_design_prompt_plans_evaluator_until_it_exists(self, tmp_path):
        p1 = self._design_prompt(tmp_path, 1)
        assert "local evaluator" in p1 and str(tmp_path / "evaluator") in p1
        assert "largest allowed sizes" in p1
        (tmp_path / "evaluator").mkdir()
        (tmp_path / "evaluator" / "README.md").write_text("run: python eval.py\n")
        p2 = self._design_prompt(tmp_path, 2)
        assert "run: python eval.py" in p2 and "largest allowed sizes" not in p2


class TestBudgetSplit:
    def test_defaults(self):
        s = v7_settings(_campaign(design_profile="v7"))
        assert s.arm_budget_usd == 4.0 and 2 * s.iteration_budget_usd <= 25

    def test_configurable(self):
        s = v7_settings(_campaign(design_profile="v7", v7={"arm_budget_usd": 3, "iteration_budget_usd": 9}))
        assert (s.arm_budget_usd, s.iteration_budget_usd) == (3, 9)

    @pytest.mark.parametrize("n_sessions,design", [(1, 1.5), (2, 3.0), (3, 4.0), (3, 2.0)])
    def test_full_iteration_stays_within_cap_and_25_gives_two_designs(self, n_sessions, design):
        from orchestrator.v7_execute import screening_cap, winner_cap
        s = v7_settings(_campaign(design_profile="v7"))
        remaining = s.iteration_budget_usd - design
        caps = []
        for i in range(n_sessions):
            caps.append(screening_cap(s, remaining, n_sessions - i))
            remaining -= caps[-1]
        win = winner_cap(s, remaining)
        assert all(c <= s.arm_budget_usd for c in caps)
        assert win >= s.winner_min_usd
        total = design + sum(caps) + win
        assert total <= s.iteration_budget_usd + 1e-9
        assert total + design <= 25  # a second design starts before $25 even if every session spends its cap

    def test_arm_cap_is_full_when_budget_allows(self):
        from orchestrator.v7_execute import screening_cap
        s = v7_settings(_campaign(design_profile="v7", v7={"iteration_budget_usd": 20}))
        assert screening_cap(s, 18.0, 2) == s.arm_budget_usd


# ─── SDK dispatcher dollar caps ─────────────────────────────────────────────

class _Runner:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        item = self._scripted.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _metrics(work_dir):
    p = Path(work_dir) / "llm_metrics.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def _sdk(tmp_path, campaign, runner, monkeypatch):
    monkeypatch.setattr("orchestrator.sdk_dispatch.time.sleep", lambda _s: None)
    campaign["target_system"]["repo_path"] = str(tmp_path)
    (tmp_path / "runs" / "iter-1").mkdir(parents=True, exist_ok=True)
    return SDKDispatcher(work_dir=tmp_path, campaign=campaign, sdk_runner=runner, max_retries=3)


BUDGET_ERR = dict(text="", is_error=True, error_message="session cost reached the cap",
                  subtype="error_max_budget_usd")


class TestDispatcherBudget:
    def test_budget_reaches_runner_and_metrics(self, tmp_path, monkeypatch):
        runner = _Runner([SDKResult(text="ok")])
        d = _sdk(tmp_path, _campaign(design_profile="v7"), runner, monkeypatch)
        with d.session_budget(3.5, label="h-main"):
            d.dispatch("planner", "design", output_path=tmp_path / "out.md", iteration=1)
        assert runner.calls[0]["max_cost_usd"] == 3.5
        row = _metrics(tmp_path)[-1]
        assert row["budget_usd"] == 3.5 and row["session_label"] == "h-main"

    def test_no_budget_by_default(self, tmp_path, monkeypatch):
        runner = _Runner([SDKResult(text="ok")])
        d = _sdk(tmp_path, _campaign(design_profile="v6"), runner, monkeypatch)
        d.dispatch("planner", "design", output_path=tmp_path / "out.md", iteration=1)
        assert "max_cost_usd" not in runner.calls[0]
        assert "budget_usd" not in _metrics(tmp_path)[-1]

    def test_budget_stop_wraps_up_once_and_never_restarts(self, tmp_path, monkeypatch):
        from orchestrator.design_profile import WRAP_UP_PROMPT
        runner = _Runner([SDKResult(session_id="s-1", **BUDGET_ERR),
                          SDKResult(session_id="s-1", **BUDGET_ERR)])
        d = _sdk(tmp_path, _campaign(design_profile="v7"), runner, monkeypatch)
        with d.session_budget(4.0):
            d.dispatch("planner", "design", output_path=tmp_path / "out.md", iteration=1)
        assert len(runner.calls) == 2
        assert runner.calls[1]["resume"] == "s-1" and runner.calls[1]["prompt"] == WRAP_UP_PROMPT
        assert runner.calls[1]["max_cost_usd"] < 4.0

    def test_turn_limit_wrap_up_gets_small_cap(self, tmp_path, monkeypatch):
        runner = _Runner([SDKResult(text="", is_error=True, error_message="max", subtype="error_max_turns",
                                    session_id="s-2"), SDKResult(text="wrapped")])
        d = _sdk(tmp_path, _campaign(design_profile="v7"), runner, monkeypatch)
        with d.session_budget(4.0):
            d.dispatch("planner", "design", output_path=tmp_path / "out.md", iteration=1)
        assert runner.calls[1]["resume"] == "s-2" and runner.calls[1]["max_cost_usd"] < 4.0

    def test_budget_stop_without_session_is_final(self, tmp_path, monkeypatch):
        runner = _Runner([SDKResult(**BUDGET_ERR)])
        d = _sdk(tmp_path, _campaign(design_profile="v7"), runner, monkeypatch)
        with d.session_budget(4.0):
            d.dispatch("planner", "design", output_path=tmp_path / "out.md", iteration=1)
        assert len(runner.calls) == 1
        retry = (tmp_path / "retry_log.jsonl").read_text()
        assert "max_budget_stop" in retry


def _transient(output_tokens):
    from orchestrator.sdk_dispatch import SDKTransientError
    exc = SDKTransientError("silence watchdog")
    exc.usage = {"output_tokens": output_tokens}
    return exc


class TestCapSurvivesRetries:
    """A capped session's spend accumulates across retries; retries only get what is left of the cap."""

    def test_transient_spend_is_logged_and_retry_gets_the_remainder(self, tmp_path, monkeypatch):
        from orchestrator.metrics import spent_usd
        runner = _Runner([_transient(20_000), SDKResult(text="ok", output_tokens=10_000)])  # $1.50, $0.75
        d = _sdk(tmp_path, _campaign(design_profile="v7"), runner, monkeypatch)
        with d.session_budget(4.0, label="h-main"):
            d.dispatch("planner", "design", output_path=tmp_path / "out.md", iteration=1)
        assert runner.calls[1]["max_cost_usd"] == pytest.approx(2.5)
        assert spent_usd(tmp_path / "llm_metrics.jsonl") == pytest.approx(2.25)

    def test_transients_that_use_up_the_cap_stop_the_session(self, tmp_path, monkeypatch):
        from orchestrator.metrics import spent_usd
        runner = _Runner([_transient(30_000), _transient(30_000), SDKResult(text="never")])
        d = _sdk(tmp_path, _campaign(design_profile="v7"), runner, monkeypatch)
        with d.session_budget(4.0):
            d.dispatch("planner", "design", output_path=tmp_path / "out.md", iteration=1)
        assert len(runner.calls) == 2
        assert runner.calls[1]["max_cost_usd"] == pytest.approx(1.75)
        assert spent_usd(tmp_path / "llm_metrics.jsonl") == pytest.approx(4.5)
        assert "max_budget_stop" in (tmp_path / "retry_log.jsonl").read_text()

    def test_failed_wrap_up_never_restarts_with_a_fresh_cap(self, tmp_path, monkeypatch):
        runner = _Runner([SDKResult(session_id="s-1", output_tokens=53_334, **BUDGET_ERR),
                          SDKResult(text="", is_error=True, error_message="api boom", output_tokens=1_000),
                          SDKResult(text="fresh restart")])
        d = _sdk(tmp_path, _campaign(design_profile="v7"), runner, monkeypatch)
        with d.session_budget(4.0):
            d.dispatch("planner", "design", output_path=tmp_path / "out.md", iteration=1)
        assert len(runner.calls) == 2

    def test_wrap_up_cap_covers_a_few_cached_context_reads(self, tmp_path, monkeypatch):
        runner = _Runner([SDKResult(session_id="s-1", output_tokens=53_334, last_turn_cost_usd=0.9,
                                    **BUDGET_ERR), SDKResult(text="wrapped")])
        d = _sdk(tmp_path, _campaign(design_profile="v7"), runner, monkeypatch)
        with d.session_budget(4.0):
            d.dispatch("planner", "design", output_path=tmp_path / "out.md", iteration=1)
        assert runner.calls[1]["max_cost_usd"] >= 3 * 0.9
        assert runner.calls[1]["max_cost_usd"] <= 4.0

    def test_wrap_up_floor_unchanged_for_small_contexts(self):
        from orchestrator.design_profile import budget_wrap_up_usd
        assert budget_wrap_up_usd(4.0) == 1.0 and budget_wrap_up_usd(0.5) == 0.25
        assert budget_wrap_up_usd(4.0, last_turn_usd=0.1) == 1.0

    def test_uncapped_transient_logs_no_row(self, tmp_path, monkeypatch):
        runner = _Runner([_transient(20_000), SDKResult(text="ok")])
        d = _sdk(tmp_path, _campaign(design_profile="v6"), runner, monkeypatch)
        d.dispatch("planner", "design", output_path=tmp_path / "out.md", iteration=1)
        assert len(_metrics(tmp_path)) == 1 and "max_cost_usd" not in runner.calls[1]


class TestDefaultRunnerCostCap:
    @staticmethod
    def _fake_sdk(n_messages, consumed):
        import types

        class _Opts:
            def __init__(self, **kw):
                self.kw = kw

        class AssistantMessage:
            def __init__(self, i):
                self.content = []
                self.usage = {"output_tokens": 10_000}
                self.message_id = f"m{i}"
                self.session_id = "sess-7"

        class ResultMessage:
            is_error = False
            usage = {}
            total_cost_usd = 0.0
            duration_ms = 0
            num_turns = 1
            session_id = "sess-7"

        async def _query(*, prompt, options):  # noqa: ARG001
            for i in range(n_messages):
                consumed.append(i)
                yield AssistantMessage(i)
                yield AssistantMessage(i)  # same reply streamed twice: counted once
            yield ResultMessage()

        m = types.ModuleType("claude_agent_sdk")
        m.ClaudeAgentOptions = _Opts
        m.query = _query
        return m

    def _run(self, monkeypatch, tmp_path, **kw):
        import sys
        from orchestrator.sdk_dispatch import _default_sdk_runner_factory
        consumed = []
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", self._fake_sdk(10, consumed))
        res = _default_sdk_runner_factory()(prompt="p", model="m", cwd=tmp_path, max_turns=5, **kw)
        return res, consumed

    def test_stops_at_cap_with_resumable_session(self, monkeypatch, tmp_path):
        # 10k output tokens at $75/M = $0.75 per reply; cap $2 stops on the third reply
        res, consumed = self._run(monkeypatch, tmp_path, max_cost_usd=2.0)
        assert res.is_error and res.subtype == "error_max_budget_usd"
        assert res.session_id == "sess-7" and len(consumed) == 3
        assert res.output_tokens == 30_000 and res.cost_usd == pytest.approx(2.25)
        assert res.last_turn_cost_usd == pytest.approx(0.75)

    def test_no_cap_runs_to_completion(self, monkeypatch, tmp_path):
        res, consumed = self._run(monkeypatch, tmp_path)
        assert not res.is_error and len(consumed) == 10

    def test_transient_mid_stream_carries_the_partial_usage(self, monkeypatch, tmp_path):
        import sys
        from orchestrator.sdk_dispatch import SDKTransientError, _default_sdk_runner_factory
        sdk = self._fake_sdk(10, [])
        good = sdk.query

        async def _dies(*, prompt, options):
            n = 0
            async for m in good(prompt=prompt, options=options):
                yield m
                n += 1
                if n == 4:  # two replies, each streamed twice
                    raise ConnectionError("server disconnected")
        sdk.query = _dies
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", sdk)
        with pytest.raises(SDKTransientError) as info:
            _default_sdk_runner_factory()(prompt="p", model="m", cwd=tmp_path, max_turns=5, max_cost_usd=9.0)
        assert info.value.usage["output_tokens"] == 20_000


# ─── v7 EXECUTE flow on a real git repo with a scripted SDK runner ─────────

def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "solution.py").write_text("v = 0\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=x@x", "-c", "user.name=x", "commit", "-q", "-m", "seed")
    return repo


class _Fake:
    """Scripted executor: acts on the prompt it receives, as a real session would (files on disk)."""

    def __init__(self, work_dir, iter_dir, scores, valid=None, cost_tokens=20_000):
        self.work_dir, self.iter_dir = Path(work_dir), Path(iter_dir)
        self.scores, self.valid = scores, valid or {}
        self.cost_tokens = cost_tokens  # output tokens per session ($1.50 at $75/M)
        self.winner_saw = None
        self.sessions = []
        self.winner_mode = "normal"  # "sloppy": no patch, no candidate_id, new file; "cut": no findings
        self.winner_tokens = cost_tokens
        self.no_result = False  # screening sessions write a patch but no result.json
        self.budgets = {}

    def __call__(self, **kw):
        if "max_cost_usd" in kw:
            self.budgets.setdefault(len(self.sessions), kw["max_cost_usd"])
        if (self.winner_mode != "normal" and "Build the local evaluator" not in kw["prompt"]
                and "Screen arm `" not in kw["prompt"]):
            return self._odd_winner(Path(kw["cwd"]))
        return self._call(**kw)

    def _odd_winner(self, cwd):
        self.sessions.append("winner")
        self.winner_saw = (cwd / "solution.py").read_text()
        win = self.winner_saw.split("=")[1].strip()
        (cwd / "solution.py").write_text(f"v = {win}1\n")
        (cwd / "helper.py").write_text("H = 1\n")
        if self.winner_mode == "sloppy":
            (self.iter_dir / "experiment_plan.yaml").write_text(yaml.safe_dump({
                "metadata": {"iteration": 1, "bundle_ref": "bundle.yaml"},
                "arms": [{"arm_id": "h-main", "conditions": [{"name": "kept", "cmd": "measure"}]}]}))
            (self.iter_dir / "findings.json").write_text(json.dumps({
                "iteration": 1, "bundle_ref": "bundle.yaml", "experiment_valid": True,
                "discrepancy_analysis": "x",
                "arms": [{"arm_type": "h-main", "predicted": "p", "observed": "o", "status": "CONFIRMED",
                          "error_type": None, "diagnostic_note": None,
                          "metadata": {"score": float(f"{win}1")}}]}))
            (self.iter_dir / "principle_updates.json").write_text("[]")
        return SDKResult(text="done", output_tokens=self.winner_tokens)

    def _call(self, **kw):
        prompt, cwd = kw["prompt"], Path(kw["cwd"])
        if "Build the local evaluator" in prompt:
            self.sessions.append("evaluator")
            (self.work_dir / "evaluator").mkdir(exist_ok=True)
            (self.work_dir / "evaluator" / "README.md").write_text("python eval.py\n")
        elif "Screen arm `" in prompt:
            key = prompt.split("Screen arm `", 1)[1].split("`", 1)[0]
            self.sessions.append(key)
            score = self.scores[key]
            (cwd / "solution.py").write_text(f"v = {score}\n")
            patch = subprocess.run(["git", "diff"], cwd=cwd, capture_output=True, text=True).stdout
            (self.iter_dir / "patches" / f"{key}.patch").write_text(patch)
            out = self.iter_dir / "arms" / key
            out.mkdir(parents=True, exist_ok=True)
            if self.no_result:
                return SDKResult(text="done", output_tokens=self.cost_tokens)
            (out / "result.json").write_text(json.dumps({
                "arm_key": key, "arm_type": "h-main" if key == "h-main" else "h-alternative",
                "mechanism_family": key, "metrics": {"score": score},
                "validity_check": {"passed": self.valid.get(key, True), "detail": "tiny case"},
                "predicted": "score >= 60", "observed": f"score {score}",
                "status": "CONFIRMED" if score >= 60 else "REFUTED", "error_type": None}))
        else:
            self.sessions.append("winner")
            self.winner_saw = (cwd / "solution.py").read_text()
            win = self.winner_saw.split("=")[1].strip()
            key = next((k for k, s in self.scores.items() if win.startswith(str(s))), "h-main")
            (cwd / "solution.py").write_text(f"v = {win}1\n")
            patch = subprocess.run(["git", "diff"], cwd=cwd, capture_output=True, text=True).stdout
            (self.iter_dir / "patches" / f"{key}.patch").write_text(patch)
            (self.iter_dir / "experiment_plan.yaml").write_text(yaml.safe_dump({
                "metadata": {"iteration": 1, "bundle_ref": "bundle.yaml"},
                "arms": [{"arm_id": key, "conditions": [{"name": "kept", "cmd": "measure"}]}]}))
            (self.iter_dir / "findings.json").write_text(json.dumps({
                "iteration": 1, "bundle_ref": "bundle.yaml", "experiment_valid": True,
                "discrepancy_analysis": "x",
                "arms": [{"arm_type": "h-main" if key == "h-main" else "h-alternative", "predicted": "p",
                          "observed": "o", "status": "CONFIRMED", "error_type": None,
                          "diagnostic_note": None,
                          "metadata": {"candidate_id": key, "score": float(f"{win}1")}}]}))
            (self.iter_dir / "principle_updates.json").write_text("[]")
        return SDKResult(text="done", output_tokens=self.cost_tokens)


V7_BUNDLE = _bundle(MAIN, ALT, dict(ALT, mechanism_family="cycle cover by matching"))


def _v7_setup(tmp_path, monkeypatch, scores, valid=None, bundle=V7_BUNDLE, **v7cfg):
    repo = _make_repo(tmp_path)
    work = tmp_path / "work"
    it = work / "runs" / "iter-1"
    for sub in ("inputs", "results", "patches"):
        (it / sub).mkdir(parents=True)
    _design_dir(tmp_path, bundle)
    for f in (tmp_path / "iter").iterdir():
        shutil.copy(f, it / f.name)
    campaign = _campaign(design_profile="v7", objective={"weights": {"score": 1.0}},
                         **({"v7": v7cfg} if v7cfg else {}))
    campaign["target_system"]["repo_path"] = str(repo)
    fake = _Fake(work, it, scores, valid)
    monkeypatch.setattr("orchestrator.sdk_dispatch.time.sleep", lambda _s: None)
    d = SDKDispatcher(work_dir=work, campaign=campaign, sdk_runner=fake, max_retries=1)
    return repo, work, it, campaign, fake, d


def _run(repo, work, it, campaign, d):
    from orchestrator.v7_execute import run_v7_execute
    return run_v7_execute(d, campaign, work, it, 1, repo, extras=[])


SCORES = {"h-main": 50, "h-alternative-1": 70, "h-alternative-2": 60}


class TestV7Execute:
    def test_each_arm_screened_in_capped_session_then_winner_continues(self, tmp_path, monkeypatch):
        repo, work, it, campaign, fake, d = _v7_setup(tmp_path, monkeypatch, SCORES)
        wt, eid = _run(repo, work, it, campaign, d)
        assert fake.sessions == ["evaluator", "h-main", "h-alternative-1", "h-alternative-2", "winner"]
        assert fake.winner_saw == "v = 70\n"  # the winner session starts from the winning arm's version
        rows = [r for r in _metrics(work) if "budget_usd" in r]
        labels = [r["session_label"] for r in rows]
        assert labels == ["evaluator", "h-main", "h-alternative-1", "h-alternative-2", "winner"]
        s = v7_settings(campaign)
        assert all(r["budget_usd"] <= s.arm_budget_usd for r in rows[:-1])
        spent = sum(r["output_tokens"] for r in rows[:-1]) * 75 / 1e6
        assert rows[-1]["budget_usd"] == pytest.approx(s.iteration_budget_usd - spent, abs=0.01)
        # only the winner's worktree is left for the caller to clean up
        assert _git(repo, "worktree", "list").count("\n") == 2 and wt.exists()

    def test_losing_arms_recorded_as_findings_and_principles(self, tmp_path, monkeypatch):
        repo, work, it, campaign, fake, d = _v7_setup(tmp_path, monkeypatch, SCORES)
        _run(repo, work, it, campaign, d)
        findings = json.loads((it / "findings.json").read_text())
        jsonschema.validate(findings, FINDINGS_SCHEMA)
        ids = [a["metadata"]["candidate_id"] for a in findings["arms"]]
        assert ids == ["h-alternative-1", "h-main", "h-alternative-2"]
        main = findings["arms"][1]
        assert main["status"] == "REFUTED" and main["metadata"]["score"] == 50
        principles = json.loads((it / "principle_updates.json").read_text())
        assert {p["id"] for p in principles} == {"iter-1-h-main-lost", "iter-1-h-alternative-2-lost"}
        p_schema = json.loads((SCHEMAS / "principles.schema.json").read_text())
        jsonschema.validate({"principles": principles}, p_schema)
        assert all((it / "patches" / f"{k}.patch").stat().st_size > 0 for k in SCORES)

    def test_invalid_arm_cannot_win(self, tmp_path, monkeypatch):
        repo, work, it, campaign, fake, d = _v7_setup(
            tmp_path, monkeypatch, SCORES, valid={"h-alternative-1": False})
        _run(repo, work, it, campaign, d)
        assert fake.winner_saw == "v = 60\n"
        principles = json.loads((it / "principle_updates.json").read_text())
        lost = next(p for p in principles if p["id"] == "iter-1-h-alternative-1-lost")
        assert "validity check" in lost["statement"]
        from orchestrator.composite_score import update_best_found
        from orchestrator.iteration import _resolve_objective
        findings = json.loads((it / "findings.json").read_text())
        findings["arms"] = findings["arms"][1:]  # drop the winner: only the screened losers remain
        (it / "findings.json").write_text(json.dumps(findings))
        top = update_best_found(work, objective=_resolve_objective(campaign))["top_k"][0]
        assert top["candidate_id"] == "iter-1/h-main/h-main"  # the invalid 70 never ranks

    def test_no_valid_arm_winner_starts_from_incumbent(self, tmp_path, monkeypatch):
        repo, work, it, campaign, fake, d = _v7_setup(
            tmp_path, monkeypatch, SCORES, valid={k: False for k in SCORES})
        _run(repo, work, it, campaign, d)
        assert fake.winner_saw == "v = 0\n"

    def test_resume_skips_finished_screens(self, tmp_path, monkeypatch):
        repo, work, it, campaign, fake, d = _v7_setup(tmp_path, monkeypatch, SCORES)
        _run(repo, work, it, campaign, d)
        fake.sessions.clear()
        for name in ("findings.json", "principle_updates.json"):
            (it / name).unlink()
        state = json.loads((it / "arms" / "state.json").read_text())
        del state["winner"]
        (it / "arms" / "state.json").write_text(json.dumps(state))
        _run(repo, work, it, campaign, d)
        assert fake.sessions == ["winner"]
        assert fake.winner_saw == "v = 701\n"  # resumes from the winner's latest patch

    def test_evaluator_session_only_when_missing(self, tmp_path, monkeypatch):
        repo, work, it, campaign, fake, d = _v7_setup(tmp_path, monkeypatch, SCORES)
        (work / "evaluator").mkdir()
        (work / "evaluator" / "README.md").write_text("exists\n")
        _run(repo, work, it, campaign, d)
        assert "evaluator" not in fake.sessions

    def test_winner_prompt_carries_screening_summary(self, tmp_path, monkeypatch):
        repo, work, it, campaign, fake, d = _v7_setup(tmp_path, monkeypatch, SCORES)
        prompts = []
        orig = fake.__call__

        def spy(**kw):
            prompts.append(kw["prompt"])
            return orig(**kw)
        d._sdk_runner = spy
        _run(repo, work, it, campaign, d)
        winner_prompt = prompts[-1]
        assert "Screening results" in winner_prompt and "h-alternative-1" in winner_prompt
        assert "winner" in winner_prompt.lower()

    def test_winner_patch_is_the_kept_worktree_and_carries_forward(self, tmp_path, monkeypatch):
        from orchestrator.carry_forward import carry_forward_best
        from orchestrator.composite_score import update_best_found
        from orchestrator.iteration import _resolve_objective
        repo, work, it, campaign, fake, d = _v7_setup(tmp_path, monkeypatch, SCORES)
        fake.winner_mode = "sloppy"  # no patch, arm_type h-main, no candidate_id, a new file
        _run(repo, work, it, campaign, d)
        patch = (it / "patches" / "h-alternative-1.patch").read_text()
        assert "v = 701" in patch and "helper.py" in patch
        win = json.loads((it / "findings.json").read_text())["arms"][0]
        assert win["arm_type"] == "h-alternative" and win["metadata"]["candidate_id"] == "h-alternative-1"
        top = update_best_found(work, objective=_resolve_objective(campaign))["top_k"][0]
        assert top["candidate_id"] == "iter-1/h-alternative/h-alternative-1" and top["score"] == 701
        assert carry_forward_best(work, repo)
        assert (repo / "solution.py").read_text() == "v = 701\n" and (repo / "helper.py").is_file()

    def test_arm_without_result_never_applies_its_patch(self, tmp_path, monkeypatch):
        repo, work, it, campaign, fake, d = _v7_setup(tmp_path, monkeypatch, SCORES)
        fake.no_result = True
        _run(repo, work, it, campaign, d)
        assert fake.winner_saw == "v = 0\n"
        assert json.loads((it / "arms" / "state.json").read_text())["winner"]["patch_applied"] is False

    def test_cut_winner_resumes_its_worktree_on_the_remaining_budget(self, tmp_path, monkeypatch):
        repo, work, it, campaign, fake, d = _v7_setup(tmp_path, monkeypatch, SCORES)
        fake.winner_mode = "cut"  # $1.50 per attempt, never writes findings.json
        wt, _ = _run(repo, work, it, campaign, d)
        assert not (it / "findings.json").exists() and wt.exists()
        _run(repo, work, it, campaign, d)
        assert fake.winner_saw == "v = 701\n"  # the retry continues in the kept worktree
        assert fake.budgets[5] == pytest.approx(12.0 - 5 * 1.5, abs=0.01)  # only what is left

    def test_spent_budget_stops_the_winner_and_records_the_screening(self, tmp_path, monkeypatch):
        repo, work, it, campaign, fake, d = _v7_setup(tmp_path, monkeypatch, SCORES)
        fake.winner_mode, fake.winner_tokens = "cut", 80_000  # $6: the iteration budget is gone
        _run(repo, work, it, campaign, d)
        findings = json.loads((it / "findings.json").read_text())
        jsonschema.validate(findings, FINDINGS_SCHEMA)
        ids = [a["metadata"]["candidate_id"] for a in findings["arms"]]
        assert ids[0] == "h-alternative-1" and set(ids) == set(SCORES)
        assert findings["arms"][0]["metadata"]["score"] == 70
        assert (it / "experiment_plan.yaml").exists() and (it / "principle_updates.json").exists()
        # the measured screening patch is kept, not the unmeasured worktree state
        assert "v = 70\n" in (it / "patches" / "h-alternative-1.patch").read_text()
        from orchestrator.validate import validate_execution
        assert validate_execution(it, campaign=campaign)["status"] == "pass"
        n = len(fake.sessions)
        _run(repo, work, it, campaign, d)
        assert len(fake.sessions) == n  # no more spending once the budget is gone


# ─── full iteration through run_iteration ──────────────────────────────────

TEMPLATES = ROOT / "orchestrator" / "templates"


class _DesignAndExecute(_Fake):
    """Adds a scripted designer that writes the v7 bundle."""

    def __call__(self, **kw):
        p = kw["prompt"]
        if "scientific planner" in p.split("\n", 1)[0] or p.startswith("# Design"):
            self.sessions.append("design")
            it = self.work_dir / "runs" / "iter-1"
            (it / "problem.md").write_text("# P\n")
            (it / "handoff_snapshot.md").write_text("# H\n")
            (it / "bundle.yaml").write_text(yaml.safe_dump(V7_BUNDLE))
            return SDKResult(text="designed", output_tokens=self.cost_tokens)
        return super().__call__(**kw)


def test_run_iteration_v7_end_to_end(tmp_path, monkeypatch):
    import orchestrator.iteration as ri
    from orchestrator.dispatch import StubDispatcher
    from orchestrator.iteration import IterationOutcome, run_iteration
    repo = _make_repo(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    for t in ("state.json", "ledger.json", "principles.json"):
        shutil.copy(TEMPLATES / t, work / t)
    campaign = _campaign(design_profile="v7", objective={"weights": {"score": 1.0}})
    campaign["target_system"]["repo_path"] = str(repo)
    fake = _DesignAndExecute(work, work / "runs" / "iter-1", SCORES)
    monkeypatch.setattr("orchestrator.sdk_dispatch._default_sdk_runner_factory", lambda: fake)
    monkeypatch.setattr("orchestrator.sdk_dispatch.time.sleep", lambda _s: None)

    def stub(work_dir, campaign, model=None):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return StubDispatcher(work_dir)
    monkeypatch.setattr(ri, "LLMDispatcher", stub)
    assert run_iteration(campaign, work, iteration=1, auto_approve=True) == IterationOutcome.COMPLETED
    assert fake.sessions == ["design", "evaluator", "h-main", "h-alternative-1", "h-alternative-2", "winner"]
    rows = {r["session_label"]: r["budget_usd"] for r in _metrics(work) if "session_label" in r}
    assert rows["design"] == v7_settings(campaign).design_budget_usd
    best = json.loads((work / "best_found.json").read_text())["top_k"][0]
    assert best["candidate_id"] == "iter-1/h-alternative/h-alternative-1" and best["score"] == 701
    assert _git(repo, "worktree", "list").count("\n") == 1  # winner worktree cleaned up too
    from orchestrator.iteration import _maybe_carry_forward
    _maybe_carry_forward(campaign, work, str(repo))
    assert (repo / "solution.py").read_text() == "v = 701\n"


def test_run_iteration_v7_keeps_cut_winner_worktree(tmp_path, monkeypatch):
    import orchestrator.iteration as ri
    from orchestrator.dispatch import StubDispatcher
    from orchestrator.iteration import ExecuteAnalyzeIncompleteError, run_iteration
    repo = _make_repo(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    for t in ("state.json", "ledger.json", "principles.json"):
        shutil.copy(TEMPLATES / t, work / t)
    campaign = _campaign(design_profile="v7", objective={"weights": {"score": 1.0}})
    campaign["target_system"]["repo_path"] = str(repo)
    fake = _DesignAndExecute(work, work / "runs" / "iter-1", SCORES)
    fake.winner_mode = "cut"
    monkeypatch.setattr("orchestrator.sdk_dispatch._default_sdk_runner_factory", lambda: fake)
    monkeypatch.setattr("orchestrator.sdk_dispatch.time.sleep", lambda _s: None)

    def stub(work_dir, campaign, model=None):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return StubDispatcher(work_dir)
    monkeypatch.setattr(ri, "LLMDispatcher", stub)
    with pytest.raises(ExecuteAnalyzeIncompleteError):
        run_iteration(campaign, work, iteration=1, auto_approve=True)
    assert _git(repo, "worktree", "list").count("\n") == 2  # the winner's worktree is kept for resume
