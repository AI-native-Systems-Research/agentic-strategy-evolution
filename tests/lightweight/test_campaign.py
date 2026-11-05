"""Session errors, the campaign worktree, commits and evidence export (FakeClient only)."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import pytest
from claude_agent_sdk.types import HookMatcher

from orchestrator.lightweight.config import parse_campaign_config
from orchestrator.lightweight.final_check import check_answer
from orchestrator.lightweight.hooks import HookState, build_hooks
from orchestrator.lightweight.loop import Campaign
from orchestrator.lightweight.session import Session, SessionResultError
from orchestrator.lightweight.validators import ValidatorContext, validate_answer
from tests.fakes.sdk_client import FakeAssistantMessage, FakeClient, FakePreCompact, FakeResultMessage


def _campaign_yaml(repo_path: str = "/tmp/repo") -> dict:
    return {"research_question": "Is the bug fixable?", "run_id": "test-run", "max_iterations": 3,
            "target_system": {"name": "t", "repo_path": repo_path}}


def _answer() -> dict:
    return {"answer": "fixed", "deliverable": "patch", "repro": "pytest test_bug.py",
            "claims": [{"id": "c1", "metric": "pass_rate", "value": 1.0, "condition": "default",
                        "evidence": {"path": "results.json", "key": "/pass_rate", "value": 1.0}}]}


def _answer_turn(work_dir: Path, **more) -> dict:
    """The agent's turn: answer.json plus the evidence file its claim cites."""
    return {str(work_dir / "results.json"): json.dumps({"pass_rate": 1.0}),
            str(work_dir / "answer.json"): json.dumps(_answer()), **more}


def _no_gap(_opts):
    msg = FakeResultMessage(session_id="rev")
    msg.result = '{"gap": false, "why": "x"}'
    return FakeClient(script=[msg])


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "README").write_text("x\n")
    _git(repo, "add", "README")
    _git(repo, "commit", "-qm", "init")
    return repo


def _campaign(repo: Path, work_dir: Path, client: FakeClient, opts_seen: list | None = None) -> Campaign:
    work_dir.mkdir(parents=True, exist_ok=True)

    def factory(opts):
        if opts_seen is not None:
            opts_seen.append(opts)
        return client

    return Campaign(parse_campaign_config(_campaign_yaml(str(repo))), work_dir, factory, challenger_factory=_no_gap)


# ── error results ───────────────────────────────────────────────────────


def _session(tmp_path, script, sleeps):
    client = FakeClient(script=script)

    async def sleep(s):
        sleeps.append(s)

    return Session(lambda _o: client, {"work_dir": str(tmp_path / "w")}, sleep=sleep)


async def test_api_error_status_429_is_retried(tmp_path):
    sleeps: list = []
    s = _session(tmp_path, [FakeResultMessage(is_error=True, api_error_status=429, result="x"),
                            FakeResultMessage(session_id="ok")], sleeps)
    await s.connect()
    assert (await s.turn("hi")).session_id == "ok"
    assert len(sleeps) == 1


async def test_api_error_status_5xx_without_text_is_retried(tmp_path):
    sleeps: list = []
    s = _session(tmp_path, [FakeResultMessage(is_error=True, api_error_status=503),
                            FakeResultMessage(session_id="ok")], sleeps)
    await s.connect()
    assert (await s.turn("hi")).session_id == "ok"


async def test_auth_error_raises_not_retried(tmp_path):
    sleeps: list = []
    s = _session(tmp_path, [FakeResultMessage(is_error=True, api_error_status=401,
                                              result="authentication_failed")], sleeps)
    await s.connect()
    with pytest.raises(SessionResultError, match="authentication_failed"):
        await s.turn("hi")
    assert sleeps == []


