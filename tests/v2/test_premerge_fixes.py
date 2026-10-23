"""Pre-merge fixes P1-P6 (full-branch review)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from claude_agent_sdk.types import HookMatcher

from orchestrator.v2.hooks import HookState, build_hooks
from orchestrator.v2.loop import Campaign, _write_json, iter_dir
from orchestrator.v2.session import Session, SessionResultError
from tests.fakes.sdk_client import FakeAssistantMessage, FakeClient, FakePreCompact, FakeResultMessage
from tests.v2.test_loop import (
    _baseline, _build_per_turn_files, _bundle, _campaign_yaml, _git, _init_repo, _make_script,
    _plan, _problem, parse_campaign_config,
)
from tests.v2.test_resume import _FINDINGS, _config, _exec_report_turns, _seed_execute_state


def _ok(n: int) -> list[FakeResultMessage]:
    return [FakeResultMessage(session_id="") for _ in range(n)]  # "" = no session id to resume


# ── P1: missing baseline ────────────────────────────────────────────────


async def test_p1_resume_reruns_missing_baseline(tmp_path):
    work_dir = tmp_path / "c"
    idir = _seed_execute_state(work_dir)
    (work_dir / "baseline.json").unlink()
    client = FakeClient(script=_ok(3), per_turn_files=[
        {str(work_dir / "baseline.json"): json.dumps(_baseline())}, *_exec_report_turns(work_dir, idir)])
    result = await Campaign(_config(), work_dir, lambda _o: client).resume()
    assert "BASELINE phase" in client.queries[0]
    assert result["stop_reason"] == "answered"
    assert json.loads((work_dir / "baseline.json").read_text())["task_type"] == "debug"


# ── P2: error results ───────────────────────────────────────────────────


def _session(tmp_path, script, sleeps):
    client = FakeClient(script=script)

    async def sleep(s):
        sleeps.append(s)

    return Session(lambda _o: client, {"work_dir": str(tmp_path / "w")}, sleep=sleep)


async def test_p2_api_error_status_429_is_retried(tmp_path):
    sleeps: list = []
    s = _session(tmp_path, [FakeResultMessage(is_error=True, api_error_status=429, result="x"),
                            FakeResultMessage(session_id="ok")], sleeps)
    await s.connect()
    assert (await s.turn("hi")).session_id == "ok"
    assert len(sleeps) == 1


async def test_p2_api_error_status_5xx_without_text_is_retried(tmp_path):
    sleeps: list = []
    s = _session(tmp_path, [FakeResultMessage(is_error=True, api_error_status=503),
                            FakeResultMessage(session_id="ok")], sleeps)
    await s.connect()
    assert (await s.turn("hi")).session_id == "ok"


async def test_p2_auth_error_raises_not_retried(tmp_path):
    sleeps: list = []
    s = _session(tmp_path, [FakeResultMessage(is_error=True, api_error_status=401,
                                              result="authentication_failed")], sleeps)
    await s.connect()
    with pytest.raises(SessionResultError, match="authentication_failed"):
        await s.turn("hi")
    assert sleeps == []


async def test_p2_context_full_falls_back_to_fresh_session_from_digest(tmp_path):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    per_turn = _build_per_turn_files(work_dir)
    per_turn[1:1] = [{}, {}]  # DESIGN (context full), then the fallback priming turn
    script = [FakeResultMessage(session_id="ses-1"),
              FakeResultMessage(is_error=True, result="Prompt is too long", session_id="ses-1"),
              *_make_script(4)]
    client = FakeClient(script=script, per_turn_files=per_turn)
    opts_seen: list = []

    def factory(opts):
        opts_seen.append(opts)
        return client

    cfg = parse_campaign_config(_campaign_yaml())
    result = await Campaign(cfg, work_dir, factory).run()
    assert result["stop_reason"] == "answered"
    assert client.queries[2].startswith("Resuming campaign at DESIGN phase, iteration 1")
    assert "DESIGN phase" in client.queries[3]  # the phase message is sent again
    assert opts_seen[-1].resume is None  # a fresh session, not a resume of the full one


# ── P3: resume at iteration 1 ───────────────────────────────────────────


async def test_p3_resume_at_iteration_1_has_no_previous_findings(tmp_path):
    work_dir = tmp_path / "c"
    idir = _seed_execute_state(work_dir)
    _write_json(idir / "findings.json", _FINDINGS)  # written before the crash
    client = FakeClient(script=[FakeResultMessage()] * 2,
                        per_turn_files=_exec_report_turns(work_dir, idir))
    await Campaign(_config(), work_dir, lambda _o: client).resume()
    ledger = json.loads((work_dir / "ledger.json").read_text())
    assert ledger[0]["claims_changed"] is True  # first claims ever, not "same as itself"


# ── P4: campaign worktree ───────────────────────────────────────────────


def _git_campaign(repo: Path, client: FakeClient, opts_seen: list | None = None):
    work_dir = repo / ".nous" / "test-run"
    work_dir.mkdir(parents=True, exist_ok=True)

    def factory(opts):
        if opts_seen is not None:
            opts_seen.append(opts)
        return client

    return Campaign(parse_campaign_config(_campaign_yaml(repo_path=str(repo))), work_dir, factory), work_dir


async def test_p4_commits_go_to_campaign_worktree_not_user_branch(tmp_path):
    repo = _init_repo(tmp_path)
    user_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    (repo / "secret.env").write_text("TOKEN=x\n")  # user's untracked file
    (repo / "README").write_text("dirty\n")  # user's uncommitted edit
    wt = repo / ".nous-experiments" / "test-run"
    work_dir = repo / ".nous" / "test-run"
    per_turn = _build_per_turn_files(work_dir)
    per_turn[1][str(wt / "src.py")] = "print('fix')\n"
    opts_seen: list = []
    campaign, _ = _git_campaign(repo, FakeClient(script=_make_script(4), per_turn_files=per_turn), opts_seen)
    assert (await campaign.run())["stop_reason"] == "answered"

    assert opts_seen[0].cwd == str(wt)
    assert _git(repo, "log", "--format=%s", user_branch).split("\n")[0] == "init"
    assert (repo / "README").read_text() == "dirty\n"
    tree = _git(repo, "ls-tree", "-r", "--name-only", "nous/test-run").split()
    assert "src.py" in tree and "secret.env" not in tree
    assert "nous_evidence/runs/iter-1/results.json" in tree  # evidence exported into the worktree
    assert "nous: iter-1 REPORT" in _git(repo, "log", "--format=%s", "nous/test-run")


async def test_p4_resume_reuses_the_worktree(tmp_path):
    repo = _init_repo(tmp_path)
    work_dir = repo / ".nous" / "test-run"
    campaign, _ = _git_campaign(repo, FakeClient(script=_make_script(4),
                                                 per_turn_files=_build_per_turn_files(work_dir)))
    await campaign.run()
    opts_seen: list = []
    again, _ = _git_campaign(repo, FakeClient(script=_make_script(1), per_turn_files=[
        _build_per_turn_files(work_dir)[3]]), opts_seen)
    assert (await again.resume())["stop_reason"] == "resumed_report"
    assert opts_seen[0].cwd == str(repo / ".nous-experiments" / "test-run")


async def test_p4_failed_git_step_is_preflight_error(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")  # no commits: HEAD does not resolve
    campaign, _ = _git_campaign(repo, FakeClient(script=_make_script(4)))
    with pytest.raises(ValueError, match="Preflight failed"):
        await campaign.run()


async def test_p4_non_git_repo_warns_and_makes_no_commits(tmp_path, caplog):
    repo = tmp_path / "plain"
    repo.mkdir()
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    client = FakeClient(script=_make_script(4), per_turn_files=_build_per_turn_files(work_dir))
    cfg = parse_campaign_config(_campaign_yaml(repo_path=str(repo)))
    with caplog.at_level(logging.WARNING):
        assert (await Campaign(cfg, work_dir, lambda _o: client).run())["stop_reason"] == "answered"
    assert sum("not a git repo" in r.message for r in caplog.records) == 1
    assert not (repo / ".nous-experiments").exists()


# ── P5: breaker across resumes ──────────────────────────────────────────


async def test_p5_breaker_trips_across_resumes(tmp_path):
    work_dir = tmp_path / "c"
    idir = _seed_execute_state(work_dir)
    _write_json(work_dir / "state.json", {"phase": "EXECUTE", "iteration": 1})
    crash = FakeResultMessage(is_error=True, result="authentication_failed", session_id="")
    for n in (1, 2):
        client = FakeClient(script=[*_ok(1), crash])  # fallback priming turn, then EXECUTE fails
        with pytest.raises(SessionResultError):
            await Campaign(_config(), work_dir, lambda _o: client).resume()
        assert len(json.loads((work_dir / "state.json").read_text())["breaker_recent"]) == n
    client = FakeClient(script=[*_ok(1), crash, *_ok(1)],
                        per_turn_files=[{}, {}, _exec_report_turns(work_dir, idir)[1]])
    result = await Campaign(_config(), work_dir, lambda _o: client).resume()
    assert result["stop_reason"] == "halt"
    assert json.loads((work_dir / "halt.json").read_text())["phase"] == "EXECUTE"
    assert (work_dir / "answer.json").exists()  # REPORT still ran


async def test_p5_design_failure_counts_for_the_breaker(tmp_path):
    work_dir = tmp_path / "c"
    _seed_execute_state(work_dir)
    _write_json(work_dir / "state.json", {"phase": "DESIGN", "iteration": 1,
                                          "breaker_recent": []})
    crash = FakeResultMessage(is_error=True, result="authentication_failed", session_id="")
    client = FakeClient(script=[*_ok(1), crash])
    with pytest.raises(SessionResultError):
        await Campaign(_config(), work_dir, lambda _o: client).resume()
    assert len(json.loads((work_dir / "state.json").read_text())["breaker_recent"]) == 1


async def test_p5_repeated_baseline_crash_trips_and_reports(tmp_path):
    work_dir = tmp_path / "c"
    crash = FakeResultMessage(is_error=True, result="authentication_failed", session_id="")
    _write_json(work_dir / "state.json", {"phase": "BASELINE", "iteration": 0})
    for _ in range(2):
        with pytest.raises(SessionResultError):
            await Campaign(_config(), work_dir, lambda _o: FakeClient(script=[*_ok(1), crash])).resume()
    client = FakeClient(script=[*_ok(1), crash, *_ok(5)])
    result = await Campaign(_config(), work_dir, lambda _o: client).resume()
    assert result["stop_reason"] == "no_baseline"
    assert json.loads((work_dir / "halt.json").read_text())["phase"] == "BASELINE"
    assert (work_dir / "final_check.json").exists()


# ── P6: fake fires every hook ───────────────────────────────────────────


async def test_p6_fake_fires_failure_precompact_and_stop_hooks(tmp_path):
    state = HookState(work_dir=tmp_path, phase="REPORT")
    stop_inputs: list = []
    hooks = build_hooks(state)
    gate = hooks["Stop"][0].hooks[0]

    async def stop_spy(hook_input, tid, ctx):
        stop_inputs.append(hook_input["stop_hook_active"])
        return await gate(hook_input, tid, ctx)

    hooks["Stop"] = [HookMatcher(matcher="", hooks=[stop_spy])]
    tool = {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "false"},
            "is_error": True, "response": "Exit code 2"}
    from tests.v2.test_loop import _answer_turn
    client = FakeClient(
        script=[FakeAssistantMessage(content=[tool]), FakePreCompact(),
                FakeResultMessage(), FakeResultMessage()],
        per_turn_files=[{}, _answer_turn(tmp_path)], hooks=hooks)
    await client.connect()
    await client.query("go")
    msgs = [m async for m in client.receive_response()]

    row = json.loads((tmp_path / "runs.jsonl").read_text())
    assert row["exit_code"] == 2  # PostToolUseFailure recorded the failed command
    assert (tmp_path / "state" / "digest.json").exists()  # PreCompact fired
    assert client.stop_decisions == ["block", None]  # no answer.json, then the fixed turn
    assert stop_inputs == [False, True]
    assert sum(isinstance(m, FakeResultMessage) for m in msgs) == 1


async def test_p6_stop_gate_blocks_invalid_design_then_allows(tmp_path):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    idir = iter_dir(work_dir, 1)
    per_turn = _build_per_turn_files(work_dir)
    bad_bundle = {"hypotheses": [_bundle()["hypotheses"][0]]}  # one family, no reason
    per_turn.insert(1, {str(idir / "problem.json"): json.dumps(_problem()),
                        str(idir / "bundle.json"): json.dumps(bad_bundle),
                        str(idir / "plan.json"): json.dumps(_plan())})
    holder: dict = {}

    def factory(opts):
        holder["c"] = FakeClient(script=_make_script(5), per_turn_files=per_turn, hooks=opts.hooks)
        return holder["c"]

    cfg = parse_campaign_config(_campaign_yaml())
    result = await Campaign(cfg, work_dir, factory).run()
    assert result["stop_reason"] == "answered"
    assert holder["c"].stop_decisions == [None, "block", None, None, None]
    assert len(holder["c"].queries) == 4  # the gate fixed DESIGN; no repair turn needed
    assert json.loads((idir / "bundle.json").read_text()) == _bundle()
