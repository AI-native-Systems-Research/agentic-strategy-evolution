"""design_profile v8: transcript caps, judge profile, warm winner, exploit iterations, repairs, robustness.

No live LLM: SDK sessions are scripted runners (``sdk_runner=``) or fake ``claude_agent_sdk`` modules
whose "CLI" is a dummy local process, as in tests/test_sdk_cli_reap.py.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import types
import warnings
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.design_profile import design_guidance, execute_guidance, v7_settings, v8_settings
from orchestrator.sdk_dispatch import SDKDispatcher, SDKHangError, SDKResult, _default_sdk_runner_factory
from orchestrator.validate import validate_design
from tests.test_sdk_cli_reap import _alive
from tests.test_v7_profile import (
    ALT, CAMPAIGN_SCHEMA, FINDINGS_SCHEMA, MAIN, ROOT, TEMPLATES, _bundle, _campaign, _design_dir,
    _git, _make_repo, _metrics, _Runner,
)

V8_BUNDLE = _bundle(MAIN, ALT)


def _v8(**extra):
    return _campaign(design_profile="v8", objective={"weights": {"score": 1.0}}, **extra)


# ─── profile plumbing ───────────────────────────────────────────────────────────────────────

class TestProfile:
    def test_schema_accepts_v8_and_its_block(self):
        c = _v8(v8={"arm_budget_usd": 3, "iteration_budget_usd": 15, "winner_share": 0.5,
                    "repair_budget_usd": 0.5, "hang_minutes": 10, "official_log": "/tmp/x.jsonl"})
        jsonschema.validate(c, CAMPAIGN_SCHEMA)

    def test_v8_reads_its_block_and_falls_back_to_v7(self):
        assert v7_settings(_v8(v8={"iteration_budget_usd": 20})).iteration_budget_usd == 20
        assert v7_settings(_v8(v7={"iteration_budget_usd": 30})).iteration_budget_usd == 30
        s8 = v8_settings(_v8())
        assert (s8.winner_share, s8.repair_budget_usd, s8.hang_minutes, s8.assumed_time_limit_s) == (
            0.4, 1.0, 15.0, 1.0)

    def test_v8_uses_the_v7_guidance_and_bundle_rules(self, tmp_path):
        for fn in (lambda c: design_guidance(c, 30), execute_guidance):
            assert fn(_v8()) == fn(_campaign(design_profile="v7"))
        d = _design_dir(tmp_path, _bundle({k: v for k, v in MAIN.items() if k != "validity_check"}))
        errors = validate_design(d, campaign=_v8())["errors"]
        assert any("validity_check" in e for e in errors)

    def test_shared_prompts_have_no_v8_text(self):
        for name in ("design.md", "execute_analyze.md", "build_evaluator.md", "execute_arm.md"):
            text = (ROOT / "prompts" / "methodology" / name).read_text()
            assert "v8" not in text and "judge_profile" not in text

    def test_v8_prompts_have_no_double_dash(self):
        for name in ("build_evaluator_v8.md", "execute_arm_v8.md", "continue_arm.md", "repair_arm.md"):
            assert "--" not in (ROOT / "prompts" / "methodology" / name).read_text()


class TestBudgetSplit:
    def test_winner_keeps_at_least_forty_percent(self):
        from orchestrator.v8_execute import v8_screening_cap, winner_reserve
        c = _v8(v8={"iteration_budget_usd": 20, "arm_budget_usd": 10})
        s, s8 = v7_settings(c), v8_settings(c)
        assert winner_reserve(s, s8) == pytest.approx(8.0)
        caps = [v8_screening_cap(s, s8, 16.0, 2)]
        assert 16.0 - 2 * caps[0] >= 8.0 - 1e-9


# ─── 1. caps from the transcript ────────────────────────────────────────────────────────────

_SLEEPER = "import time; time.sleep(60)"


def _iso(t=None):
    return datetime.fromtimestamp(t or time.time(), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _transcript_sdk(transcript: Path, spawned: dict, *, replies=0, stream_out=10, tx_out=10_000,
                    silent_s=0.0, api_errors=False, finish=True):
    """A fake SDK whose CLI is a real sleeping process; the stream ends when that process is killed.

    Each reply streams ``stream_out`` output tokens (what the SDK reports) and writes ``tx_out`` to the
    transcript (the truth). ``silent_s``: after the replies, write transcript lines for this long without
    any stream message (a long reply), with system/api_error lines when ``api_errors``.
    """
    import anyio

    class _Opts:
        def __init__(self, **kw):
            self.kw = kw

    class SystemMessage:
        def __init__(self, subtype, data):
            self.subtype, self.data = subtype, data

    class AssistantMessage:
        def __init__(self, i):
            self.content = []
            self.usage = {"output_tokens": stream_out}
            self.message_id = f"msg_{i}"
            self.session_id = "sess-t"

    class ResultMessage:
        is_error = False
        usage = {"output_tokens": stream_out}
        total_cost_usd = 0.0
        duration_ms = 1
        num_turns = 1
        session_id = "sess-t"
        subtype = "success"
        result = "done"

    class SubprocessCLITransport:
        def __init__(self, prompt, options):  # noqa: ARG002
            self._process = None

        async def connect(self):
            self._process = await anyio.open_process([sys.executable, "-c", _SLEEPER])
            spawned["cli"] = self._process.pid

        async def close(self):
            return None

    def write(line):
        with open(transcript, "a") as f:
            f.write(json.dumps(line) + "\n")

    async def _query(*, prompt, options, transport=None):  # noqa: ARG001
        await transport.connect()
        pid = spawned["cli"]
        yield SystemMessage("init", {"session_id": "sess-t"})
        for i in range(replies):
            if not _alive(pid):
                return
            for _ in range(2):  # one reply is several transcript lines repeating its usage
                write({"type": "assistant", "timestamp": _iso(), "uuid": f"u{i}",
                       "message": {"id": f"msg_{i}", "usage": {"output_tokens": tx_out}}})
            yield AssistantMessage(i)
            await anyio.sleep(0.01)
        t0 = time.time()
        n = 0
        while time.time() - t0 < silent_s:
            if not _alive(pid):
                return
            if api_errors:
                write({"type": "system", "subtype": "api_error", "level": "error", "timestamp": _iso(),
                       "content": "Request timed out."})
            else:
                n += 1
                write({"type": "assistant", "timestamp": _iso(),
                       "message": {"id": f"long_{n}", "usage": {"output_tokens": tx_out}}})
            await anyio.sleep(0.05)
        if finish:
            os.kill(pid, 15)  # a CLI exits after its final result
            yield ResultMessage()

    m = types.ModuleType("claude_agent_sdk")
    m.ClaudeAgentOptions = _Opts
    m.query = _query
    m.SubprocessCLITransport = SubprocessCLITransport
    return m


@pytest.fixture
def spawned():
    procs = {}
    yield procs
    for pid in procs.values():
        try:
            os.kill(pid, 9)
        except (ProcessLookupError, TypeError):
            pass


def _transcript_runner(monkeypatch, tmp_path, spawned, **sdk_kw):
    transcript = tmp_path / "sess-t.jsonl"
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", _transcript_sdk(transcript, spawned, **sdk_kw))
    locator = lambda cwd, ids: [transcript] if "sess-t" in ids and transcript.exists() else []  # noqa: E731
    return _default_sdk_runner_factory(transcript_locator=locator, poll_s=0.05), transcript


class TestTranscriptCaps:
    def test_cap_counts_transcript_output_tokens(self, monkeypatch, tmp_path, spawned):
        # $0.75 per reply in the transcript, $0.00075 on the stream: the stream alone never reaches $2
        runner, _ = _transcript_runner(monkeypatch, tmp_path, spawned, replies=10)
        res = runner(prompt="p", model="m", cwd=tmp_path, max_turns=5, max_cost_usd=2.0, transcript_caps=True)
        assert res.is_error and res.subtype == "error_max_budget_usd" and res.session_id == "sess-t"
        assert res.output_tokens == 30_000 and res.cost_usd == pytest.approx(2.25)
        assert not _alive(spawned["cli"])

    def test_without_transcript_caps_the_stream_undercounts(self, monkeypatch, tmp_path, spawned):
        runner, _ = _transcript_runner(monkeypatch, tmp_path, spawned, replies=10)
        res = runner(prompt="p", model="m", cwd=tmp_path, max_turns=5, max_cost_usd=2.0)
        assert not res.is_error and res.output_tokens == 10  # the v7 blind spot, unchanged for v7

    def test_background_poll_stops_a_session_with_no_stream_messages(self, monkeypatch, tmp_path, spawned):
        runner, _ = _transcript_runner(monkeypatch, tmp_path, spawned, replies=0, silent_s=20.0)
        t0 = time.time()
        res = runner(prompt="p", model="m", cwd=tmp_path, max_turns=5, max_cost_usd=2.0, transcript_caps=True)
        assert time.time() - t0 < 15
        assert res.subtype == "error_max_budget_usd" and res.cost_usd >= 2.0
        assert not _alive(spawned["cli"])

    def test_finished_session_reports_transcript_usage(self, monkeypatch, tmp_path, spawned):
        runner, _ = _transcript_runner(monkeypatch, tmp_path, spawned, replies=2)
        res = runner(prompt="p", model="m", cwd=tmp_path, max_turns=5, max_cost_usd=9.0, transcript_caps=True)
        assert not res.is_error and res.output_tokens == 20_000

    def test_resumed_history_is_not_counted_again(self, monkeypatch, tmp_path, spawned):
        runner, transcript = _transcript_runner(monkeypatch, tmp_path, spawned, replies=1)
        transcript.write_text(json.dumps({"type": "assistant", "timestamp": _iso(time.time() - 3600),
                                          "message": {"id": "old", "usage": {"output_tokens": 500_000}}}) + "\n")
        res = runner(prompt="p", model="m", cwd=tmp_path, max_turns=5, max_cost_usd=9.0, transcript_caps=True,
                     resume="sess-t")
        assert res.output_tokens == 10_000

    def test_metrics_row_and_iteration_spend_use_transcript_numbers(self, monkeypatch, tmp_path, spawned):
        from orchestrator.v7_execute import iteration_spent, mark_iteration_start
        runner, _ = _transcript_runner(monkeypatch, tmp_path, spawned, replies=10)
        monkeypatch.setattr("orchestrator.sdk_dispatch.time.sleep", lambda _s: None)
        c = _v8()
        c["target_system"]["repo_path"] = str(tmp_path)
        it = tmp_path / "runs" / "iter-1"
        it.mkdir(parents=True)
        mark_iteration_start(c, tmp_path, it)
        d = SDKDispatcher(work_dir=tmp_path, campaign=c, sdk_runner=runner, max_retries=1)
        with d.session_budget(2.0, label="h-main"):
            d.dispatch("planner", "design", output_path=tmp_path / "o.md", iteration=1)
        row = _metrics(tmp_path)[-1]
        assert row["output_tokens"] == 30_000 and row["session_label"] == "h-main"
        assert iteration_spent(c, tmp_path, it) == pytest.approx(2.25)
        assert "max_budget_stop" in (tmp_path / "retry_log.jsonl").read_text()  # and no wrap-up turn

    def test_default_locator_finds_session_and_subagent_files(self, tmp_path):
        from orchestrator.sdk_dispatch import default_transcript_paths, project_key
        cwd = tmp_path / "wt.x"
        cwd.mkdir()
        proj = tmp_path / "cfg" / "projects" / project_key(cwd)
        (proj / "s1" / "subagents").mkdir(parents=True)
        (proj / "s1.jsonl").write_text("")
        (proj / "s1" / "subagents" / "agent-a.jsonl").write_text("")
        (tmp_path / "cfg" / "projects" / "other").mkdir()
        (tmp_path / "cfg" / "projects" / "other" / "s2.jsonl").write_text("")
        found = {p.name for p in default_transcript_paths(cwd, {"s1", "s2"}, config_dir=tmp_path / "cfg")}
        assert found == {"s1.jsonl", "agent-a.jsonl", "s2.jsonl"}


class TestNoWrapUpAfterCap:
    BUDGET_ERR = dict(text="", is_error=True, error_message="cap", subtype="error_max_budget_usd",
                      session_id="s-1")

    def _sdk(self, tmp_path, monkeypatch, campaign, runner):
        monkeypatch.setattr("orchestrator.sdk_dispatch.time.sleep", lambda _s: None)
        campaign["target_system"]["repo_path"] = str(tmp_path)
        (tmp_path / "runs" / "iter-1").mkdir(parents=True, exist_ok=True)
        return SDKDispatcher(work_dir=tmp_path, campaign=campaign, sdk_runner=runner, max_retries=2)

    def test_arm_cap_stop_has_no_wrap_up_turn(self, tmp_path, monkeypatch):
        runner = _Runner([SDKResult(**self.BUDGET_ERR), SDKResult(text="never")])
        d = self._sdk(tmp_path, monkeypatch, _v8(), runner)
        with d.session_budget(4.0, label="h-main"):
            d.dispatch("planner", "design", output_path=tmp_path / "o.md", iteration=1)
        assert len(runner.calls) == 1 and runner.calls[0]["transcript_caps"] is True
        assert "max_budget_wrap_up" not in (tmp_path / "retry_log.jsonl").read_text()

    def test_design_cap_stop_keeps_its_wrap_up(self, tmp_path, monkeypatch):
        runner = _Runner([SDKResult(**self.BUDGET_ERR), SDKResult(text="wrapped")])
        d = self._sdk(tmp_path, monkeypatch, _v8(), runner)
        with d.session_budget(4.0, label="design"):
            d.dispatch("planner", "design", output_path=tmp_path / "o.md", iteration=1)
        assert len(runner.calls) == 2 and runner.calls[1]["resume"] == "s-1"

    def test_v7_keeps_its_wrap_up_and_stream_caps(self, tmp_path, monkeypatch):
        runner = _Runner([SDKResult(**self.BUDGET_ERR), SDKResult(text="wrapped")])
        d = self._sdk(tmp_path, monkeypatch, _campaign(design_profile="v7"), runner)
        with d.session_budget(4.0, label="h-main"):
            d.dispatch("planner", "design", output_path=tmp_path / "o.md", iteration=1)
        assert len(runner.calls) == 2
        assert "transcript_caps" not in runner.calls[0] and "hang_after_s" not in runner.calls[0]


# ─── 6b. hang watchdog ──────────────────────────────────────────────────────────────────────

class TestHangWatchdog:
    def test_api_error_loop_without_replies_kills_the_session(self, monkeypatch, tmp_path, spawned):
        runner, _ = _transcript_runner(monkeypatch, tmp_path, spawned, replies=1, silent_s=20.0,
                                       api_errors=True)
        t0 = time.time()
        with pytest.raises(SDKHangError) as info:
            runner(prompt="p", model="m", cwd=tmp_path, max_turns=5, max_cost_usd=9.0, transcript_caps=True,
                   hang_after_s=0.4)
        assert time.time() - t0 < 15
        assert info.value.session_id == "sess-t" and info.value.usage["output_tokens"] == 10_000
        assert not _alive(spawned["cli"])

    def test_long_reply_without_api_errors_is_not_a_hang(self, monkeypatch, tmp_path, spawned):
        runner, _ = _transcript_runner(monkeypatch, tmp_path, spawned, replies=0, silent_s=1.0, tx_out=1)
        res = runner(prompt="p", model="m", cwd=tmp_path, max_turns=5, hang_after_s=0.3)
        assert not res.is_error

    def test_dispatcher_does_not_retry_a_hang(self, tmp_path, monkeypatch):
        err = SDKHangError("hung")
        err.usage, err.session_id = {"output_tokens": 20_000}, "s-h"
        runner = _Runner([err, SDKResult(text="never")])
        monkeypatch.setattr("orchestrator.sdk_dispatch.time.sleep", lambda _s: None)
        c = _v8()
        c["target_system"]["repo_path"] = str(tmp_path)
        (tmp_path / "runs" / "iter-1").mkdir(parents=True)
        d = SDKDispatcher(work_dir=tmp_path, campaign=c, sdk_runner=runner, max_retries=3)
        with pytest.raises(SDKHangError), d.session_budget(4.0, label="h-main"):
            d.dispatch("planner", "design", output_path=tmp_path / "o.md", iteration=1)
        assert len(runner.calls) == 1 and runner.calls[0]["hang_after_s"] == 15 * 60
        assert '"hang"' in (tmp_path / "retry_log.jsonl").read_text()
        assert _metrics(tmp_path)[-1]["output_tokens"] == 20_000  # the hung session's spend is charged


# ─── 2 and 7. judge profile ─────────────────────────────────────────────────────────────────

def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _instrument(work, limit=None, runs=(10.0, 10.0, 10.0)):
    it = work / "runs" / "iter-1"
    it.mkdir(parents=True, exist_ok=True)
    (it / "instrument.json").write_text(json.dumps({
        "max_cpu_s": 0.5, "time_limit_s": limit, "speed_first": False,
        "noise": {"runs": list(runs), "min": min(runs), "max": max(runs), "spread": max(runs) - min(runs)}}))


class TestJudgeProfile:
    def test_assumes_one_second_when_the_statement_gives_none(self, tmp_path):
        from orchestrator.judge_profile import update_judge_profile
        _instrument(tmp_path, limit=None)
        p = update_judge_profile(_v8(), tmp_path)
        assert p["assumed_time_limit_s"] == 1.0 and p["time_limit_source"].startswith("assumed")
        _instrument(tmp_path, limit=2.0)
        assert update_judge_profile(_v8(), tmp_path)["assumed_time_limit_s"] == 2.0

    def test_longest_accepted_runtime_and_likely_timeouts(self, tmp_path):
        from orchestrator.judge_profile import SUMMARY_FILE, update_judge_profile
        _instrument(tmp_path)
        _write_jsonl(tmp_path / "official_measures.jsonl", [
            {"ts": 1, "sha256": "a", "score": 60}, {"ts": 2, "sha256": "b", "score": 61},
            {"ts": 3, "sha256": "c", "score": 0}, {"ts": 4, "sha256": "d", "score": 0, "rejected": True}])
        _write_jsonl(tmp_path / "evaluator" / "local_runs.jsonl", [
            {"sha256": "a", "score": 60, "max_cpu_s": 0.8}, {"sha256": "b", "score": 62, "max_cpu_s": 1.6},
            {"sha256": "c", "score": 70, "max_cpu_s": 27.0}, {"sha256": "d", "score": 70, "max_cpu_s": 0.1}])
        p = update_judge_profile(_v8(), tmp_path)
        assert p["longest_accepted_local"]["local_max_cpu_s"] == 1.6
        assert [t["sha256"] for t in p["likely_timeouts"]] == ["c"]
        on_disk = json.loads((tmp_path / "judge_profile.json").read_text())
        assert on_disk["likely_timeouts"][0]["local_max_cpu_s"] == 27.0
        summary = (tmp_path / SUMMARY_FILE).read_text()
        assert len([l for l in summary.splitlines() if l.startswith("- ")]) == 3
        assert "1.6 s" in summary and "too slow" in summary

    def test_evaluator_untrusted_when_first_two_measures_disagree(self, tmp_path):
        from orchestrator.judge_profile import judge_summary, update_judge_profile
        _instrument(tmp_path, runs=(10.0, 10.5, 11.0))  # noise 1: allowed gap 2 * 1 + 5 = 7
        _write_jsonl(tmp_path / "official_measures.jsonl", [
            {"ts": 1, "sha256": "a", "score": 10.4}, {"ts": 2, "sha256": "b", "score": 9.9}])
        _write_jsonl(tmp_path / "evaluator" / "local_runs.jsonl", [
            {"sha256": "a", "score": 91.8, "max_cpu_s": 1}, {"sha256": "b", "score": 90.0, "max_cpu_s": 1}])
        p = update_judge_profile(_v8(), tmp_path)
        assert p["evaluator"]["trusted"] is False and p["evaluator"]["threshold"] == 7.0
        assert "UNTRUSTED" in judge_summary(_v8(), tmp_path)

    def test_evaluator_trusted_when_close_and_checked_per_session(self, tmp_path):
        from orchestrator.judge_profile import update_judge_profile, watch_session
        _instrument(tmp_path)
        _write_jsonl(tmp_path / "evaluator" / "local_runs.jsonl", [
            {"sha256": "a", "score": 50, "max_cpu_s": 1}, {"sha256": "b", "score": 52, "max_cpu_s": 1}])
        with watch_session(_v8(), tmp_path, "h-main", poll_s=0.05):
            now = time.time()
            _write_jsonl(tmp_path / "official_measures.jsonl", [
                {"ts": now, "sha256": "a", "score": 49}, {"ts": now, "sha256": "b", "score": 50}])
        p = update_judge_profile(_v8(), tmp_path)
        assert p["evaluator"]["trusted"] is True and p["evaluator"]["session"] == "h-main"

    def test_other_profiles_get_no_judge_summary(self, tmp_path):
        from orchestrator.judge_profile import judge_summary
        assert judge_summary(_campaign(design_profile="v7"), tmp_path) == ""
        assert not (tmp_path / "judge_profile.json").exists()

    def test_official_log_path_is_configurable(self, tmp_path):
        from orchestrator.judge_profile import best_official
        log = tmp_path / "elsewhere.jsonl"
        _write_jsonl(log, [{"ts": 1, "sha256": "a", "score": 33}])
        assert best_official(_v8(v8={"official_log": str(log)}), tmp_path) == 33


# ─── v8 EXECUTE on a real git repo with a scripted SDK runner ───────────────────────────────

class _V8Fake:
    """Scripted v8 sessions acting on their prompts (files on disk), like real ones would."""

    def __init__(self, work_dir, iter_dir, scores, valid=None, cost_tokens=20_000):
        self.work_dir, self.iter_dir = Path(work_dir), Path(iter_dir)
        self.scores, self.valid = dict(scores), dict(valid or {})
        self.cost_tokens = cost_tokens
        self.calls = []  # (name, kwargs)
        self.raise_in = {}  # session name -> exception to raise once
        self.repair_scores = {}
        self.baseline = False
        self.next_step = None
        self.instrument = None

    def __call__(self, **kw):
        prompt, cwd = kw["prompt"], Path(kw["cwd"])
        if "Build the local evaluator" in prompt:
            name = "evaluator"
        elif "Screen arm `" in prompt:
            name = prompt.split("Screen arm `", 1)[1].split("`", 1)[0]
        elif "Repair arm `" in prompt:
            name = "repair:" + prompt.split("Repair arm `", 1)[1].split("`", 1)[0]
        elif "won the screening" in prompt:
            name = "winner:" + prompt.split("Arm `", 1)[1].split("`", 1)[0]
        elif prompt.startswith("# Design") or "scientific planner" in prompt.split("\n", 1)[0]:
            name = "design"
        else:
            name = "other"
        self.calls.append((name, dict(kw)))
        exc = self.raise_in.pop(name, None)
        if exc is not None:
            raise exc
        return getattr(self, "_" + name.split(":")[0].replace("-", "_"), self._arm)(name, prompt, cwd)

    def _patch(self, cwd, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(subprocess.run(["git", "diff"], cwd=cwd, capture_output=True, text=True).stdout)

    def _result(self, key, score, valid=True):
        out = self.iter_dir / "arms" / key
        out.mkdir(parents=True, exist_ok=True)
        r = {"arm_key": key, "arm_type": "h-main" if key == "h-main" else "h-alternative",
             "mechanism_family": key, "metrics": {"score": score},
             "validity_check": {"passed": valid, "detail": "tiny case"},
             "predicted": "score >= 60", "observed": f"score {score}",
             "status": "CONFIRMED" if score >= 60 else "REFUTED", "error_type": None,
             "per_group": [{"group": "large", "n": 3, "mean_score": score, "max_cpu_s": 0.5, "timeouts": 0}]}
        if self.next_step:
            r["next_step"] = self.next_step
        (out / "result.json").write_text(json.dumps(r))

    def _evaluator(self, name, prompt, cwd):
        (self.work_dir / "evaluator").mkdir(exist_ok=True)
        (self.work_dir / "evaluator" / "README.md").write_text("python eval.py\n")
        if self.instrument is not None:
            (self.iter_dir / "instrument.json").write_text(json.dumps(self.instrument))
        if self.baseline:
            (cwd / "solution.py").write_text("v = 5\n")
            self._patch(cwd, re.search(r"git diff > (\S+baseline\.patch)", prompt).group(1))
        return SDKResult(text="done", output_tokens=self.cost_tokens, session_id="sess-evaluator")

    def _arm(self, key, prompt, cwd):
        score = self.scores[key]
        (cwd / "solution.py").write_text(f"v = {score}\n")
        self._patch(cwd, self.iter_dir / "patches" / f"{key}.patch")
        self._result(key, score, self.valid.get(key, True))
        return SDKResult(text="done", output_tokens=self.cost_tokens, session_id=f"sess-{key}")

    def _repair(self, name, prompt, cwd):
        key = name.split(":", 1)[1]
        score = self.repair_scores.get(key, self.scores[key])
        (cwd / "solution.py").write_text(f"v = {score}\n")
        self._patch(cwd, self.iter_dir / "patches" / f"{key}.patch")
        self._result(key, score, True)
        return SDKResult(text="fixed", output_tokens=5_000, session_id=f"sess-{key}")

    def _winner(self, name, prompt, cwd):
        key = name.split(":", 1)[1]
        self.winner_saw = (cwd / "solution.py").read_text()
        old = self.winner_saw.split("=")[1].strip()
        (cwd / "solution.py").write_text(f"v = {old}1\n")
        self._patch(cwd, self.iter_dir / "patches" / f"{key}.patch")
        self._result(key, int(f"{old}1"), True)
        return SDKResult(text="deeper", output_tokens=self.cost_tokens, session_id=f"sess-{key}")

    def names(self):
        return [n for n, _ in self.calls]


def _setup(tmp_path, monkeypatch, scores, bundle=V8_BUNDLE, valid=None, **v8cfg):
    repo = _make_repo(tmp_path)
    work = tmp_path / "work"
    it = work / "runs" / "iter-1"
    for sub in ("inputs", "results", "patches"):
        (it / sub).mkdir(parents=True)
    _design_dir(tmp_path, bundle)
    for f in (tmp_path / "iter").iterdir():
        shutil.copy(f, it / f.name)
    campaign = _v8(**({"v8": v8cfg} if v8cfg else {}))
    campaign["target_system"]["repo_path"] = str(repo)
    fake = _V8Fake(work, it, scores, valid)
    monkeypatch.setattr("orchestrator.sdk_dispatch.time.sleep", lambda _s: None)
    d = SDKDispatcher(work_dir=work, campaign=campaign, sdk_runner=fake, max_retries=1)
    return repo, work, it, campaign, fake, d


def _execute(repo, work, it, campaign, d, iteration=1):
    from orchestrator.v8_execute import run_v8_execute
    return run_v8_execute(d, campaign, work, it, iteration, repo, extras=[])


SCORES = {"h-main": 50, "h-alternative-1": 70}


class TestWarmWinner:
    def test_winner_continues_its_own_session_and_worktree(self, tmp_path, monkeypatch):
        repo, work, it, campaign, fake, d = _setup(tmp_path, monkeypatch, SCORES)
        wt, eid = _execute(repo, work, it, campaign, d)
        assert fake.names() == ["evaluator", "h-main", "h-alternative-1", "winner:h-alternative-1"]
        screen = dict(fake.calls)["h-alternative-1"]
        cont = dict(fake.calls)["winner:h-alternative-1"]
        assert cont["resume"] == "sess-h-alternative-1" and cont["cwd"] == screen["cwd"] == wt
        assert fake.winner_saw == "v = 70\n"  # its own kept state, not a fresh worktree
        s = v7_settings(campaign)
        assert cont["max_cost_usd"] >= 0.4 * s.iteration_budget_usd
        assert _git(repo, "worktree", "list").count("\n") == 2  # only the winner's worktree is left

    def test_orchestrator_writes_every_artifact(self, tmp_path, monkeypatch):
        from orchestrator.validate import validate_execution
        repo, work, it, campaign, fake, d = _setup(tmp_path, monkeypatch, SCORES)
        _execute(repo, work, it, campaign, d)
        findings = json.loads((it / "findings.json").read_text())
        jsonschema.validate(findings, FINDINGS_SCHEMA)
        assert [a["metadata"]["candidate_id"] for a in findings["arms"]] == ["h-alternative-1", "h-main"]
        assert findings["arms"][0]["metadata"]["score"] == 701
        principles = json.loads((it / "principle_updates.json").read_text())
        assert [p["id"] for p in principles] == ["iter-1-h-main-lost"]
        assert validate_execution(it, campaign=campaign)["status"] == "pass"
        update = (it / "handoff_update.md").read_text()
        assert "h-alternative-1" in update and "701" in update
        assert "v = 701" in (it / "patches" / "h-alternative-1.patch").read_text()

    def test_crash_resume_does_not_redo_screens(self, tmp_path, monkeypatch):
        class _Die(BaseException):
            pass
        repo, work, it, campaign, fake, d = _setup(tmp_path, monkeypatch, SCORES)
        fake.raise_in["winner:h-alternative-1"] = _Die()
        with pytest.raises(_Die):
            _execute(repo, work, it, campaign, d)
        n = len(fake.calls)
        _execute(repo, work, it, campaign, d)
        assert fake.names()[n:] == ["winner:h-alternative-1"]
        assert fake.winner_saw == "v = 70\n"


class TestRepair:
    def test_zero_score_arm_gets_one_repair_in_its_session_and_can_win(self, tmp_path, monkeypatch):
        repo, work, it, campaign, fake, d = _setup(tmp_path, monkeypatch, {"h-main": 40, "h-alternative-1": 0})
        fake.repair_scores["h-alternative-1"] = 80
        _execute(repo, work, it, campaign, d)
        assert fake.names() == ["evaluator", "h-main", "h-alternative-1", "repair:h-alternative-1",
                                "winner:h-alternative-1"]
        rep = dict(fake.calls)["repair:h-alternative-1"]
        assert rep["resume"] == "sess-h-alternative-1" and rep["cwd"] == dict(fake.calls)["h-alternative-1"]["cwd"]
        assert rep["max_cost_usd"] == pytest.approx(v8_settings(campaign).repair_budget_usd)
        assert "official judge scored it 0" in rep["prompt"]

    def test_invalid_arm_repaired_once_only(self, tmp_path, monkeypatch):
        repo, work, it, campaign, fake, d = _setup(tmp_path, monkeypatch, SCORES,
                                                   valid={"h-alternative-1": False})
        fake.repair_scores["h-alternative-1"] = 60
        _execute(repo, work, it, campaign, d)
        assert fake.names().count("repair:h-alternative-1") == 1
        assert "repair:h-main" not in fake.names()
        assert fake.names()[-1] == "winner:h-alternative-1"  # 60 after repair beats 50

    def test_repair_can_be_disabled(self, tmp_path, monkeypatch):
        repo, work, it, campaign, fake, d = _setup(tmp_path, monkeypatch, {"h-main": 40, "h-alternative-1": 0},
                                                   repair_budget_usd=0)
        _execute(repo, work, it, campaign, d)
        assert not any(n.startswith("repair:") for n in fake.names())


class TestRobustness:
    def test_any_exception_in_an_arm_marks_it_failed_and_the_iteration_goes_on(self, tmp_path, monkeypatch):
        class ProcessError(Exception):  # what the SDK raises when the CLI dies; not a RuntimeError
            pass
        repo, work, it, campaign, fake, d = _setup(tmp_path, monkeypatch, SCORES)
        fake.raise_in["h-alternative-1"] = ProcessError("Command failed with exit code -9")
        fake.repair_scores["h-alternative-1"] = 65
        _execute(repo, work, it, campaign, d)
        state = json.loads((it / "arms" / "state.json").read_text())
        assert state["sessions"]["h-alternative-1"]["outcome"] == "failed"
        assert "repair:h-alternative-1" in fake.names()  # a crash is repaired, not ranked as is
        assert (it / "findings.json").exists()

    def test_hung_arm_restarts_from_its_saved_patch_in_a_fresh_worktree(self, tmp_path, monkeypatch):
        repo, work, it, campaign, fake, d = _setup(tmp_path, monkeypatch, SCORES)
        (it / "patches" / "h-main.patch").write_text(_patch_for(repo, "v = 33\n"))
        hang = SDKHangError("hung")
        hang.usage, hang.session_id = {"output_tokens": 1000}, "sess-hung"
        fake.raise_in["h-main"] = hang
        seen = {}
        orig = fake._arm

        def arm(key, prompt, cwd):
            if key == "h-main":
                seen["start"], seen["prompt"], seen["cwd"] = (cwd / "solution.py").read_text(), prompt, cwd
            return orig(key, prompt, cwd)
        fake._arm = arm
        _execute(repo, work, it, campaign, d)
        first, second = [kw for n, kw in fake.calls if n == "h-main"]
        assert seen["start"] == "v = 33\n" and "hung" in seen["prompt"]
        assert first["cwd"] != second["cwd"] and second.get("resume") is None
        assert not Path(first["cwd"]).exists()


def _patch_for(repo, content):
    (repo / "solution.py").write_text(content)
    diff = _git(repo, "diff")
    _git(repo, "checkout", "--", "solution.py")
    return diff


class TestBaseline:
    def test_evaluator_baseline_is_committed_and_arms_start_from_it(self, tmp_path, monkeypatch):
        repo, work, it, campaign, fake, d = _setup(tmp_path, monkeypatch, SCORES)
        fake.baseline = True
        seen = {}
        orig = fake._arm

        def arm(key, prompt, cwd):
            seen.setdefault(key, (cwd / "solution.py").read_text())
            return orig(key, prompt, cwd)
        fake._arm = arm
        _execute(repo, work, it, campaign, d)
        assert seen == {"h-main": "v = 5\n", "h-alternative-1": "v = 5\n"}
        assert (repo / "solution.py").read_text() == "v = 5\n"
        assert "measured baseline" in _git(repo, "log", "-1", "--format=%s")
        ev_prompt = dict(fake.calls)["evaluator"]["prompt"]
        assert "simplest correct solution" in ev_prompt and "never" in ev_prompt and "{{" not in ev_prompt


# ─── 3b. exploit while improving, explore when stalled ──────────────────────────────────────

def _prev_iteration(work, before, after, next_step=None, noise_runs=None):
    prev = work / "runs" / "iter-1"
    (prev / "arms" / "h-main").mkdir(parents=True, exist_ok=True)
    (prev / "bundle.yaml").write_text(yaml.safe_dump(_bundle(MAIN)))
    (prev / "problem.md").write_text("# P1\n")
    (prev / "arms" / "state.json").write_text(json.dumps(
        {"sessions": {}, "winner": {"key": "h-main"}, "best_before": before, "best_after": after}))
    r = {"metrics": {"score": after}, "mechanism_family": "greedy packing",
         "validity_check": {"passed": True}}
    if next_step:
        r["next_step"] = next_step
    (prev / "arms" / "h-main" / "result.json").write_text(json.dumps(r))
    if noise_runs:
        _instrument(work, runs=noise_runs)


class TestExploitExplore:
    def test_improvement_above_noise_exploits(self, tmp_path):
        from orchestrator.v8_execute import decide_mode, v8_design_note
        _prev_iteration(tmp_path, 40, 44, noise_runs=(43, 43.5, 44))
        assert decide_mode(_v8(), tmp_path, 2)["mode"] == "exploit"
        note = v8_design_note(_v8(), tmp_path, 2)
        assert "single `h-main`" in note and "no `h-alternative`" in note
        assert "## Judge profile (v8)" in note

    def test_plateau_explores(self, tmp_path):
        from orchestrator.v8_execute import decide_mode, v8_design_note
        _prev_iteration(tmp_path, 44, 44.3)  # noise unknown: needs more than 0.5
        assert decide_mode(_v8(), tmp_path, 2)["mode"] == "explore"
        assert "Exploit iteration" not in v8_design_note(_v8(), tmp_path, 2)

    def test_first_iteration_explores(self, tmp_path):
        from orchestrator.v8_execute import decide_mode
        assert decide_mode(_v8(), tmp_path, 1)["mode"] == "explore"

    def test_decision_is_kept_once_made(self, tmp_path):
        from orchestrator.v8_execute import decide_mode
        _prev_iteration(tmp_path, 40, 44)
        assert decide_mode(_v8(), tmp_path, 2)["mode"] == "exploit"
        _prev_iteration(tmp_path, 44, 44)
        assert decide_mode(_v8(), tmp_path, 2)["mode"] == "exploit"

    def test_next_step_writes_a_valid_single_arm_bundle_without_a_design_call(self, tmp_path):
        from orchestrator.v8_execute import maybe_write_exploit_bundle
        _prev_iteration(tmp_path, 40, 44, next_step="swap the greedy order for a size-descending order")
        it = tmp_path / "runs" / "iter-2"
        assert maybe_write_exploit_bundle(_v8(), tmp_path, it, 2)
        bundle = yaml.safe_load((it / "bundle.yaml").read_text())
        assert [a["type"] for a in bundle["arms"]] == ["h-main"]
        assert bundle["arms"][0]["mechanism"].startswith("swap the greedy order")
        assert validate_design(it, campaign=_v8())["status"] == "pass"

    def test_no_next_step_or_plateau_keeps_the_design_call(self, tmp_path):
        from orchestrator.v8_execute import maybe_write_exploit_bundle
        _prev_iteration(tmp_path, 40, 44)
        assert not maybe_write_exploit_bundle(_v8(), tmp_path, tmp_path / "runs" / "iter-2", 2)
        other = tmp_path / "b"
        _prev_iteration(other, 44, 44, next_step="x")
        assert not maybe_write_exploit_bundle(_v8(), other, other / "runs" / "iter-2", 2)

    def test_execute_records_progress_for_the_next_decision(self, tmp_path, monkeypatch):
        from orchestrator.v8_execute import decide_mode
        repo, work, it, campaign, fake, d = _setup(tmp_path, monkeypatch, SCORES)
        _execute(repo, work, it, campaign, d)
        state = json.loads((it / "arms" / "state.json").read_text())
        assert state["best_before"] is None and state["best_after"] == 701
        (work / "runs" / "iter-2").mkdir()
        assert decide_mode(campaign, work, 2)["mode"] == "explore"  # no earlier best to improve on
        state["best_before"] = 50
        (it / "arms" / "state.json").write_text(json.dumps(state))
        (work / "runs" / "iter-2" / "arms").mkdir(parents=True, exist_ok=True)
        (work / "runs" / "iter-2" / "arms" / "state.json").write_text("{}")
        assert decide_mode(campaign, work, 2)["mode"] == "exploit"


# ─── full iterations through run_iteration ─────────────────────────────────────────────────

class _DesignFake(_V8Fake):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.bundle = V8_BUNDLE

    def _design(self, name, prompt, cwd):
        it = self.iter_dir
        it.mkdir(parents=True, exist_ok=True)
        (it / "problem.md").write_text("# P\n")
        (it / "handoff_snapshot.md").write_text("# H\n")
        b = dict(self.bundle)
        b["metadata"] = dict(b["metadata"], iteration=int(it.name.split("-")[1]))
        (it / "bundle.yaml").write_text(yaml.safe_dump(b))
        return SDKResult(text="designed", output_tokens=self.cost_tokens)


def _iteration_setup(tmp_path, monkeypatch, scores=SCORES):
    import orchestrator.iteration as ri
    from orchestrator.dispatch import StubDispatcher
    repo = _make_repo(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    for t in ("state.json", "ledger.json", "principles.json"):
        shutil.copy(TEMPLATES / t, work / t)
    campaign = _v8()
    campaign["target_system"]["repo_path"] = str(repo)
    fake = _DesignFake(work, work / "runs" / "iter-1", scores)
    monkeypatch.setattr("orchestrator.sdk_dispatch._default_sdk_runner_factory", lambda: fake)
    monkeypatch.setattr("orchestrator.sdk_dispatch.time.sleep", lambda _s: None)

    def stub(work_dir, campaign, model=None):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return StubDispatcher(work_dir)
    monkeypatch.setattr(ri, "LLMDispatcher", stub)
    return repo, work, campaign, fake


def test_run_iteration_v8_end_to_end(tmp_path, monkeypatch):
    from orchestrator.iteration import IterationOutcome, run_iteration
    repo, work, campaign, fake = _iteration_setup(tmp_path, monkeypatch)
    assert run_iteration(campaign, work, iteration=1, auto_approve=True) == IterationOutcome.COMPLETED
    assert fake.names() == ["evaluator", "design", "h-main", "h-alternative-1", "winner:h-alternative-1"]
    design_prompt = dict(fake.calls)["design"]["prompt"]
    assert "## Judge profile (v8)" in design_prompt
    for name in ("evaluator", "h-main", "winner:h-alternative-1"):
        p = dict(fake.calls)[name]["prompt"]
        assert "## Judge profile (v8)" in p and "{{" not in p
    best = json.loads((work / "best_found.json").read_text())["top_k"][0]
    assert best["candidate_id"] == "iter-1/h-alternative/h-alternative-1" and best["score"] == 701
    assert _git(repo, "worktree", "list").count("\n") == 1
    assert (work / "judge_profile.json").is_file()


def test_run_iteration_v8_exploit_iteration_skips_design(tmp_path, monkeypatch):
    from orchestrator.iteration import IterationOutcome, run_iteration
    repo, work, campaign, fake = _iteration_setup(tmp_path, monkeypatch)
    fake.next_step = "tune the window size"
    assert run_iteration(campaign, work, iteration=1, auto_approve=True) == IterationOutcome.COMPLETED
    state1 = json.loads((work / "runs" / "iter-1" / "arms" / "state.json").read_text())
    state1["best_before"] = 50  # iteration 1 improved 50 -> 701
    (work / "runs" / "iter-1" / "arms" / "state.json").write_text(json.dumps(state1))
    from orchestrator.iteration import _maybe_carry_forward
    _maybe_carry_forward(campaign, work, str(repo))
    from orchestrator.engine import Engine
    Engine(work).transition("DESIGN")  # what the campaign loop does between iterations
    fake.iter_dir = work / "runs" / "iter-2"
    fake.scores["h-main"] = 7011
    n = len(fake.calls)
    assert run_iteration(campaign, work, iteration=2, auto_approve=True) == IterationOutcome.COMPLETED
    assert fake.names()[n:] == ["h-main", "winner:h-main"]  # no design call, no alternatives
    bundle = yaml.safe_load((work / "runs" / "iter-2" / "bundle.yaml").read_text())
    assert bundle["arms"][0]["mechanism"] == "tune the window size"


# ─── frontiercs launcher hooks ──────────────────────────────────────────────────────────────

GEN = ROOT / "experiments" / "frontiercs" / "gen"


class TestLauncher:
    def test_wall_hours_default_and_flag(self, monkeypatch):
        monkeypatch.syspath_prepend(str(GEN))
        import nous_research_isolated as N
        assert N.wall_timeout_s(None) == 4 * 3600 and N.wall_timeout_s(6.0) == 6 * 3600

    def test_daemon_records_feed_the_judge_profile(self, monkeypatch, tmp_path):
        import hashlib
        monkeypatch.syspath_prepend(str(GEN))
        import nous_research_isolated as N
        from orchestrator.judge_profile import update_judge_profile
        code = b"int main(){while(true);}\n"
        log = tmp_path / "official_x.jsonl"
        N.record_official(log, code, 0.0)
        N.record_official(log, b"exploit", 0.0, rejected=True)
        _write_jsonl(tmp_path / "evaluator" / "local_runs.jsonl",
                     [{"sha256": hashlib.sha256(code).hexdigest(), "score": 55, "max_cpu_s": 25.0}])
        p = update_judge_profile(_v8(v8={"official_log": str(log)}), tmp_path)
        assert p["n_official"] == 1 and len(p["likely_timeouts"]) == 1

    def test_both_launchers_offer_v8_and_wall_hours(self):
        for name in ("nous_research_isolated.py", "nous_research_cap.py"):
            out = subprocess.run([sys.executable, str(GEN / name), "--help"], cwd=GEN, capture_output=True,
                                 text=True, timeout=60).stdout
            assert "v7,v8}" in out and "--wall-hours" in out


class TestDesignHang:
    def test_hung_design_restarts_once_in_a_fresh_session(self, tmp_path, monkeypatch):
        from orchestrator.v8_execute import run_v8_design
        hang = SDKHangError("hung")
        hang.usage, hang.session_id = {"output_tokens": 10_000}, "s-d"
        runner = _Runner([hang, SDKResult(text="designed")])
        monkeypatch.setattr("orchestrator.sdk_dispatch.time.sleep", lambda _s: None)
        c = _v8()
        c["target_system"]["repo_path"] = str(tmp_path)
        it = tmp_path / "runs" / "iter-1"
        it.mkdir(parents=True)
        d = SDKDispatcher(work_dir=tmp_path, campaign=c, sdk_runner=runner, max_retries=3)
        run_v8_design(d, c, tmp_path, it, 1)
        assert len(runner.calls) == 2 and runner.calls[1].get("resume") is None
        assert runner.calls[1]["max_cost_usd"] == pytest.approx(8.0 - 0.75)  # v8 design default $8

    def test_exploit_threshold_is_never_below_half_a_point(self, tmp_path):
        from orchestrator.v8_execute import EXPLORE, decide_mode
        _prev_iteration(tmp_path, 40.0, 40.2)  # +0.2 on a deterministic judge (noise 0) is not progress
        (tmp_path / "runs" / "iter-2").mkdir(parents=True, exist_ok=True)
        assert decide_mode(_v8(), tmp_path, 2)["mode"] == EXPLORE

    def test_v8_budget_defaults_are_real_dollars(self):
        from orchestrator.design_profile import v7_settings
        s = v7_settings(_v8())
        assert (s.iteration_budget_usd, s.design_budget_usd, s.arm_budget_usd) == (22.0, 8.0, 6.0)
        v7 = v7_settings({**_v8(), "design_profile": "v7"})
        assert (v7.iteration_budget_usd, v7.design_budget_usd, v7.arm_budget_usd) == (12.0, 4.0, 4.0)

    def test_orchestrator_written_design_survives_a_resume(self, tmp_path):
        from orchestrator.v8_execute import maybe_write_exploit_bundle
        _prev_iteration(tmp_path, 40, 44, next_step="go")
        it = tmp_path / "runs" / "iter-2"
        assert maybe_write_exploit_bundle(_v8(), tmp_path, it, 2)
        assert maybe_write_exploit_bundle(_v8(), tmp_path, it, 2)  # not handed to the designer again


def test_default_locator_reads_the_exact_project_dir_without_listing_projects(tmp_path, monkeypatch):
    """Inside the frontiercs sandbox only the run's own project dirs are readable, not projects/."""
    import glob as _glob
    from orchestrator.sdk_dispatch import default_transcript_paths, project_key
    cwd = tmp_path / "ws"
    cwd.mkdir()
    proj = tmp_path / "cfg" / "projects" / project_key(cwd)
    proj.mkdir(parents=True)
    (proj / "s1.jsonl").write_text("")
    real_glob = _glob.glob

    def no_listing(pattern, *a, **kw):
        if pattern.startswith(str(tmp_path / "cfg" / "projects" / "*")) or "projects/" + "*" in pattern:
            raise AssertionError("listed projects/")
        return real_glob(pattern, *a, **kw)
    monkeypatch.setattr(_glob, "glob", no_listing)
    assert [p.name for p in default_transcript_paths(cwd, {"s1"}, config_dir=tmp_path / "cfg")] == ["s1.jsonl"]


def test_instrument_summary_judges_speed_against_the_assumed_limit(tmp_path):
    from orchestrator.instrument import instrument_summary
    it = tmp_path / "runs" / "iter-1"
    it.mkdir(parents=True)
    (it / "instrument.json").write_text(json.dumps({
        "max_cpu_s": 0.8, "time_limit_s": None, "speed_first": False,
        "noise": {"runs": [1, 1, 1], "min": 1, "max": 1, "spread": 0}}))
    v8 = instrument_summary(_v8(), tmp_path, 1)
    assert "time limit 1 s (assumed" in v8 and "make it faster" in v8
    v7 = instrument_summary(_campaign(design_profile="v7"), tmp_path, 1)
    assert "time limit unknown" in v7 and "make it faster" not in v7