async def test_context_full_falls_back_to_fresh_session_from_digest(tmp_path):
    work_dir = tmp_path / "work"
    script = [FakeResultMessage(is_error=True, result="Prompt is too long", session_id="ses-1"),
              FakeResultMessage(session_id="ses-2"), FakeResultMessage(session_id="ses-2")]
    client = FakeClient(script=script, per_turn_files=[{}, {}, _answer_turn(work_dir)])
    opts_seen: list = []
    campaign = _campaign(tmp_path / "none", work_dir, client, opts_seen)
    assert (await campaign.run())["stop_reason"] == "answered"
    assert client.queries[1].startswith("Resuming campaign at INVESTIGATE phase, iteration 1")
    assert client.queries[2] == client.queries[0]  # the task message is sent again
    assert opts_seen[-1].resume is None  # a fresh session, not a resume of the full one


# ── campaign worktree ───────────────────────────────────────────────────


async def test_commits_go_to_campaign_worktree_not_user_branch(tmp_path):
    repo = _init_repo(tmp_path)
    user_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    (repo / "secret.env").write_text("TOKEN=x\n")  # user's untracked file
    (repo / "README").write_text("dirty\n")  # user's uncommitted edit
    wt = repo / ".nous-experiments" / "test-run"
    work_dir = repo / ".nous" / "test-run"
    client = FakeClient(script=[FakeResultMessage()],
                        per_turn_files=[_answer_turn(work_dir, **{str(wt / "src.py"): "print('fix')\n"})])
    opts_seen: list = []
    assert (await _campaign(repo, work_dir, client, opts_seen).run())["stop_reason"] == "answered"

    assert opts_seen[0].cwd == str(wt)
    assert _git(repo, "log", "--format=%s", user_branch).split("\n")[0] == "init"
    assert (repo / "README").read_text() == "dirty\n"
    tree = _git(repo, "ls-tree", "-r", "--name-only", "nous/test-run").split()
    assert "src.py" in tree and "secret.env" not in tree
    assert "nous_evidence/results.json" in tree  # evidence exported into the worktree
    assert not any(p.startswith(".nous/") for p in tree)  # the work dir is never committed
    assert _git(repo, "log", "--format=%s", "nous/test-run").split("\n")[0] == "nous: iter-1 ANSWER"


async def test_user_checkout_stays_clean(tmp_path):
    repo = _init_repo(tmp_path)
    work_dir = tmp_path / "work"  # NOUS_CAMPAIGN_PARENT-style, outside the repo
    wt = repo / ".nous-experiments" / "test-run"
    client = FakeClient(script=[FakeResultMessage()],
                        per_turn_files=[_answer_turn(work_dir, **{str(wt / "src.py"): "print('fix')\n"})])
    assert (await _campaign(repo, work_dir, client).run())["stop_reason"] == "answered"
    assert _git(repo, "status", "--porcelain") == ""
    assert ".gitignore" not in _git(repo, "ls-files").split()
    exclude = (repo / ".git" / "info" / "exclude").read_text().splitlines()
    assert exclude.count(".nous-experiments/") == 1
    # a resume of a finished campaign reuses everything and adds no second exclude line
    (work_dir / "state.json").write_text(json.dumps({"phase": "INVESTIGATE", "iteration": 1}))
    again = FakeClient(script=[FakeResultMessage()], per_turn_files=[_answer_turn(work_dir)])
    await _campaign(repo, work_dir, again).resume()
    assert (repo / ".git" / "info" / "exclude").read_text().splitlines().count(".nous-experiments/") == 1


async def test_resume_reuses_the_worktree(tmp_path):
    repo = _init_repo(tmp_path)
    work_dir = repo / ".nous" / "test-run"
    await _campaign(repo, work_dir, FakeClient(script=[FakeResultMessage()],
                                               per_turn_files=[_answer_turn(work_dir)])).run()
    (work_dir / "state.json").write_text(json.dumps({"phase": "INVESTIGATE", "iteration": 1}))
    opts_seen: list = []
    again = _campaign(repo, work_dir, FakeClient(script=[FakeResultMessage()],
                                                 per_turn_files=[_answer_turn(work_dir)]), opts_seen)
    assert (await again.resume())["stop_reason"] == "answered"
    assert opts_seen[0].cwd == str(repo / ".nous-experiments" / "test-run")


async def test_failed_git_step_is_preflight_error(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")  # no commits: HEAD does not resolve
    with pytest.raises(ValueError, match="Preflight failed"):
        await _campaign(repo, tmp_path / "work", FakeClient()).run()


async def test_non_git_repo_warns_and_makes_no_commits(tmp_path, caplog):
    repo = tmp_path / "plain"
    repo.mkdir()
    work_dir = tmp_path / "work"
    client = FakeClient(script=[FakeResultMessage()], per_turn_files=[_answer_turn(work_dir)])
    with caplog.at_level(logging.WARNING):
        assert (await _campaign(repo, work_dir, client).run())["stop_reason"] == "answered"
    assert sum("not a git repo" in r.message for r in caplog.records) == 1
    assert not (repo / ".nous-experiments").exists()


async def test_failed_commit_is_logged_not_raised(tmp_path, caplog):
    repo = _init_repo(tmp_path)
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    work_dir = tmp_path / "work"
    client = FakeClient(script=[FakeResultMessage()], per_turn_files=[_answer_turn(work_dir)])
    with caplog.at_level(logging.WARNING):
        assert (await _campaign(repo, work_dir, client).run())["stop_reason"] == "answered"
    assert any("commit" in r.message for r in caplog.records)


async def test_task_message_names_the_working_copy(tmp_path):
    """dbg eval run: the agent read repo_path from campaign.yaml and fixed the user's checkout."""
    repo = _init_repo(tmp_path)
    work_dir = tmp_path / "work"
    client = FakeClient(script=[FakeResultMessage()], per_turn_files=[_answer_turn(work_dir)])
    await _campaign(repo, work_dir, client).run()
    wt = repo / ".nous-experiments" / "test-run"
    assert f"Your working copy is {wt}" in client.queries[0]
    assert f"never change {repo}" in client.queries[0]
    assert str(work_dir / "answer.json") in client.queries[0]
    assert str(work_dir / "notebook.jsonl") in client.queries[0]


# ── the fake fires every hook ───────────────────────────────────────────


async def test_fake_fires_failure_precompact_and_stop_hooks(tmp_path):
    state = HookState(work_dir=tmp_path)
    stop_inputs: list = []
    answers = iter([{"decision": "block", "reason": "no answer"}, {}])

    async def stop_spy(hook_input, tid, ctx):
        stop_inputs.append(hook_input["stop_hook_active"])
        return next(answers)

    hooks = build_hooks(state, stop_spy)
    tool = {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "false"},
            "is_error": True, "response": "Exit code 2"}
    client = FakeClient(
        script=[FakeAssistantMessage(content=[tool]), FakePreCompact(),
                FakeResultMessage(), FakeResultMessage()],
        per_turn_files=[{}, {}], hooks=hooks)
    await client.connect()
    await client.query("go")
    msgs = [m async for m in client.receive_response()]

    row = json.loads((tmp_path / "runs.jsonl").read_text())
    assert row["exit_code"] == 2  # PostToolUseFailure recorded the failed command
    assert row["phase"] == "INVESTIGATE"
    assert (tmp_path / "state" / "digest.json").exists()  # PreCompact fired
    assert client.stop_decisions == ["block", None]
    assert stop_inputs == [False, True]
    assert sum(isinstance(m, FakeResultMessage) for m in msgs) == 1
    assert isinstance(hooks["Stop"][0], HookMatcher)


# ── evidence export ─────────────────────────────────────────────────────


async def test_export_copies_evidence_into_repo(tmp_path):
    """answer.json is the deliverable: its evidence must resolve from the target repo root too."""
    repo, work_dir = tmp_path / "repo", tmp_path / "work"
    repo.mkdir()
    client = FakeClient(script=[FakeResultMessage()], per_turn_files=[_answer_turn(work_dir)])
    await _campaign(repo, work_dir, client).run()

    claim = json.loads((work_dir / "answer.json").read_text())["claims"][0]
    path = claim["evidence"]
    assert path == "nous_evidence/results.json"
    assert claim["evidence_detail"] == {"path": path, "key": "/pass_rate", "value": 1.0}
    assert json.loads((repo / path).read_text()) == {"pass_rate": 1.0}
    assert (work_dir / path).exists()
    check = json.loads((work_dir / "final_check.json").read_text())
    assert check["answer_valid"] is True and check["evidence_errors"] == []


async def test_invalid_answer_is_repaired_before_export(tmp_path):
    repo, work_dir = tmp_path / "repo", tmp_path / "work"
    repo.mkdir()
    bad = _answer()
    bad["claims"][0]["evidence_ref"] = bad["claims"][0].pop("evidence")
    client = FakeClient(script=[FakeResultMessage()] * 2, per_turn_files=[
        {**_answer_turn(work_dir), str(work_dir / "answer.json"): json.dumps(bad)}, _answer_turn(work_dir)])
    await _campaign(repo, work_dir, client).run()

    assert client.queries[1].startswith("Fix these before you stop:") and "answer: schema" in client.queries[1]
    answer = json.loads((work_dir / "answer.json").read_text())
    assert answer["claims"][0]["evidence"] == "nous_evidence/results.json"
    assert (repo / "nous_evidence" / "results.json").is_file()


def test_answer_string_evidence_must_exist(tmp_path):
    ans = {**_answer(), "claims": [{**_answer()["claims"][0], "evidence": "nous_evidence/missing.json"}]}
    errs = validate_answer(ans, ValidatorContext(work_dir=tmp_path))
    assert any("missing.json" in e for e in errs)
    (tmp_path / "nous_evidence").mkdir()
    (tmp_path / "nous_evidence" / "missing.json").write_text('{"pass_rate": 1.0}')
    assert validate_answer(ans, ValidatorContext(work_dir=tmp_path)) == []


def test_export_handles_mixed_and_pre_prefixed_evidence(tmp_path):
    """dbg rep1 (R13): claims mixed {path,key,value} already under nous_evidence/ and bare path strings."""
    repo, work = tmp_path / "ws", tmp_path / "work"
    repo.mkdir(); (work / "nous_evidence").mkdir(parents=True)
    (work / "R1.json").write_text('{"n": 5}')
    (work / "nous_evidence" / "R1.json").write_text('{"n": 5}')
    (work / "answer.json").write_text(json.dumps({**_answer(), "claims": [
        {"id": "C1", "metric": "n", "value": 5, "condition": "c",
         "evidence": {"path": "nous_evidence/R1.json", "key": "/n", "value": 5}},
        {"id": "C2", "metric": "n", "value": 5, "condition": "c", "evidence": "R1.json"},
    ]}))
    cfg = parse_campaign_config(_campaign_yaml(repo_path=str(repo)))
    Campaign(cfg, work, client_factory=None)._export_evidence()
    claims = json.loads((work / "answer.json").read_text())["claims"]
    assert [c["evidence"] for c in claims] == ["nous_evidence/R1.json"] * 2
    assert claims[0]["evidence_detail"]["key"] == "/n"
    assert (repo / "nous_evidence" / "R1.json").is_file()
    assert check_answer(work)["evidence_errors"] == []


def test_export_coerces_numeric_string_claim_values(tmp_path):
    """Output contract: claim value is a number. R13 round 3: "114630" passed Nous but not the contract reader."""
    repo, work = tmp_path / "ws", tmp_path / "work"
    repo.mkdir(); work.mkdir()
    (work / "out.txt").write_text("total: 114630 rate: 1.5")
    (work / "answer.json").write_text(json.dumps({**_answer(), "claims": [
        {"id": "C1", "metric": "n", "value": "114630", "condition": "c", "evidence": "out.txt"},
        {"id": "C2", "metric": "r", "value": "1.5", "condition": "c", "evidence": "out.txt"},
        {"id": "C3", "metric": "s", "value": "PASS", "condition": "c", "evidence": "out.txt"},
    ]}))
    Campaign(parse_campaign_config(_campaign_yaml(repo_path=str(repo))), work, client_factory=None)._export_evidence()
    vals = [c["value"] for c in json.loads((work / "answer.json").read_text())["claims"]]
    assert vals == [114630, 1.5, "PASS"]
